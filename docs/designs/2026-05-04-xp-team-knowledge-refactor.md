# xp 重构方案：团队级最佳实践沉淀与召回系统

**Date:** 2026-05-04

## Context

xp 原先定位为个人 agent 经验沉淀工具，使用本地文件存储，6 个 MCP tool，单人使用。本次重构的核心动因：

1. **定位升级**：从个人工具升级为团队级 coding 最佳实践沉淀 + 召回系统
2. **支持多人协作**：需要中心化存储，团队成员共享经验知识库
3. **开箱即用**：用户侧零配置，直接连接远端 MCP Server
4. **精简 MCP tool**：从 6 个精简为 3 个（search / save / feedback）
5. **Agent 优化**：tool 描述引导 agent 正确调用，确保沉淀的经验方便召回

## Discussion

### 知识层级结构

系统引入三层知识层级，对应组织结构：

```
Team（团队）—— 最抽象，跨业务通用
  └── Business（业务）—— 中等抽象
        └── Project（项目 = Git 仓库）—— 最具体
```

- 经验天然属于某个层级，但可以被人工**双向迁移**（提升或降级）
- Project 经验由 agent 自动沉淀；Business / Team 经验由人工从下层遴选
- Agent 定时扫描，找出「提升候选」，推荐给人工决策

### 提升判断逻辑

Agent 通过多维度评分决定是否推荐提升：

```
提升得分 = 跨项目出现次数 × 0.5
         + adoption_rate × 0.3
         + min(recall_count / 10, 1) × 0.2

得分 > 0.7 → 标记为「提升候选」，推送给人工审核
```

触发条件：
- 同 Business 下 ≥ 2 个不同 Project 存在语义相似经验（相似度 > 0.85）
- adoption_rate > 0.6 且 recall_count > 5
- created_at > 30 天前（排除不稳定的新经验）

Agent 只做推荐，人工来决策（支持确认提升、手动降级、删除）。

### MCP tool 精简

原 6 个 tool（search_best_practices / extract_experience / record_session / record_feedback / infer_adoption / finalize_task）被精简为 3 个：

| 旧 tool | 合并到 |
|---------|--------|
| search_best_practices | search |
| extract_experience | save |
| record_session | search（搜索时记录 session） |
| record_feedback | feedback |
| infer_adoption | feedback（隐式推断兜底） |
| finalize_task | 拆分到 save + feedback |

### 项目元信息收集

经过讨论，最终方案：agent 调用 search 时，主动读取当前项目的 `package.json` / `pyproject.toml` / `go.mod` 等配置文件，将关键依赖信息作为参数传入。通过 tool description 引导 agent 完成这一步，server 解析后与 project_id 关联存储，用于搜索时的技术栈过滤增强。

MCP roots 能力虽然存在，但在远端部署场景下 server 无法读取客户端本地文件，因此不采用。

### 部署模式

始终中心化，不支持纯本地模式：
- 用户侧只需在 MCP 配置里填入 server URL 和 personal token
- 团队管理员 Docker 一键部署
- MCP 和 REST API 共享同一个 Service 层（方案 C），单进程部署

### 指标体系

核心健康指标三个：

| 指标 | 健康阈值 |
|------|---------|
| 采纳率（helpful / total_recall） | > 60% |
| 未命中率（无经验的任务 / 总任务） | < 20% |
| Pending 堆积量 | < 20 条 |

## Approach

1. **中心化部署**：单进程 FastAPI，MCP endpoint + REST endpoint 共享 Service 层，连接 PostgreSQL + pgvector
2. **层级化知识库**：Team → Business → Project 三层，经验可双向流动，agent 推荐提升候选
3. **3 个 MCP tool**：search（召回）/ save（沉淀）/ feedback（反馈），覆盖完整工作流
4. **开箱即用**：用户侧零配置，管理员 Docker 一键部署

## Architecture

### 整体部署图

```
用户本地（Cursor / Claude Desktop）
    │
    │  MCP HTTP SSE
    ▼
xp-server（单进程，FastAPI）
    ├── /mcp     → MCP endpoint（search / save / feedback）
    └── /api     → REST endpoint（CLI / Web UI / 人工 review）
    │
    ▼
PostgreSQL + pgvector
    ├── experiences（经验表 + embedding 向量）
    ├── search_events（搜索事件）
    ├── feedback_events（反馈事件）
    └── projects / businesses / teams（层级表）
```

### Tool 1：`search`

**调用时机**：agent 判断是 coding 任务时，在任务开始前调用。

**输入参数**：
```json
{
  "task_description": "修复 userId 为 null 导致的 NPE",
  "project_id": "github.com/org/my-service",
  "project_manifest": "<package.json 或 pyproject.toml 的关键内容，限 2000 tokens>"
}
```

参数来源：
- `task_description`：agent 对当前任务的描述，≤ 500 字
- `project_id`：从 `git remote get-url origin` 提取并标准化，无 git 时用目录绝对路径
- `project_manifest`：agent 读取 `package.json` / `pyproject.toml` / `go.mod`（按优先级取第一个），只传 dependencies 相关字段，超出 2000 tokens 截断

**执行逻辑**：
```
1. 解析 project_manifest，提取 language / framework / top_dependencies
   更新或创建 ProjectMetadata 记录

2. 构造搜索上下文：
   query_text = task_description + " " + language + " " + top_dependencies
   query_embedding = embed(query_text)

3. 并发向量搜索三个层级（各取 Top-10，相似度 > 0.5 保留）：
   Project 经验：WHERE project_id = ? AND status = 'active'
   Business 经验：通过 project_id 关联
   Team 经验：通过 business_id 关联

4. 技术栈过滤增强：
   经验 tags 与 language/dependencies 有交集 → 相似度得分 × 1.15

5. 合并排序（Project ×1.2, Business ×1.0, Team ×0.9），去重，取 Top-5

6. 记录 search_event：{ query_embedding, result_ids, project_id, session_id, timestamp }

7. 返回经验列表 + search_event_id
```

### Tool 2：`save`

**调用时机**：agent 完成编码任务后自动调用，无论成功与否。

**输入参数**：
```json
{
  "task_description": "...",
  "solution": "...",
  "key_decisions": "...",
  "tags": ["java", "null-safety"],
  "project_id": "github.com/org/my-service",
  "search_event_id": "evt_xyz",
  "outcome": "success | partial | failed"
}
```

**初始 confidence**：success → 0.65，partial → 0.55，failed → 0.40

**执行逻辑**：
```
1. LLM 提取结构化信息：
   - 生成 title（≤15字，动词开头）
   - 推断 type：bugfix / feature / pattern
   - 推断 level：L1（具体步骤）/ L2（设计模式）/ L3（架构原则）

2. 向量化：embed(title + solution + key_decisions) → 存入 pgvector

3. 重复检测：
   similarity > 0.85 → 返回警告，建议 agent 确认是否合并
   0.70 < similarity < 0.85 → 记录关联，不阻断

4. 质量评分：
   solution > 50字 → +30
   key_decisions > 30字 → +30
   tags ≥ 2 → +20
   outcome = success → +20，否则 +10
   score ≥ 80 → auto-activate（status=active）
   score < 80 → status=pending，等待人工 review

5. 关联 search_event（标记召回空缺补充）

6. 返回 experience_id
```

### Tool 3：`feedback`

**调用时机**：search 结果对本次任务有帮助时，任务结束后调用。

**输入参数**：
```json
{
  "search_event_id": "evt_xyz",
  "helpful_ids": ["exp_001"],
  "unhelpful_ids": ["exp_002"],
  "comment": "可选的文字说明"
}
```

**执行逻辑**：
```
1. 校验 ids 合法性（必须在该 search_event 的 result_ids 里）

2. 更新 confidence：
   helpful → confidence = min(confidence + 0.1, 1.0)，更新 last_hit_at
   unhelpful → confidence = max(confidence - 0.05, 0.0)
   confidence < 0.2 → 标记为待归档

3. 记录 feedback_event，计算 adoption_rate

4. 异步处理 comment：LLM 分析 unhelpful 原因，打 improvement_hint 标签

5. 异步重新计算「提升候选得分」
```

**隐式采纳推断**（兜底机制）：
```
if search_event 无对应 feedback AND 后续有 save 调用：
    对比 save.solution 与 search 结果的语义相似度
    similarity > 0.6 → 隐式采纳，confidence += 0.05
    similarity < 0.3 → 未采纳，不调整
```

### 数据模型要点

```python
Experience:
    id, title, type, level
    problem, solution, key_decisions
    tags: list[str]
    confidence: float       # 0.0 ~ 1.0
    status: pending | active | archived
    scope_type: project | business | team
    scope_id: str
    promoted_to: UUID | None  # 提升副本的 id
    demoted_from: UUID | None # 降级副本的 id
    recall_count: int
    adoption_rate: float
    last_hit_at: datetime
    created_at: datetime
    embedding: vector(384)   # pgvector

SearchEvent:
    id, session_id, project_id
    query_embedding: vector(384)
    result_ids: list[UUID]
    timestamp: datetime

FeedbackEvent:
    id, search_event_id
    helpful_ids, unhelpful_ids: list[UUID]
    comment: str | None
    timestamp: datetime
```

### 鉴权与多租户

```
personal_token → 解析 user_id → 所属 team_id
project_id → 校验是否属于该 team

权限：
  save / search：project 成员
  人工 review / 提升 / 降级：business owner 或 team admin
```
