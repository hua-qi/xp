class TestComputeHealthStatus:
    def test_all_healthy(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.7,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=5,
            feedback_coverage=0.5,
        )
        assert result["overall"] == "healthy"
        assert all(v["ok"] for v in result["indicators"].values())

    def test_low_adoption_rate_is_unhealthy(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.4,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=5,
            feedback_coverage=0.5,
        )
        assert result["indicators"]["adoption_rate"]["ok"] is False
        assert result["overall"] != "healthy"

    def test_high_pending_count_is_unhealthy(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.7,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=25,
            feedback_coverage=0.5,
        )
        assert result["indicators"]["pending_count"]["ok"] is False

    def test_returns_indicators_dict_with_all_keys(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.7,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=5,
            feedback_coverage=0.5,
        )
        expected_keys = {
            "adoption_rate", "miss_rate", "zero_result_rate",
            "zombie_rate", "pending_count", "feedback_coverage"
        }
        assert set(result["indicators"].keys()) == expected_keys
