from src.models import SearchEvent, FeedbackEvent


class TestSearchEvent:
    def test_search_event_has_required_fields(self):
        evt = SearchEvent(
            id="evt-001",
            session_id="sess-001",
            project_id="github.com/org/repo",
            query_text="修复 NPE 问题",
            result_ids=["exp-001", "exp-002"],
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.id == "evt-001"
        assert evt.result_ids == ["exp-001", "exp-002"]

    def test_search_event_result_ids_defaults_to_empty(self):
        evt = SearchEvent(
            id="evt-002",
            session_id="sess-001",
            project_id="github.com/org/repo",
            query_text="test",
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.result_ids == []


class TestFeedbackEvent:
    def test_feedback_event_has_required_fields(self):
        evt = FeedbackEvent(
            id="fb-001",
            search_event_id="evt-001",
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-002"],
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.search_event_id == "evt-001"
        assert evt.helpful_ids == ["exp-001"]

    def test_feedback_event_comment_defaults_to_none(self):
        evt = FeedbackEvent(
            id="fb-002",
            search_event_id="evt-001",
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.comment is None
        assert evt.helpful_ids == []
        assert evt.unhelpful_ids == []
