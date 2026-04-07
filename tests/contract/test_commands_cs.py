import dataclasses
from src.application.commands import SaveCommand, SearchV2Command, FeedbackV2Command


def test_save_command_has_minimal_fields():
    fields = {f.name for f in dataclasses.fields(SaveCommand)}
    assert "task_description" in fields
    assert "outcome_description" in fields
    assert "outcome" in fields
    assert "project_id" in fields


def test_save_command_no_longer_requires_solution():
    cmd = SaveCommand(
        task_description="task",
        outcome_description="outcome",
        outcome="success",
        project_id="p-1",
    )
    assert cmd.task_description == "task"


def test_search_v2_command_fields():
    fields = {f.name for f in dataclasses.fields(SearchV2Command)}
    assert "task_description" in fields
    assert "project_id" in fields


def test_feedback_v2_command_has_adopted_rejected():
    fields = {f.name for f in dataclasses.fields(FeedbackV2Command)}
    assert "adopted_ids" in fields
    assert "rejected_ids" in fields
    assert "comment" in fields
