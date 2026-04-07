from unittest.mock import AsyncMock, MagicMock, patch


def make_mock_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


async def test_llm_call_returns_content():
    from src.infrastructure.llm import LLMClient
    client = LLMClient(api_base="http://fake", api_key="key", model="gpt-4o-mini", timeout=10)
    with patch.object(client._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = make_mock_response("hello")
        result = await client.call("你好")
    assert result == "hello"


async def test_llm_call_returns_none_on_timeout():
    from src.infrastructure.llm import LLMClient
    import asyncio
    client = LLMClient(api_base="http://fake", api_key="key", model="gpt-4o-mini", timeout=1)
    with patch.object(client._client.chat.completions, "create", side_effect=asyncio.TimeoutError):
        result = await client.call("你好")
    assert result is None
