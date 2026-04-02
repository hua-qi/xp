from typing import Optional
from ..models import Feedback, ExperienceStatus
from .constants import (
    CONFIDENCE_HELPFUL_DELTA,
    CONFIDENCE_UNHELPFUL_DELTA,
    CONFIDENCE_MIN,
    CONFIDENCE_MAX,
)


def compute_new_confidence(current: float, helpful: bool) -> float:
    delta = CONFIDENCE_HELPFUL_DELTA if helpful else CONFIDENCE_UNHELPFUL_DELTA
    return round(max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, current + delta)), 3)


class FeedbackService:
    def __init__(self, store, metrics):
        self._store = store
        self._metrics = metrics

    async def record_feedback(self, experience_id: str, adopted: bool, reason: Optional[str] = None) -> bool:
        exp = self._store.get(experience_id)
        if not exp:
            return False

        feedback = Feedback(experience_id=experience_id, adopted=adopted, reason=reason)
        self._metrics.record_feedback(feedback)

        stats = self._metrics.get_experience_stats(experience_id)
        if stats:
            new_confidence = exp.confidence * 0.9 + stats.adoption_rate * 0.1
            exp.confidence = round(new_confidence, 3)
            if exp.confidence < 0.1:
                exp.status = ExperienceStatus.ARCHIVED
                exp.reject_reason = "Low adoption rate, auto archived"
            self._store.update(exp)

        return True
