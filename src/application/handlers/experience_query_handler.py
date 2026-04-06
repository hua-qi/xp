from __future__ import annotations
from typing import Callable
from ..commands import ListExperiencesCommand, DeleteExperienceCommand, GetExperienceCommand
from ..unit_of_work import AbstractUnitOfWork


class ExperienceQueryHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    async def handle_list(self, cmd: ListExperiencesCommand) -> list:
        from ...models import ExperienceStatus
        try:
            status_enum = ExperienceStatus(cmd.status)
        except ValueError:
            raise ValueError(f"Invalid status: {cmd.status}")
        async with self._uow_factory() as uow:
            return uow.experiences.list_by_status(status_enum.value)

    async def handle_delete(self, cmd: DeleteExperienceCommand) -> str | None:
        async with self._uow_factory() as uow:
            all_exps = []
            for status in ["pending", "active", "archived"]:
                all_exps.extend(uow.experiences.list_by_status(status))
            matches = [e for e in all_exps if e.id.startswith(cmd.prefix)]
            if len(matches) != 1:
                return None
            return matches[0].id

    async def handle_get(self, cmd: GetExperienceCommand):
        async with self._uow_factory() as uow:
            return uow.experiences.get(cmd.experience_id)
