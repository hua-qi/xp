import uuid
from datetime import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)


def _make_pending_exp(title="测试标题", key_decisions="重要坑：不要直接修改 state"):
    return Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title=title,
        tags=[],
        problem="测试问题",
        solution="测试解决方案",
        key_decisions=key_decisions,
        confidence=0.6,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(),
    )


async def test_review_reject_requires_reason(monkeypatch, capsys):
    exp = _make_pending_exp()
    uow = InMemoryUnitOfWork()
    uow.experiences._committed[exp.id] = exp

    inputs = iter(["n", "", "测试拒绝原因", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    async def _mock_uow():
        return uow

    with patch("src.cli._get_uow", _mock_uow):
        from src.cli import cmd_review
        await cmd_review([])

    captured = capsys.readouterr()
    assert "拒绝原因不能为空" in captured.out


async def test_review_batch_confirm(monkeypatch, capsys):
    uow = InMemoryUnitOfWork()
    exp_ids = []
    for i in range(3):
        exp = _make_pending_exp(title=f"测试标题{i}")
        uow.experiences._committed[exp.id] = exp
        exp_ids.append(exp.id)

    inputs = iter(["b"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    async def _mock_uow():
        return uow

    with patch("src.cli._get_uow", _mock_uow):
        from src.cli import cmd_review
        await cmd_review([])

    for eid in exp_ids:
        loaded = uow.experiences._committed.get(eid) or uow.experiences._pending.get(eid)
        assert loaded.status == ExperienceStatus.ACTIVE
        assert loaded.confidence == 0.65


async def test_review_admin_only_blocked(monkeypatch, capsys):
    monkeypatch.setenv("XP_ADMIN_KEY", "secret123")
    monkeypatch.setenv("XP_USER_KEY", "wrongkey")
    with pytest.raises(SystemExit):
        from src.cli import cmd_review
        await cmd_review([])


async def test_review_admin_only_allowed(monkeypatch, capsys):
    monkeypatch.setenv("XP_ADMIN_KEY", "secret123")
    monkeypatch.setenv("XP_USER_KEY", "secret123")

    uow = InMemoryUnitOfWork()

    monkeypatch.setattr("builtins.input", lambda _: "q")

    async def _mock_uow():
        return uow

    with patch("src.cli._get_uow", _mock_uow):
        from src.cli import cmd_review
        await cmd_review([])
