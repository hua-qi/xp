from __future__ import annotations


def compute_promotion_score(
    cross_project_count: int,
    adoption_rate: float,
    recall_count: int,
) -> float:
    recall_component = min(recall_count / 10, 1.0)
    return cross_project_count * 0.5 + adoption_rate * 0.3 + recall_component * 0.2


def is_promotion_candidate(
    score: float,
    cross_project_count: int,
    adoption_rate: float,
    recall_count: int,
    age_days: int,
) -> bool:
    if score <= 0.7:
        return False
    if cross_project_count < 2:
        return False
    if adoption_rate <= 0.6:
        return False
    if recall_count <= 5:
        return False
    if age_days <= 30:
        return False
    return True


def determine_promotion_target(
    score: float,
    cross_project_count: int,
    cross_business_count: int,
) -> str | None:
    if score <= 0.7:
        return None
    if cross_project_count < 2:
        return None
    if cross_business_count >= 2:
        return "team"
    return "business"
