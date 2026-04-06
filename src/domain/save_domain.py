from __future__ import annotations

_OUTCOME_CONFIDENCE = {
    "success": 0.65,
    "partial": 0.55,
    "failed": 0.40,
}


def initial_confidence_for_outcome(outcome: str) -> float:
    return _OUTCOME_CONFIDENCE.get(outcome, 0.55)
