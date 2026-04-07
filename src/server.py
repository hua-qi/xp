from __future__ import annotations
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from .config import get_config
from .application.commands import SaveCommand, SearchV2Command, FeedbackV2Command

_command_bus = None
_backend = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _command_bus, _backend
    from .infrastructure.backends.mysql import MySQLBackend
    from .infrastructure.llm import LLMClient
    from .embeddings import LocalBGEProvider
    from .container import build_command_bus

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
    _command_bus = build_command_bus(
        backend=_backend,
        llm=llm,
        embedding_provider=embed,
    )
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
