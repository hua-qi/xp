from __future__ import annotations
import numpy as np
from .constants import DUPLICATE_SIMILARITY_THRESHOLD


def cosine_similarity_1d(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    normalized = matrix / norms
    q_norm = np.linalg.norm(query)
    q_unit = query / q_norm if q_norm > 0 else query
    return normalized @ q_unit


def check_duplicate(
    query_vec: np.ndarray,
    all_vecs: np.ndarray,
    all_ids: list[str],
) -> tuple[bool, str, float]:
    if len(all_ids) == 0 or all_vecs.size == 0:
        return False, "", 0.0
    scores = cosine_similarity_1d(query_vec, all_vecs)
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    if best_score >= DUPLICATE_SIMILARITY_THRESHOLD:
        return True, all_ids[best_idx], best_score
    return False, "", best_score
