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


@pytest.fixture
def service(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    return KnowledgeService(ExperienceStore(), MetricsStore())


async def test_quality_gate_rejects_empty_key_decisions(service):
    with pytest.raises(ValueError, match="key_decisions"):
        await service.extract_experience(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码，确保状态持久化正常",
            key_decisions="",
        )


async def test_quality_gate_rejects_short_key_decisions(service):
    with pytest.raises(ValueError, match="key_decisions"):
        await service.extract_experience(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码，确保状态持久化正常",
            key_decisions="注意一下",
        )


async def test_quality_gate_rejects_short_solution(service):
    with pytest.raises(ValueError, match="solution_summary"):
        await service.extract_experience(
            task_description="修复登录 bug",
            solution_summary="改了代码",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        )


async def test_key_decisions_stored_separately(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    monkeypatch.setattr(service, "_llm_generate_title", lambda text: (_ for _ in ()).throw(RuntimeError("no llm")))

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    assert exp.key_decisions == "不要在 useEffect 里直接调用 setState，会导致无限循环"
    assert "关键决策" not in exp.solution
    assert exp.solution == "在 token 过期时自动刷新，并存入 localStorage，确保状态持久化"


async def test_vectorization_uses_key_decisions_not_solution(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    captured_texts = []

    class CapturingProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            captured_texts.extend(texts)
            return [[0.1] * 64 for _ in texts]

    set_provider(CapturingProvider())

    monkeypatch.setattr(service, "_llm_generate_title", lambda text: (_ for _ in ()).throw(RuntimeError("no llm")))

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    assert any("不要在 useEffect" in t for t in captured_texts), \
        f"向量文本应包含 key_decisions，实际: {captured_texts}"
    assert not any("localStorage" in t for t in captured_texts), \
        f"向量文本不应包含 solution_summary，实际: {captured_texts}"


async def test_llm_title_generation_success(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def fake_llm_title(text):
        return "登录状态不保持修复"

    monkeypatch.setattr(service, "_llm_generate_title", fake_llm_title)

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    assert exp.title == "登录状态不保持修复"


async def test_llm_title_generation_fallback(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def failing_llm_title(text):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(service, "_llm_generate_title", failing_llm_title)

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    assert exp.title.startswith("修复登录后状态不保持")


async def test_dedup_raises_on_similar_experience(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    from src.storage import VectorStore

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.9] * 64 for _ in texts]

    set_provider(FakeProvider())

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
    service._store.add(existing)

    import src.storage as storage_mod
    VectorStore().save_vector(exp_id, [0.9] * 64)

    with pytest.raises(ValueError, match=exp_id[:8]):
        await service.extract_experience(
            task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
            solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        )


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


async def test_server_extract_response_includes_key_decisions(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    import src.server as server_mod
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService

    async def fake_llm_title(self, text):
        raise RuntimeError("no llm")

    monkeypatch.setattr(KnowledgeService, "_llm_generate_title", fake_llm_title)

    svc = KnowledgeService(ExperienceStore(), MetricsStore())
    monkeypatch.setattr(server_mod, "_service", svc)

    result = await server_mod.call_tool("extract_experience", {
        "task_description": "修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        "solution_summary": "在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        "key_decisions": "不要在 useEffect 里直接调用 setState，会导致无限循环",
    })

    data = json.loads(result[0].text)
    assert "key_decisions" in data
    assert data["key_decisions"] == "不要在 useEffect 里直接调用 setState，会导致无限循环"
