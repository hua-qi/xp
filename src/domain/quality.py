def compute_quality_score(
    key_decisions: str,
    solution_summary: str,
    related_files: list,
    tech_stack: list,
    duplicate_similarity: float = 0.0,
) -> int:
    score = 0

    kd_len = len(key_decisions.strip())
    if kd_len >= 50:
        score += 40
    elif kd_len >= 20:
        score += 20

    ss_len = len(solution_summary.strip())
    if ss_len >= 50:
        score += 20
    elif ss_len >= 20:
        score += 10

    if related_files:
        score += 15

    if tech_stack:
        score += 15

    if duplicate_similarity <= 0.6:
        score += 10

    return score
