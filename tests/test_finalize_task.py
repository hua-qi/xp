import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def service(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    return KnowledgeService(ExperienceStore(), MetricsStore())


async def test_finalize_task_method_exists(service):
    assert hasattr(service, "finalize_task")


async def test_finalize_task_extract_fails_session_still_runs(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    result = await service.finalize_task(
        session_id="test-session-001",
        task_description="测试任务",
        solution_summary="解决方案摘要超过二十个字符的内容",
        key_decisions="短",
        final_response="最终回复内容",
    )

    assert result["extract"]["status"] == "skipped"
    assert "key_decisions" in result["extract"]["reason"]
    assert result["session"]["status"] == "ok"


async def test_finalize_task_all_steps_succeed(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def fake_llm_title(text):
        raise RuntimeError("no llm")

    monkeypatch.setattr(service, "_llm_generate_title", fake_llm_title)

    result = await service.finalize_task(
        session_id="test-session-002",
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        final_response="实现了 token 自动刷新逻辑",
    )

    assert result["extract"]["status"] == "ok"
    assert result["extract"]["id"] is not None
    assert result["session"]["status"] == "ok"
    assert result["adoption"]["status"] == "ok"


async def test_server_finalize_task_extract_fails_session_recorded(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    import src.server as server_mod
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    svc = KnowledgeService(ExperienceStore(), MetricsStore())
    monkeypatch.setattr(server_mod, "_service", svc)

    result = await server_mod.call_tool("finalize_task", {
        "session_id": "server-test-001",
        "task_description": "测试任务描述",
        "solution_summary": "解决方案摘要超过二十个字符的内容",
        "key_decisions": "短",
        "final_response": "最终回复",
    })

    import json
    data = json.loads(result[0].text)
    assert data["extract"]["status"] == "skipped"
    assert data["session"]["status"] == "ok"
