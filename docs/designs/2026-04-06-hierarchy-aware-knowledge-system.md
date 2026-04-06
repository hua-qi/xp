# 层级感知知识体系设计

**Date:** 2026-04-06

## Context

xp 当前已实现 PyPI 分发和 stdio MCP 接入，用户可通过 `xp login` 连接团队 Supabase 知识库。但知识库是扁平结构，teams/businesses/projects 三张层级表虽已建立但完全未被使用，`scope_type` 和 `scope_id` 字段只在内存中做简单过滤，没有真正的层级感知逻辑。

本次设计目标：实现完整的三层知识层级体系，包括层级感知的沉淀、召回、反馈、升层推荐，以及可量化的统计指标体系。

**核心设计原则：**
1. 召回要快，沉淀可以慢
2. 用户无感知，开发者和管理员可以多做
3. 沉淀可量化的指标

## Discussion

### 层级结构

确认采用 Team → Business → Project 三层结构，三层之间全部为**多对多关系**（真实组织需求，如一个基础设施项目可能同时服务多个业务线）。通过三张关联表维护映射关系，由管理员负责维护，用户无感知。

### 部署模式

`xp-server` 维持 **stdio 本地模式**（pip install xp-agent，本地进程被 Claude Desktop 启动）。设计文档中描述的 HTTP 中心化模式暂不采用。

由此引发两个问题：
- **安全性**：若本地直连 DB，`database_url` 暴露在用户的 `config.json` 中，存在安全风险
- **LLM 配置**：开发者希望统一管理 LLM，保证所有用户效果一致，但 stdio 模式下 LLM 调用发生在本地

**解决方案**：将所有数据库操作和 LLM 调用封装到 Supabase Edge Function，本地 `xp-server` 只携带 token 转发请求，**不持有 database_url**，不做任何数据库操作。

### 沉淀逻辑

- save 由 Claude 任务完成后主动调用，Claude 自主拆分成多条逐条 save
- 查重分两层：先在 project 层查重（相似度 > 0.85 则更新），再跨层查重（business + team 层）
- 跨层查重若解决方案也相似则舍弃（已被更高层覆盖），解决方案不同则在 project 层新建
- 质量评分决定是否 auto-activate（score ≥ 80 直接 active，否则 pending 等待 review）

### 召回逻辑

- search 由 Claude 任务开始时主动调用
- 通过关联表做三层展开：project_id → business_ids[] → team_ids[]
- 三层并发向量搜索，加权合并（project ×1.2 / business ×1.0 / team ×0.9），技术栈匹配 ×1.15
- 全部在 Edge Function 云端完成，本地不做向量计算，保证召回速度

### 升层推荐

- pg_cron 每周一、周四各触发一次 `scan-promotions` Edge Function
- 扫描算法：adoption_rate > 0.6、recall_count > 5、created_at > 30 天、跨项目相似经验 >= 2
- 综合评分 > 0.7 推荐升到 business 层；business 层副本在 >= 2 个不同 business 有相似经验则推荐升到 team 层
- 目标层级由扫描器自动判断，邮件通知对应 owner 审核
- 被 ignore 的候选一个月后可重新评估；升层后 promotion_candidates 记录删除

### 指标体系

所有人均可查看，xp stats 支持按 project/business/team 维度过滤，以及跨层级对比视图，末尾固定展示知识库健康状态。

## Approach

1. **全部 MCP 操作云端化**：search / save / feedback 全部通过 Supabase Edge Function 处理，本地 xp-server 只做转发，不持有数据库凭证
2. **LLM 统一由管理员配置**：LLM API Key 存储在 Supabase Edge Function Secrets，用户无需关心
3. **三层多对多关联**：通过 project_business / business_team / user_business 三张关联表实现，管理员维护
4. **隐式采纳兜底**：save 后 10 分钟无 feedback 则 pg_cron 触发隐式采纳推断
5. **升层推荐自动化**：定期扫描推荐候选，管理员交互式审核（参考 xp review 风格）

## Architecture

### 部署架构

```
用户本地（Claude Desktop）
  │  stdio
  ▼
xp-server（本地进程，pip install xp-agent）
  │  携带 token，HTTP 调用
  ▼
Supabase Edge Functions
  ├── verify-token      登录验证，返回 token 元信息
  ├── search            向量生成 + 三层召回 + 记录 search_event
  ├── process-save      LLM 提取 + 查重 + 质量评分 + 写库
  ├── process-feedback  confidence 更新 + LLM 分析 comment + 触发隐式推断
  └── scan-promotions   pg_cron 升层扫描 + 发邮件通知
  │
  ▼
PostgreSQL + pgvector
```

### 数据模型变更

**新增关联表：**
```sql
project_business  (project_id TEXT, business_id TEXT)
business_team     (business_id TEXT, team_id TEXT)
user_business     (user_id TEXT, business_id TEXT)

promotion_candidates (
    id              TEXT PRIMARY KEY,
    experience_id   TEXT NOT NULL,
    target_scope_type TEXT NOT NULL,  -- business / team
    target_scope_id   TEXT NOT NULL,
    score           FLOAT NOT NULL,
    status          TEXT NOT NULL,    -- pending / ignored / promoted
    ignored_at      TIMESTAMPTZ,      -- 一个月后可重新评估
    created_at      TIMESTAMPTZ DEFAULT now()
)
```

**已有表新增字段：**
```
businesses：owner_email TEXT
teams：owner_email TEXT
user_tokens：email TEXT
```

**config.json 变更：**
```json
{
  "token": "xp_xxx"
}
```
不再存储 database_url，只持有 token。

### 沉淀流程（process-save Edge Function）

```
Step 1: token 验证，获取权限
Step 2: LLM 提取 title / type / level
Step 3: 生成 embedding
Step 4: project 层查重（> 0.85 → 更新）
Step 5: 跨层查重（business + team）
        解决方案相似 → 舍弃
        解决方案不同 → project 层新建
Step 6: 质量评分（≥ 80 → active，否则 pending）
Step 7: 写入 confidence（success 0.65 / partial 0.55 / failed 0.40）
```

### 召回流程（search Edge Function）

```
Step 1: token 验证
Step 2: project_id → business_ids[] → team_ids[]（查关联表）
Step 3: 解析 project_manifest，提取 tags[]
Step 4: 生成 query_embedding
Step 5: 三层并发向量搜索，各取 Top-10（相似度 > 0.5）
Step 6: 加权合并（scope 权重 + 技术栈权重），去重，Top-5
Step 7: 记录 search_event，返回结果 + search_event_id
```

### 反馈流程（process-feedback Edge Function）

```
Step 1: token 验证，校验 ids 合法性
Step 2: 更新 confidence（helpful +0.1 / unhelpful -0.05）
        confidence < 0.2 → 标记待归档
Step 3: 记录 feedback_event，更新 adoption_rate
Step 4: 异步 LLM 分析 comment，写入 improvement_hint
Step 5: 异步重新计算提升候选得分

隐式采纳推断（pg_cron 每 10 分钟）：
  search_event 有对应 save 但无 feedback 且距 save > 10 分钟
  → 对比 save.solution 与 search 结果语义相似度
    > 0.6 → confidence += 0.05
    < 0.3 → 不调整
```

### 升层推荐流程（scan-promotions Edge Function）

```
pg_cron 每周一、周四触发

扫描条件（全部满足）：
  adoption_rate > 0.6 且 recall_count > 5
  created_at > 30 天前
  不在 pending/promoted 候选中
  （ignored 且 ignored_at > 30 天前 → 可重新评估）

评分：
  score = cross_project_count × 0.5
        + adoption_rate × 0.3
        + min(recall_count / 10, 1) × 0.2

目标层级：
  score > 0.7 且 cross_project_count >= 2 → business 层
  business 层副本在 >= 2 个不同 business 有相似经验 → team 层

结果：写入 promotion_candidates，邮件通知 owner
```

### 统计指标（xp stats）

```bash
xp stats                    # 整体概览
xp stats --since 7d         # 按时间过滤
xp stats --project <id>     # 项目维度
xp stats --business <id>    # 业务线维度
xp stats --team <id>        # 团队维度
xp stats --compare          # 跨层级对比
```

| 类别 | 指标 | 健康阈值 |
|------|------|---------|
| 召回质量 | 采纳率 | > 60% |
| 召回质量 | 未命中率 | < 20% |
| 召回质量 | 零结果率 | < 10% |
| 经验质量 | 僵尸经验率（90天未召回） | < 15% |
| 经验质量 | Pending 堆积量 | < 20 条 |
| 使用深度 | feedback 覆盖率 | > 40% |

`xp stats` 末尾固定展示知识库健康状态，标注各指标是否达标。

### 管理员命令

```bash
# 层级管理
xp admin create-team     --name "xx团队" --owner-email admin@xx.com
xp admin create-business --name "支付业务" --owner-email biz@xx.com
xp admin link            --project <project_id> --business <biz-id>
xp admin link            --business <biz-id> --team <team-id>

# 用户管理
xp admin create-token    --user alice --email alice@xx.com --business <biz-id>

# 升层管理（交互风格参考 xp review）
xp promote list
xp promote <id> --to business <biz-id>
xp promote <id> --to team <team-id>
xp promote ignore <id>
```

### Server 侧 LLM 用途汇总

| 时机 | 用途 | 同步/异步 |
|------|------|---------|
| process-save | 生成 title、推断 type/level | 同步 |
| process-feedback | 分析 unhelpful 原因，打 improvement_hint | 异步 |
| 隐式采纳推断 | 对比 solution 语义相似度 | 异步（pg_cron） |

---
**文档版本**: v1.0
**最后更新**: 2026-04-06
