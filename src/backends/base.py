from abc import ABC, abstractmethod
from typing import Optional
from ..models import Experience, ExperienceStatus, Session, Feedback, ExperienceStats


class StorageBackend(ABC):

    @abstractmethod
    def add_experience(self, exp: Experience) -> Experience:
        ...

    @abstractmethod
    def get_experience(self, exp_id: str) -> Optional[Experience]:
        ...

    @abstractmethod
    def update_experience(self, exp: Experience) -> bool:
        ...

    @abstractmethod
    def delete_experience(self, exp_id: str) -> bool:
        ...

    @abstractmethod
    def list_by_status(self, status: ExperienceStatus) -> list[Experience]:
        ...

    @abstractmethod
    def record_session(self, session: Session):
        ...

    @abstractmethod
    def record_feedback(self, feedback: Feedback):
        ...

    @abstractmethod
    def get_experience_stats(self, exp_id: str) -> Optional[ExperienceStats]:
        ...

    @abstractmethod
    def save_vector(self, exp_id: str, vector: list[float]):
        ...

    @abstractmethod
    def get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> tuple[list[str], "np.ndarray"]:
        ...
