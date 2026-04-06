# ADR-003: 存储层全量迁移至 PostgreSQL，整个调用链改为 async

**状态**: 已采纳  
**日期**: 2026-04-05

## 背景

项目存储层存在架构断层：

- `src/storage.py` 是遗留的 SQLite/JSON 实现，被 7 个旧 handler 直接 import 绕过 UoW
- `src/infrastructure/backends/postgres.py` 是写好但从未被调用的死代码
- `UnitOfWork` 通过三个薄 Adapter 包装 storage，但旧 handler 根本不用 UoW
- `PostgresBackend` 全部是 `async def` 方法（基于 asyncpg），但调用链是同步的

核心动机：用户决定本地也使用云数据库（Supabase/Neon 免费套餐），"本地 SQLite + 生产 PG"双路径需求消失，目标简化为**完全切到 PostgreSQL，重构干净**。

## 决策

### 1. async 策略

选择**整个调用链改为 async**（而非 Store Adapter 内部 `asyncio.run()` 包装）：

- `CommandBus.dispatch` → `async def`
- 所有 handler 的 `handle_*` → `async def`，`with` → `async with`
- `build_command_bus` → `async def`
- `server.py`、`rest_api.py` 路由 → async
- `cli.py` → 整体 `async main` + `asyncio.run(main())`

### 2. UoW 接口扩展

`AbstractUnitOfWork` 新增 `async __aenter__`/`async __aexit__` 抽象方法。  
`PostgresUnitOfWork`（`UnitOfWork(backend=backend)`）实现：进入时 `await backend.connect()`，退出时 `await backend.close()`。

### 3. Store 双路径兼容

旧 Adapter 层（`ExperienceStoreAdapter`/`VectorStoreAdapter`）追加 async 方法（`aadd`/`aget`/`alist_by_status`/`asave_vector`/`aget_all_vectors`），内部仍调用同步 legacy store——确保在 `DATABASE_URL` 未配置时系统仍可运行。

`InMemoryUnitOfWork`（测试用）同样实现 async context manager 和 async store 方法，handler 可统一使用 `await uow.experiences.aadd()` 路径，对两套实现透明。

### 4. container.py 自动切换

```python
async def build_command_bus(project="default") -> CommandBus:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        backend = PostgresBackend(dsn=dsn)
        uow_factory = lambda: UnitOfWork(backend=backend)
    else:
        uow_factory = lambda: UnitOfWork()   # 保留 legacy 路径
```

### 5. 旧 handler 策略

- `ExperienceQueryHandler`：重写为完全使用 UoW，不再 import storage
- `ExperienceHandler`、`FeedbackHandler`：改为 async def + async with
- `StatsHandler`、`AnalyzeHandler`、`SearchHandler`、`SessionHandler`、`InferAdoptionHandler`、`ExtractHandler`：仅改签名为 `async def`，内部 storage 调用暂时保留（这些 handler 深度依赖 storage 特有方法，完整切换需独立计划）

## 备选方案

**方案 A：Store Adapter 内部 asyncio.run() 包装**  
保持 handler 同步不变，Adapter 内部用 `asyncio.run()` 调用 asyncpg。  
→ 被废弃：每次 DB 操作重建事件循环，性能差；且在已有事件循环（FastAPI/MCP server）内部调用 `asyncio.run()` 会直接抛 RuntimeError。

**方案 B：本地 SQLite + 生产 PG 双路径长期共存**  
→ 被废弃：用户明确不需要，维护两套代码长期增加复杂度。

## 结果

### 正面影响

- 整个调用链统一为 async，与 FastAPI、MCP server、asyncpg 的 async 原生模型自然契合
- `CommandBus.dispatch` 是 async，handler 注册和调用一致，不再有"同步 handler 被 await"的运行时陷阱
- `PostgresUnitOfWork` 接入后，每个请求独立 connect/close，连接池管理交给 asyncpg
- 所有 297 个测试通过（包含 unit / integration / characterization / e2e），零回归

### 负面/妥协

- `StatsHandler`、`AnalyzeHandler` 等旧 handler 内部仍然直接 import `storage.py`，尚未完成切换，需后续独立清理
- `cli.py` 中 `cmd_review`、`cmd_import`、`cmd_show` 等直接操作 storage 的命令尚未迁移到 UoW
- `storage.py` 文件暂未删除，待上述 handler 全部迁移后再移除

---

**文档版本**: v1.0  
**最后更新**: 2026-05-04
