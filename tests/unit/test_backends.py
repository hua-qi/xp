import os
import pytest


def test_storage_backend_is_abstract():
    from src.infrastructure.backends.base import StorageBackend
    import inspect
    assert inspect.isabstract(StorageBackend)


def test_local_backend_implements_interface(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import LocalBackend
    backend = LocalBackend()
    assert hasattr(backend, "add_experience")
    assert hasattr(backend, "get_experience")
    assert hasattr(backend, "list_by_status")
    assert hasattr(backend, "save_vector")


POSTGRES_DSN = os.environ.get("TEST_POSTGRES_DSN", "")


@pytest.mark.skipif(not POSTGRES_DSN, reason="TEST_POSTGRES_DSN not set")
async def test_postgres_backend_add_and_get(tmp_path):
    from src.infrastructure.backends.postgres import PostgresBackend
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    import uuid
    from datetime import datetime

    backend = PostgresBackend(POSTGRES_DSN)
    await backend.connect()

    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="PostgreSQL 测试经验",
        tags=["python"],
        problem="测试问题",
        solution="测试解决方案",
        key_decisions="测试关键决策",
        confidence=0.8,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
    )

    await backend.async_add_experience(exp)
    loaded = await backend.async_get_experience(exp.id)

    assert loaded is not None
    assert loaded.title == exp.title
    assert loaded.key_decisions == exp.key_decisions

    await backend.async_delete_experience(exp.id)
    await backend.close()


def test_get_backend_defaults_to_local(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.delenv("XP_BACKEND", raising=False)
    monkeypatch.delenv("XP_POSTGRES_DSN", raising=False)
    from src.storage import get_backend, LocalBackend
    backend = get_backend()
    assert isinstance(backend, LocalBackend)


def test_get_backend_postgres_requires_dsn(monkeypatch):
    monkeypatch.setenv("XP_BACKEND", "postgres")
    monkeypatch.delenv("XP_POSTGRES_DSN", raising=False)
    from src.storage import get_backend
    with pytest.raises(RuntimeError, match="XP_POSTGRES_DSN"):
        get_backend()
