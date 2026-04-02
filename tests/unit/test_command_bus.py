import pytest
from src.application.command_bus import CommandBus, UnregisteredCommandError
from src.application.commands import RecordFeedbackCommand


def test_dispatch_registered_command():
    bus = CommandBus()
    bus.register(RecordFeedbackCommand, lambda cmd: "ok")
    result = bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
    assert result == "ok"


def test_dispatch_unregistered_command_raises():
    bus = CommandBus()
    with pytest.raises(UnregisteredCommandError):
        bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))


def test_register_overwrites_previous_handler():
    bus = CommandBus()
    bus.register(RecordFeedbackCommand, lambda cmd: "first")
    bus.register(RecordFeedbackCommand, lambda cmd: "second")
    result = bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
    assert result == "second"
