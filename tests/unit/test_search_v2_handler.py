import pytest
from src.application.commands import SearchV2Command
from src.application.handlers.search_v2_handler import SearchV2Handler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType, SearchEvent,
)


def make_active_exp(exp_id, scope_type=ScopeType.PROJECT, scope_id="proj-001", tags=None):
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title=f"经验 {exp_id}",
        tags=tags or ["python"],
        problem="问题",
        solution="解决方案，超过五十个字的详细描述文本内容这里要足够长才行",
        key_decisions="关键决策，超过三十字的关键信息",
        confidence=0.65,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at="2026-01-01T00:00:00",
        metadata=ExperienceMetadata(tech_stack=tags or ["python"]),
        scope_type=scope_type,
        scope_id=scope_id,
    )


class FakeEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        import numpy as np
        v = np.ones(64, dtype=np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


class TestSearchV2HandlerReturnsResults:
    def _make_handler_and_uow(self):
        uow = InMemoryUnitOfWork()
        provider = FakeEmbeddingProvider()
        handler = SearchV2Handler(uow_factory=lambda: uow, embedding_provider=provider)
        return handler, uow

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_active_experiences(self):
        handler, uow = self._make_handler_and_uow()
        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest="",
        )
        result = await handler.handle(cmd)
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_returns_search_event_id(self):
        handler, uow = self._make_handler_and_uow()
        exp = make_active_exp("exp-001", scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))

        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest='{"dependencies": {"fastapi": "^0.110"}}',
            session_id="sess-001",
        )
        result = await handler.handle(cmd)
        assert "search_event_id" in result
        assert result["search_event_id"] is not None

    @pytest.mark.asyncio
    async def test_project_scope_results_included(self):
        handler, uow = self._make_handler_and_uow()
        exp = make_active_exp("exp-001", scope_type=ScopeType.PROJECT, scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))

        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest="",
        )
        result = await handler.handle(cmd)
        ids = [r["id"] for r in result["results"]]
        assert "exp-001" in ids

    @pytest.mark.asyncio
    async def test_results_contain_required_fields(self):
        handler, uow = self._make_handler_and_uow()
        exp = make_active_exp("exp-001", scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))

        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest="",
        )
        result = await handler.handle(cmd)
        if result["results"]:
            r = result["results"][0]
            assert "id" in r
            assert "title" in r
            assert "solution" in r
            assert "key_decisions" in r
            assert "source_level" in r
            assert "tags" in r
