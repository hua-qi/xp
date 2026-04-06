import pytest
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.handlers.experience_handler import ExperienceHandler
from src.application.commands import CreateExperienceCommand, ActivateExperienceCommand, ArchiveExperienceCommand
from src.domain.events import ExperienceCreated, ExperienceActivated, ExperienceArchived
from src.domain.constants import QUALITY_SCORE_AUTO_ACTIVATE
from src.models import ExperienceStatus


class FakeLLM:
    def generate_title(self, text: str) -> str:
        return "测试标题"


class FakeMetadata:
    def infer(self, text: str) -> dict:
        return {"tech_stack": ["python"], "scene": ["测试"], "level": "L2"}


def _make_handler(uow):
    return ExperienceHandler(
        uow_factory=lambda: uow,
        llm=FakeLLM(),
        metadata_inferrer=FakeMetadata(),
    )


@pytest.mark.asyncio
async def test_create_high_quality_experience_auto_activates():
    uow = InMemoryUnitOfWork()
    handler = _make_handler(uow)
    cmd = CreateExperienceCommand(
        task_output="问题描述\n" + "这是详细的解决方案描述" * 6 + "\n" + "关键技术决策详细说明" * 6,
    )
    exp = await handler.handle_create(cmd)

    assert exp is not None
    assert exp.status == "ACTIVE"

    events = uow.get_events()
    created_events = [e for e in events if isinstance(e, ExperienceCreated)]
    activated_events = [e for e in events if isinstance(e, ExperienceActivated)]
    assert len(created_events) == 1
    assert len(activated_events) == 1
    assert activated_events[0].triggered_by == "auto"


@pytest.mark.asyncio
async def test_create_low_quality_experience_stays_pending():
    uow = InMemoryUnitOfWork()
    handler = _make_handler(uow)
    cmd = CreateExperienceCommand(
        task_output="问题描述\n解决方案很简短\n" + "关键决策详细说明" * 3,
    )
    exp = await handler.handle_create(cmd)

    assert exp is not None
    assert exp.status == "PENDING"

    events = uow.get_events()
    activated_events = [e for e in events if isinstance(e, ExperienceActivated)]
    assert len(activated_events) == 0


@pytest.mark.asyncio
async def test_activate_experience_manually():
    uow = InMemoryUnitOfWork()

    class FakeExp:
        id = "exp-100"
        status = "PENDING"
        confidence = 0.5
        reject_reason = None

    uow.experiences._committed["exp-100"] = FakeExp()
    handler = _make_handler(uow)
    await handler.handle_activate(ActivateExperienceCommand(experience_id="exp-100"))

    exp = uow.experiences.get("exp-100")
    assert exp.status == ExperienceStatus.ACTIVE

    events = uow.get_events()
    activated_events = [e for e in events if isinstance(e, ExperienceActivated)]
    assert len(activated_events) == 1
    assert activated_events[0].triggered_by == "manual"


@pytest.mark.asyncio
async def test_archive_experience():
    uow = InMemoryUnitOfWork()

    class FakeExp:
        id = "exp-200"
        status = "ACTIVE"
        confidence = 0.5
        reject_reason = None

    uow.experiences._committed["exp-200"] = FakeExp()
    handler = _make_handler(uow)
    await handler.handle_archive(ArchiveExperienceCommand(experience_id="exp-200", reason="手动归档"))

    exp = uow.experiences.get("exp-200")
    assert exp.status == ExperienceStatus.ARCHIVED

    events = uow.get_events()
    archived_events = [e for e in events if isinstance(e, ExperienceArchived)]
    assert len(archived_events) == 1
    assert archived_events[0].reason == "手动归档"
