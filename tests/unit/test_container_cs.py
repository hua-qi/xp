from unittest.mock import MagicMock


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
    assert SaveCommand in bus._handlers
