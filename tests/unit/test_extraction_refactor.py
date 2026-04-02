import json
import uuid
from datetime import datetime

import pytest


def make_store(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore
    return ExperienceStore()


def test_key_decisions_roundtrip(tmp_path, monkeypatch):
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )

    store = make_store(tmp_path, monkeypatch)
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="测试标题",
        tags=[],
        problem="测试问题",
        solution="测试解决方案",
        confidence=0.8,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        key_decisions="这是关键决策，不要在 useEffect 直接 setState",
    )
    store.add(exp)
    loaded = store.get(exp.id)
    assert loaded is not None
    assert loaded.key_decisions == "这是关键决策，不要在 useEffect 直接 setState"


def test_key_decisions_backward_compat(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    exp_id = str(uuid.uuid4())
    old_data = {
        exp_id: {
            "id": exp_id,
            "type": "bugfix",
            "level": "L2",
            "title": "旧经验",
            "tags": [],
            "problem": "旧问题",
            "solution": "旧解决方案",
            "confidence": 0.8,
            "status": "active",
            "source": "agent",
            "created_at": datetime.utcnow().isoformat(),
        }
    }
    knowledge_file = tmp_path / "knowledge.json"
    knowledge_file.write_text(json.dumps(old_data), encoding="utf-8")

    from src.storage import ExperienceStore
    store = ExperienceStore()
    loaded = store.get(exp_id)
    assert loaded is not None
    assert loaded.key_decisions == ""


def _make_handler(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.application.handlers.extract_handler import ExtractHandler
    from src.infrastructure.unit_of_work import UnitOfWork
    return ExtractHandler(uow_factory=UnitOfWork)


def test_quality_gate_rejects_empty_key_decisions(tmp_path, monkeypatch):
    from src.application.commands import ExtractExperienceCommand
    handler = _make_handler(tmp_path, monkeypatch)
    with pytest.raises((ValueError, Exception)):
        handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码，确保状态持久化正常",
            key_decisions="",
        ))


def test_quality_gate_rejects_short_key_decisions(tmp_path, monkeypatch):
    from src.application.commands import ExtractExperienceCommand
    handler = _make_handler(tmp_path, monkeypatch)
    with pytest.raises((ValueError, Exception)):
        handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码，确保状态持久化正常",
            key_decisions="注意一下",
        ))


def test_quality_gate_rejects_short_solution(tmp_path, monkeypatch):
    from src.application.commands import ExtractExperienceCommand
    handler = _make_handler(tmp_path, monkeypatch)
    with pytest.raises((ValueError, Exception)):
        handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录 bug",
            solution_summary="改了代码",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        ))


def test_key_decisions_stored_separately(tmp_path, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.commands import ExtractExperienceCommand

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XP_LLM_API_KEY", raising=False)

    handler = _make_handler(tmp_path, monkeypatch)
    exp = handler.handle_extract(ExtractExperienceCommand(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    ))

    assert exp.key_decisions == "不要在 useEffect 里直接调用 setState，会导致无限循环"
    assert "关键决策" not in exp.solution
    assert exp.solution == "在 token 过期时自动刷新，并存入 localStorage，确保状态持久化"


def test_vectorization_uses_key_decisions_not_solution(tmp_path, monkeypatch):
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

    handler = _make_handler(tmp_path, monkeypatch)
    handler.handle_extract(ExtractExperienceCommand(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    ))

    assert any("不要在 useEffect" in t for t in captured_texts), \
        f"向量文本应包含 key_decisions，实际: {captured_texts}"
    assert not any("localStorage" in t for t in captured_texts), \
        f"向量文本不应包含 solution_summary，实际: {captured_texts}"


def test_llm_title_generation_fallback(tmp_path, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.commands import ExtractExperienceCommand

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XP_LLM_API_KEY", raising=False)

    handler = _make_handler(tmp_path, monkeypatch)
    exp = handler.handle_extract(ExtractExperienceCommand(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    ))

    assert exp.title.startswith("修复登录后状态不保持")


def test_dedup_raises_on_similar_experience(tmp_path, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    from src.storage import VectorStore
    from src.application.commands import ExtractExperienceCommand

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.9] * 64 for _ in texts]

    set_provider(FakeProvider())

    handler = _make_handler(tmp_path, monkeypatch)

    import src.storage as storage_mod
    store = storage_mod.ExperienceStore()
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
    )
    store.add(existing)
    VectorStore().save_vector(exp_id, [0.9] * 64)

    with pytest.raises(ValueError, match=exp_id[:8]):
        handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
            solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        ))


def test_review_shows_key_decisions(tmp_path, monkeypatch, capsys):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.storage import ExperienceStore
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )

    store = ExperienceStore()
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
    )
    store.add(exp)

    monkeypatch.setattr("builtins.input", lambda _: "q")

    from src.cli import cmd_review
    cmd_review([])

    captured = capsys.readouterr()
    assert "关键决策" in captured.out
    assert "重要坑：不要直接修改 state" in captured.out


def test_server_extract_response_includes_key_decisions(tmp_path, monkeypatch):
    pytest.skip("depends on mcp module not installed")
