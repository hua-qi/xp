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
