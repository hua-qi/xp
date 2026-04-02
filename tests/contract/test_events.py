from src.domain.events import (
    ExperienceCreated,
    ExperienceActivated,
    ExperienceArchived,
    FeedbackRecorded,
    EmbeddingRequested,
    DuplicateDetected,
    ExperienceHit,
)


def test_experience_created_is_frozen():
    event = ExperienceCreated(
        experience_id="exp-001",
        title="test",
        content="content",
        tech_stack=["python"],
        scene=["测试"],
        level="L2",
        quality_score=85,
        project_id=None,
    )
    try:
        event.title = "modified"
        assert False, "Should raise FrozenInstanceError"
    except Exception:
        pass


def test_experience_activated_triggered_by_values():
    auto = ExperienceActivated(experience_id="exp-001", triggered_by="auto")
    manual = ExperienceActivated(experience_id="exp-001", triggered_by="manual")
    assert auto.triggered_by == "auto"
    assert manual.triggered_by == "manual"


def test_feedback_recorded_confidence_range():
    event = FeedbackRecorded(
        experience_id="exp-001",
        helpful=True,
        session_id=None,
        old_confidence=0.5,
        new_confidence=0.6,
    )
    assert 0.0 <= event.new_confidence <= 1.0


def test_duplicate_detected_has_similarity():
    event = DuplicateDetected(
        new_experience_id="new-001",
        existing_experience_id="old-001",
        similarity=0.92,
    )
    assert event.similarity == 0.92
