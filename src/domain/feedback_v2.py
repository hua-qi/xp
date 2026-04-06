from __future__ import annotations


def compute_confidence_after_helpful(current: float) -> float:
    return round(min(current + 0.1, 1.0), 3)


def compute_confidence_after_unhelpful(current: float) -> float:
    return round(max(current - 0.05, 0.0), 3)


def should_archive(confidence: float) -> bool:
    return confidence < 0.2


def validate_feedback_ids(
    helpful_ids: list[str],
    unhelpful_ids: list[str],
    result_ids: list[str],
) -> list[str]:
    errors = []
    result_set = set(result_ids)
    helpful_set = set(helpful_ids)
    unhelpful_set = set(unhelpful_ids)

    overlap = helpful_set & unhelpful_set
    for exp_id in overlap:
        errors.append(f"{exp_id} 同时出现在 helpful_ids 和 unhelpful_ids 中（both）")

    for exp_id in helpful_ids:
        if exp_id not in result_set:
            errors.append(f"{exp_id} 不在 search_event 的 result_ids 中")

    for exp_id in unhelpful_ids:
        if exp_id not in result_set:
            errors.append(f"{exp_id} 不在 search_event 的 result_ids 中")

    return errors
