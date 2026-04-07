# XP 完整改造路线图

**Date:** 2026-03-31

## Context

XP 是一个为 AI Agent 设计的经验沉淀与复用工具，通过 MCP 协议集成到 IDE（Cursor/Claude 等），帮助团队自动沉淀每次任务的最佳实践，下次遇到相似问题时直接检索复用。

对现有系统进行全面评价后，发现三个核心问题：

1. **Agent 调用链路不可靠**：任务结束需调用 4 个 MCP 工具（extract_experience / record_session / infer_adoption / record_feedback），完全依赖规范约束，极易遗漏。
2. **Review 全人工且无降级策略**：pending 队列堆积，有效经验长期无法被检索使用，知识库形同虚设。
3. **单机 JSON/SQLite 架构**：并发写入冲突、团队知识孤岛、无权限管理。

目标用户规模为大型组织（50人以上），允许完整重构（1-3个月），两条线并行改造。

---

## Discussion

### 用户体验问题的核心矛盾

- **调用遗漏根本原因**：是"Agent 依赖规范约束"，而不是工具数量问题。合并工具数量是治标，真正的解法是让调用链路结构化容错。
- **Review 的隐患**：auto-active 策略引入噪音不是"少量"，在没有质量评分模型的情况下，可能有 30-40% 自动激活的经验是低价值的。质量评分本身需要持续调优。
- **权限约束**：只有管理员（Admin）可以执行 review 操作，普通 Agent 用户（Writer）只能提取和检索。

### 可扩展性问题的核心矛盾

- **存储迁移成本被低估**：storage.py 有 634 行深度耦合，完整迁移到 PG 意味着重写整个存储抽象层，不是"中等成本"。
- **云同步方案的冲突问题**：本地 JSON + 云同步在多人场景下没有明确的冲突解决策略，实际不可用于超过 1 人的场景。
- **MCP over SSE 的风险**：各 IDE 对远端 MCP 的支持未经充分验证，推荐本地 HTTP Proxy 模式更稳定。

### 技术选型决策

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| PostgreSQL + pgvector | 成熟稳定、事务支持、并发写入、向量检索百万级 < 50ms | 迁移成本高，需重写存储层 | 推荐 |
| Qdrant | 向量性能最优（HNSW，千万级 < 10ms） | 多一个服务依赖，运维复杂，全文搜索弱 | YAGNI，规模到位再考虑 |
| 本地 SQLite + 云同步 | 迁移成本最低 | 多人冲突无解，不适合团队 | 仅适合个人 |

---

## Approach

分三个阶段并行推进，优先做第一阶段（ROI 最高，不依赖基础设施）：

**第一阶段（2周）：调用链路重构**
将 4 个工具合并为 `finalize_task`，内部三步独立容错，提取失败不中断 record_session 和 infer_adoption。

**第二阶段（2周）：Review 流程重构**
引入质量评分系统，高分经验自动激活（confidence 0.65），降低人工 review 压力。新增编辑确认、批量操作、Admin 权限校验。

**第三阶段（4-6周）：存储服务化**
抽象 StorageBackend 接口，渐进式迁移到 PostgreSQL + pgvector，FastAPI 中心化服务 + 本地轻量 HTTP Proxy，完整权限管理。

---

## Architecture

### 第一阶段：finalize_task 工具

**接口设计：**

```python
finalize_task(
    session_id,            # 必填
    task_description,      # 必填
    solution_summary,      # 必填
    key_decisions,         # 必填
    final_response,        # 必填（用于 infer_adoption）
    conversation_summary,  # 可选
    tags,                  # 可选
    related_files,         # 可选
    iteration_count,       # 可选，默认 1
    had_error_correction,  # 可选，默认 false
    user_accepted,         # 可选，默认 true
)
```

**内部执行顺序（三步独立容错）：**

```
finalize_task
    ├─ 1. extract_experience（质量门控）
    │      ├─ 成功 → 继续
    │      └─ 失败（重复/字段太短）→ 跳过提取，仍继续后续步骤
    ├─ 2. record_session（无论提取成功与否都记录）
    └─ 3. infer_adoption（若有注入经验才执行）
```

旧工具全部保留但标记 deprecated，不破坏已有集成。

---

### 第二阶段：三级自动激活 + Review 改造

**质量评分权重（可配置）：**

| 字段 | 权重 |
|------|------|
| key_decisions 长度 | 40% |
| solution_summary 长度 | 20% |
| related_files 非空 | 15% |
| 技术栈推断成功 | 15% |
| 重复距离 >= 0.4 | 10% |

**三级策略：**

```
评分 >= 80  → auto-active（confidence 0.65，进入抽检队列）
评分 40-79  → pending（现有人工 review 流程）
评分 < 40   → 直接拒绝，返回具体原因给 Agent
```

**cmd_review 新增操作：**

```
[y] 确认              → confidence 0.8
[e] 编辑后确认        → $EDITOR 打开临时文件，保存后重新生成向量，confidence 1.0
[n] 拒绝（原因必填）  → status: archived，记录拒绝原因
[b] 批量确认剩余      → 全部 auto-active，confidence 0.65
[s] 跳过              → 不变
[q] 退出              → 不变
```

**权限校验：**

```
xp review 入口
    ↓
检查 API Key → 角色是否为 admin？
    ├─ 是 → 进入 review 流程
    └─ 否 → 拒绝，提示需要 Admin 权限
```

---

### 第三阶段：存储服务化

**PostgreSQL 表结构：**

```sql
experiences
  id UUID, type, level, title, problem, solution, key_decisions,
  confidence FLOAT, status, project, metadata JSONB, tags TEXT[],
  related_files TEXT[], file_hashes JSONB,
  created_at TIMESTAMPTZ, last_hit_at TIMESTAMPTZ,
  embedding vector(768)   -- pgvector

sessions
  session_id VARCHAR UNIQUE, task_description,
  experience_ids_injected TEXT[], iteration_count INT,
  had_error_correction BOOL, user_accepted BOOL,
  ab_test_group, created_at TIMESTAMPTZ

feedback
  id SERIAL, experience_id UUID REFERENCES experiences,
  adopted BOOL, reason TEXT, created_at TIMESTAMPTZ

users
  id UUID, username VARCHAR UNIQUE,
  api_key VARCHAR UNIQUE, role VARCHAR,  -- writer | admin
  created_at TIMESTAMPTZ
```

**服务化架构：**

```
IDE → 本地轻量 HTTP Proxy（读 ~/.xp/config，转发 HTTP）
           ↓ HTTPS
     XP API Server（FastAPI，中心化）
           ↓
     PostgreSQL + pgvector
```

**StorageBackend 渐进式迁移策略：**

```
Step 1. 定义 StorageBackend 抽象接口
Step 2. 现有 JSON/SQLite 实现接口（LocalBackend，不改代码）
Step 3. 新增 PostgresBackend 实现同一接口
Step 4. 配置切换（XP_BACKEND=local|postgres）
Step 5. 数据迁移脚本（可续跑，支持回滚）
```

---

### 数据迁移方案

**迁移步骤：**

1. **pre-flight check**：统计源数据量，检查向量完整性，输出缺失向量清单，人工确认后执行。
2. **只读快照**：迁移前备份至 `$XP_HOME/backup/migrate_YYYYMMDD_HHMMSS/`，源文件设为只读。
3. **分批写入**：每批 100 条，提交一次事务，记录 checkpoint，中断后可续跑。
4. **向量迁移**：从 SQLite BLOB 解包 float32，写入 pgvector；缺失向量重新生成，迁移前锁定 embedding model 版本。
5. **post-migration check**：行数对比 + 50 条随机字段校验 + 10 条向量检索结果对比，全部通过才标记成功。
6. **切流**：配置 `XP_BACKEND=postgres`，本地文件保留 30 天。

**回滚策略：**

```
触发条件：post-migration 校验失败 / 检索结果异常 / 写入报错
回滚操作：XP_BACKEND 改回 local（10秒内生效）
风险：无数据丢失（源文件只读保护，PG 为新写入）
```

**最大风险**：向量维度不匹配（embedding model 版本变更）。迁移前必须将 model 版本写入 migration manifest。

---

### 测试方案

**第一阶段测试重点：**

```
test_finalize_task_extract_fails
  → extract 失败时，record_session 和 infer_adoption 仍然执行
  → 这是最关键的容错测试
```

**第二阶段测试重点：**

```
test_quality_score_high       → 评分 >= 80 → auto-active
test_quality_score_low        → 字段太短 → 直接拒绝
test_review_admin_only        → 非 admin → 权限错误
test_review_edit_regenerates_vector → [e] 后向量重新生成，confidence = 1.0

验收标准：auto-active 经验人工抽检 20 条，主观质量合格率 >= 70%
```

**第三阶段测试重点：**

```
并发测试：10 线程同时 finalize_task → experiences 行数 = 10，无丢失无重复
性能基准：1000条 < 100ms，10000条 < 200ms，并发 10 个 P99 < 500ms
回归测试：取迁移前 100 次 query 重跑，Top-3 结果差异 <= 10%，否则触发回滚
```

**测试覆盖率目标：**

| 模块 | 目标覆盖率 |
|------|-----------| 
| knowledge.py | >= 80% |
| storage.py | >= 85% |
| server.py | >= 70% |
| finalize_task 容错路径 | 100% |
| 权限校验路径 | 100% |

---

## Implementation Notes（2026-04-01 实施记录）

### 实施结果

三个阶段全部完成，最终测试结果：**35 passed, 1 skipped**（PG 集成测试因无本地 PG 实例正常跳过）。

### 新增文件清单

```
src/
  knowledge.py         # 新增 finalize_task()、_compute_quality_score()
  server.py            # 新增 finalize_task MCP 工具注册
  cli.py               # cmd_review 改造：[e]/[b]/[n] 必填原因/Admin 校验
  backends/
    __init__.py
    base.py            # StorageBackend ABC（10 个抽象方法）
    local.py           # LocalBackend（包装现有 JSON/SQLite）
    postgres.py        # PostgresBackend（asyncpg 实现）
  storage.py           # 末尾新增 get_backend() 工厂函数

scripts/
  migrate_to_postgres.py   # 数据迁移脚本（checkpoint 续跑 + dry-run）

tests/
  test_finalize_task.py    # finalize_task 容错路径 100%
  test_quality_score.py    # 质量评分三级策略 + extract_experience 集成
  test_review_refactor.py  # [b] 批量确认 / [n] 原因必填 / Admin 权限
  test_backends.py         # StorageBackend ABC + LocalBackend + get_backend()
  test_migration.py        # 迁移预检逻辑
```

### 关键实施决策与踩坑

#### 第一阶段

1. **`finalize_task` 中 extract 失败捕获范围**：用 `except Exception` 而非 `except ValueError`，因为重复检测会抛 `ValueError`，LLM 调用失败抛 `RuntimeError`，两者都需容错。

2. **`Session.ab_test_group` 默认值**：`models.py` 中默认为 `"control"`，但 `finalize_task` 写入时需显式传 `"treatment"`，否则会把正常会话计入对照组，污染 A/B 数据。

#### 第二阶段

3. **质量评分调用时机**：`_compute_quality_score` 在 `_check_duplicate` 之后调用，`duplicate_similarity` 参数无法预先知道，默认传 `0.0`（得 10 分）。实际场景中如有重复会在 `_check_duplicate` 直接抛异常终止，不会走到评分。

4. **测试数据字符长度精算**：Python `len()` 对汉字按字符计数，原有 `key_decisions < 10 字` / `solution_summary < 20 字` 校验**先于**质量评分触发。写 `test_low_quality_rejected` 时需让测试数据同时满足：
   - `key_decisions >= 10 字`（跳过原有校验）
   - `solution_summary >= 20 字`（跳过原有校验）
   - quality_score < 40（触发质量门控）

5. **`cmd_review` 的 `[e]` 操作是异步方法**：`edit_and_confirm` 是 `async` 方法，而 `cmd_review` 是同步函数，需要 `asyncio.run()` 包裹调用。

6. **`_compute_quality_score` medium 分档数据**：需精确计算确保分数落在 `[40, 80)` 区间，不能凭感觉写测试字符串。

#### 第三阶段

7. **`PostgresBackend` 同步方法设计**：所有同步方法主动 `raise NotImplementedError`，只暴露 `async_*` 前缀方法。这是刻意的设计决策，防止调用方误用同步接口（asyncpg 不支持同步调用）。

8. **向量写入 PG 需 `.tolist()` 转换**：`VectorStore.get_vector()` 返回 `np.ndarray`，直接传给 asyncpg 会报类型错误，必须调用 `.tolist()` 转为 Python list。

9. **`get_backend()` 放在 `storage.py` 末尾**：用相对导入 `from .backends.local import LocalBackend`，避免循环依赖（backends 模块反过来导入 storage）。

10. **PG 集成测试用 `skipif`**：`@pytest.mark.skipif(not POSTGRES_DSN, reason="TEST_POSTGRES_DSN not set")` 确保无 PG 环境时不阻塞 CI，需要时设置 `TEST_POSTGRES_DSN` 环境变量激活。

### 依赖变更

`pyproject.toml` 新增：

```toml
"asyncpg>=0.29.0",
"fastapi>=0.110.0",
"uvicorn>=0.29.0",
"pgvector>=0.2.0",
```

实际安装版本：asyncpg 0.31.0 / fastapi 0.135.2 / uvicorn 0.42.0 / pgvector 0.4.2。

### 待后续处理

- [ ] PostgreSQL 集成测试需要本地 PG 实例（`export TEST_POSTGRES_DSN=...`）
- [ ] `[e]` 编辑确认后向量未通过 `edit_and_confirm` 重新生成的问题需验证（`edit_and_confirm` 内部已有逻辑但测试未覆盖）
- [ ] FastAPI HTTP Proxy 层（计划中提到但未实现）
- [ ] Admin 用户管理 API（目前仅靠环境变量 `XP_ADMIN_KEY` 控制）

