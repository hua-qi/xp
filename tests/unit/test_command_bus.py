import pytest
from src.application.command_bus import CommandBus, UnregisteredCommandError
from src.application.commands import RecordFeedbackCommand


@pytest.mark.asyncio
async def test_dispatch_registered_command():
    bus = CommandBus()
    async def handler(cmd):
        return "ok"
    bus.register(RecordFeedbackCommand, handler)
    result = await bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
    assert result == "ok"


@pytest.mark.asyncio
async def test_dispatch_unregistered_command_raises():
    bus = CommandBus()
    with pytest.raises(UnregisteredCommandError):
        await bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))


@pytest.mark.asyncio
async def test_register_overwrites_previous_handler():
    bus = CommandBus()
    async def handler1(cmd):
        return "first"
    async def handler2(cmd):
        return "second"
    bus.register(RecordFeedbackCommand, handler1)
    bus.register(RecordFeedbackCommand, handler2)
    result = await bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
    assert result == "second"


from src.application.commands import SearchV2Command, SaveCommand, FeedbackV2Command


def test_abstract_uow_has_async_context_manager():
    from src.application.unit_of_work import AbstractUnitOfWork
    assert hasattr(AbstractUnitOfWork, '__aenter__')
    assert hasattr(AbstractUnitOfWork, '__aexit__')


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


import inspect


def test_build_command_bus_is_async():
    from src.container import build_command_bus
    assert inspect.iscoroutinefunction(build_command_bus)


class TestCommandBusNewCommands:
    @pytest.mark.asyncio
    async def test_search_v2_command_is_registered(self):
        from src.container import build_command_bus
        from unittest.mock import patch, AsyncMock, MagicMock
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
            with patch("src.infrastructure.backends.postgres.asyncpg") as mock_pg:
                mock_pool = MagicMock()
                mock_pg.create_pool = AsyncMock(return_value=mock_pool)
                bus = await build_command_bus()
        assert SearchV2Command in bus._handlers

    @pytest.mark.asyncio
    async def test_save_command_is_registered(self):
        from src.container import build_command_bus
        from unittest.mock import patch, AsyncMock, MagicMock
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
            with patch("src.infrastructure.backends.postgres.asyncpg") as mock_pg:
                mock_pool = MagicMock()
                mock_pg.create_pool = AsyncMock(return_value=mock_pool)
                bus = await build_command_bus()
        assert SaveCommand in bus._handlers

    @pytest.mark.asyncio
    async def test_feedback_v2_command_is_registered(self):
        from src.container import build_command_bus
        from unittest.mock import patch, AsyncMock, MagicMock
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}):
            with patch("src.infrastructure.backends.postgres.asyncpg") as mock_pg:
                mock_pool = MagicMock()
                mock_pg.create_pool = AsyncMock(return_value=mock_pool)
                bus = await build_command_bus()
        assert FeedbackV2Command in bus._handlers
