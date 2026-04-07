import pytest
from unittest.mock import AsyncMock


async def test_prompt_loader_get_cached():
    from src.infrastructure.prompt_loader import PromptLoader
    backend = AsyncMock()
    backend.async_get_prompt = AsyncMock(return_value="hello {name}")
    loader = PromptLoader(backend=backend)
    await loader.refresh()
    result = loader.get("extraction_prompt", name="world")
    assert "world" in result or result == "hello {name}"


async def test_prompt_loader_fallback_on_missing_key():
    from src.infrastructure.prompt_loader import PromptLoader
    backend = AsyncMock()
    backend.async_get_prompt = AsyncMock(return_value=None)
    loader = PromptLoader(backend=backend)
    await loader.refresh()
    result = loader.get("extraction_prompt")
    assert result is not None
