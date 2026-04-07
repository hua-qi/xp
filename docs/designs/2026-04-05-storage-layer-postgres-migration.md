# 存储层全量迁移到 PostgreSQL

**Date:** 2026-04-05

## Context

项目当前的存储层存在严重的架构断层：`src/storage.py` 是遗留的 SQLite/JSON 实现，`src/infrastructure/backends/postgres.py` 是后来写好的 PostgreSQL 实现，但两者并存且 PostgreSQL 路径从未被调用——它是死代码。

`UnitOfWork` 通过三个薄 Adapter（`infrastructure/stores/`）wrap 遗留 `storage.py`，而有 7 个旧 handler 甚至绕过 `UnitOfWork`，直接 `import storage` 自己实例化 Store，导致依赖注入形同虚设。

核心动机：**本地开发依赖少、快速验证可行性**，同时希望生产环境使用 PostgreSQL。经过讨论，用户决定本地也使用云数据库（Supabase/Neon 免费套餐），因此"本地 SQLite / 生产 PG 双 backend"的需求消失，目标简化为：**完全切到 PostgreSQL，重构干净**。

## Discussion

### 方案探索

**方案 A：环境变量驱动的 Backend Factory**
`DATABASE_URL` 有则用 PG，无则用 SQLite。改动最小，两套代码长期共存。复杂度低。

**方案 B：统一接口 + 两个完整实现**
`SqliteExperienceStore` 和 `PostgresExperienceStore` 各做一个干净实现。架构清晰但需重写 SQLite 层。复杂度中。

**方案 C：本地 Docker + PG，单一代码路径**
不维护两套 Store，但本地需要 Docker，违背零依赖初衷。

→ 用户选择**直接完全切到 PG**，不保留 SQLite。

### async 策略

`PostgresBackend` 全部是 `async def async_xxx()` 方法（基于 asyncpg），但现有调用链是同步的。两种解法：

- **解法 1（简单）**：Store Adapter 内部用 `asyncio.run()` 包装，对外保持同步接口。Handler 零改动，但每次 DB 操作重建事件循环，性能略差。
- **解法 2（干净）**：整个调用链改为 async，`bus.dispatch` 改为 `await bus.dispatch`，所有 handler 改为 `async def`。

→ 用户选择**解法 2**，重构就重构干净。

### CLI 处理策略

CLI 是同步命令行工具，全 async 后需要处理事件循环：

- **做法 A**：每个命令内部 `asyncio.run()`，简单直接。
- **做法 B**：CLI 整体改为一个 async main，共用一个事件循环。

→ 用户选择**做法 B**，整体 async main。

### 发现的额外遗漏

全面扫描后发现问题比预期多：

1. **7 个旧 handler 绕过 UoW 直接用 storage.py**：`analyze_handler`、`experience_query_handler`、`extract_handler`、`infer_adoption_handler`、`search_handler`、`session_handler`、`stats_handler`——虽然接受 `uow_factory` 参数但内部根本没用。
2. **`AbstractUnitOfWork` 接口没有 async 方法签名**，需要补充。
3. **CLI 有 19 处直接调用 storage.py**，切 PG 后全部失效。

## Approach

完全移除 SQLite/JSON 遗留链路，接通 PostgresBackend，整个调用链改为 async。最终架构：

```
CLI / REST API / MCP Server
    ↓ await bus.dispatch(Command)
CommandBus（async dispatch）
    ↓ await handler.handle(cmd)
Handler（async，通过 uow_factory 访问存储）
    ↓ async with uow_factory() as uow
UnitOfWork（持有 PostgresBackend，实现 __aenter__ / __aexit__）
    ↓ await backend.async_xxx()
PostgresBackend（asyncpg 连接池）
    ↓
PostgreSQL + pgvector（云数据库）
```

测试层完全不受影响：`InMemoryUnitOfWork` 补充 `async __aenter__ / __aexit__` 后，所有 unit test 继续绿。

## Architecture

### 变更清单（按执行顺序）

#### Step 1：扩展抽象接口
- `src/application/unit_of_work.py`：为 `AbstractExperienceStore`、`AbstractVectorStore`、`AbstractMetricsStore` 新增 async 方法签名（`aget`、`aadd`、`aupdate`、`alist_by_status` 等）；`AbstractUnitOfWork` 新增 `async __aenter__ / __aexit__`
- `src/application/command_bus.py`：新增 `async def dispatch()`

#### Step 2：接通 PostgresBackend
- `src/infrastructure/unit_of_work.py`：改为持有 `PostgresBackend` 实例，`__aenter__` 调用 `backend.connect()`，`__aexit__` 调用 `backend.close()`
- `src/infrastructure/stores/*.py`：三个 Adapter 改为 `async def`，直接 delegate 到 `PostgresBackend.async_xxx()`
- 删除 `src/infrastructure/stores/` 中的同步 wrap 逻辑

#### Step 3：修复 7 个旧 Handler
- 移除 `from ...storage import ExperienceStore/VectorStore/MetricsStore` 直接导入
- 改为使用 `self._uow_factory` 注入的 UoW
- `def handle_xxx` → `async def handle_xxx`
- `with self._uow_factory()` → `async with self._uow_factory()`

#### Step 4：修复 4 个新 Handler
- `search_v2_handler`、`save_handler`、`feedback_v2_handler`、`promotion_handler`
- `def handle` → `async def handle`，`with` → `async with`

#### Step 5：server.py
- `call_tool` 已是 `async`，`bus.dispatch(...)` → `await bus.dispatch(...)`

#### Step 6：rest_api.py
- 所有路由函数加 `async def`
- `bus.dispatch(...)` → `await bus.dispatch(...)`

#### Step 7：cli.py
- 整体改为 `async main` + 顶层 `asyncio.run(main())`
- 移除 19 处直接 `import storage` 调用，全部改走 `bus.dispatch`
- 各子命令改为 `async def`

#### Step 8：配置与清理
- `src/container.py`：`build_command_bus()` 改为 `async def`，创建 `PostgresBackend(dsn=os.getenv("DATABASE_URL"))` 并注入
- 新增 `.env.example`，包含 `DATABASE_URL=postgresql://user:pass@host:5432/xp`
- 删除 `src/storage.py`（遗留层）
- 删除 `src/infrastructure/stores/`（薄 Adapter 层，不再需要）

#### Step 9：测试层兼容
- `tests/helpers/fake_uow.py`：`InMemoryUnitOfWork` 补充 `async __aenter__ / __aexit__`，`InMemoryExperienceStore` 等补充 async 方法
- 所有 unit test 预期零改动即可通过

### 关键约束

- `PostgresBackend` 已有完整实现，**不需要重写任何 SQL**
- asyncpg 连接池在 `UnitOfWork.__aenter__` 时建立，`__aexit__` 时释放
- `DATABASE_URL` 通过环境变量注入，本地用 `.env` 文件，生产用部署平台的环境变量
- unit test 全程使用 `InMemoryUnitOfWork`，不需要真实数据库
