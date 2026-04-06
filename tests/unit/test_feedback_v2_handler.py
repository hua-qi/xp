import pytest
from src.application.commands import FeedbackV2Command
from src.application.handlers.feedback_v2_handler import FeedbackV2Handler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType, SearchEvent,
)


def make_exp(exp_id, confidence=0.65):
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title="测试经验",
        tags=["python"],
        problem="问题",
        solution="解决方案超过五十字这里足够长",
        key_decisions="关键决策超过三十字这里",
        confidence=confidence,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at="2026-01-01T00:00:00",
        metadata=ExperienceMetadata(),
        scope_type=ScopeType.PROJECT,
        scope_id="proj-001",
    )


def make_search_event(event_id, result_ids):
    return SearchEvent(
        id=event_id,
        session_id="sess-001",
        project_id="proj-001",
        query_text="test",
        timestamp="2026-05-04T00:00:00",
        result_ids=result_ids,
    )


class FakeSearchEventStore:
    def __init__(self):
        self._events: dict = {}

    def save(self, event):
        self._events[event.id] = event

    def get(self, event_id: str):
        return self._events.get(event_id)


class TestFeedbackV2HandlerValidation:
    def _make_handler(self, uow=None, event_store=None):
        if uow is None:
            uow = InMemoryUnitOfWork()
        if event_store is None:
            event_store = FakeSearchEventStore()
        handler = FeedbackV2Handler(uow_factory=lambda: uow, search_event_store=event_store)
        return handler, uow, event_store

    @pytest.mark.asyncio
    async def test_invalid_helpful_id_returns_error(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001")

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            helpful_ids=["exp-999"],
        )
        result = await handler.handle(cmd)
        assert result["status"] == "error"
        assert "exp-999" in result["message"]

    @pytest.mark.asyncio
    async def test_valid_helpful_id_increases_confidence(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.65)

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            helpful_ids=["exp-001"],
        )
        result = await handler.handle(cmd)
        assert result["status"] == "ok"
        updated_exp = uow.experiences.get("exp-001")
        assert abs(updated_exp.confidence - 0.75) < 1e-4

    @pytest.mark.asyncio
    async def test_valid_unhelpful_id_decreases_confidence(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.65)

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            unhelpful_ids=["exp-001"],
        )
        result = await handler.handle(cmd)
        assert result["status"] == "ok"
        updated_exp = uow.experiences.get("exp-001")
        assert abs(updated_exp.confidence - 0.60) < 1e-4

    @pytest.mark.asyncio
    async def test_confidence_below_0_2_marks_for_archive(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.22)

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            unhelpful_ids=["exp-001"],
        )
        await handler.handle(cmd)
        updated_exp = uow.experiences.get("exp-001")
        assert updated_exp.status == ExperienceStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_search_event_not_found_returns_error(self):
        handler, uow, evt_store = self._make_handler()
        cmd = FeedbackV2Command(
            search_event_id="evt-not-exist",
            helpful_ids=["exp-001"],
        )
        result = await handler.handle(cmd)
        assert result["status"] == "error"
