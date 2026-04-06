import os
import pytest


def test_storage_backend_is_abstract():
    from src.infrastructure.backends.base import StorageBackend
    import inspect
    assert inspect.isabstract(StorageBackend)


POSTGRES_DSN = os.environ.get("TEST_POSTGRES_DSN", "")


@pytest.mark.skipif(not POSTGRES_DSN, reason="TEST_POSTGRES_DSN not set")
async def test_postgres_backend_add_and_get():
    from src.infrastructure.backends.postgres import PostgresBackend
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
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
        metadata=ExperienceMetadata(),
    )

    await backend.async_add_experience(exp)
    loaded = await backend.async_get_experience(exp.id)

    assert loaded is not None
    assert loaded.title == exp.title
    assert loaded.key_decisions == exp.key_decisions

    await backend.async_delete_experience(exp.id)
    await backend.close()
