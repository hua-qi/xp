from __future__ import annotations
from dataclasses import dataclass

_SCOPE_WEIGHTS = {
    "project": 1.2,
    "business": 1.0,
    "team": 0.9,
}


@dataclass
class ScopeWeightedResult:
    exp_id: str
    score: float
    scope_type: str


def apply_scope_weight(score: float, scope_type: str) -> float:
    weight = _SCOPE_WEIGHTS.get(scope_type, 1.0)
    return score * weight


def apply_tech_stack_boost(
    score: float,
    exp_tags: list[str],
    query_languages: list[str],
    query_dependencies: list[str],
) -> float:
    query_tokens = set(t.lower() for t in query_languages + query_dependencies)
    exp_tokens = set(t.lower() for t in exp_tags)
    if query_tokens & exp_tokens:
        return score * 1.15
    return score


def merge_and_deduplicate(
    results: list[ScopeWeightedResult],
    top_k: int,
    threshold: float = 0.0,
) -> list[ScopeWeightedResult]:
    best: dict[str, ScopeWeightedResult] = {}
    for r in results:
        if r.score < threshold:
            continue
        existing = best.get(r.exp_id)
        if existing is None or r.score > existing.score:
            best[r.exp_id] = r
    sorted_results = sorted(best.values(), key=lambda x: x.score, reverse=True)
    return sorted_results[:top_k]


def resolve_scope_ids(
    project_id: str,
    project_to_businesses: dict[str, list[str]],
    business_to_teams: dict[str, list[str]],
) -> dict[str, list[str]]:
    business_ids = project_to_businesses.get(project_id, [])
    team_ids: list[str] = []
    for biz_id in business_ids:
        for team_id in business_to_teams.get(biz_id, []):
            if team_id not in team_ids:
                team_ids.append(team_id)
    return {
        "project": [project_id],
        "business": business_ids,
        "team": team_ids,
    }
