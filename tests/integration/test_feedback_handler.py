import pytest
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.handlers.feedback_handler import FeedbackHandler
from src.application.commands import RecordFeedbackCommand
from src.domain.events import FeedbackRecorded
from src.domain.constants import CONFIDENCE_HELPFUL_DELTA, CONFIDENCE_UNHELPFUL_DELTA


def _make_fake_exp(exp_id: str, confidence: float = 0.5):
    class FakeExp:
        id = exp_id
        status = "ACTIVE"
        reject_reason = None

        def __init__(self, conf):
            self.confidence = conf

    return FakeExp(confidence)


@pytest.mark.asyncio
async def test_helpful_feedback_raises_confidence():
    uow = InMemoryUnitOfWork()
    exp = _make_fake_exp("exp-001", confidence=0.5)
    uow.experiences._committed["exp-001"] = exp

    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="exp-001", helpful=True)
    await handler.handle_feedback(cmd)

    updated = uow.experiences.get("exp-001")
    assert updated.confidence == round(0.5 + CONFIDENCE_HELPFUL_DELTA, 3)


@pytest.mark.asyncio
async def test_unhelpful_feedback_lowers_confidence():
    uow = InMemoryUnitOfWork()
    exp = _make_fake_exp("exp-002", confidence=0.5)
    uow.experiences._committed["exp-002"] = exp

    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="exp-002", helpful=False)
    await handler.handle_feedback(cmd)

    updated = uow.experiences.get("exp-002")
    assert updated.confidence == round(0.5 + CONFIDENCE_UNHELPFUL_DELTA, 3)


@pytest.mark.asyncio
async def test_feedback_recorded_event_published():
    uow = InMemoryUnitOfWork()
    exp = _make_fake_exp("exp-003", confidence=0.5)
    uow.experiences._committed["exp-003"] = exp

    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="exp-003", helpful=True)
    await handler.handle_feedback(cmd)

    events = uow.get_events()
    feedback_events = [e for e in events if isinstance(e, FeedbackRecorded)]
    assert len(feedback_events) == 1
    assert feedback_events[0].experience_id == "exp-003"
    assert feedback_events[0].helpful is True


@pytest.mark.asyncio
async def test_feedback_for_nonexistent_experience_returns_false():
    uow = InMemoryUnitOfWork()
    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="not-exist", helpful=True)
    result = await handler.handle_feedback(cmd)
    assert result is False
