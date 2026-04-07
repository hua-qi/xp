# MCP Tools v2：search / save / feedback

## 概述

xp v2 将 MCP tool 从 6 个精简为 3 个，覆盖 agent 工作流的完整闭环：任务开始前召回经验（search）、任务完成后沉淀经验（save）、反馈经验是否有用（feedback）。

**架构**：本地 xp-server 完全无状态，不持有 `database_url`，只持有 `token`。所有业务逻辑（向量搜索、LLM 提取、质量评分、升层扫描）运行在 Supabase Edge Function；本地 `call_tool` 通过 `EdgeFunctionClient` 携带 token 转发请求，直接返回结果。

## 设计思路

### 工具映射关系

| v1 tool | 合并到 v2 |
|---------|-----------|
| `search_best_practices` | `search` |
| `extract_experience` | `save` |
| `record_session` | `search`（搜索时同步记录 session） |
| `record_feedback` | `feedback` |
| `infer_adoption` | `feedback`（隐式推断兜底） |
| `finalize_task` | 拆分到 `save` + `feedback` |

### 调用时序

```
任务开始
  └── 是 coding 任务？
        └── YES → 调用 search（召回相关经验）
任务进行中
  └── （使用召回的经验）
任务完成
  ├── 调用 save（沉淀本次经验）
  └── search 有结果 且 经验有帮助？
        └── YES → 调用 feedback（上报采纳信号）
```

## 实现细节

### Tool 1：`search`

**调用时机**：agent 判断是 coding 任务时，在任务开始前调用。

**输入参数**：

```json
{
  "task_description": "修复 userId 为 null 导致的 NPE",
  "project_id": "github.com/org/my-service",
  "project_manifest": "<package.json 或 pyproject.toml 的关键内容>"
}
```

参数说明：

| 参数 | 必填 | 来源 | 限制 |
|------|------|------|------|
| `task_description` | 是 | agent 描述当前任务目标 | ≤ 500 字 |
| `project_id` | 是 | 从 `git remote get-url origin` 提取并标准化，无 git 时用目录绝对路径 | 标准化格式：`github.com/org/repo` |
| `project_manifest` | 是 | agent 读取 `package.json` / `pyproject.toml` / `go.mod`（按优先级取第一个），只传 dependencies 相关字段 | ≤ 2000 tokens，超出截断 |

**执行逻辑**：

```
1. 解析 project_manifest：
   提取 language / framework / top_dependencies
   更新或创建 ProjectMetadata 记录

2. 构造搜索上下文：
   query_text = task_description + " " + language + " " + top_dependencies
   query_embedding = embed(query_text)

3. 并发向量搜索三个层级（各取 Top-10，相似度 > 0.5 保留）：
   Project 经验：WHERE scope_id = project_id AND status = 'active'
   Business 经验：通过 project_id 关联 business_id
   Team 经验：通过 business_id 关联 team_id

4. 技术栈过滤增强：
   经验 tags 与解析出的 language/dependencies 有交集
   → 相似度得分 × 1.15

5. 合并排序：
   Project ×1.2, Business ×1.0, Team ×0.9
   去重（同一经验的不同层级副本只保留最高分）
   取 Top-5 返回

6. 记录 search_event：
   { query_embedding, result_ids, project_id, session_id, timestamp }

7. 返回：经验列表 + search_event_id
```

**返回示例**：

```json
{
  "search_event_id": "evt_xyz",
  "results": [
    {
      "id": "exp_001",
      "title": "Service 层入口 null 检查模式",
      "level": "L1",
      "source_level": "Project",
      "tags": ["java", "null-safety"],
      "problem": "...",
      "solution": "...",
      "key_decisions": "..."
    }
  ]
}
```

---

### Tool 2：`save`

**调用时机**：agent 完成编码任务后自动调用，无论成功与否。

**输入参数**：

```json
{
  "task_description": "修复 userId 为 null 导致的 NPE",
  "solution": "在 UserService.getUser() 入口增加 Objects.requireNonNull 检查",
  "key_decisions": "在 Service 层而非 DAO 层做 null 检查，因为这是业务约束",
  "tags": ["java", "null-safety"],
  "project_id": "github.com/org/my-service",
  "search_event_id": "evt_xyz",
  "outcome": "success"
}
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `task_description` | 是 | 任务描述 |
| `solution` | 是 | 解决方案，≥ 50 字效果更好 |
| `key_decisions` | 是 | 关键决策或踩坑点，≥ 30 字效果更好 |
| `tags` | 是 | 技术栈标签，建议 ≥ 2 个 |
| `project_id` | 是 | 同 search 的 project_id |
| `search_event_id` | 否 | 若本次任务前调用过 search，传入 event_id 关联 |
| `outcome` | 是 | `success` / `partial` / `failed` |

**初始 confidence**：`success` → 0.65，`partial` → 0.55，`failed` → 0.40

**执行逻辑**：

```
1. LLM 提取结构化信息：
   - 生成 title（≤15字，动词开头，如「Service 层入口 null 检查」）
   - 推断 type：bugfix / feature / pattern
   - 推断 level：
       L1 = 具体步骤（这个文件这个方法怎么写）
       L2 = 设计模式（这类问题的通用解法）
       L3 = 架构原则（跨系统通用的思路）

2. 向量化：
   embed_text = title + " " + solution + " " + key_decisions
   → 生成 embedding 存入 pgvector

3. 重复检测（在同 project 内）：
   similarity > 0.85 → 返回警告，建议 agent 确认是否合并
   0.70 ~ 0.85 → 记录关联，不阻断

4. 质量评分（决定是否 auto-activate）：
   solution > 50字 → +30
   key_decisions > 30字 → +30
   tags ≥ 2 → +20
   outcome = success → +20，否则 +10
   score ≥ 80 → status = active（auto-activate）
   score < 80 → status = pending（等待人工 review）

5. 关联 search_event（标记为对召回空缺的补充）

6. 异步触发：检查是否满足「提升候选」条件

7. 返回 experience_id
```

---

### Tool 3：`feedback`

**调用时机**：search 返回的经验对本次任务有帮助时，任务结束后调用。

**输入参数**：

```json
{
  "search_event_id": "evt_xyz",
  "helpful_ids": ["exp_001"],
  "unhelpful_ids": ["exp_002"],
  "comment": "exp_001 的解法直接复用，exp_002 提到的方案在我们项目里不适用"
}
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `search_event_id` | 是 | 对应 search 返回的 event_id |
| `helpful_ids` | 否 | 有帮助的经验 id 列表 |
| `unhelpful_ids` | 否 | 无帮助的经验 id 列表 |
| `comment` | 否 | 文字说明，用于 LLM 分析改进方向 |

**执行逻辑**：

```
1. 校验 ids 合法性：
   helpful_ids 和 unhelpful_ids 都必须在该 search_event 的 result_ids 中
   防止 agent 传入幻觉 id

2. 更新 confidence：
   helpful → confidence = min(confidence + 0.1, 1.0)，更新 last_hit_at
   unhelpful → confidence = max(confidence - 0.05, 0.0)
   confidence < 0.2 → 标记为待归档（需人工确认）

3. 记录 feedback_event：
   计算 adoption_rate = helpful_count / total_recall_count

4. 异步处理 comment：
   LLM 分析 unhelpful 的原因（过时 / 技术栈不符 / 描述不清）
   给经验打 improvement_hint 标签，供人工 review 时参考

5. 异步重新计算「提升候选得分」
```

**隐式采纳推断（兜底机制）**：

当 agent 调用了 search 但未调用 feedback 时（任务结束后通过 save 判断任务已结束），系统自动推断：

```
if search_event 无对应 feedback AND 后续有 save 调用：
    对比 save.solution 与 search 结果 solution 的语义相似度
    similarity > 0.6 → 隐式采纳，confidence += 0.05（小幅增加）
    similarity < 0.3 → 未采纳，不调整
```

## 指标体系

| 层级 | 指标 | 健康阈值 | 含义 |
|------|------|---------|------|
| 召回质量 | 采纳率 | > 60% | 被召回的经验有多少真正帮到了人 |
| 召回质量 | 未命中率 | < 20% | agent 解决了问题但系统没有相关经验 |
| 召回质量 | 零结果率 | < 10% | 搜索没搜到任何东西 |
| 经验质量 | 僵尸经验率 | < 15% | 90 天未召回的比例 |
| 经验质量 | Pending 堆积量 | < 20 条 | 等待人工 review 的积压 |
| 使用深度 | feedback 覆盖率 | > 40% | agent 有没有养成反馈习惯 |

## 相关文件

- `docs/design/adr/ADR-002-team-knowledge-hierarchy-and-centralized-deployment.md` - 架构决策记录
- `docs/features/team-knowledge-hierarchy.md` - 层级知识库与经验流动详解
- `docs/designs/2026-05-04-xp-team-knowledge-refactor.md` - 原始设计草稿
- `src/server.py` - MCP tool 注册与实现入口（v2 起调用 EdgeFunctionClient 转发）
- `src/edge_client.py` - EdgeFunctionClient，封装对 Supabase Edge Function 的 HTTP 调用

---
**文档版本**: v1.1  
**最后更新**: 2026-06-04
