from __future__ import annotations
from src.application.unit_of_work import (
    AbstractUnitOfWork,
    AbstractExperienceStore,
    AbstractVectorStore,
    AbstractMetricsStore,
    AbstractAnalyticsStore,
)
import numpy as np


class InMemoryExperienceStore(AbstractExperienceStore):
    def __init__(self):
        self._committed: dict = {}
        self._pending: dict = {}

    def add(self, exp) -> None:
        self._pending[exp.id] = exp
        return exp

    def get(self, exp_id: str):
        return self._pending.get(exp_id) or self._committed.get(exp_id)

    def update(self, exp) -> None:
        self._pending[exp.id] = exp

    def list_by_status(self, status: str) -> list:
        merged = {**self._committed, **self._pending}
        def _status_val(s):
            return s.value.lower() if hasattr(s, "value") else str(s).lower()
        return [e for e in merged.values() if _status_val(e.status) == status.lower()]

    def _commit(self):
        self._committed.update(self._pending)
        self._pending = {}

    def _rollback(self):
        self._pending = {}

    async def aadd(self, exp) -> None:
        self.add(exp)

    async def aget(self, exp_id: str):
        return self.get(exp_id)

    async def aupdate(self, exp) -> None:
        self.update(exp)

    async def alist_by_status(self, status: str) -> list:
        return self.list_by_status(status)

    def list_active(self) -> list:
        return self.list_by_status("active")


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

    async def asave_vector(self, exp_id: str, vector: list[float]) -> None:
        self.save_vector(exp_id, vector)

    async def aget_all_vectors(self, exp_ids=None):
        return self.get_all_vectors(exp_ids)

    def save_vectors(self, items: list) -> None:
        for exp_id, vector in items:
            self.save_vector(exp_id, vector)


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


class InMemoryAnalyticsStore(AbstractAnalyticsStore):
    def __init__(self):
        self._sessions: list = []
        self._feedbacks: list = []

    async def record_session(self, session) -> None:
        self._sessions.append(session)

    async def record_feedback(self, feedback) -> None:
        self._feedbacks.append(feedback)

    async def get_stats(self, since_days: int | None = None) -> dict:
        return {
            "search_total": 0, "search_hit_rate": 0.0, "review_confirmed": 0,
            "review_rejected": 0, "review_pass_rate": 0.0, "session_total": len(self._sessions),
            "result_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
            "result_not_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
            "avg_result_count": 0.0, "query_adoption_rate": 0.0, "top_adopted_experiences": [],
            "zombie_count_db": 0, "ab_test_groups": {}, "new_sessions_30d": 0,
        }

    async def get_feedback_summary(self, since_days: int | None = None) -> dict:
        return {
            "total_feedback": len(self._feedbacks), "adopted_count": 0, "adoption_rate": 0.0,
            "low_adoption_count": 0, "low_adoption_ids": [], "reject_reasons": {},
        }

    async def get_search_miss_queries(self, since_days: int = 30, limit: int = 10) -> list[dict]:
        return []

    async def get_recent_query_keywords(self, since_days: int = 30, top_k: int = 20) -> list[str]:
        return []

    async def get_hitted_experience_ids(self) -> list[str]:
        return []

    async def get_review_reject_reasons(self, limit: int = 10) -> dict[str, int]:
        return {}


class InMemoryUnitOfWork(AbstractUnitOfWork):
    def __init__(self):
        super().__init__()
        self.experiences = InMemoryExperienceStore()
        self.vectors = InMemoryVectorStore()
        self.metrics = InMemoryMetricsStore()
        self.analytics = InMemoryAnalyticsStore()
        self.committed = False

    def __enter__(self) -> "InMemoryUnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.experiences._commit()
            self.committed = True
        else:
            self.experiences._rollback()

    async def __aenter__(self) -> "InMemoryUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.experiences._commit()
            self.committed = True
        else:
            self.experiences._rollback()
