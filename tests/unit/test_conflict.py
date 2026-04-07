import numpy as np
from src.domain.conflict import (
    detect_duplicate_or_conflict,
    ConflictResult,
)


def vec(values):
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_no_conflict_when_similarity_low():
    new_p = vec([1.0, 0.0, 0.0])
    new_s = vec([1.0, 0.0, 0.0])
    existing = [
        ("exp-1", vec([0.0, 1.0, 0.0]), vec([0.0, 1.0, 0.0])),
    ]
    result = detect_duplicate_or_conflict(new_p, new_s, existing)
    assert result is None


def test_duplicate_detected_when_both_high():
    new_p = vec([1.0, 0.0, 0.0])
    new_s = vec([0.0, 1.0, 0.0])
    existing = [
        ("exp-1", vec([0.99, 0.1, 0.0]), vec([0.0, 0.99, 0.1])),
    ]
    result = detect_duplicate_or_conflict(new_p, new_s, existing)
    assert result is not None
    assert result.type == "duplicate"
    assert result.existing_id == "exp-1"


def test_conflict_detected_when_problem_high_solution_low():
    new_p = vec([1.0, 0.0, 0.0])
    new_s = vec([0.0, 0.0, 1.0])
    existing = [
        ("exp-1", vec([0.99, 0.1, 0.0]), vec([1.0, 0.0, 0.0])),
    ]
    result = detect_duplicate_or_conflict(new_p, new_s, existing)
    assert result is not None
    assert result.type == "conflict"
