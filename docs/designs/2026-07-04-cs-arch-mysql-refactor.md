# XP 重构：CS 架构 + MySQL 存储

**Date:** 2026-07-04

## Context

当前 XP 是一个"每个开发者本地跑 MCP Server + 连接远端 PostgreSQL"的本地工具。随着团队规模扩大，暴露出四个核心痛点：

1. **部署复杂**：每个人都要配置 Python 环境、依赖、数据库连接
2. **版本不一致**：团队成员运行不同版本的 MCP Server，行为有差异
3. **无法集中管控**：无法在服务端做统一认证、限流、日志监控
4. **客户端单一**：只支持 Claude/Cursor，无法接入 Web 页面、脚本等其他客户端

同时，公司基础设施以 MySQL 为主，PostgreSQL 需要额外维护，存在合规和运维成本问题。

重构目标：迁移到 **CS 架构（MCP Streamable HTTP 远端模式）+ MySQL 存储**，实现本地零安装、集中管控。

---

## Discussion

### 架构方向选择

探索了三个方向：

- **方案 A（最小改造）**：MCP stdio 不动，加 HTTP 中间层，保留 PostgreSQL
- **方案 B（全面迁移）**：完全切换为 HTTP 中心服务 + MySQL + 外置向量服务
- **方案 C（远端 MCP）**：本地什么都不装，Agent 直连远端 MCP Server

最终选择**方案 C**：本地零安装，Agent 通过 MCP Streamable HTTP 协议直连公司服务器，是 MCP 协议演进的推荐方向。

### 向量检索方案选择

核心挑战：MySQL 不像 PostgreSQL 有成熟的 pgvector 扩展，向量能力需要另解。

探索了多个方案：

| 方案 | 语义能力 | 速度 | MySQL 友好 |
|---|---|---|---|
| MySQL 8.4 VECTOR 原生 | 一般 | 快 | 好 |
| 纯 LLM 检索 | 最强 | 慢（2-3s） | 最好 |
| MySQL FULLTEXT | 弱 | 极快 | 最好 |
| 应用层向量计算（numpy） | 强 | 快（<20ms） | 好 |
| FULLTEXT + LLM rerank | 强 | 中（500ms-1s） | 好 |

关键洞察：分层过滤（project + business + team）后，每次查询涉及经验条数通常 < 1000 条，应用层 numpy 计算完全可行。

### A/B Test 决策

由于 LLM rerank 与向量语义匹配各有优劣，且无法事先判断哪个更优，决定通过 **A/B Test** 让数据说话：

- **A 组**：全文检索粗筛 + LLM rerank（纯文本，无向量）
- **B 组**：本地模型（BGE-m3）+ 应用层向量语义匹配
- **指标**：`adoption_rate`（经验采纳率），辅以 search 延迟
- **分流**：按 project_id 固定五五分组
- **决策**：人工对比指标后改配置切换，全量走胜出组

### Embedding 模型选择

原 BGE-small-zh（512维）针对中文优化，但团队 problem 描述为**中英混合**，改用 **BGE-m3（1024维）**，支持 100+ 语言，中英混合效果更好。存储影响：每条 4KB，1 万条 = 40MB，可接受。

### Save 流程设计

原方案依赖端侧 Agent 传入结构化字段（solution、key_decisions 等），但端侧 Agent 性能不稳定，输入质量参差不齐。

改为：**Agent 只传任务原始描述，Server 侧 LLM 负责提炼结构化字段**。

Agent 传入最小集合：
```
task_description     任务原始描述
outcome_description  过程和结果原始描述
outcome              success / partial / failed
project_id           归属项目
```

Server LLM 提炼：`title, problem, solution, key_decisions, tags, type`

### 冲突与重复检测

save 时做相似度检测，根据结果分叉：

- problem 相似 + solution 相似（> 0.85）→ **重复**，提示合并
- problem 相似 + solution 差异大 → **冲突**，LLM 推断冲突类型，进入审核队列

冲突类型（LLM 推断）：
1. `outdated`：旧经验已过时
2. `alternative`：同一问题的不同可行方案
3. `version_diff`：适用于不同技术栈版本
4. `new_may_wrong`：新经验可能有误
5. `condition_diff`：适用条件不同，各有场景

处理原则：系统不自动判断保留哪条，**标记 + 进审核队列 + 人工决定**。

### Feedback 设计

feedback 是指标核心 tool，重新设计语义：

- `adopted`：Agent 明确使用了经验且任务成功
- `rejected`：召回了但没有采用
- `skipped`：未读就跳过（不影响任何指标）

新增 comment 语义分析：
- `"完全不适用"` → 正常降低 confidence
- `"方向对但有误"` → 触发**经验待修正流程**，status=needs_fix，confidence 不变，进入修正队列

修正队列需携带上下文：原经验内容 + Agent 的 comment + 当时的 task_description + outcome_description。

---

## Approach

### 整体架构

```
Agent (Claude/Cursor)
  ↓ HTTPS + MCP Streamable HTTP（本地零安装）
Remote MCP Server（公司统一部署）
  ├── FastAPI + 认证中间件（user_tokens 表）
  ├── Application Layer（DDD 分层结构保留）
  └── MySQL
       ├── 元数据、关系数据、prompt 配置
       └── embedding BLOB（B 组，BGE-m3 1024维）
```

### MCP Tools（三个核心 tool）

```
search(task_description, project_id)
save(task_description, outcome_description, outcome, project_id)
feedback(session_id, adopted_ids, rejected_ids, comment)
```

通过 system prompt 强约束调用时机：
- `search`：任务开始前必须调用
- `save`：任务完成后必须调用
- `feedback`：save 之后紧跟调用

### 人工审核（xp review 统一入口）

| 队列 | 触发条件 | 操作 |
|---|---|---|
| 质量待审 | 质量评分 < 80 | 通过 / 拒绝 / 编辑 |
| 冲突审核 | save 检测到冲突 | keep_new / keep_old / keep_both / merge / add_condition |
| 待修正 | feedback 判定方向对但有误 | 编辑确认 / 驳回 |
| 升层候选 | 每 3 天扫描 | 确认升层 / 忽略 |

### 定时任务

| 任务 | 频率 |
|---|---|
| LLM 提炼重试（retry_count=3 的 pending 经验）| 每 12 小时 |
| 升层候选扫描 | 每 3 天 |

### Prompt 热更新

所有 prompt 存 MySQL `prompt_configs` 表，启动时加载进内存，定时刷新，无需重启服务。

| key | 用途 |
|---|---|
| `extraction_prompt` | save 时提炼结构化字段 |
| `conflict_type_prompt` | 冲突类型推断 |
| `rerank_prompt` | A 组 search LLM 排序 |
| `comment_analysis_prompt` | feedback comment 语义分析 |

---

## Architecture

### Search 流程

```
传入：task_description, project_id
  ↓
层级过滤（MySQL 单次查询）
  project + business（通过 project_business）+ team（通过 business_team）
  过滤掉 conflict_with IS NOT NULL AND status=pending 的冲突待审经验
  ↓
按 project_id hash % 2 确定 ab_group
  ↓
A 组：拉取 id, title, problem, solution
      → LLM rerank（只输出 ID 列表，控制延迟）
      → rerank 失败返回空
B 组：拉取 id, embedding BLOB
      → np.frombuffer 反序列化
      → numpy 批量余弦相似度
      → score > 0.5，取 top 3
  ↓
记录 session（含 ab_group）
返回 top 3 + session_id
```

### Save 流程

```
传入：task_description, outcome_description, outcome, project_id
  ↓
LLM 提炼（最多重试 3 次）
  成功 → title, problem, solution, key_decisions, tags, type
  失败 → status=pending, retry_count=3, raw_input=JSON原始输入
         后台定时任务每 12 小时重试
  ↓
冲突 & 重复检测（按 project_id 查同项目经验）
  B 组：向量余弦相似度
  A 组：MySQL FULLTEXT 相似度
  problem > 0.85 且 solution > 0.85 → duplicate_warning
  problem > 0.85 且 solution 差异大 →
    LLM 推断冲突类型（5 种）
    新经验存入，双方 conflict_with 互标
    插入 conflict_reviews 表
  ↓
质量评分（复用现有 compute_save_quality_score）
  >= 80 → status=active
  <  80 → status=pending
  ↓
B 组：embed(problem) → float32 → BLOB 存入
A 组：不生成 embedding
  ↓
写入 MySQL
```

### Feedback 流程

```
传入：session_id, adopted_ids, rejected_ids, comment
  ↓
校验：所有 ID 必须在 session.experience_ids_injected 中
      不能同时出现在 adopted 和 rejected 列表
  ↓
comment 非空 → LLM 语义分析
  "irrelevant"（完全不适用）→ 正常流程
  "needs_fix"（方向对但有误）→
    rejected 经验 status=needs_fix
    插入 correction_requests（含 task_description、outcome_description）
    confidence 不变
  ↓
写 feedback 表（每条经验一条记录）
  ↓
更新 experience_stats：
  所有召回：hit_count += 1
  adopted： adopted_count += 1，last_adopted_at=now()
  rejected：rejected_count += 1
  重算 adoption_rate
  ↓
更新 experiences：
  adopted：  confidence += 0.1（max 1.0）
  rejected（非 needs_fix）：confidence -= 0.05
  needs_fix：confidence 不变
  全部：recall_count += 1，last_hit_at=now()
  confidence < 0.2 → status=archived
  ↓
更新 sessions：user_accepted = adopted_ids 非空
```

### 数据库变更

**experiences 表新增字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `embedding` | BLOB | BGE-m3 1024维 float32，约 4KB，B 组使用 |
| `ab_group` | ENUM('A','B') | A/B test 分组标记 |
| `conflict_with` | VARCHAR(36) | 冲突的经验 ID |
| `retry_count` | INT | LLM 提炼重试次数，最大 3 |
| `raw_input` | JSON | 提炼失败时保留的原始输入 |

**新增表**：

```sql
-- 冲突审核队列
CREATE TABLE conflict_reviews (
  id               VARCHAR(36)  PRIMARY KEY,
  experience_id_a  VARCHAR(36)  NOT NULL,
  experience_id_b  VARCHAR(36)  NOT NULL,
  conflict_type    VARCHAR(32)  NOT NULL,
  status           ENUM('pending','resolved') NOT NULL DEFAULT 'pending',
  resolution       VARCHAR(32)  NULL,
  condition_note   TEXT         NULL,
  resolved_at      DATETIME     NULL,
  created_at       DATETIME     NOT NULL
);

-- 经验待修正队列
CREATE TABLE correction_requests (
  id                  VARCHAR(36)  PRIMARY KEY,
  experience_id       VARCHAR(36)  NOT NULL,
  session_id          VARCHAR(36)  NOT NULL,
  comment             TEXT         NOT NULL,
  task_description    TEXT         NOT NULL,
  outcome_description TEXT         NOT NULL,
  status              ENUM('pending','fixed','dismissed') NOT NULL DEFAULT 'pending',
  fixed_at            DATETIME     NULL,
  created_at          DATETIME     NOT NULL
);

-- Prompt 热更新配置
CREATE TABLE prompt_configs (
  key         VARCHAR(64)  PRIMARY KEY,
  content     TEXT         NOT NULL,
  updated_at  DATETIME     NOT NULL
);
```

### 模块改动范围

| 模块 | 改动类型 | 说明 |
|---|---|---|
| `server.py` | 重写 | stdio → MCP HTTP Transport，只保留 3 个 tool |
| `backends/mysql.py` | 新建 | 实现 StorageBackend 接口，替换 postgres.py |
| `embeddings.py` | 小改 | 模型名改为 BGE-m3，维度常量改为 1024 |
| `application/commands.py` | 小改 | SaveCommand 字段变更 |
| `handlers/save_handler.py` | 重写 | 加 LLM 提炼、冲突检测逻辑 |
| `handlers/search_v2_handler.py` | 重写 | A/B 分流、层级过滤优化 |
| `handlers/feedback_v2_handler.py` | 重写 | comment 语义分析、stats 完整更新 |
| `handlers/promotion_handler.py` | 基本不变 | 业务逻辑复用，存储层切换即可 |
| `domain/` 各文件 | 基本不变 | 业务逻辑可复用 |
| `llm.py` | 新建 | 统一 LLM 调用入口 |
| `scheduler.py` | 新建 | 定时任务（重试 + 升层扫描）|

### LLM 统一配置

```
XP_LLM_API_BASE    API 地址（指向公司内部 LLM 服务）
XP_LLM_API_KEY     认证 key
XP_LLM_MODEL       模型名称，默认 gpt-4o-mini
XP_LLM_TIMEOUT     超时时间，默认 30s
```

所有 prompt 内容与模型配置解耦，单独存 `prompt_configs` 表，支持热更新。

---

### Prompt 初始内容

**extraction_prompt**
```
你是一个工程经验提炼助手。根据以下任务信息，提炼出结构化的工程经验。

## 输入
任务描述：{task_description}
任务结果：{outcome_description}
结果状态：{outcome}

## 输出要求
严格按照以下 JSON 格式输出，不要输出其他内容：
{
  "title": "10-20字的经验标题，概括核心问题和解法",
  "problem": "清晰描述问题场景和背景，50字以上",
  "solution": "具体的解决方案和步骤，50字以上",
  "key_decisions": "关键决策点和踩坑点，30字以上",
  "tags": ["技术栈标签", "最多5个"],
  "type": "bugfix 或 feature 或 pattern 三选一"
}
```

**conflict_type_prompt**
```
以下两条工程经验针对相似问题给出了不同方案，请判断冲突类型。

## 已有经验
问题：{existing_problem}
方案：{existing_solution}
创建时间：{existing_created_at}
采纳率：{existing_adoption_rate}

## 新经验
问题：{new_problem}
方案：{new_solution}

## 冲突类型
请从以下类型中选择一个，只输出类型名称：
- outdated：旧经验已过时，新经验是更好的替代
- alternative：同一问题的不同可行方案
- version_diff：适用于不同技术栈版本
- new_may_wrong：新经验可能有误，旧经验更可靠
- condition_diff：适用条件不同，各有适用场景
```

**rerank_prompt**
```
根据以下任务描述，从候选经验中选出最相关的至多3条。

## 任务
{task_description}

## 候选经验
{candidates}

## 输出要求
只输出 JSON 数组，包含最相关的经验 ID，按相关度降序排列：
["id-1", "id-2", "id-3"]
若没有相关经验，输出：[]
```

**comment_analysis_prompt**
```
以下是用户对一条工程经验的反馈 comment，请判断反馈语义类型。

## 反馈内容
{comment}

## 判断规则
- 如果反馈表达"经验完全不适用、方向错误、和当前问题无关"，输出：irrelevant
- 如果反馈表达"经验思路/方向是对的，但某些细节、版本、参数有误"，输出：needs_fix

只输出一个词：irrelevant 或 needs_fix
```

---

### 本地开发测试链路

重构后本地测试比现在更简单，不需要配置 stdio MCP：

```
Agent (Cursor/Claude)
  ↓ http://localhost:8000/mcp
本地 FastAPI 进程（uvicorn 启动）
  ↓
本地 MySQL（Docker 启动）
```

Agent 配置只需把 URL 指向 `http://localhost:8000/mcp`，对 Claude/Cursor 完全透明。

**Docker 启动本地 MySQL**：
```bash
docker run -d \
  --name xp-mysql \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=xp \
  -p 3306:3306 \
  mysql:8.4
```

**环境变量**（`.env`）：
```
DATABASE_URL=mysql+aiomysql://root:root@localhost:3306/xp
XP_LLM_API_BASE=https://...
XP_LLM_API_KEY=...
XP_LLM_MODEL=gpt-4o-mini
XP_LLM_TIMEOUT=30
```

---

### 实施决策

- **从零实现**：不在现有代码上做增量修改，重新构建，避免历史包袱
- **实现顺序**：依赖 → 模型 → LLM → Embedding → 存储层 → Handlers → 定时任务 → 传输层 → 容器组装
- **测试策略**：每个模块实现后本地单测验证，全部完成后端到端联调
