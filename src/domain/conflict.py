from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np

DUPLICATE_THRESHOLD = 0.85
CONFLICT_PROBLEM_THRESHOLD = 0.85
CONFLICT_SOLUTION_MAX = 0.6


@dataclass
class ConflictResult:
    type: str
    existing_id: str
    problem_similarity: float
    solution_similarity: float


def detect_duplicate_or_conflict(
    new_problem_vec: np.ndarray,
    new_solution_vec: np.ndarray,
    existing: list[tuple[str, np.ndarray, np.ndarray]],
) -> Optional[ConflictResult]:
    for exp_id, ep_vec, es_vec in existing:
        p_sim = float(np.dot(new_problem_vec, ep_vec))
        s_sim = float(np.dot(new_solution_vec, es_vec))
        if p_sim >= DUPLICATE_THRESHOLD and s_sim >= DUPLICATE_THRESHOLD:
            return ConflictResult(
                type="duplicate",
                existing_id=exp_id,
                problem_similarity=p_sim,
                solution_similarity=s_sim,
            )
        if p_sim >= CONFLICT_PROBLEM_THRESHOLD and s_sim < CONFLICT_SOLUTION_MAX:
            return ConflictResult(
                type="conflict",
                existing_id=exp_id,
                problem_similarity=p_sim,
                solution_similarity=s_sim,
            )
    return None
