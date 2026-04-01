from typing import Optional
import numpy as np

from .base import StorageBackend
from ..models import Experience, ExperienceStatus, Session, Feedback, ExperienceStats
from ..storage import ExperienceStore, MetricsStore, VectorStore


class LocalBackend(StorageBackend):
    def __init__(self):
        self._exp_store = ExperienceStore()
        self._metrics = MetricsStore()
        self._vectors = VectorStore()

    def add_experience(self, exp: Experience) -> Experience:
        return self._exp_store.add(exp)

    def get_experience(self, exp_id: str) -> Optional[Experience]:
        return self._exp_store.get(exp_id)

    def update_experience(self, exp: Experience) -> bool:
        return self._exp_store.update(exp)

    def delete_experience(self, exp_id: str) -> bool:
        return self._exp_store.delete(exp_id)

    def list_by_status(self, status: ExperienceStatus) -> list[Experience]:
        return self._exp_store.list_by_status(status)

    def record_session(self, session: Session):
        self._metrics.record_session(session)

    def record_feedback(self, feedback: Feedback):
        self._metrics.record_feedback(feedback)

    def get_experience_stats(self, exp_id: str) -> Optional[ExperienceStats]:
        return self._metrics.get_experience_stats(exp_id)

    def save_vector(self, exp_id: str, vector: list[float]):
        self._vectors.save_vector(exp_id, vector)

    def get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> tuple[list[str], np.ndarray]:
        return self._vectors.get_all_vectors(exp_ids)
