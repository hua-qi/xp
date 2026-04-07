import pytest
from unittest.mock import AsyncMock
from src.application.commands import FeedbackV2Command
from src.application.handlers.feedback_v2_handler import FeedbackV2Handler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType,
)


def make_exp(exp_id, confidence=0.65):
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title="测试经验",
        tags=["python"],
        problem="问题",
        solution="解决方案超过五十字这里足够长",
        key_decisions="关键决策超过三十字这里",
        confidence=confidence,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at="2026-01-01T00:00:00",
        metadata=ExperienceMetadata(),
        scope_type=ScopeType.PROJECT,
        scope_id="proj-001",
    )


def make_backend():
    backend = AsyncMock()
    backend.async_update_experience_stats = AsyncMock()
    backend.async_update_experience = AsyncMock()
    backend.async_add_correction_request = AsyncMock()
    return backend


class TestFeedbackV2HandlerValidation:
    def _make_handler(self, uow=None, llm_response=None):
        if uow is None:
            uow = InMemoryUnitOfWork()
        backend = make_backend()
        llm = AsyncMock()
        llm.call = AsyncMock(return_value=llm_response)
        handler = FeedbackV2Handler(uow_factory=lambda: uow, backend=backend, llm=llm)
        return handler, uow, backend

    @pytest.mark.asyncio
    async def test_valid_helpful_id_increases_confidence(self):
        uow = InMemoryUnitOfWork()
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.65)
        handler, uow, _ = self._make_handler(uow=uow)
        cmd = FeedbackV2Command(session_id="sess-001", adopted_ids=["exp-001"])
        await handler.handle(cmd)
        updated_exp = uow.experiences.get("exp-001")
        assert abs(updated_exp.confidence - 0.75) < 1e-4

    @pytest.mark.asyncio
    async def test_valid_unhelpful_id_decreases_confidence(self):
        uow = InMemoryUnitOfWork()
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.65)
        handler, uow, _ = self._make_handler(uow=uow)
        cmd = FeedbackV2Command(session_id="sess-001", rejected_ids=["exp-001"])
        await handler.handle(cmd)
        updated_exp = uow.experiences.get("exp-001")
        assert abs(updated_exp.confidence - 0.60) < 1e-4

    @pytest.mark.asyncio
    async def test_confidence_below_0_2_marks_for_archive(self):
        uow = InMemoryUnitOfWork()
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.22)
        handler, uow, _ = self._make_handler(uow=uow)
        cmd = FeedbackV2Command(session_id="sess-001", rejected_ids=["exp-001"])
        await handler.handle(cmd)
        updated_exp = uow.experiences.get("exp-001")
        assert updated_exp.status == ExperienceStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_needs_fix_comment_creates_correction_request(self):
        uow = InMemoryUnitOfWork()
        uow.experiences._committed["exp-001"] = make_exp("exp-001")
        handler, uow, backend = self._make_handler(uow=uow, llm_response="needs_fix")
        cmd = FeedbackV2Command(
            session_id="sess-001",
            rejected_ids=["exp-001"],
            comment="方向对但版本号有误",
        )
        await handler.handle(cmd)
        backend.async_add_correction_request.assert_called_once()
