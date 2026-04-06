import uuid
from datetime import datetime
import pytest


def _make_handler():
    from src.application.handlers.extract_handler import ExtractHandler
    from tests.helpers.fake_uow import InMemoryUnitOfWork
    return ExtractHandler(uow_factory=InMemoryUnitOfWork)


async def test_key_decisions_roundtrip():
    from src.models import ExperienceStatus
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.commands import ExtractExperienceCommand

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())
    handler = _make_handler()
    exp = await handler.handle_extract(ExtractExperienceCommand(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    ))
    assert exp.key_decisions == "不要在 useEffect 里直接调用 setState，会导致无限循环"


def test_quality_gate_rejects_empty_key_decisions():
    from src.application.commands import ExtractExperienceCommand
    import asyncio
    handler = _make_handler()
    with pytest.raises((ValueError, Exception)):
        asyncio.run(handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码，确保状态持久化正常",
            key_decisions="",
        )))


def test_quality_gate_rejects_short_key_decisions():
    from src.application.commands import ExtractExperienceCommand
    import asyncio
    handler = _make_handler()
    with pytest.raises((ValueError, Exception)):
        asyncio.run(handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码，确保状态持久化正常",
            key_decisions="注意一下",
        )))


def test_quality_gate_rejects_short_solution():
    from src.application.commands import ExtractExperienceCommand
    import asyncio
    handler = _make_handler()
    with pytest.raises((ValueError, Exception)):
        asyncio.run(handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录 bug",
            solution_summary="改了代码",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        )))


async def test_key_decisions_stored_separately(monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.commands import ExtractExperienceCommand

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XP_LLM_API_KEY", raising=False)

    handler = _make_handler()
    exp = await handler.handle_extract(ExtractExperienceCommand(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    ))

    assert exp.key_decisions == "不要在 useEffect 里直接调用 setState，会导致无限循环"
    assert "关键决策" not in exp.solution
    assert exp.solution == "在 token 过期时自动刷新，并存入 localStorage，确保状态持久化"


async def test_vectorization_uses_key_decisions_not_solution(monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.commands import ExtractExperienceCommand

    captured_texts = []

    class CapturingProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            captured_texts.extend(texts)
            return [[0.1] * 64 for _ in texts]

    set_provider(CapturingProvider())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XP_LLM_API_KEY", raising=False)

    handler = _make_handler()
    await handler.handle_extract(ExtractExperienceCommand(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    ))

    assert any("不要在 useEffect" in t for t in captured_texts)
    assert not any("localStorage" in t for t in captured_texts)


async def test_llm_title_generation_fallback(monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.commands import ExtractExperienceCommand

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XP_LLM_API_KEY", raising=False)

    handler = _make_handler()
    exp = await handler.handle_extract(ExtractExperienceCommand(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    ))

    assert exp.title.startswith("修复登录后状态不保持")


async def test_dedup_raises_on_similar_experience():
    from src.embeddings import EmbeddingProvider, set_provider
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
    )
    from src.application.commands import ExtractExperienceCommand
    from tests.helpers.fake_uow import InMemoryUnitOfWork

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.9] * 64 for _ in texts]

    set_provider(FakeProvider())

    uow = InMemoryUnitOfWork()
    exp_id = str(uuid.uuid4())
    existing = Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="登录状态不保持修复",
        tags=[],
        problem="修复登录后状态不保持的 bug",
        solution="token 自动刷新",
        key_decisions="不要在 useEffect 里直接 setState",
        confidence=0.8,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(),
    )
    uow.experiences._committed[exp_id] = existing
    uow.vectors._data[exp_id] = [0.9] * 64

    handler = ExtractHandler = __import__(
        "src.application.handlers.extract_handler", fromlist=["ExtractHandler"]
    ).ExtractHandler
    h = handler(uow_factory=lambda: uow)

    with pytest.raises(ValueError, match=exp_id[:8]):
        await h.handle_extract(ExtractExperienceCommand(
            task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
            solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        ))


async def test_review_shows_key_decisions(monkeypatch, capsys):
    from unittest.mock import patch
    from tests.helpers.fake_uow import InMemoryUnitOfWork
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
    )

    uow = InMemoryUnitOfWork()
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="测试标题",
        tags=[],
        problem="测试问题",
        solution="测试解决方案",
        key_decisions="重要坑：不要直接修改 state",
        confidence=0.8,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(),
    )
    uow.experiences._committed[exp.id] = exp

    monkeypatch.setattr("builtins.input", lambda _: "q")

    async def _mock_uow():
        return uow

    with patch("src.cli._get_uow", _mock_uow):
        from src.cli import cmd_review
        await cmd_review([])

    captured = capsys.readouterr()
    assert "关键决策" in captured.out
    assert "重要坑：不要直接修改 state" in captured.out


def test_server_extract_response_includes_key_decisions():
    pytest.skip("depends on mcp module not installed")
