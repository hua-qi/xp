import numpy as np
from src.domain.experience import check_duplicate
from src.domain.constants import DUPLICATE_SIMILARITY_THRESHOLD


def _make_vec(val: float, dim: int = 4) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[0] = val
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def test_no_duplicate_when_vectors_empty():
    is_dup, _, _ = check_duplicate(
        query_vec=_make_vec(1.0),
        all_vecs=np.array([], dtype=np.float32),
        all_ids=[],
    )
    assert is_dup is False


def test_high_similarity_detected_as_duplicate():
    vec = _make_vec(1.0)
    is_dup, exp_id, sim = check_duplicate(
        query_vec=vec,
        all_vecs=np.array([vec]),
        all_ids=["exp-001"],
    )
    assert is_dup is True
    assert exp_id == "exp-001"
    assert sim >= DUPLICATE_SIMILARITY_THRESHOLD


def test_low_similarity_not_duplicate():
    query = _make_vec(1.0, dim=4)
    other = np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
    other = other / np.linalg.norm(other)
    is_dup, _, sim = check_duplicate(
        query_vec=query,
        all_vecs=other,
        all_ids=["exp-002"],
    )
    assert is_dup is False
    assert sim < DUPLICATE_SIMILARITY_THRESHOLD
