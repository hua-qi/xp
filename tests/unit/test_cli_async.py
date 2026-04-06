import inspect
import src.cli as cli_module
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_main_function_is_async():
    assert inspect.iscoroutinefunction(cli_module.main)


def test_cmd_stats_is_async():
    assert inspect.iscoroutinefunction(cli_module.cmd_stats)


def test_cmd_analyze_is_async():
    assert inspect.iscoroutinefunction(cli_module.cmd_analyze)


@pytest.mark.asyncio
async def test_promote_list_calls_scan_command(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    mock_result = {"candidates": []}
    mock_bus = MagicMock()
    mock_bus.dispatch = AsyncMock(return_value=mock_result)

    with patch("src.cli._get_bus", new=AsyncMock(return_value=mock_bus)):
        from src.cli import cmd_promote
        await cmd_promote(["list"])

    mock_bus.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_promote_list_no_candidates_prints_message(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    mock_bus = MagicMock()
    mock_bus.dispatch = AsyncMock(return_value={"candidates": []})

    with patch("src.cli._get_bus", new=AsyncMock(return_value=mock_bus)):
        from src.cli import cmd_promote
        await cmd_promote(["list"])

    captured = capsys.readouterr()
    assert "候选" in captured.out or "没有" in captured.out
