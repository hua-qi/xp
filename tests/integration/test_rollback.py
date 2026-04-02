from tests.helpers.fake_uow import InMemoryUnitOfWork


def test_experience_not_persisted_when_exception_raised():
    uow = InMemoryUnitOfWork()

    try:
        with uow:
            class FakeExp:
                id = "exp-rollback"
                status = "ACTIVE"

            uow.experiences.add(FakeExp())
            raise RuntimeError("模拟存储失败")
    except RuntimeError:
        pass

    assert uow.experiences.get("exp-rollback") is None
    assert uow.committed is False


def test_experience_persisted_on_success():
    uow = InMemoryUnitOfWork()

    with uow:
        class FakeExp:
            id = "exp-success"
            status = "ACTIVE"

        uow.experiences.add(FakeExp())

    assert uow.experiences.get("exp-success") is not None
    assert uow.committed is True
