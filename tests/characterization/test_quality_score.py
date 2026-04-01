import pytest


class TestQualityScore:
    def test_max_score(self, svc):
        score = svc._compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["src/foo.py"],
            tech_stack=["python"],
            duplicate_similarity=0.0,
        )
        assert score == 100

    def test_min_passing_score(self, svc):
        score = svc._compute_quality_score(
            key_decisions="a" * 20,
            solution_summary="b" * 20,
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        )
        assert score == 40

    def test_key_decisions_short_gives_zero(self, svc):
        score = svc._compute_quality_score(
            key_decisions="短",
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.0,
        )
        assert score == 60

    def test_high_duplicate_similarity_loses_points(self, svc):
        score = svc._compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.9,
        )
        assert score == 90

    def test_empty_everything_zero(self, svc):
        score = svc._compute_quality_score(
            key_decisions="",
            solution_summary="",
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        )
        assert score == 10
