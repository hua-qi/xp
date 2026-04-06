import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_login_success_writes_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))

    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    verify_result = {
        "database_url": "postgresql://u:p@host/db",
        "user_id": "alice",
        "team_id": "team-01",
    }

    with patch("src.cli.verify_token", new=AsyncMock(return_value=verify_result)), \
         patch("builtins.input", return_value="xp_abc123"):
        from src.cli import cmd_login
        await cmd_login([])

    config = cfg_module.load_config()
    assert config is not None
    assert config["token"] == "xp_abc123"
    assert config["user_id"] == "alice"


@pytest.mark.asyncio
async def test_login_invalid_token_prints_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XP_HOME", str(tmp_path))

    with patch("src.cli.verify_token", new=AsyncMock(return_value=None)), \
         patch("builtins.input", return_value="bad_token"):
        from src.cli import cmd_login
        await cmd_login([])

    captured = capsys.readouterr()
    assert "无效" in captured.out or "失败" in captured.out


@pytest.mark.asyncio
async def test_login_does_not_write_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))

    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    verify_result = {
        "user_id": "alice",
        "project_id": "github.com/org/repo",
        "edge_function_url": "https://xxx.supabase.co/functions/v1",
    }

    with patch("src.cli.verify_token", new=AsyncMock(return_value=verify_result)), \
         patch("builtins.input", return_value="xp_abc123"):
        from src.cli import cmd_login
        await cmd_login([])

    config = cfg_module.load_config()
    assert config is not None
    assert config["token"] == "xp_abc123"
    assert "database_url" not in config
    assert config.get("edge_function_url") == "https://xxx.supabase.co/functions/v1"
