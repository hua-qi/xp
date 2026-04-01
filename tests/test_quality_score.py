import pytest


@pytest.fixture
def service(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    return KnowledgeService(ExperienceStore(), MetricsStore())


def test_quality_score_method_exists(service):
    assert hasattr(service, "_compute_quality_score")


def test_quality_score_high(service):
    score = service._compute_quality_score(
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环，应该使用 useCallback 包裹",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化，不影响用户体验",
        related_files=["src/hooks/useAuth.ts"],
        tech_stack=["react", "typescript"],
        duplicate_similarity=0.1,
    )
    assert score >= 80


def test_quality_score_medium(service):
    score = service._compute_quality_score(
        key_decisions="注意不要直接在渲染函数里调用 setState",
        solution_summary="修改了代码逻辑，将状态更新移到回调中，状态正常了",
        related_files=[],
        tech_stack=[],
        duplicate_similarity=0.5,
    )
    assert 40 <= score < 80


def test_quality_score_low(service):
    score = service._compute_quality_score(
        key_decisions="短",
        solution_summary="改了",
        related_files=[],
        tech_stack=[],
        duplicate_similarity=0.5,
    )
    assert score < 40


async def test_high_quality_auto_activates(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.models import ExperienceStatus

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def fake_llm_title(text):
        raise RuntimeError("no llm")

    monkeypatch.setattr(service, "_llm_generate_title", fake_llm_title)

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化，不影响用户体验",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环，应该使用 useCallback 包裹回调函数",
        related_files=["src/hooks/useAuth.ts"],
        tags=["react", "typescript"],
    )

    assert exp.status == ExperienceStatus.ACTIVE
    assert exp.confidence == 0.65


async def test_low_quality_rejected(service):
    with pytest.raises(ValueError, match="质量评分过低"):
        await service.extract_experience(
            task_description="改了个东西，修复了一个小问题",
            solution_summary="把代码里的判断条件改了一下，现在功能正常了可以用",
            key_decisions="注意别直接修改状态变量",
        )
