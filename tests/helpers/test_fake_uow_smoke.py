from tests.helpers.fake_uow import InMemoryUnitOfWork


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
