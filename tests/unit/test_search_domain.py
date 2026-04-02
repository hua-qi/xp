from src.domain.search_domain import rank_results, ab_assign


def _make_candidate(exp_id: str):
    class FakeExp:
        id = exp_id
        similarity = 0.0
    return FakeExp()


def test_rank_results_sorted_by_score():
    c1 = _make_candidate("a")
    c2 = _make_candidate("b")
    c3 = _make_candidate("c")
    candidates = [c1, c2, c3]
    scores = [0.7, 0.9, 0.5]
    result = rank_results(candidates, scores, limit=3)
    assert [r.id for r in result] == ["b", "a", "c"]


def test_rank_results_respects_limit():
    candidates = [_make_candidate(str(i)) for i in range(5)]
    scores = [float(i) / 10 for i in range(5)]
    result = rank_results(candidates, scores, limit=2)
    assert len(result) == 2


def test_rank_results_similarity_set_on_exp():
    c = _make_candidate("x")
    result = rank_results([c], [0.88], limit=5)
    assert result[0].similarity == round(0.88, 3)


def test_ab_assign_returns_treatment_for_most_sessions():
    groups = {ab_assign(f"session-{i}") for i in range(20)}
    assert "treatment" in groups


def test_ab_assign_same_session_always_same_group():
    g1 = ab_assign("fixed-session-abc")
    g2 = ab_assign("fixed-session-abc")
    assert g1 == g2


def test_rank_results_empty_input():
    result = rank_results([], [], limit=10)
    assert result == []
