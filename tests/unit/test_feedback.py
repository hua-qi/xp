from src.domain.feedback import compute_new_confidence
from src.domain.constants import (
    CONFIDENCE_HELPFUL_DELTA,
    CONFIDENCE_UNHELPFUL_DELTA,
    CONFIDENCE_MIN,
    CONFIDENCE_MAX,
)


def test_helpful_feedback_increases_confidence():
    result = compute_new_confidence(0.5, helpful=True)
    assert result == round(0.5 + CONFIDENCE_HELPFUL_DELTA, 3)


def test_unhelpful_feedback_decreases_confidence():
    result = compute_new_confidence(0.5, helpful=False)
    assert result == round(0.5 + CONFIDENCE_UNHELPFUL_DELTA, 3)


def test_confidence_never_exceeds_max():
    result = compute_new_confidence(0.95, helpful=True)
    assert result <= CONFIDENCE_MAX


def test_confidence_never_below_min():
    result = compute_new_confidence(0.02, helpful=False)
    assert result >= CONFIDENCE_MIN


def test_helpful_at_max_stays_at_max():
    result = compute_new_confidence(1.0, helpful=True)
    assert result == CONFIDENCE_MAX
