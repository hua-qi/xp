import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import secrets


@pytest.mark.asyncio
async def test_admin_create_token_writes_to_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    fake_token = "xp_" + secrets.token_urlsafe(16)
    mock_backend = MagicMock()
    mock_backend.execute = AsyncMock()
    mock_backend.acquire = AsyncMock()

    with patch("src.cli._admin_insert_token", new=AsyncMock(return_value=fake_token)) as mock_insert, \
         patch("builtins.input", side_effect=["alice", "team-01"]):
        from src.cli import cmd_admin
        await cmd_admin(["create-token"])

    mock_insert.assert_called_once()
    call_kwargs = mock_insert.call_args
    assert call_kwargs.kwargs.get("user_id") == "alice" or call_kwargs.args[0] == "alice"


@pytest.mark.asyncio
async def test_admin_create_token_prints_token(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    with patch("src.cli._admin_insert_token", new=AsyncMock(return_value="xp_generated_token")), \
         patch("builtins.input", side_effect=["bob", "team-02"]):
        from src.cli import cmd_admin
        await cmd_admin(["create-token"])

    captured = capsys.readouterr()
    assert "xp_generated_token" in captured.out


@pytest.mark.asyncio
async def test_admin_create_team_requires_name(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    with patch("builtins.input", side_effect=["", ""]):
        from src.cli import cmd_admin
        await cmd_admin(["create-team"])
    captured = capsys.readouterr()
    assert "错误" in captured.out or "不能为空" in captured.out


@pytest.mark.asyncio
async def test_admin_create_business_requires_name(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    with patch("builtins.input", side_effect=["", ""]):
        from src.cli import cmd_admin
        await cmd_admin(["create-business"])
    captured = capsys.readouterr()
    assert "错误" in captured.out or "不能为空" in captured.out


@pytest.mark.asyncio
async def test_admin_unknown_subcommand_prints_usage(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    from src.cli import cmd_admin
    await cmd_admin(["unknown-cmd"])
    captured = capsys.readouterr()
    assert "用法" in captured.out or "usage" in captured.out.lower()
