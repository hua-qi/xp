import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager


@pytest.mark.asyncio
async def test_server_main_uses_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)
    cfg_module.save_config({
        "token": "xp_abc",
        "user_id": "alice",
        "edge_function_url": "https://test.supabase.co/functions/v1",
    })

    mock_read = MagicMock()
    mock_write = MagicMock()

    import src.server as server_module
    importlib.reload(server_module)

    @asynccontextmanager
    async def _fake_stdio():
        yield (mock_read, mock_write)

    server_module.stdio_server = _fake_stdio
    server_module.app.run = AsyncMock()
    server_module.app.create_initialization_options = MagicMock(return_value={})

    await server_module.main()

    assert server_module._edge_client is not None


@pytest.mark.asyncio
async def test_server_main_exits_when_no_config_and_no_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XP_HOME", str(tmp_path))

    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    import src.server as server_module
    importlib.reload(server_module)

    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit):
        await server_module.main()

    captured = capsys.readouterr()
    assert "xp login" in captured.err or "xp login" in captured.out


@pytest.mark.asyncio
async def test_server_call_tool_search_uses_edge_client(monkeypatch, tmp_path):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({
        "token": "xp_test",
        "edge_function_url": "https://test.supabase.co/functions/v1",
    })

    mock_search_result = {"results": [], "search_event_id": "evt-001"}

    with patch("src.server.EdgeFunctionClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=mock_search_result)
        mock_client_cls.return_value = mock_client

        import src.server as server_module
        importlib.reload(server_module)
        server_module._edge_client = mock_client

        from mcp.types import TextContent
        result = await server_module.call_tool(
            "search",
            {
                "task_description": "修复 bug",
                "project_id": "github.com/org/repo",
                "project_manifest": "{}",
            },
        )

    mock_client.search.assert_called_once()
    assert isinstance(result, list)
    assert isinstance(result[0], TextContent)
