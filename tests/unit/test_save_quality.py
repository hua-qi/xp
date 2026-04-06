from src.domain.quality import compute_save_quality_score


class TestComputeSaveQualityScore:
    def test_zero_score_for_empty_fields(self):
        score = compute_save_quality_score(
            solution="短",
            key_decisions="短",
            tags=[],
            outcome="failed",
        )
        assert score == 10

    def test_solution_over_50_chars_adds_30(self):
        solution = "x" * 51
        score = compute_save_quality_score(
            solution=solution, key_decisions="", tags=[], outcome="failed"
        )
        assert score == 40

    def test_key_decisions_over_30_chars_adds_30(self):
        kd = "x" * 31
        score = compute_save_quality_score(
            solution="", key_decisions=kd, tags=[], outcome="failed"
        )
        assert score == 40

    def test_two_or_more_tags_adds_20(self):
        score = compute_save_quality_score(
            solution="", key_decisions="", tags=["python", "fastapi"], outcome="failed"
        )
        assert score == 30

    def test_outcome_success_adds_20(self):
        score = compute_save_quality_score(
            solution="", key_decisions="", tags=[], outcome="success"
        )
        assert score == 20

    def test_outcome_partial_adds_10(self):
        score = compute_save_quality_score(
            solution="", key_decisions="", tags=[], outcome="partial"
        )
        assert score == 10

    def test_full_score_100_for_all_conditions_met(self):
        score = compute_save_quality_score(
            solution="x" * 51,
            key_decisions="x" * 31,
            tags=["python", "fastapi"],
            outcome="success",
        )
        assert score == 100

    def test_score_80_auto_activates(self):
        score = compute_save_quality_score(
            solution="x" * 51,
            key_decisions="x" * 31,
            tags=["python", "fastapi"],
            outcome="partial",
        )
        assert score == 90
        assert score >= 80
