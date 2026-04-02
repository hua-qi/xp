from __future__ import annotations
import hashlib
from .constants import AB_TEST_CONTROL_MODULO


def rank_results(candidates: list, scores: list[float], limit: int) -> list:
    paired = list(zip(candidates, scores))
    paired.sort(key=lambda x: x[1], reverse=True)
    paired = paired[:limit]
    for exp, score in paired:
        exp.similarity = round(float(score), 3)
    return [exp for exp, _ in paired]


def ab_assign(session_id: str) -> str:
    hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
    if hash_val % AB_TEST_CONTROL_MODULO == 0:
        return "control"
    return "treatment"
