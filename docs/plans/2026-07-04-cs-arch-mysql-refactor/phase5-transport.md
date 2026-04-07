# Phase 5: 传输层

---

## Task 15: MCP HTTP Server 重写

**Files:**
- Modify: `src/server.py`
- Create: `tests/unit/test_server_http.py`

> **背景**：原 server.py 是 MCP stdio 模式（每个开发者本地跑）。新版改为 MCP Streamable HTTP 模式，Agent 通过 `http://host:8000/mcp` 直连。只保留 `search`、`save`、`feedback` 三个 tool。

**Step 1: 读现有 server.py 了解已注册哪些 tool**

```bash
# 阅读 src/server.py 前 80 行
```

**Step 2: 写失败测试**

```python
# tests/unit/test_server_http.py
def test_server_has_search_tool():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "search" in source

def test_server_has_save_tool():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "save" in source

def test_server_has_feedback_tool():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "feedback" in source

def test_server_does_not_use_stdio_transport():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "StdioServerTransport" not in source
    assert "stdio_server" not in source
```

**Step 3: 运行测试，观察哪些失败**

```bash
python -m pytest tests/unit/test_server_http.py -v
```

预期：`test_server_does_not_use_stdio_transport` FAIL（现有是 stdio）

**Step 4: 重写 server.py**

```python
# src/server.py
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from .container import build_command_bus
from .infrastructure.backends.mysql import MySQLBackend
from .infrastructure.llm import LLMClient
from .embeddings import LocalBGEProvider
from .config import get_config
from .application.commands import SaveCommand, SearchV2Command, FeedbackV2Command


_command_bus = None
_backend: MySQLBackend | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _command_bus, _backend
    cfg = get_config()
    _backend = MySQLBackend(dsn=cfg.DATABASE_URL)
    await _backend.connect()
    llm = LLMClient(
        api_base=cfg.LLM_API_BASE,
        api_key=cfg.LLM_API_KEY,
        model=cfg.LLM_MODEL,
        timeout=cfg.LLM_TIMEOUT,
    )
    embed = LocalBGEProvider()
    _command_bus = build_command_bus(backend=_backend, llm=llm, embedding_provider=embed)
    yield
    await _backend.disconnect()


mcp = FastMCP("xp", lifespan=lifespan)


@mcp.tool()
async def search(task_description: str, project_id: str) -> dict[str, Any]:
    """在任务开始前调用，获取相关工程经验。返回 session_id 和经验列表。"""
    cmd = SearchV2Command(task_description=task_description, project_id=project_id)
    return await _command_bus.dispatch(cmd)


@mcp.tool()
async def save(
    task_description: str,
    outcome_description: str,
    outcome: str,
    project_id: str,
    session_id: str = "",
) -> dict[str, Any]:
    """在任务完成后调用，保存工程经验。outcome 取值：success / partial / failed。"""
    cmd = SaveCommand(
        task_description=task_description,
        outcome_description=outcome_description,
        outcome=outcome,
        project_id=project_id,
        session_id=session_id or None,
    )
    return await _command_bus.dispatch(cmd)


@mcp.tool()
async def feedback(
    session_id: str,
    adopted_ids: list[str],
    rejected_ids: list[str],
    comment: str = "",
) -> dict[str, Any]:
    """在 save 之后调用，告知哪些经验被采纳/拒绝。"""
    cmd = FeedbackV2Command(
        session_id=session_id,
        adopted_ids=adopted_ids,
        rejected_ids=rejected_ids,
        comment=comment or None,
    )
    return await _command_bus.dispatch(cmd)


def run():
    import uvicorn
    port = int(os.getenv("XP_PORT", "8000"))
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port)
```

**Step 5: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_server_http.py -v
```

预期：PASS（4 个测试）

**Step 6: 提交**

```bash
git add src/server.py tests/unit/test_server_http.py
git commit -m "feat: rewrite MCP server to Streamable HTTP transport"
```

---

## Task 16: 容器组装更新

**Files:**
- Modify: `src/container.py`
- Create: `tests/unit/test_container_cs.py`

**Step 1: 阅读现有 container.py 了解 build_command_bus 签名**

```bash
# 阅读 src/container.py
```

**Step 2: 写失败测试**

```python
# tests/unit/test_container_cs.py
from unittest.mock import MagicMock, AsyncMock

def test_build_command_bus_accepts_new_params():
    from src.container import build_command_bus
    bus = build_command_bus(
        backend=MagicMock(),
        llm=MagicMock(),
        embedding_provider=MagicMock(),
    )
    assert bus is not None

def test_command_bus_has_save_v2_registered():
    from src.container import build_command_bus
    from src.application.commands import SaveCommand
    bus = build_command_bus(
        backend=MagicMock(),
        llm=MagicMock(),
        embedding_provider=MagicMock(),
    )
    assert SaveCommand in bus._handlers or hasattr(bus, "_handlers")
```

**Step 3: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_container_cs.py -v
```

预期：部分 FAIL（参数签名不对）

**Step 4: 更新 container.py 的 build_command_bus 函数签名**

在现有函数中增加 `backend`、`llm`、`embedding_provider` 参数，并将新 Handler 注册进 CommandBus：

```python
# src/container.py（在现有 build_command_bus 基础上修改函数签名）
def build_command_bus(
    backend=None,
    llm=None,
    embedding_provider=None,
    # 保留旧参数以保持向后兼容（如有）
    **kwargs,
):
    from .application.command_bus import CommandBus
    from .application.handlers.save_handler import SaveHandler
    from .application.handlers.search_v2_handler import SearchV2Handler
    from .application.handlers.feedback_v2_handler import FeedbackV2Handler
    from .application.commands import (
        SaveCommand, SearchV2Command, FeedbackV2Command,
    )
    # ... 保留现有 handler 注册 ...
    
    bus = CommandBus()
    
    # 新增 CS arch handlers
    if backend is not None:
        from .application.unit_of_work import PostgresUnitOfWork  # 或新的 MySQL UoW
        uow_factory = lambda: ...  # 根据 container.py 现有方式创建 UoW factory
        
        bus.register(SaveCommand, SaveHandler(uow_factory=uow_factory, llm=llm))
        bus.register(SearchV2Command, SearchV2Handler(backend=backend, llm=llm, embedding_provider=embedding_provider))
        bus.register(FeedbackV2Command, FeedbackV2Handler(uow_factory=uow_factory, backend=backend, llm=llm))
    
    return bus
```

> **重要**：读取现有 `container.py` 的实际结构后，根据实际代码修改，不要盲目替换整个文件。保留所有现有 Handler 注册，仅新增上述三个。

**Step 5: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_container_cs.py -v
```

预期：PASS

**Step 6: 运行全量测试确认无回归**

```bash
python -m pytest tests/ -q -k "not postgres and not server"
```

预期：全绿（或仅已知 skip 项）

**Step 7: 提交**

```bash
git add src/container.py tests/unit/test_container_cs.py
git commit -m "feat: update container to register CS arch handlers"
```
