from src.domain.search_v2 import (
    apply_scope_weight,
    apply_tech_stack_boost,
    merge_and_deduplicate,
    ScopeWeightedResult,
)


class TestApplyScopeWeight:
    def test_project_scope_multiplied_by_1_2(self):
        result = apply_scope_weight(score=0.8, scope_type="project")
        assert abs(result - 0.8 * 1.2) < 1e-6

    def test_business_scope_multiplied_by_1_0(self):
        result = apply_scope_weight(score=0.8, scope_type="business")
        assert abs(result - 0.8 * 1.0) < 1e-6

    def test_team_scope_multiplied_by_0_9(self):
        result = apply_scope_weight(score=0.8, scope_type="team")
        assert abs(result - 0.8 * 0.9) < 1e-6

    def test_unknown_scope_returns_original_score(self):
        result = apply_scope_weight(score=0.8, scope_type="unknown")
        assert abs(result - 0.8) < 1e-6


class TestApplyTechStackBoost:
    def test_matching_tag_boosts_score_by_1_15(self):
        score = apply_tech_stack_boost(
            score=0.8,
            exp_tags=["python", "fastapi"],
            query_languages=["python"],
            query_dependencies=["fastapi"],
        )
        assert abs(score - 0.8 * 1.15) < 1e-6

    def test_no_matching_tag_returns_original_score(self):
        score = apply_tech_stack_boost(
            score=0.8,
            exp_tags=["java"],
            query_languages=["python"],
            query_dependencies=["fastapi"],
        )
        assert abs(score - 0.8) < 1e-6

    def test_empty_exp_tags_returns_original_score(self):
        score = apply_tech_stack_boost(
            score=0.8,
            exp_tags=[],
            query_languages=["python"],
            query_dependencies=["fastapi"],
        )
        assert abs(score - 0.8) < 1e-6


class TestMergeAndDeduplicate:
    def _make_result(self, exp_id, score, scope_type="project"):
        return ScopeWeightedResult(exp_id=exp_id, score=score, scope_type=scope_type)

    def test_results_sorted_by_score_descending(self):
        results = [
            self._make_result("exp-001", 0.6, "project"),
            self._make_result("exp-002", 0.9, "business"),
            self._make_result("exp-003", 0.7, "team"),
        ]
        merged = merge_and_deduplicate(results, top_k=3)
        scores = [r.score for r in merged]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_limits_results(self):
        results = [self._make_result(f"exp-{i}", float(i) / 10, "project") for i in range(10)]
        merged = merge_and_deduplicate(results, top_k=5)
        assert len(merged) == 5

    def test_duplicate_exp_id_keeps_highest_score(self):
        results = [
            self._make_result("exp-001", 0.6, "project"),
            self._make_result("exp-001", 0.9, "business"),
        ]
        merged = merge_and_deduplicate(results, top_k=5)
        assert len(merged) == 1
        assert merged[0].score == 0.9

    def test_empty_results_returns_empty(self):
        assert merge_and_deduplicate([], top_k=5) == []

    def test_results_below_threshold_excluded(self):
        results = [
            self._make_result("exp-001", 0.8, "project"),
            self._make_result("exp-002", 0.3, "project"),
        ]
        merged = merge_and_deduplicate(results, top_k=5, threshold=0.5)
        assert len(merged) == 1
        assert merged[0].exp_id == "exp-001"


class TestResolveScopeIds:
    def test_project_id_always_included_in_project_scope(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001"]},
            business_to_teams={"biz-001": ["team-001"]},
        )
        assert "proj-001" in result["project"]

    def test_returns_associated_business_ids(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001", "biz-002"]},
            business_to_teams={},
        )
        assert "biz-001" in result["business"]
        assert "biz-002" in result["business"]

    def test_returns_associated_team_ids(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001"]},
            business_to_teams={"biz-001": ["team-001"]},
        )
        assert "team-001" in result["team"]

    def test_no_business_association_returns_empty_business(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={},
            business_to_teams={},
        )
        assert result["business"] == []
        assert result["team"] == []

    def test_multi_business_multi_team_deduplicates(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001", "biz-002"]},
            business_to_teams={
                "biz-001": ["team-001"],
                "biz-002": ["team-001"],
            },
        )
        assert result["team"].count("team-001") == 1
