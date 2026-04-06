import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_verify_token_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "database_url": "postgresql://u:p@host/db",
        "user_id": "alice",
        "team_id": "team-01",
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from src.auth import verify_token
        result = await verify_token("xp_abc123", auth_url="https://example.supabase.co/functions/v1/verify-token")

    assert result["user_id"] == "alice"
    assert result["database_url"].startswith("postgresql://")


@pytest.mark.asyncio
async def test_verify_token_invalid_returns_none():
    mock_response = MagicMock()
    mock_response.status_code = 401

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from src.auth import verify_token
        result = await verify_token("bad_token", auth_url="https://example.supabase.co/functions/v1/verify-token")

    assert result is None
