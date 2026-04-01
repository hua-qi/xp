import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata, ExperienceStats,
)


def make_exp(confidence=0.6):
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
    async def test_returns_false_for_nonexistent(self):
        from src.domain.feedback import FeedbackService
        mock_store = MagicMock()
        mock_store.get.return_value = None
        mock_metrics = MagicMock()
        svc = FeedbackService(mock_store, mock_metrics)
        result = await svc.record_feedback("nonexistent", adopted=True)
        assert result is False

    async def test_adopted_true_increases_confidence(self):
        from src.domain.feedback import FeedbackService
        exp = make_exp(confidence=0.6)
        mock_store = MagicMock()
        mock_store.get.return_value = exp
        mock_metrics = MagicMock()
        stats = ExperienceStats(
            experience_id=exp.id,
            hit_count=1, adopted_count=1, rejected_count=0,
            adoption_rate=1.0,
        )
        mock_metrics.get_experience_stats.return_value = stats
        svc = FeedbackService(mock_store, mock_metrics)

        await svc.record_feedback(exp.id, adopted=True)
        mock_store.update.assert_called_once()
        updated_exp = mock_store.update.call_args[0][0]
        assert updated_exp.confidence > 0.6

    async def test_low_confidence_auto_archives(self):
        from src.domain.feedback import FeedbackService
        exp = make_exp(confidence=0.05)
        mock_store = MagicMock()
        mock_store.get.return_value = exp
        mock_metrics = MagicMock()
        stats = ExperienceStats(
            experience_id=exp.id,
            hit_count=10, adopted_count=0, rejected_count=10,
            adoption_rate=0.0,
        )
        mock_metrics.get_experience_stats.return_value = stats
        svc = FeedbackService(mock_store, mock_metrics)

        await svc.record_feedback(exp.id, adopted=False)
        updated_exp = mock_store.update.call_args[0][0]
        assert updated_exp.status == ExperienceStatus.ARCHIVED
