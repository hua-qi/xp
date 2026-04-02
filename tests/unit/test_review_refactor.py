import uuid
from datetime import datetime
import pytest


@pytest.fixture
def store_with_pending(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    store = ExperienceStore()
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="测试标题",
        tags=[],
        problem="测试问题",
        solution="测试解决方案",
        key_decisions="重要坑：不要直接修改 state",
        confidence=0.6,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
    )
    store.add(exp)
    return store, exp


def test_review_reject_requires_reason(store_with_pending, monkeypatch, capsys):
    _, exp = store_with_pending
    inputs = iter(["n", "", "测试拒绝原因", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    from src.cli import cmd_review
    cmd_review([])
    captured = capsys.readouterr()
    assert "拒绝原因不能为空" in captured.out


def test_review_batch_confirm(tmp_path, monkeypatch, capsys):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    store = ExperienceStore()
    exp_ids = []
    for i in range(3):
        exp = Experience(
            id=str(uuid.uuid4()),
            type=ExperienceType.BUGFIX,
            level=ExperienceLevel.L2,
            title=f"测试标题{i}",
            tags=[],
            problem="测试问题",
            solution="测试解决方案",
            key_decisions="关键决策内容",
            confidence=0.6,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.AGENT,
            created_at=datetime.utcnow().isoformat(),
        )
        store.add(exp)
        exp_ids.append(exp.id)

    inputs = iter(["b"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    from src.cli import cmd_review
    cmd_review([])

    from src.models import ExperienceStatus
    for eid in exp_ids:
        loaded = store.get(eid)
        assert loaded.status == ExperienceStatus.ACTIVE
        assert loaded.confidence == 0.65


def test_review_admin_only_blocked(monkeypatch, capsys):
    monkeypatch.setenv("XP_ADMIN_KEY", "secret123")
    monkeypatch.setenv("XP_USER_KEY", "wrongkey")
    with pytest.raises(SystemExit):
        from src.cli import cmd_review
        cmd_review([])


def test_review_admin_only_allowed(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setenv("XP_ADMIN_KEY", "secret123")
    monkeypatch.setenv("XP_USER_KEY", "secret123")
    monkeypatch.setattr("builtins.input", lambda _: "q")
    from src.cli import cmd_review
    cmd_review([])
