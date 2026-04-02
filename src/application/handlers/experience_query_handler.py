from __future__ import annotations
from typing import Callable
from ..commands import ListExperiencesCommand, DeleteExperienceCommand, GetExperienceCommand
from ..unit_of_work import AbstractUnitOfWork


class ExperienceQueryHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    def handle_list(self, cmd: ListExperiencesCommand) -> list:
        from ...storage import ExperienceStore
        from ...models import ExperienceStatus

        store = ExperienceStore()
        try:
            status_enum = ExperienceStatus(cmd.status)
        except ValueError:
            raise ValueError(f"Invalid status: {cmd.status}")
        return store.list_by_status(status_enum)

    def handle_delete(self, cmd: DeleteExperienceCommand) -> str | None:
        from ...storage import ExperienceStore
        from ...models import ExperienceStatus

        store = ExperienceStore()
        all_exps = []
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(store.list_by_status(status))
        matches = [e for e in all_exps if e.id.startswith(cmd.prefix)]
        if len(matches) != 1:
            return None
        store.delete(matches[0].id)
        return matches[0].id

    def handle_get(self, cmd: GetExperienceCommand):
        from ...storage import ExperienceStore
        store = ExperienceStore()
        return store.get(cmd.experience_id)
