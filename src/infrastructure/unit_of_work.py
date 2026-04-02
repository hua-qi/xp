from __future__ import annotations
from ..application.unit_of_work import AbstractUnitOfWork
from .stores.experience_store import ExperienceStoreAdapter
from .stores.vector_store import VectorStoreAdapter
from .stores.metrics_store import MetricsStoreAdapter


class UnitOfWork(AbstractUnitOfWork):
    def __init__(self):
        super().__init__()
        self.experiences = ExperienceStoreAdapter()
        self.vectors = VectorStoreAdapter()
        self.metrics = MetricsStoreAdapter()

    def __enter__(self) -> "UnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass
