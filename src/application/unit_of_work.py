from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class AbstractExperienceStore(ABC):
    @abstractmethod
    def add(self, exp) -> None: ...

    @abstractmethod
    def get(self, exp_id: str): ...

    @abstractmethod
    def update(self, exp) -> None: ...

    @abstractmethod
    def list_by_status(self, status: str) -> list: ...


class AbstractVectorStore(ABC):
    @abstractmethod
    def save_vector(self, exp_id: str, vector: list[float]) -> None: ...

    @abstractmethod
    def get_all_vectors(self, exp_ids: list[str] | None = None): ...


class AbstractMetricsStore(ABC):
    @abstractmethod
    def record_search(self, query: str, result_count: int) -> None: ...

    @abstractmethod
    def record_feedback(self, feedback) -> None: ...

    @abstractmethod
    def get_experience_stats(self, exp_id: str): ...


class AbstractAnalyticsStore(ABC):
    @abstractmethod
    async def record_session(self, session) -> None: ...

    @abstractmethod
    async def record_feedback(self, feedback) -> None: ...

    @abstractmethod
    async def get_stats(self, since_days: int | None = None) -> dict: ...

    @abstractmethod
    async def get_feedback_summary(self, since_days: int | None = None) -> dict: ...

    @abstractmethod
    async def get_search_miss_queries(self, since_days: int = 30, limit: int = 10) -> list[dict]: ...

    @abstractmethod
    async def get_recent_query_keywords(self, since_days: int = 30, top_k: int = 20) -> list[str]: ...

    @abstractmethod
    async def get_hitted_experience_ids(self) -> list[str]: ...

    @abstractmethod
    async def get_review_reject_reasons(self, limit: int = 10) -> dict[str, int]: ...


class AbstractUnitOfWork(ABC):
    experiences: AbstractExperienceStore
    vectors: AbstractVectorStore
    metrics: AbstractMetricsStore
    analytics: AbstractAnalyticsStore

    def __init__(self):
        self._events: list[Any] = []

    def collect_event(self, event: Any) -> None:
        self._events.append(event)

    def get_events(self) -> list[Any]:
        return list(self._events)

    @abstractmethod
    def __enter__(self) -> "AbstractUnitOfWork": ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...

    @abstractmethod
    async def __aenter__(self) -> "AbstractUnitOfWork": ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
