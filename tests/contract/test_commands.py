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
