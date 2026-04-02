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


class AbstractUnitOfWork(ABC):
    experiences: AbstractExperienceStore
    vectors: AbstractVectorStore
    metrics: AbstractMetricsStore

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
