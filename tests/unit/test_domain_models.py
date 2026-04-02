from src.domain.models import Experience
from src.domain.events import ExperienceActivated, ExperienceArchived


def _make_exp(status="PENDING") -> Experience:
    return Experience(
        id="exp-001",
        title="标题",
        problem="问题",
        solution="解决",
        key_decisions="决策",
        status=status,
        confidence=0.6,
        tech_stack=["python"],
        scene=["测试"],
        level="L2",
        exp_type="experience",
        source="agent",
        project_id=None,
        created_at="2026-01-01T00:00:00",
    )


def test_activate_sets_status_active():
    exp = _make_exp("PENDING")
    events = exp.activate("manual")
    assert exp.status == "ACTIVE"
    assert len(events) == 1
    assert isinstance(events[0], ExperienceActivated)
    assert events[0].triggered_by == "manual"


def test_activate_auto_triggered_by():
    exp = _make_exp("PENDING")
    events = exp.activate("auto")
    assert events[0].triggered_by == "auto"


def test_archive_sets_status_and_reason():
    exp = _make_exp("ACTIVE")
    events = exp.archive("outdated")
    assert exp.status == "ARCHIVED"
    assert exp.reject_reason == "outdated"
    assert len(events) == 1
    assert isinstance(events[0], ExperienceArchived)
    assert events[0].reason == "outdated"
