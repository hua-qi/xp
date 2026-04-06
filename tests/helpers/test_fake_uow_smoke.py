import pytest
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import ScopeType


def test_inmemory_uow_commits_on_success():
    with InMemoryUnitOfWork() as uow:
        uow.committed
    assert uow.committed is True


def test_inmemory_uow_does_not_commit_on_exception():
    uow = InMemoryUnitOfWork()
    try:
        with uow:
            raise ValueError("fail")
    except ValueError:
        pass
    assert uow.committed is False


class TestInMemoryExperienceStoreScopeFilter:
    def test_list_by_status_returns_all_statuses_correctly(self):
        from tests.helpers.fake_uow import InMemoryExperienceStore

        store = InMemoryExperienceStore()

        class FakeExp:
            def __init__(self, id, status, scope_type):
                self.id = id
                self.status = status
                self.scope_type = scope_type

        store._committed["e1"] = FakeExp("e1", "active", ScopeType.PROJECT)
        store._committed["e2"] = FakeExp("e2", "pending", ScopeType.BUSINESS)

        active = store.list_by_status("active")
        assert len(active) == 1
        assert active[0].id == "e1"

    def test_list_by_status_filters_scope_type_correctly(self):
        from tests.helpers.fake_uow import InMemoryExperienceStore

        store = InMemoryExperienceStore()

        class FakeExp:
            def __init__(self, id, status, scope_type):
                self.id = id
                self.status = status
                self.scope_type = scope_type

        store._committed["e1"] = FakeExp("e1", "active", ScopeType.PROJECT)
        store._committed["e2"] = FakeExp("e2", "active", ScopeType.BUSINESS)
        store._committed["e3"] = FakeExp("e3", "active", ScopeType.TEAM)

        all_active = store.list_by_status("active")
        assert len(all_active) == 3

        project_only = [e for e in all_active if e.scope_type == ScopeType.PROJECT]
        assert len(project_only) == 1
        assert project_only[0].id == "e1"


@pytest.mark.asyncio
async def test_inmemory_uow_async_context_manager():
    uow = InMemoryUnitOfWork()
    async with uow as u:
        assert u is uow
    assert uow.committed is True


@pytest.mark.asyncio
async def test_inmemory_uow_async_rollback_on_exception():
    uow = InMemoryUnitOfWork()
    try:
        async with uow:
            raise ValueError("fail")
    except ValueError:
        pass
    assert uow.committed is False

