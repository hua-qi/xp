from __future__ import annotations
from ...application.unit_of_work import AbstractMetricsStore
from ...storage import MetricsStore as _LegacyMetricsStore


class MetricsStoreAdapter(AbstractMetricsStore):
    def __init__(self):
        self._store = _LegacyMetricsStore()

    def record_search(self, query: str, result_count: int) -> None:
        self._store.record_search(query, result_count)

    def record_feedback(self, feedback) -> None:
        self._store.record_feedback(feedback)

    def get_experience_stats(self, exp_id: str):
        return self._store.get_experience_stats(exp_id)
