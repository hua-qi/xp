import pytest
from datetime import datetime, timedelta
from src.application.commands import ScanPromotionCandidatesCommand
from src.application.handlers.promotion_handler import PromotionScanHandler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType,
)


def make_exp(exp_id, scope_id="proj-001", adoption_rate=0.8, recall_count=10, age_days=60):
    created_at = (datetime.utcnow() - timedelta(days=age_days)).isoformat()
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title=f"经验 {exp_id}",
        tags=["python"],
        problem="null 检查问题",
        solution="在 Service 层添加 null 检查",
        key_decisions="在 Service 而非 DAO 层检查",
        confidence=0.65,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=created_at,
        metadata=ExperienceMetadata(tech_stack=["python"]),
        scope_type=ScopeType.PROJECT,
        scope_id=scope_id,
        adoption_rate=adoption_rate,
        recall_count=recall_count,
    )


class FakeEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        import numpy as np
        v = np.ones(64, dtype=np.float32)
        return (v / np.linalg.norm(v)).tolist()


class TestPromotionScanHandler:
    def _make_handler(self, uow=None):
        if uow is None:
            uow = InMemoryUnitOfWork()
        provider = FakeEmbeddingProvider()
        handler = PromotionScanHandler(uow_factory=lambda: uow, embedding_provider=provider)
        return handler, uow

    @pytest.mark.asyncio
    async def test_no_candidates_when_store_empty(self):
        handler, uow = self._make_handler()
        cmd = ScanPromotionCandidatesCommand()
        result = await handler.handle(cmd)
        assert result["candidates"] == []

    @pytest.mark.asyncio
    async def test_no_candidates_when_no_vectors(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp1
        cmd = ScanPromotionCandidatesCommand()
        result = await handler.handle(cmd)
        assert result["candidates"] == []

    @pytest.mark.asyncio
    async def test_finds_candidates_across_two_projects(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        exp2 = make_exp("exp-002", scope_id="proj-002")
        uow.experiences._committed["exp-001"] = exp1
        uow.experiences._committed["exp-002"] = exp2
        vec = FakeEmbeddingProvider().embed_text("test")
        uow.vectors.save_vector("exp-001", vec)
        uow.vectors.save_vector("exp-002", vec)

        cmd = ScanPromotionCandidatesCommand()
        result = await handler.handle(cmd)
        assert len(result["candidates"]) >= 1

    @pytest.mark.asyncio
    async def test_candidate_has_required_fields(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        exp2 = make_exp("exp-002", scope_id="proj-002")
        uow.experiences._committed["exp-001"] = exp1
        uow.experiences._committed["exp-002"] = exp2
        vec = FakeEmbeddingProvider().embed_text("test")
        uow.vectors.save_vector("exp-001", vec)
        uow.vectors.save_vector("exp-002", vec)

        result = await handler.handle(ScanPromotionCandidatesCommand())
        if result["candidates"]:
            c = result["candidates"][0]
            assert "experience_id" in c
            assert "score" in c
            assert "cross_project_count" in c
            assert "reason" in c

    @pytest.mark.asyncio
    async def test_dry_run_does_not_modify_experiences(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        exp2 = make_exp("exp-002", scope_id="proj-002")
        uow.experiences._committed["exp-001"] = exp1
        uow.experiences._committed["exp-002"] = exp2
        vec = FakeEmbeddingProvider().embed_text("test")
        uow.vectors.save_vector("exp-001", vec)
        uow.vectors.save_vector("exp-002", vec)

        await handler.handle(ScanPromotionCandidatesCommand(dry_run=True))
        assert uow.experiences.get("exp-001").stale_reason is None

    @pytest.mark.asyncio
    async def test_non_dry_run_marks_stale_reason(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        exp2 = make_exp("exp-002", scope_id="proj-002")
        uow.experiences._committed["exp-001"] = exp1
        uow.experiences._committed["exp-002"] = exp2
        vec = FakeEmbeddingProvider().embed_text("test")
        uow.vectors.save_vector("exp-001", vec)
        uow.vectors.save_vector("exp-002", vec)

        result = await handler.handle(ScanPromotionCandidatesCommand(dry_run=False))
        if result["candidates"]:
            exp_id = result["candidates"][0]["experience_id"]
            updated_exp = uow.experiences.get(exp_id)
            assert updated_exp.stale_reason is not None
            assert "promotion_candidate" in updated_exp.stale_reason

    @pytest.mark.asyncio
    async def test_same_project_exps_not_counted_as_cross_project(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        exp2 = make_exp("exp-002", scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp1
        uow.experiences._committed["exp-002"] = exp2
        vec = FakeEmbeddingProvider().embed_text("test")
        uow.vectors.save_vector("exp-001", vec)
        uow.vectors.save_vector("exp-002", vec)

        result = await handler.handle(ScanPromotionCandidatesCommand())
        assert result["candidates"] == []
