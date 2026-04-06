import pytest
import uuid
from datetime import datetime
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)
from src.domain.feedback import compute_new_confidence
from src.domain.constants import (
    CONFIDENCE_HELPFUL_DELTA,
    CONFIDENCE_UNHELPFUL_DELTA,
    AUTO_ARCHIVE_ADOPTION_THRESHOLD,
)
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.handlers.feedback_handler import FeedbackHandler
from src.application.commands import RecordFeedbackCommand


def make_exp(confidence=0.6) -> Experience:
    return Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="t", tags=[], problem="p", solution="s",
        key_decisions="kd", confidence=confidence,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(),
    )


class TestFeedbackService:
    @pytest.mark.asyncio
    async def test_returns_false_for_nonexistent(self):
        uow = InMemoryUnitOfWork()
        handler = FeedbackHandler(lambda: uow)
        result = await handler.handle_feedback(
            RecordFeedbackCommand(experience_id="nonexistent", helpful=True)
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_adopted_true_increases_confidence(self):
        exp = make_exp(confidence=0.6)
        uow = InMemoryUnitOfWork()
        uow.experiences._committed[exp.id] = exp

        handler = FeedbackHandler(lambda: uow)
        await handler.handle_feedback(RecordFeedbackCommand(experience_id=exp.id, helpful=True))

        updated = uow.experiences.get(exp.id)
        assert updated.confidence == round(0.6 + CONFIDENCE_HELPFUL_DELTA, 3)

    @pytest.mark.asyncio
    async def test_low_confidence_auto_archives(self):
        exp = make_exp(confidence=AUTO_ARCHIVE_ADOPTION_THRESHOLD)
        uow = InMemoryUnitOfWork()
        uow.experiences._committed[exp.id] = exp

        handler = FeedbackHandler(lambda: uow)
        await handler.handle_feedback(RecordFeedbackCommand(experience_id=exp.id, helpful=False))

        updated = uow.experiences.get(exp.id)
        assert updated.status == ExperienceStatus.ARCHIVED
