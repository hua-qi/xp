import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.infrastructure.backends.mysql import MySQLBackend


@pytest.fixture
def backend():
    return MySQLBackend(dsn="mysql+aiomysql://root:root@localhost:3306/xp")


def test_mysql_backend_instantiation(backend):
    assert backend is not None


async def test_get_experiences_by_project_returns_list(backend):
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.fetchall = AsyncMock(return_value=[])
    mock_conn.cursor = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_cur), __aexit__=AsyncMock()))
    mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))
    backend._pool = mock_pool
    result = await backend.async_get_experiences_by_project("proj-1")
    assert isinstance(result, list)


async def test_save_vector_stores_blob(backend):
    import numpy as np
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.execute = AsyncMock()
    mock_conn.cursor = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_cur), __aexit__=AsyncMock()))
    mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))
    backend._pool = mock_pool
    vec = [0.0] * 1024
    await backend.async_save_vector("exp-1", vec)
    mock_cur.execute.assert_called_once()
