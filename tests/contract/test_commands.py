from dataclasses import fields
from src.application.commands import (
    CreateExperienceCommand,
    SearchExperienceCommand,
    RecordFeedbackCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
)


def test_create_experience_command_required_fields():
    cmd = CreateExperienceCommand(task_output="test")
    assert cmd.task_output == "test"
    assert cmd.project_id is None
    assert cmd.session_id is None


def test_search_experience_command_defaults():
    cmd = SearchExperienceCommand(query="test")
    assert cmd.limit == 10
    assert cmd.tech_stack == []


def test_record_feedback_command_fields():
    cmd = RecordFeedbackCommand(experience_id="exp-001", helpful=True)
    assert cmd.experience_id == "exp-001"
    assert cmd.helpful is True
    assert cmd.session_id is None


def test_activate_command_has_experience_id():
    cmd = ActivateExperienceCommand(experience_id="exp-001")
    assert cmd.experience_id == "exp-001"


def test_archive_command_has_reason():
    cmd = ArchiveExperienceCommand(experience_id="exp-001", reason="outdated")
    assert cmd.reason == "outdated"


from src.application.commands import SearchV2Command, SaveCommand, FeedbackV2Command


class TestSearchV2Command:
    def test_search_v2_command_has_task_description(self):
        cmd = SearchV2Command(
            task_description="修复 NPE",
            project_id="github.com/org/repo",
            project_manifest='{"dependencies": {"react": "^18"}}',
        )
        assert cmd.task_description == "修复 NPE"
        assert cmd.project_id == "github.com/org/repo"

    def test_search_v2_command_session_id_defaults_to_none(self):
        cmd = SearchV2Command(
            task_description="test",
            project_id="github.com/org/repo",
            project_manifest="",
        )
        assert cmd.session_id is None


class TestSaveCommand:
    def test_save_command_required_fields(self):
        cmd = SaveCommand(
            task_description="修复 NPE",
            solution="在 Service 层增加 null 检查",
            key_decisions="在 Service 而不是 DAO 层做检查",
            tags=["java", "null-safety"],
            project_id="github.com/org/repo",
            outcome="success",
        )
        assert cmd.outcome == "success"
        assert cmd.search_event_id is None

    def test_save_command_search_event_id_optional(self):
        cmd = SaveCommand(
            task_description="test",
            solution="sol",
            key_decisions="kd",
            tags=[],
            project_id="proj",
            outcome="success",
            search_event_id="evt-001",
        )
        assert cmd.search_event_id == "evt-001"


class TestFeedbackV2Command:
    def test_feedback_v2_command_required_fields(self):
        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-002"],
        )
        assert cmd.search_event_id == "evt-001"

    def test_feedback_v2_command_comment_defaults_to_none(self):
        cmd = FeedbackV2Command(search_event_id="evt-001")
        assert cmd.comment is None
        assert cmd.helpful_ids == []
        assert cmd.unhelpful_ids == []
