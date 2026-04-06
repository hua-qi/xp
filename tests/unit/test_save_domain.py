from src.domain.save_domain import initial_confidence_for_outcome


class TestInitialConfidence:
    def test_success_gives_0_65(self):
        assert initial_confidence_for_outcome("success") == 0.65

    def test_partial_gives_0_55(self):
        assert initial_confidence_for_outcome("partial") == 0.55

    def test_failed_gives_0_40(self):
        assert initial_confidence_for_outcome("failed") == 0.40

    def test_unknown_outcome_gives_0_55_as_default(self):
        assert initial_confidence_for_outcome("unknown") == 0.55
