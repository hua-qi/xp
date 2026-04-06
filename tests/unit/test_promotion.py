import pytest
from src.domain.promotion import (
    compute_promotion_score,
    is_promotion_candidate,
)


class TestComputePromotionScore:
    def test_all_zeros_gives_zero(self):
        score = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=0)
        assert score == 0.0

    def test_formula_cross_project_weight_is_0_5(self):
        score = compute_promotion_score(cross_project_count=2, adoption_rate=0.0, recall_count=0)
        assert abs(score - 2 * 0.5) < 1e-6

    def test_formula_adoption_rate_weight_is_0_3(self):
        score = compute_promotion_score(cross_project_count=0, adoption_rate=1.0, recall_count=0)
        assert abs(score - 0.3) < 1e-6

    def test_formula_recall_count_capped_at_1(self):
        score_10 = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=10)
        score_100 = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=100)
        assert abs(score_10 - score_100) < 1e-6

    def test_formula_recall_count_weight_is_0_2(self):
        score = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=10)
        assert abs(score - 0.2) < 1e-6

    def test_combined_score(self):
        score = compute_promotion_score(
            cross_project_count=2,
            adoption_rate=0.8,
            recall_count=10,
        )
        expected = 2 * 0.5 + 0.8 * 0.3 + 1.0 * 0.2
        assert abs(score - expected) < 1e-6


class TestIsPromotionCandidate:
    def _make_input(self, **kwargs):
        defaults = dict(
            score=0.8,
            cross_project_count=2,
            adoption_rate=0.7,
            recall_count=6,
            age_days=31,
        )
        defaults.update(kwargs)
        return defaults

    def test_all_conditions_met_returns_true(self):
        assert is_promotion_candidate(**self._make_input()) is True

    def test_score_below_0_7_returns_false(self):
        assert is_promotion_candidate(**self._make_input(score=0.69)) is False

    def test_cross_project_count_below_2_returns_false(self):
        assert is_promotion_candidate(**self._make_input(cross_project_count=1)) is False

    def test_adoption_rate_below_0_6_returns_false(self):
        assert is_promotion_candidate(**self._make_input(adoption_rate=0.59)) is False

    def test_recall_count_below_5_returns_false(self):
        assert is_promotion_candidate(**self._make_input(recall_count=4)) is False

    def test_age_days_below_30_returns_false(self):
        assert is_promotion_candidate(**self._make_input(age_days=29)) is False


class TestDeterminePromotionTarget:
    def test_score_above_threshold_and_two_projects_targets_business(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.8,
            cross_project_count=2,
            cross_business_count=0,
        )
        assert result == "business"

    def test_two_or_more_businesses_targets_team(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.8,
            cross_project_count=3,
            cross_business_count=2,
        )
        assert result == "team"

    def test_low_score_returns_none(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.5,
            cross_project_count=2,
            cross_business_count=0,
        )
        assert result is None

    def test_only_one_project_returns_none(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.9,
            cross_project_count=1,
            cross_business_count=0,
        )
        assert result is None
