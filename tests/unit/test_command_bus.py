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


def test_build_command_bus_is_sync():
    from src.container import build_command_bus
    assert not inspect.iscoroutinefunction(build_command_bus)


class TestCommandBusNewCommands:
    def test_search_v2_command_is_registered(self):
        from src.container import build_command_bus
        from unittest.mock import MagicMock
        bus = build_command_bus(
            backend=MagicMock(),
            llm=MagicMock(),
            embedding_provider=MagicMock(),
        )
        assert SearchV2Command in bus._handlers

    def test_save_command_is_registered(self):
        from src.container import build_command_bus
        from unittest.mock import MagicMock
        bus = build_command_bus(
            backend=MagicMock(),
            llm=MagicMock(),
            embedding_provider=MagicMock(),
        )
        assert SaveCommand in bus._handlers

    def test_feedback_v2_command_is_registered(self):
        from src.container import build_command_bus
        from unittest.mock import MagicMock
        bus = build_command_bus(
            backend=MagicMock(),
            llm=MagicMock(),
            embedding_provider=MagicMock(),
        )
        assert FeedbackV2Command in bus._handlers
