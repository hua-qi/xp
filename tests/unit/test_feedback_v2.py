import pytest
from src.domain.feedback_v2 import (
    compute_confidence_after_helpful,
    compute_confidence_after_unhelpful,
    validate_feedback_ids,
    should_archive,
)


class TestConfidenceUpdate:
    def test_helpful_increases_confidence_by_0_1(self):
        assert abs(compute_confidence_after_helpful(0.6) - 0.7) < 1e-6

    def test_helpful_caps_at_1_0(self):
        assert compute_confidence_after_helpful(0.95) == 1.0

    def test_unhelpful_decreases_confidence_by_0_05(self):
        assert abs(compute_confidence_after_unhelpful(0.6) - 0.55) < 1e-6

    def test_unhelpful_floors_at_0_0(self):
        assert compute_confidence_after_unhelpful(0.02) == 0.0


class TestShouldArchive:
    def test_confidence_below_0_2_should_archive(self):
        assert should_archive(0.19) is True

    def test_confidence_exactly_0_2_should_not_archive(self):
        assert should_archive(0.2) is False

    def test_confidence_above_0_2_should_not_archive(self):
        assert should_archive(0.5) is False


class TestValidateFeedbackIds:
    def test_all_ids_in_result_ids_is_valid(self):
        errors = validate_feedback_ids(
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-002"],
            result_ids=["exp-001", "exp-002", "exp-003"],
        )
        assert errors == []

    def test_helpful_id_not_in_result_ids_returns_error(self):
        errors = validate_feedback_ids(
            helpful_ids=["exp-999"],
            unhelpful_ids=[],
            result_ids=["exp-001", "exp-002"],
        )
        assert len(errors) == 1
        assert "exp-999" in errors[0]

    def test_unhelpful_id_not_in_result_ids_returns_error(self):
        errors = validate_feedback_ids(
            helpful_ids=[],
            unhelpful_ids=["exp-888"],
            result_ids=["exp-001"],
        )
        assert len(errors) == 1
        assert "exp-888" in errors[0]

    def test_empty_ids_always_valid(self):
        errors = validate_feedback_ids(
            helpful_ids=[],
            unhelpful_ids=[],
            result_ids=["exp-001"],
        )
        assert errors == []

    def test_id_in_both_helpful_and_unhelpful_returns_error(self):
        errors = validate_feedback_ids(
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-001"],
            result_ids=["exp-001"],
        )
        assert any("exp-001" in e and ("both" in e.lower() or "同时" in e) for e in errors)
