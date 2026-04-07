# PostgreSQL 全量迁移实施方案

**Goal:** 将存储层从遗留 SQLite/JSON（`storage.py`）完全迁移到 PostgreSQL，整个调用链改为 async。

**Architecture:** 移除 `storage.py` 和 `infrastructure/stores/` 薄适配层，让 `UnitOfWork` 直接持有 `PostgresBackend`，并实现 `async __aenter__/__aexit__`。`CommandBus.dispatch` 改为 `async def`，所有 handler 改为 `async def`，CLI 改为整体 async main，REST API 路由改为 async。

**Tech Stack:** asyncpg, PostgreSQL（Supabase/Neon 免费套餐），pytest-asyncio（仅用于异步测试），现有 FastAPI（已支持 async）。

---

## 阅读前须知

### 项目结构速览

```
src/
  application/
    command_bus.py          # CommandBus.dispatch → 改为 async def
    unit_of_work.py         # AbstractUnitOfWork → 新增 async __aenter__/__aexit__
    handlers/               # 11 个 handler → 全部改为 async def handle
  infrastructure/
    backends/postgres.py    # PostgresBackend（已实现，不需要改 SQL）
    unit_of_work.py         # UnitOfWork → 改为持有 PostgresBackend，async with
    stores/                 # 三个薄适配层 → 全部删除
  container.py              # build_command_bus → 改为 async def
  server.py                 # call_tool → bus.dispatch 改为 await
  interfaces/rest_api.py    # 路由函数 → 改为 async def
  cli.py                    # 整体改为 async main
  storage.py                # 遗留层 → 最后删除
tests/
  helpers/fake_uow.py       # InMemoryUnitOfWork → 新增 async __aenter__/__aexit__
```

### 运行测试的命令

```bash
pytest tests/unit/ -v
pytest tests/helpers/ -v
pytest tests/ -v
```

### 安装依赖

```bash
uv add pytest-asyncio
```

（asyncpg 已在依赖中，仅需补充 pytest-asyncio 用于异步测试。）

### DATABASE_URL 格式

```
postgresql://user:password@host:5432/dbname
```

本地开发推荐 Supabase 或 Neon 免费套餐，在项目根目录创建 `.env` 文件。

---

## Task 1：为 InMemoryUnitOfWork 补充 async 接口（测试基础设施）

> 这是后续所有任务的基础。所有 unit test 都用 InMemoryUnitOfWork，先让它支持 async，后续 handler 改成 async 后测试才能通过。

**Files:**
- Modify: `tests/helpers/fake_uow.py`
- Test: `tests/helpers/test_fake_uow_smoke.py`

**Step 1: 写失败测试**

在 `tests/helpers/test_fake_uow_smoke.py` 末尾追加：

```python
import pytest

@pytest.mark.asyncio
async def test_inmemory_uow_async_context_manager():
    uow = InMemoryUnitOfWork()
    async with uow as u:
        assert u is uow
    assert uow.committed is True


@pytest.mark.asyncio
async def test_inmemory_uow_async_rollback_on_exception():
    uow = InMemoryUnitOfWork()
    try:
        async with uow:
            raise ValueError("fail")
    except ValueError:
        pass
    assert uow.committed is False
```

**Step 2: 运行，确认失败**

```bash
pytest tests/helpers/test_fake_uow_smoke.py::test_inmemory_uow_async_context_manager -v
```

预期：`FAILED` —— `AttributeError: __aenter__`

**Step 3: 在 `tests/helpers/fake_uow.py` 中为 `InMemoryUnitOfWork` 补充 async 方法**

在 `InMemoryUnitOfWork` 类末尾添加：

```python
    async def __aenter__(self) -> "InMemoryUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.experiences._commit()
            self.committed = True
        else:
            self.experiences._rollback()
```

**Step 4: 运行，确认通过**

```bash
pytest tests/helpers/test_fake_uow_smoke.py -v
```

预期：全部 `PASSED`

**Step 5: 提交**

```bash
git add tests/helpers/fake_uow.py tests/helpers/test_fake_uow_smoke.py
git commit -m "test: add async context manager support to InMemoryUnitOfWork"
```

---

## Task 2：为 AbstractUnitOfWork 添加 async 抽象方法

> 抽象接口要先定义，具体实现（PostgresUnitOfWork）和 Fake 才能正确实现它。

**Files:**
- Modify: `src/application/unit_of_work.py`

**Step 1: 写失败测试**

在 `tests/unit/test_command_bus.py` 中追加：

```python
def test_abstract_uow_has_async_context_manager():
    from src.application.unit_of_work import AbstractUnitOfWork
    assert hasattr(AbstractUnitOfWork, '__aenter__')
    assert hasattr(AbstractUnitOfWork, '__aexit__')
```

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_command_bus.py::test_abstract_uow_has_async_context_manager -v
```

预期：`FAILED` —— `AssertionError`

**Step 3: 修改 `src/application/unit_of_work.py`**

在 `AbstractUnitOfWork` 类末尾追加（紧接在 `__exit__` 抽象方法后面）：

```python
    @abstractmethod
    async def __aenter__(self) -> "AbstractUnitOfWork": ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
```

**Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_command_bus.py::test_abstract_uow_has_async_context_manager -v
```

预期：`PASSED`

**Step 5: 确认其他测试没有破坏**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

**Step 6: 提交**

```bash
git add src/application/unit_of_work.py tests/unit/test_command_bus.py
git commit -m "feat: add async abstract context manager to AbstractUnitOfWork"
```

---

## Task 3：CommandBus 改为 async dispatch

> handler 全部改为 async 后，CommandBus 必须能 await 它们。

**Files:**
- Modify: `src/application/command_bus.py`
- Test: `tests/unit/test_command_bus.py`

**Step 1: 写失败测试**

在 `tests/unit/test_command_bus.py` 中追加：

```python
import pytest

@pytest.mark.asyncio
async def test_async_dispatch_registered_command():
    bus = CommandBus()
    async def handler(cmd):
        return "async_ok"
    bus.register(RecordFeedbackCommand, handler)
    result = await bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
    assert result == "async_ok"


@pytest.mark.asyncio
async def test_async_dispatch_unregistered_raises():
    bus = CommandBus()
    with pytest.raises(UnregisteredCommandError):
        await bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
```

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_command_bus.py::test_async_dispatch_registered_command -v
```

预期：`FAILED` —— `TypeError: object str can't be used in 'await' expression`

**Step 3: 修改 `src/application/command_bus.py`**

将 `dispatch` 方法改为：

```python
    async def dispatch(self, command: Any) -> Any:
        handler = self._handlers.get(type(command))
        if handler is None:
            raise UnregisteredCommandError(f"No handler for {type(command).__name__}")
        return await handler(command)
```

**Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_command_bus.py -v
```

预期：全部 `PASSED`

**Step 5: 提交**

```bash
git add src/application/command_bus.py tests/unit/test_command_bus.py
git commit -m "feat: make CommandBus.dispatch async"
```

---

## Task 4：将 4 个"新" Handler 改为 async

> `SearchV2Handler`、`SaveHandler`、`FeedbackV2Handler`、`PromotionScanHandler` 已经正确使用 `self._uow_factory()`，只需要将 `with` 改为 `async with`，方法签名改为 `async def`。

**Files:**
- Modify: `src/application/handlers/search_v2_handler.py`
- Modify: `src/application/handlers/save_handler.py`
- Modify: `src/application/handlers/feedback_v2_handler.py`
- Modify: `src/application/handlers/promotion_handler.py`
- Test: `tests/unit/test_search_v2_handler.py`
- Test: `tests/unit/test_save_handler.py`
- Test: `tests/unit/test_feedback_v2_handler.py`
- Test: `tests/unit/test_promotion_handler.py`

**Step 1: 在现有 test 文件中将测试改为 async**

打开 `tests/unit/test_search_v2_handler.py`，在文件顶部添加：

```python
import pytest
```

将 `class TestSearchV2HandlerReturnsResults` 中所有测试方法由 `def` 改为 `async def`，并添加装饰器：

```python
@pytest.mark.asyncio
async def test_returns_empty_when_no_active_experiences(self):
    handler, uow = self._make_handler_and_uow()
    cmd = SearchV2Command(...)
    result = await handler.handle(cmd)   # 加 await
    assert result["results"] == []
```

对 `tests/unit/test_save_handler.py` 做同样的改动（所有测试方法加 `async def` + `@pytest.mark.asyncio`，`handler.handle(cmd)` 改为 `await handler.handle(cmd)`）。

对 `tests/unit/test_feedback_v2_handler.py` 和 `tests/unit/test_promotion_handler.py` 同理。

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_search_v2_handler.py -v
```

预期：`FAILED` —— handler.handle 不是 coroutine

**Step 3: 修改 `search_v2_handler.py`**

```python
# 将：
def handle(self, cmd: SearchV2Command) -> dict:
    ...
    with self._uow_factory() as uow:
        all_exps = uow.experiences.list_by_status("active")
    ...
    with self._uow_factory() as uow:
        ...

# 改为：
async def handle(self, cmd: SearchV2Command) -> dict:
    ...
    async with self._uow_factory() as uow:
        all_exps = uow.experiences.list_by_status("active")
    ...
    async with self._uow_factory() as uow:
        ...
```

> 注意：`list_by_status`、`get_all_vectors`、`save_vector` 暂时保持同步调用——它们在 InMemoryUnitOfWork 中是同步的，PostgresBackend 接入时（Task 7）才改为 await。

**Step 4: 修改 `save_handler.py`**

```python
# 将：
def handle(self, cmd: SaveCommand) -> dict:
    ...
    with self._uow_factory() as uow:
        ...

# 改为：
async def handle(self, cmd: SaveCommand) -> dict:
    ...
    async with self._uow_factory() as uow:
        ...
```

**Step 5: 修改 `feedback_v2_handler.py`**

```python
# 将：
def handle(self, cmd: FeedbackV2Command) -> dict:
    ...
    with self._uow_factory() as uow:
        ...

# 改为：
async def handle(self, cmd: FeedbackV2Command) -> dict:
    ...
    async with self._uow_factory() as uow:
        ...
```

**Step 6: 修改 `promotion_handler.py`**

```python
# 将：
def handle(self, cmd: ScanPromotionCandidatesCommand) -> dict:
    ...
    with self._uow_factory() as uow:
        ...

# 改为：
async def handle(self, cmd: ScanPromotionCandidatesCommand) -> dict:
    ...
    async with self._uow_factory() as uow:
        ...
```

**Step 7: 运行，确认通过**

```bash
pytest tests/unit/test_search_v2_handler.py tests/unit/test_save_handler.py tests/unit/test_feedback_v2_handler.py tests/unit/test_promotion_handler.py -v
```

预期：全部 `PASSED`

**Step 8: 提交**

```bash
git add src/application/handlers/search_v2_handler.py \
        src/application/handlers/save_handler.py \
        src/application/handlers/feedback_v2_handler.py \
        src/application/handlers/promotion_handler.py \
        tests/unit/test_search_v2_handler.py \
        tests/unit/test_save_handler.py \
        tests/unit/test_feedback_v2_handler.py \
        tests/unit/test_promotion_handler.py
git commit -m "feat: make new handlers async (search_v2, save, feedback_v2, promotion)"
```

---

## Task 5：将 7 个"旧" Handler 改为 async，并切换到 UoW

> 这 7 个 handler 绕过了 UoW，直接 `from ...storage import ...`。需要：① `def` → `async def`；② 删除直接 import storage；③ 通过 `self._uow_factory()` 访问存储。

**Files:**
- Modify: `src/application/handlers/experience_handler.py`
- Modify: `src/application/handlers/feedback_handler.py`
- Modify: `src/application/handlers/experience_query_handler.py`
- Modify: `src/application/handlers/analyze_handler.py`
- Modify: `src/application/handlers/search_handler.py`
- Modify: `src/application/handlers/session_handler.py`
- Modify: `src/application/handlers/stats_handler.py`
- Modify: `src/application/handlers/infer_adoption_handler.py`
- Modify: `src/application/handlers/extract_handler.py`

### 5a：experience_handler.py

**Step 1: 写失败测试**

在 `tests/unit/test_experience.py`（或新建 `tests/unit/test_experience_handler_async.py`）添加：

```python
import pytest
from src.application.commands import ActivateExperienceCommand
from src.application.handlers.experience_handler import ExperienceHandler
from tests.helpers.fake_uow import InMemoryUnitOfWork


@pytest.mark.asyncio
async def test_activate_handler_is_async():
    uow = InMemoryUnitOfWork()
    handler = ExperienceHandler(
        uow_factory=lambda: uow,
        llm=type("L", (), {"generate_title": lambda self, t: t[:10]})(),
        metadata_inferrer=type("M", (), {"infer": lambda self, t: {"tech_stack": [], "scene": [], "level": "L2"}})(),
    )
    result = await handler.handle_activate(ActivateExperienceCommand(experience_id="x"))
    assert result is False  # 不存在时返回 False
```

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_experience_handler_async.py -v
```

**Step 3: 修改 `experience_handler.py`**

将三个方法全部加上 `async def`，将：

```python
with self._uow_factory() as uow:
```

改为：

```python
async with self._uow_factory() as uow:
```

**Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_experience_handler_async.py -v
```

### 5b：feedback_handler.py

`FeedbackHandler.handle_feedback` 已经正确使用 `uow_factory`，只需：
- `def handle_feedback` → `async def handle_feedback`
- `with self._uow_factory()` → `async with self._uow_factory()`

对应的测试（`tests/unit/test_feedback.py`）中加 `@pytest.mark.asyncio` + `await`。

### 5c：experience_query_handler.py

该 handler 直接用 `storage.ExperienceStore()`，要改为通过 UoW：

```python
async def handle_list(self, cmd: ListExperiencesCommand) -> list:
    from ...models import ExperienceStatus
    try:
        status_enum = ExperienceStatus(cmd.status)
    except ValueError:
        raise ValueError(f"Invalid status: {cmd.status}")
    async with self._uow_factory() as uow:
        return uow.experiences.list_by_status(status_enum.value)


async def handle_delete(self, cmd: DeleteExperienceCommand) -> str | None:
    from ...models import ExperienceStatus
    async with self._uow_factory() as uow:
        all_exps = []
        for status in ["pending", "active", "archived"]:
            all_exps.extend(uow.experiences.list_by_status(status))
        matches = [e for e in all_exps if e.id.startswith(cmd.prefix)]
        if len(matches) != 1:
            return None
        # PostgresBackend 提供 async_delete_experience，在 Task 7 中接入
        # 暂时用 update + status 标记（或在 AbstractExperienceStore 新增 delete 方法）
        return matches[0].id


async def handle_get(self, cmd: GetExperienceCommand):
    async with self._uow_factory() as uow:
        return uow.experiences.get(cmd.experience_id)
```

### 5d：session_handler.py

```python
async def handle_record_session(self, cmd: RecordSessionCommand):
    from ...models import Session
    from datetime import datetime

    async with self._uow_factory() as uow:
        session = Session(
            session_id=cmd.session_id,
            task_description=cmd.task_description,
            experience_ids_injected=cmd.experience_ids_injected,
            iteration_count=cmd.iteration_count,
            had_error_correction=cmd.had_error_correction,
            user_accepted=cmd.user_accepted,
            created_at=datetime.utcnow().isoformat(),
            ab_test_group=cmd.ab_test_group,
            ab_test_result_shown=cmd.ab_test_result_shown,
        )
        uow.metrics.record_search("session", 0)  # 暂用 metrics；Task 7 接入后用 backend.async_record_session
    return True
```

> 注意：`AbstractMetricsStore` 没有 `record_session` 方法。可先在接口和 InMemory 实现中新增 `record_session(session)` 方法（参考 Task 6a），或者在 Task 7 直接绕过 Store Adapter 调用 backend。

### 5e：stats_handler.py、analyze_handler.py、search_handler.py、infer_adoption_handler.py、extract_handler.py

这几个 handler 的逻辑依赖 `storage.py` 的特有方法（`get_feedback_summary`、`get_stats`、`get_search_miss_queries` 等），这些方法不在 `AbstractUnitOfWork` 接口中。

**处理策略（暂时最小化改动）：**
1. 将方法签名改为 `async def`
2. 内部的 storage 调用**暂时保留**（仍然 `from ...storage import ...`）
3. Task 7 接入 PostgresBackend 后再替换为 `await backend.async_xxx()`

这样做的好处是：测试层（InMemory）不受影响，可以先让 CommandBus 的 async dispatch 工作起来。

**Step 1: 写失败测试（以 stats_handler 为例）**

新建 `tests/unit/test_stats_handler_async.py`：

```python
import pytest
from src.application.commands import GetStatsCommand
from src.application.handlers.stats_handler import StatsHandler
from tests.helpers.fake_uow import InMemoryUnitOfWork
import inspect


def test_stats_handler_handle_is_coroutine():
    handler = StatsHandler(uow_factory=InMemoryUnitOfWork)
    assert inspect.iscoroutinefunction(handler.handle_get_stats)
```

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_stats_handler_async.py -v
```

**Step 3: 将 `def handle_get_stats` → `async def handle_get_stats`**（只改签名）

**Step 4: 对其余 4 个同理（只改签名为 async def）**

对 `analyze_handler.py`、`search_handler.py`、`infer_adoption_handler.py`、`extract_handler.py` 分别写相同的 `inspect.iscoroutinefunction` 测试，然后将对应方法改为 `async def`。

**Step 5: 运行全部测试**

```bash
pytest tests/unit/ -v --tb=short
```

**Step 6: 提交**

```bash
git add src/application/handlers/
git commit -m "feat: make all handlers async def (legacy storage calls kept for now)"
```

---

## Task 6：新建 PostgresUnitOfWork，替换 infrastructure/unit_of_work.py

> 现在抽象接口和所有 handler 都是 async 了。这个 Task 实现真正的 PostgresUnitOfWork。

**Files:**
- Modify: `src/infrastructure/unit_of_work.py`
- Test: `tests/unit/test_postgres_uow.py`（新建，使用 mock）

**Step 1: 写失败测试**

新建 `tests/unit/test_postgres_uow.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.infrastructure.unit_of_work import UnitOfWork


@pytest.mark.asyncio
async def test_postgres_uow_calls_connect_on_enter():
    backend = MagicMock()
    backend.connect = AsyncMock()
    backend.close = AsyncMock()

    uow = UnitOfWork(backend=backend)
    async with uow:
        backend.connect.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_uow_calls_close_on_exit():
    backend = MagicMock()
    backend.connect = AsyncMock()
    backend.close = AsyncMock()

    uow = UnitOfWork(backend=backend)
    async with uow:
        pass
    backend.close.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_uow_calls_close_even_on_exception():
    backend = MagicMock()
    backend.connect = AsyncMock()
    backend.close = AsyncMock()

    uow = UnitOfWork(backend=backend)
    try:
        async with uow:
            raise ValueError("boom")
    except ValueError:
        pass
    backend.close.assert_called_once()
```

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_postgres_uow.py -v
```

预期：`FAILED` —— `UnitOfWork.__init__` 不接受 `backend` 参数

**Step 3: 修改 `src/infrastructure/unit_of_work.py`**

```python
from __future__ import annotations
from ..application.unit_of_work import AbstractUnitOfWork


class _PgExperienceStore:
    def __init__(self, backend):
        self._backend = backend

    def add(self, exp):
        raise NotImplementedError("Use async path")

    def get(self, exp_id: str):
        raise NotImplementedError("Use async path")

    def update(self, exp):
        raise NotImplementedError("Use async path")

    def list_by_status(self, status: str) -> list:
        raise NotImplementedError("Use async path")

    async def aadd(self, exp):
        return await self._backend.async_add_experience(exp)

    async def aget(self, exp_id: str):
        return await self._backend.async_get_experience(exp_id)

    async def aupdate(self, exp):
        return await self._backend.async_update_experience(exp)

    async def alist_by_status(self, status: str) -> list:
        from ..models import ExperienceStatus
        return await self._backend.async_list_by_status(ExperienceStatus(status))


class _PgVectorStore:
    def __init__(self, backend):
        self._backend = backend

    def save_vector(self, exp_id: str, vector: list[float]) -> None:
        raise NotImplementedError("Use async path")

    def get_all_vectors(self, exp_ids=None):
        raise NotImplementedError("Use async path")

    async def asave_vector(self, exp_id: str, vector: list[float]) -> None:
        await self._backend.async_save_vector(exp_id, vector)

    async def aget_all_vectors(self, exp_ids=None):
        return await self._backend.async_get_all_vectors(exp_ids)


class _PgMetricsStore:
    def __init__(self, backend):
        self._backend = backend

    def record_search(self, query: str, result_count: int) -> None:
        raise NotImplementedError("Use async path")

    def record_feedback(self, feedback) -> None:
        raise NotImplementedError("Use async path")

    def get_experience_stats(self, exp_id: str):
        raise NotImplementedError("Use async path")

    async def arecord_feedback(self, feedback):
        await self._backend.async_record_feedback(feedback)

    async def aget_experience_stats(self, exp_id: str):
        return await self._backend.async_get_experience_stats(exp_id)


class UnitOfWork(AbstractUnitOfWork):
    def __init__(self, backend):
        super().__init__()
        self._backend = backend
        self.experiences = _PgExperienceStore(backend)
        self.vectors = _PgVectorStore(backend)
        self.metrics = _PgMetricsStore(backend)

    def __enter__(self):
        raise NotImplementedError("Use async with")

    def __exit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError("Use async with")

    async def __aenter__(self) -> "UnitOfWork":
        await self._backend.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._backend.close()
```

**Step 4: 运行，确认通过**

```bash
pytest tests/unit/test_postgres_uow.py -v
```

**Step 5: 提交**

```bash
git add src/infrastructure/unit_of_work.py tests/unit/test_postgres_uow.py
git commit -m "feat: implement PostgresUnitOfWork with async context manager"
```

---

## Task 7：将所有 handler 的 store 调用改为 async（await uow.experiences.aadd 等）

> 现在 `_PgExperienceStore` 只有 `aadd`/`aget`/`aupdate`/`alist_by_status`。需要将 handler 内部的同步调用改为 await。

**Files:**
- Modify: 全部 handler 文件（同 Task 4、5 的文件列表）

**Step 1: 为 save_handler 写 async store 调用的测试**

在 `tests/unit/test_save_handler.py` 中，将 `uow.experiences.get(result["experience_id"])` 改为先通过 `uow.experiences._committed` 直接访问（InMemoryExperienceStore 的内部字典，测试中可以直接查）——不需要 await，因为 InMemoryUnitOfWork 的 store 方法仍然是同步的。

> 关键点：`InMemoryExperienceStore` 的 `add/get/update/list_by_status` 保持同步；只有 `_PgExperienceStore` 才有 async 版本。handler 里要同时兼容两者。

**处理方案：** 在 handler 中用 `inspect.iscoroutinefunction` 判断，或者统一约定 handler 内部都用 `await uow.experiences.aadd(exp)` 风格，而 `InMemoryExperienceStore` 也同步添加这些 async 方法：

在 `tests/helpers/fake_uow.py` 的 `InMemoryExperienceStore` 中追加：

```python
    async def aadd(self, exp) -> None:
        self.add(exp)

    async def aget(self, exp_id: str):
        return self.get(exp_id)

    async def aupdate(self, exp) -> None:
        self.update(exp)

    async def alist_by_status(self, status: str) -> list:
        return self.list_by_status(status)
```

在 `InMemoryVectorStore` 中追加：

```python
    async def asave_vector(self, exp_id: str, vector: list[float]) -> None:
        self.save_vector(exp_id, vector)

    async def aget_all_vectors(self, exp_ids=None):
        return self.get_all_vectors(exp_ids)
```

**Step 2: 修改 handler 内部调用**

将每个 handler 中：

```python
async with self._uow_factory() as uow:
    all_exps = uow.experiences.list_by_status("active")
    exp = uow.experiences.get(exp_id)
    uow.experiences.add(exp)
    uow.experiences.update(exp)
    uow.vectors.save_vector(exp_id, vec)
    ids, vecs = uow.vectors.get_all_vectors(exp_ids)
```

改为：

```python
async with self._uow_factory() as uow:
    all_exps = await uow.experiences.alist_by_status("active")
    exp = await uow.experiences.aget(exp_id)
    await uow.experiences.aadd(exp)
    await uow.experiences.aupdate(exp)
    await uow.vectors.asave_vector(exp_id, vec)
    ids, vecs = await uow.vectors.aget_all_vectors(exp_ids)
```

**Step 3: 运行所有单元测试，确认全部通过**

```bash
pytest tests/unit/ tests/helpers/ -v
```

**Step 4: 提交**

```bash
git add src/application/handlers/ tests/helpers/fake_uow.py
git commit -m "feat: use async store methods in all handlers"
```

---

## Task 8：修改 container.py，接入 PostgresBackend

> `build_command_bus` 改为 `async def`，创建 `PostgresBackend` 并以工厂形式传入。

**Files:**
- Modify: `src/container.py`

**Step 1: 写失败测试**

在 `tests/unit/test_command_bus.py` 中追加：

```python
import inspect

def test_build_command_bus_is_async():
    from src.container import build_command_bus
    assert inspect.iscoroutinefunction(build_command_bus)
```

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_command_bus.py::test_build_command_bus_is_async -v
```

**Step 3: 修改 `src/container.py`**

```python
import os
from .infrastructure.backends.postgres import PostgresBackend
from .infrastructure.unit_of_work import UnitOfWork

async def build_command_bus(project: str = "default") -> CommandBus:
    dsn = os.environ["DATABASE_URL"]
    backend = PostgresBackend(dsn=dsn)

    def uow_factory():
        return UnitOfWork(backend=backend)

    llm = _SimpleLLM()
    metadata = _MetadataInferrer()

    # ... 其余 handler 注册代码不变，只是 uow_factory 现在返回 PostgresUnitOfWork ...

    bus = CommandBus()
    # 注册同 Task 4 之前，全部不变
    ...
    return bus
```

> `UnitOfWork` 每次 `async with` 时都会 `connect()`/`close()`，这是设计意图（每次请求一个连接池连接）。

**Step 4: 修改现有 command bus 测试**

`TestCommandBusNewCommands` 里的三个测试调用了 `build_command_bus()`，现在它是 async，要改为：

```python
@pytest.mark.asyncio
async def test_search_v2_command_is_registered(self):
    bus = await build_command_bus()
    assert SearchV2Command in bus._handlers
```

但这要求真实的 `DATABASE_URL`，不适合 unit test。改为用 mock：

```python
import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_build_command_bus_registers_search_v2():
    with patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
        with patch("src.infrastructure.backends.postgres.asyncpg") as mock_pg:
            mock_pool = AsyncMock()
            mock_pg.create_pool = AsyncMock(return_value=mock_pool)
            bus = await build_command_bus()
    assert SearchV2Command in bus._handlers
```

**Step 5: 运行测试**

```bash
pytest tests/unit/test_command_bus.py -v
```

**Step 6: 提交**

```bash
git add src/container.py tests/unit/test_command_bus.py
git commit -m "feat: make build_command_bus async, wire PostgresBackend"
```

---

## Task 9：修改 server.py，await bus.dispatch

**Files:**
- Modify: `src/server.py`

**Step 1: 写失败测试**

在 `tests/unit/test_mcp_tools.py` 中找到现有测试（或新建），验证 `call_tool` 调用后返回正确结构。将测试改为 async：

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_call_tool_search_returns_text_content():
    mock_bus = MagicMock()
    mock_bus.dispatch = AsyncMock(return_value={
        "search_event_id": "evt-001",
        "results": [],
    })
    with patch("src.server._bus", mock_bus):
        from src.server import call_tool
        result = await call_tool("search", {
            "task_description": "fix bug",
            "project_id": "github.com/org/repo",
            "project_manifest": "",
        })
    assert result[0].text is not None
```

**Step 2: 运行，确认失败**

**Step 3: 修改 `server.py`**

在 `call_tool` 内所有 `bus.dispatch(...)` 前加 `await`：

```python
result = await bus.dispatch(SearchV2Command(...))
result = await bus.dispatch(SaveCommand(...))
result = await bus.dispatch(FeedbackV2Command(...))
# ... 其余同理
```

`main()` 中 `_bus = build_command_bus(project=project)` 改为 `_bus = await build_command_bus(project=project)`。

**Step 4: 运行测试**

```bash
pytest tests/unit/test_mcp_tools.py -v
```

**Step 5: 提交**

```bash
git add src/server.py tests/unit/test_mcp_tools.py
git commit -m "feat: await bus.dispatch in server.py call_tool"
```

---

## Task 10：修改 rest_api.py，路由改为 async

**Files:**
- Modify: `src/interfaces/rest_api.py`
- Test: `tests/unit/test_rest_promotion_routes.py`（检查现有测试）

**Step 1: 检查现有测试**

```bash
pytest tests/unit/test_rest_promotion_routes.py -v
```

记录当前状态。

**Step 2: 写新的失败测试**

新建或追加 `tests/unit/test_rest_api_async.py`：

```python
import pytest
import inspect
from src.interfaces.rest_api import create_app


def test_all_routes_are_async():
    app = create_app()
    for route in app.routes:
        if hasattr(route, "endpoint"):
            assert inspect.iscoroutinefunction(route.endpoint), \
                f"Route {route.path} endpoint is not async"
```

**Step 3: 运行，确认失败**

```bash
pytest tests/unit/test_rest_api_async.py -v
```

**Step 4: 修改 `rest_api.py`**

将 `create_app` 内所有路由函数：

```python
def health():           → async def health():
def extract_experience  → async def extract_experience
def search_experiences  → async def search_experiences
# ... 其余全部加 async def
```

并将所有 `bus.dispatch(...)` 改为 `await bus.dispatch(...)`。

由于路由内部调用了 `build_command_bus()`，也需要改为 `await build_command_bus()`：

```python
@app.post("/api/experiences", status_code=201)
async def extract_experience(req: ExtractRequest):
    bus = await build_command_bus()
    exp = await bus.dispatch(ExtractExperienceCommand(...))
    ...
```

> **注意**：如果测试 `test_rest_promotion_routes.py` 使用 `TestClient`（同步），需要改为 `AsyncClient`（httpx）。先检查现有测试的写法。

**Step 5: 运行**

```bash
pytest tests/unit/test_rest_api_async.py tests/unit/test_rest_promotion_routes.py -v
```

**Step 6: 提交**

```bash
git add src/interfaces/rest_api.py tests/unit/test_rest_api_async.py
git commit -m "feat: make REST API routes async, await bus.dispatch"
```

---

## Task 11：修改 cli.py，改为整体 async main

> CLI 是最后改的，因为它直接面向用户且绕过 bus 的地方最多。

**Files:**
- Modify: `src/cli.py`

**Step 1: 写验证测试**

新建 `tests/unit/test_cli_async.py`：

```python
import inspect
import src.cli as cli_module


def test_main_function_is_async():
    assert inspect.iscoroutinefunction(cli_module.main)


def test_cmd_add_is_async():
    assert inspect.iscoroutinefunction(cli_module.cmd_add)
```

**Step 2: 运行，确认失败**

```bash
pytest tests/unit/test_cli_async.py -v
```

**Step 3: 修改 `src/cli.py`**

1. 文件顶部加 `import asyncio`（已有）
2. 将所有 `def cmd_xxx(args)` 改为 `async def cmd_xxx(args)`
3. 将内部的 `bus.dispatch(...)` 改为 `await bus.dispatch(...)`
4. 将 `_get_bus()` 改为 `async def _get_bus()` 并 `return await build_command_bus(...)`
5. **重要**：CLI 中直接调用 `storage.ExperienceStore()` 的地方（`cmd_review`、`cmd_import`、`cmd_stats` 等），改为通过 `bus.dispatch` 对应 Command
6. 将末尾入口改为：

```python
async def main():
    # ... 解析 args ...
    # 分发到 await cmd_xxx(args)

if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: 运行测试**

```bash
pytest tests/unit/test_cli_async.py -v
```

**Step 5: 手动验证 CLI 可运行**

```bash
DATABASE_URL="postgresql://..." python -m src.cli --help
```

**Step 6: 提交**

```bash
git add src/cli.py tests/unit/test_cli_async.py
git commit -m "feat: make CLI fully async, remove direct storage imports"
```

---

## Task 12：环境配置与清理遗留代码

**Files:**
- Create: `.env.example`
- Delete: `src/storage.py`（在确认所有测试通过之后）
- Delete: `src/infrastructure/stores/experience_store.py`
- Delete: `src/infrastructure/stores/vector_store.py`
- Delete: `src/infrastructure/stores/metrics_store.py`

**Step 1: 创建 `.env.example`**

```bash
cat > .env.example << 'EOF'
# PostgreSQL 连接串（Supabase / Neon 免费套餐）
DATABASE_URL=postgresql://user:password@host:5432/dbname
EOF
```

**Step 2: 确认没有任何文件仍然 import storage**

```bash
grep -r "from.*storage import\|import storage" src/ --include="*.py"
```

预期：无输出（0 个匹配）

如果有剩余，逐一修改，再次运行直到无输出。

**Step 3: 运行所有测试**

```bash
pytest tests/ -v
```

预期：全部 `PASSED`（会跳过需要真实 DB 的集成测试）

**Step 4: 删除遗留文件**

```bash
# 先确认测试全绿再执行
git rm src/storage.py
git rm src/infrastructure/stores/experience_store.py
git rm src/infrastructure/stores/vector_store.py
git rm src/infrastructure/stores/metrics_store.py
```

**Step 5: 再次运行所有测试**

```bash
pytest tests/ -v
```

**Step 6: 提交**

```bash
git add .env.example
git commit -m "feat: remove legacy storage.py and store adapters, add .env.example"
```

---

## Task 13：集成验证（需要真实 DATABASE_URL）

> 这一步需要一个真实的 PostgreSQL 实例（Supabase/Neon 免费套餐）。

**Step 1: 配置 .env**

```bash
cp .env.example .env
# 编辑 .env，填入真实的 DATABASE_URL
```

**Step 2: 验证 schema 自动创建**

```python
# 临时脚本 scripts/init_db.py
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from src.infrastructure.backends.postgres import PostgresBackend

async def main():
    backend = PostgresBackend(dsn=os.environ["DATABASE_URL"])
    await backend.connect()
    print("Schema created successfully")
    await backend.close()

asyncio.run(main())
```

运行：

```bash
python scripts/init_db.py
```

**Step 3: 验证 MCP server 可以启动**

```bash
python -m src.server
```

应该看到 MCP server 启动日志，无报错。

**Step 4: 验证 CLI 基本功能**

```bash
python -m src.cli stats
python -m src.cli list
```

**Step 5: 提交（如有配置类改动）**

```bash
git add scripts/
git commit -m "chore: add db init script for integration verification"
```

---

## 检查清单

完成所有 Task 后，确认以下各项：

- [ ] `grep -r "from.*storage import" src/` 无输出
- [ ] `grep -r "import storage" src/` 无输出
- [ ] `pytest tests/unit/ tests/helpers/ -v` 全部 PASSED
- [ ] `CommandBus.dispatch` 是 `async def`
- [ ] `AbstractUnitOfWork` 有 `async __aenter__` / `async __aexit__`
- [ ] `InMemoryUnitOfWork` 实现了 `async __aenter__` / `async __aexit__`
- [ ] `UnitOfWork`（postgres）实现了 `async __aenter__` / `async __aexit__`
- [ ] 所有 handler 的 handle 方法都是 `async def`
- [ ] `build_command_bus` 是 `async def`
- [ ] `server.py` 里 `bus.dispatch` 都有 `await`
- [ ] `rest_api.py` 所有路由都是 `async def`
- [ ] `cli.py` 是整体 async main
- [ ] `src/storage.py` 已删除
- [ ] `src/infrastructure/stores/` 已删除
