# PostgreSQL 全量迁移与 Async 调用链重构

## 概述

将存储层从遗留 SQLite/JSON（`storage.py`）完全迁移到 PostgreSQL，整个调用链改为 async。重构后 `CommandBus.dispatch`、所有 handler、`build_command_bus`、REST API 路由、CLI main 均为 async，与 FastAPI / MCP server / asyncpg 的原生 async 模型对齐。

本文档覆盖两个阶段：
- **阶段一（ADR-003）**：async 调用链重构 + PostgresUnitOfWork 接入
- **阶段二（ADR-004）**：删除本地模式，强制 PostgreSQL 单一路径

## 最终架构

### 单一路径

```
DATABASE_URL (必须配置)
    ↓
PostgresBackend(dsn=DATABASE_URL)
    ↓
PostgresUnitOfWork(backend=backend)
    ↓
handler → async with uow → uow.experiences / uow.vectors / uow.analytics
```

本地 SQLite/JSON 路径（`storage.py`、`infrastructure/stores/`）已于 v0.6.0 完全删除。

### 调用链

```
# 所有入口均为 async
await CommandBus.dispatch(cmd)
  → await handler.handle_xxx(cmd)
    → async with uow_factory() as uow
      → await uow.experiences.aadd(exp)
      → await uow.vectors.asave_vector(id, vec)
      → await uow.analytics.record_session(data)
```

## 设计思路

### 问题根因（阶段一）

迁移前存在三类问题：

1. **死代码**：`PostgresBackend` 写好但从未被调用，`UnitOfWork` 通过 Adapter 包装 `storage.py`
2. **UoW 被绕过**：7 个旧 handler 直接 `from ...storage import ExperienceStore` 自己实例化
3. **同步/async 不匹配**：`PostgresBackend` 全部是 `async def`，但调用链是同步的

### 决策（阶段二）

在 async 化完成后，双路径带来的问题：

- 遗留文件持续堆积死代码
- 新能力（analytics store）只在 PG 路径实现，两条路径行为不一致
- 测试需同时覆盖两条路径

**决策：删除本地模式，`DATABASE_URL` 从可选变为必须。** 详见 [ADR-004](../design/adr/ADR-004-remove-local-mode-postgresql-only.md)。

## 实现细节

### UnitOfWork 接口

```python
# AbstractUnitOfWork（application/unit_of_work.py）
class AbstractUnitOfWork(ABC):
    experiences: AbstractExperienceStore
    vectors: AbstractVectorStore
    analytics: AbstractAnalyticsStore   # v0.6.0 新增

    @abstractmethod
    async def __aenter__(self) -> "AbstractUnitOfWork": ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
```

```python
# PostgresUnitOfWork（infrastructure/unit_of_work.py）
async def __aenter__(self):
    await self._backend.connect()
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb):
    await self._backend.close()
```

### Analytics Store 接口

```python
class AbstractAnalyticsStore(ABC):
    @abstractmethod
    async def record_session(self, session_data: dict) -> None: ...

    @abstractmethod
    async def get_stats(self, since: str | None = None) -> dict: ...

    @abstractmethod
    async def get_feedback_summary(self) -> dict: ...

    @abstractmethod
    async def get_search_stats(self) -> dict: ...

    @abstractmethod
    async def get_adoption_rate(self) -> float: ...
```

实现：
- `_PgAnalyticsStore`：`infrastructure/unit_of_work.py`，使用 asyncpg SQL 查询
- `InMemoryAnalyticsStore`：`tests/helpers/fake_uow.py`，内存实现，供单元测试使用

### Store 方法命名约定

PG 路径使用 `a` 前缀的 async 方法：

| 同步方法 | async 方法 |
|---------|-----------|
| `add(exp)` | `aadd(exp)` |
| `get(exp_id)` | `aget(exp_id)` |
| `update(exp)` | `aupdate(exp)` |
| `list_by_status(status)` | `alist_by_status(status)` |
| `save_vector(id, vec)` | `asave_vector(id, vec)` |
| `get_all_vectors(ids)` | `aget_all_vectors(ids)` |

### container.py

```python
async def build_command_bus(project: str = "default") -> CommandBus:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Set it to your PostgreSQL connection string."
        )
    backend = PostgresBackend(dsn=dsn)
    uow_factory = lambda: UnitOfWork(backend=backend)
    ...
```

### cli.py

```python
async def _get_uow():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")
    backend = PostgresBackend(dsn=dsn)
    return UnitOfWork(backend=backend)

async def main():
    ...

if __name__ == "__main__":
    asyncio.run(main())
```

## 接口与使用

### 配置

```bash
# .env
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

`DATABASE_URL` 为**必须**配置项，缺失时系统启动即抛 `RuntimeError`。

推荐免费 PostgreSQL 选项：
- [Supabase](https://supabase.com/)（免费套餐）
- [Neon](https://neon.tech/)（免费套餐）
- 本地 Docker：`docker run -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres`

### 测试

```bash
# 单元测试（使用 InMemoryUnitOfWork，不需要真实 DB）
uv run pytest tests/unit/ tests/helpers/ -q

# 全量
uv run pytest tests/ --tb=short -q
```

测试使用 `pytest-asyncio`，`pyproject.toml` 中配置 `asyncio_mode = "auto"`，async 测试方法无需手动添加 `@pytest.mark.asyncio`。

### 集成验证（需要真实 DB）

```bash
cp .env.example .env
# 填入真实的 DATABASE_URL
python -m src.server   # MCP server 启动
python -m src.cli stats  # CLI 验证
```

## 相关文件

| 文件 | 说明 |
|------|------|
| `src/application/command_bus.py` | `dispatch` 改为 `async def` |
| `src/application/unit_of_work.py` | 新增 `AbstractAnalyticsStore` + `analytics` 属性 |
| `src/infrastructure/unit_of_work.py` | 只保留 `PostgresUnitOfWork` + `_PgAnalyticsStore` |
| `src/infrastructure/backends/postgres.py` | analytics SQL 方法 |
| `src/container.py` | `build_command_bus` → async，强制 `DATABASE_URL` |
| `src/server.py` | 所有 `bus.dispatch` 加 `await` |
| `src/interfaces/rest_api.py` | 路由改为 async |
| `src/cli.py` | async main + asyncio.run + 强制 DATABASE_URL |
| `tests/helpers/fake_uow.py` | `InMemoryUnitOfWork` + `InMemoryAnalyticsStore` |
| `.env.example` | DATABASE_URL 配置示例 |
| `docs/design/adr/ADR-003-async-postgresql-migration.md` | 阶段一架构决策 |
| `docs/design/adr/ADR-004-remove-local-mode-postgresql-only.md` | 阶段二架构决策 |

---

**文档版本**: v2.0  
**最后更新**: 2026-05-04
