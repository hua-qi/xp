from __future__ import annotations

_THRESHOLDS = {
    "adoption_rate": {"min": 0.6, "higher_is_better": True},
    "miss_rate": {"max": 0.2, "higher_is_better": False},
    "zero_result_rate": {"max": 0.1, "higher_is_better": False},
    "zombie_rate": {"max": 0.15, "higher_is_better": False},
    "pending_count": {"max": 20, "higher_is_better": False},
    "feedback_coverage": {"min": 0.4, "higher_is_better": True},
}


def compute_health_status(
    adoption_rate: float,
    miss_rate: float,
    zero_result_rate: float,
    zombie_rate: float,
    pending_count: int,
    feedback_coverage: float,
) -> dict:
    values = {
        "adoption_rate": adoption_rate,
        "miss_rate": miss_rate,
        "zero_result_rate": zero_result_rate,
        "zombie_rate": zombie_rate,
        "pending_count": pending_count,
        "feedback_coverage": feedback_coverage,
    }

    indicators = {}
    for key, value in values.items():
        threshold = _THRESHOLDS[key]
        if threshold["higher_is_better"]:
            ok = value >= threshold["min"]
        else:
            ok = value <= threshold["max"]
        indicators[key] = {"value": value, "ok": ok}

    all_ok = all(v["ok"] for v in indicators.values())
    overall = "healthy" if all_ok else "needs_attention"

    return {"overall": overall, "indicators": indicators}
