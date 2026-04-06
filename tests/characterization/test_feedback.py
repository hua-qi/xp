import pytest
import uuid
from datetime import datetime
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)


def make_exp(uow_instance, status=ExperienceStatus.ACTIVE, confidence=0.6):
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="测试经验",
        tags=[],
        problem="测试问题描述",
        solution="测试解决方案描述",
        key_decisions="关键决策：注意这里的坑",
        confidence=confidence,
        status=status,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(),
    )
    uow_instance.experiences._committed[exp.id] = exp
    return exp


class TestRecordFeedback:
    async def test_returns_true_for_existing_exp(self, svc, uow):
        exp = make_exp(uow)
        result = await svc.record_feedback(exp.id, adopted=True)
        assert result is True

    async def test_returns_false_for_nonexistent(self, svc):
        result = await svc.record_feedback("nonexistent-id", adopted=True)
        assert result is False

    async def test_confidence_decreases_on_rejection(self, svc, uow):
        exp = make_exp(uow, confidence=0.6)
        original_confidence = exp.confidence

        await svc.record_feedback(exp.id, adopted=False)
        await svc.record_feedback(exp.id, adopted=False)

        updated = uow.experiences._committed.get(exp.id) or uow.experiences._pending.get(exp.id)
        assert updated.confidence < original_confidence

    async def test_auto_archive_when_confidence_too_low(self, svc, uow):
        exp = make_exp(uow, confidence=0.11)

        for _ in range(20):
            await svc.record_feedback(exp.id, adopted=False)

        updated = uow.experiences._committed.get(exp.id) or uow.experiences._pending.get(exp.id)
        assert updated.status == ExperienceStatus.ARCHIVED
