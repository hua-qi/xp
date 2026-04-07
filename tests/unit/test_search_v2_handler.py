import pytest
from unittest.mock import AsyncMock
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.commands import SearchV2Command
from src.application.handlers.search_v2_handler import SearchV2Handler
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType,
)
import numpy as np


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


def make_fake_backend(experiences=None):
    backend = AsyncMock()
    exps = experiences or []
    backend.async_get_ab_group = AsyncMock(return_value="B")
    backend.async_get_experiences_by_project = AsyncMock(return_value=exps)
    ids = [e.id for e in exps]
    vecs = np.ones((len(exps), 2), dtype=np.float32) if exps else np.array([])
    backend.async_get_vectors_by_project = AsyncMock(return_value=(ids, vecs))
    backend.async_record_session = AsyncMock()
    return backend


class FakeEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        v = np.ones(2, dtype=np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def embed_texts(self, texts):
        return [self.embed_text(t) for t in texts]


class TestSearchV2HandlerReturnsResults:
    def _make_handler(self, backend=None, experiences=None):
        if backend is None:
            backend = make_fake_backend(experiences)
        llm = AsyncMock()
        provider = FakeEmbeddingProvider()
        handler = SearchV2Handler(backend=backend, llm=llm, embedding_provider=provider)
        return handler, backend

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_active_experiences(self):
        handler, _ = self._make_handler()
        cmd = SearchV2Command(task_description="修复 bug", project_id="proj-001")
        result = await handler.handle(cmd)
        assert isinstance(result["experiences"], list)
        assert result["experiences"] == []

    @pytest.mark.asyncio
    async def test_returns_session_id(self):
        exp = make_active_exp("exp-001", scope_id="proj-001")
        handler, _ = self._make_handler(experiences=[exp])
        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            session_id="sess-001",
        )
        result = await handler.handle(cmd)
        assert "session_id" in result
        assert result["session_id"] is not None

    @pytest.mark.asyncio
    async def test_project_scope_results_included(self):
        exp = make_active_exp("exp-001", scope_type=ScopeType.PROJECT, scope_id="proj-001")
        handler, _ = self._make_handler(experiences=[exp])
        cmd = SearchV2Command(task_description="修复 bug", project_id="proj-001")
        result = await handler.handle(cmd)
        ids = [r["id"] for r in result["experiences"]]
        assert "exp-001" in ids

    @pytest.mark.asyncio
    async def test_results_contain_required_fields(self):
        exp = make_active_exp("exp-001", scope_id="proj-001")
        handler, _ = self._make_handler(experiences=[exp])
        cmd = SearchV2Command(task_description="修复 bug", project_id="proj-001")
        result = await handler.handle(cmd)
        if result["experiences"]:
            r = result["experiences"][0]
            assert "id" in r
