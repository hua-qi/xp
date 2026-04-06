import json
import pytest
from pathlib import Path


def test_save_and_load_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({
        "token": "xp_test123",
        "user_id": "alice",
        "team_id": "team-01",
        "database_url": "postgresql://u:p@host/db",
    })

    result = cfg_module.load_config()
    assert result["token"] == "xp_test123"
    assert result["user_id"] == "alice"
    assert result["database_url"] == "postgresql://u:p@host/db"


def test_load_config_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    result = cfg_module.load_config()
    assert result is None


def test_config_file_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({"token": "x"})
    assert (tmp_path / "config.json").exists()


def test_config_token_only_is_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({"token": "xp_abc"})
    result = cfg_module.load_config()
    assert result["token"] == "xp_abc"
    assert "database_url" not in result
