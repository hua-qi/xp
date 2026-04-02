from __future__ import annotations
from ...application.unit_of_work import AbstractVectorStore
from ...storage import VectorStore as _LegacyVectorStore


class VectorStoreAdapter(AbstractVectorStore):
    def __init__(self):
        self._store = _LegacyVectorStore()

    def save_vector(self, exp_id: str, vector: list[float]) -> None:
        self._store.save_vector(exp_id, vector)

    def get_all_vectors(self, exp_ids=None):
        return self._store.get_all_vectors(exp_ids)
