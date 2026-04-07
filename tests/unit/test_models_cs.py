from src.models import Experience, ExperienceStatus


def test_experience_has_ab_group_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "ab_group" in fields


def test_experience_has_conflict_with_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "conflict_with" in fields


def test_experience_has_retry_count_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "retry_count" in fields


def test_experience_has_raw_input_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "raw_input" in fields


def test_experience_status_has_needs_fix():
    values = {s.value for s in ExperienceStatus}
    assert "needs_fix" in values
