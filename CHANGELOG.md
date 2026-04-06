# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.6.0] - 2026-05-04

### Breaking Changes

- **`DATABASE_URL` 现为必须配置项**：不再支持本地 SQLite/JSON 回退路径，缺失时抛 `RuntimeError`
- 删除 `src/storage.py`（遗留 SQLite/JSON 存储层）
- 删除 `src/infrastructure/stores/`（`experience_store.py`、`vector_store.py`、`metrics_store.py`）
- `UnitOfWork` 只接受 `PostgresBackend` 实例，不再支持无参构造

### Added

- `AbstractUnitOfWork` 新增 `analytics: AbstractAnalyticsStore` 抽象属性
- `AbstractAnalyticsStore` 提供统一接口：`record_session`、`get_stats`、`get_feedback_summary`、`get_search_stats`、`get_adoption_rate`
- `_PgAnalyticsStore` 实现全部 analytics SQL 查询
- `InMemoryAnalyticsStore`（在 `tests/helpers/fake_uow.py`）供单元测试使用

### Changed

- 所有 handler（`StatsHandler`、`AnalyzeHandler`、`SessionHandler`、`SearchHandler`、`ExtractHandler`、`InferAdoptionHandler`）完全通过 `UoW.analytics` 访问数据，不再直接 import storage
- `container.py`：`build_command_bus` 缺失 `DATABASE_URL` 时抛 `RuntimeError`，消息明确引导配置
- `cli.py`：`_get_uow()` 强制要求 `DATABASE_URL`
- `infrastructure/unit_of_work.py`：只保留 `PostgresUnitOfWork`，删除旧 Adapter 兼容路径
- 测试统一使用 `InMemoryUnitOfWork` / `InMemoryAnalyticsStore`，无需真实数据库

### Architecture

- 参见 [ADR-004: 去除本地模式，强制 PostgreSQL 单一路径](docs/design/adr/ADR-004-remove-local-mode-postgresql-only.md)

---

## [Unreleased]

### Added
- **三层知识层级完整实现**：`Team → Business → Project` 多对多关联，新增 `ProjectBusinessLink`、`BusinessTeamLink` dataclass
- **`PromotionCandidate` 数据模型**：记录升层候选经验，含 `score`、`status`、`ignored_at` 字段
- **`Team`/`Business` 新增 `owner_email` 字段**（可选）
- **`EdgeFunctionClient`**（`src/edge_client.py`）：封装 `search`/`save`/`feedback` 三个方法，所有请求携带 `Authorization: Bearer <token>` header
- **`xp promote` 命令**：查看升层候选（`list`）、执行升层（`<id> --to business/team <id>`）、忽略候选（`ignore <id>`）
- **`xp admin` 扩展**：新增 `create-team`、`create-business`、`link` 子命令
- **`xp stats` 层级过滤参数**：`--project`、`--business`、`--team`、`--compare`
- **`xp stats` 健康状态面板**：基于 `compute_health_status` 展示采纳率、未命中率、Pending 堆积、反馈覆盖率
- **`src/domain/health.py`**：`compute_health_status` 纯函数，6 项指标阈值检测
- **`src/domain/promotion.py`** 新增 `determine_promotion_target`：判断升至 `business` 还是 `team` 层
- **`src/domain/search_v2.py`** 新增 `resolve_scope_ids`：从 `project_id` 展开多对多层级关联（含 team 去重）
- **Schema 迁移**：`CREATE_SCHEMA_SQL` 新增 `project_business`、`business_team`、`user_business`、`user_tokens`、`promotion_candidates` 表，以及 `teams`/`businesses` 的 `owner_email` 列
- `PromoteExperienceCommand`、`IgnorePromotionCommand` 新增到 `commands.py`
- `GetStatsCommand` 新增 `project_id`、`business_id`、`team_id`、`compare` 字段

### Changed
- **`src/server.py` 重构**：MCP server 不再依赖 `database_url`，`main()` 改为从 config 读取 `token` + `edge_function_url` 初始化 `EdgeFunctionClient`；`search`/`save`/`feedback` 三个 tool 调用改为 `EdgeFunctionClient` 转发
- **`src/cli.py` `cmd_login`**：不再写入 `database_url`，只保存 `token`、`user_id`、`project_id`（可选）、`edge_function_url`（可选）
- **`xp admin`**：子命令从单一 `create-token` 扩展为完整 admin 体系

### Architecture
- 参见 [ADR-002: 团队级知识层级体系与中心化部署架构](docs/design/adr/ADR-002-team-knowledge-hierarchy-and-centralized-deployment.md)

---

- 新增 `PostgresUnitOfWork`（`UnitOfWork(backend=backend)`），通过 asyncpg 连接 PostgreSQL
- `AbstractUnitOfWork` 新增 `async __aenter__`/`async __aexit__` 抽象方法
- `InMemoryUnitOfWork` 实现 async context manager，支持异步测试
- `InMemoryExperienceStore`/`InMemoryVectorStore` 新增 `aadd`/`aget`/`aupdate`/`alist_by_status`/`asave_vector`/`aget_all_vectors` async 方法
- `ExperienceStoreAdapter`/`VectorStoreAdapter` 新增对应 async 方法，兼容旧 SQLite 路径
- `build_command_bus` 改为 `async def`，根据 `DATABASE_URL` 环境变量自动选择 PostgresBackend 或 Legacy UnitOfWork
- 新增 `.env.example`，说明 `DATABASE_URL` 格式
- 安装 `pytest-asyncio` 依赖，测试支持 `Mode.AUTO`

### Changed
- `CommandBus.dispatch` 改为 `async def`，所有 handler 注册调用需为 async 函数
- 所有 handler 的 `handle_*` 方法改为 `async def`，内部 `with` 改为 `async with`
- `server.py`：所有 `bus.dispatch(...)` 加 `await`，`main()` 中 `_bus = await build_command_bus()`
- `rest_api.py`：所有路由函数改为 `async def`，`await build_command_bus()` + `await bus.dispatch()`
- `cli.py`：`_get_bus`、`cmd_add`、`cmd_stats`、`cmd_analyze`、`cmd_delete`、`main` 改为 async，入口改为 `asyncio.run(main())`
- `ExperienceQueryHandler` 不再直接 import storage，改为通过 UoW 访问数据
- `ExperienceStoreAdapter.list_by_status` 支持小写 status 字符串（`"pending"/"active"/"archived"`）

