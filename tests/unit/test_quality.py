from src.domain.quality import compute_quality_score


class TestComputeQualityScore:
    def test_max_score(self):
        assert compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.0,
        ) == 100

    def test_zero_score(self):
        assert compute_quality_score(
            key_decisions="",
            solution_summary="",
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        ) == 10

    def test_mid_key_decisions(self):
        score = compute_quality_score(
            key_decisions="a" * 20,
            solution_summary="b" * 50,
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        )
        assert score == 50

    def test_high_duplicate_loses_dedup_bonus(self):
        score = compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.9,
        )
        assert score == 90
