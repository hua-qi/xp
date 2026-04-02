from __future__ import annotations
from ...application.unit_of_work import AbstractExperienceStore
from ...storage import ExperienceStore as _LegacyStore
from ...models import ExperienceStatus


class ExperienceStoreAdapter(AbstractExperienceStore):
    def __init__(self):
        self._store = _LegacyStore()

    def add(self, exp) -> None:
        self._store.add(exp)

    def get(self, exp_id: str):
        return self._store.get(exp_id)

    def update(self, exp) -> None:
        self._store.update(exp)

    def list_by_status(self, status: str) -> list:
        status_map = {
            "PENDING": ExperienceStatus.PENDING,
            "ACTIVE": ExperienceStatus.ACTIVE,
            "ARCHIVED": ExperienceStatus.ARCHIVED,
        }
        return self._store.list_by_status(status_map[status])
