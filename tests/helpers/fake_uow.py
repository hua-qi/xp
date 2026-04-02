from __future__ import annotations
from src.application.unit_of_work import (
    AbstractUnitOfWork,
    AbstractExperienceStore,
    AbstractVectorStore,
    AbstractMetricsStore,
)
import numpy as np


class InMemoryExperienceStore(AbstractExperienceStore):
    def __init__(self):
        self._committed: dict = {}
        self._pending: dict = {}

    def add(self, exp) -> None:
        self._pending[exp.id] = exp

    def get(self, exp_id: str):
        return self._pending.get(exp_id) or self._committed.get(exp_id)

    def update(self, exp) -> None:
        self._pending[exp.id] = exp

    def list_by_status(self, status: str) -> list:
        merged = {**self._committed, **self._pending}
        return [e for e in merged.values() if e.status == status]

    def _commit(self):
        self._committed.update(self._pending)
        self._pending = {}

    def _rollback(self):
        self._pending = {}


class InMemoryVectorStore(AbstractVectorStore):
    def __init__(self):
        self._data: dict[str, list[float]] = {}

    def save_vector(self, exp_id: str, vector: list[float]) -> None:
        self._data[exp_id] = vector

    def get_all_vectors(self, exp_ids=None):
        if exp_ids is not None:
            items = [(eid, v) for eid, v in self._data.items() if eid in exp_ids]
        else:
            items = list(self._data.items())
        if not items:
            return [], np.array([])
        ids, vecs = zip(*items)
        return list(ids), np.array(vecs, dtype=np.float32)


class InMemoryMetricsStore(AbstractMetricsStore):
    def __init__(self):
        self._searches: list = []
        self._feedbacks: list = []
        self._stats: dict = {}

    def record_search(self, query: str, result_count: int) -> None:
        self._searches.append({"query": query, "result_count": result_count})

    def record_feedback(self, feedback) -> None:
        self._feedbacks.append(feedback)

    def get_experience_stats(self, exp_id: str):
        return self._stats.get(exp_id)


class InMemoryUnitOfWork(AbstractUnitOfWork):
    def __init__(self):
        super().__init__()
        self.experiences = InMemoryExperienceStore()
        self.vectors = InMemoryVectorStore()
        self.metrics = InMemoryMetricsStore()
        self.committed = False

    def __enter__(self) -> "InMemoryUnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.experiences._commit()
            self.committed = True
        else:
            self.experiences._rollback()
