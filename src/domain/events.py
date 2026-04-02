from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ExperienceCreated:
    experience_id: str
    title: str
    content: str
    tech_stack: list[str]
    scene: list[str]
    level: str
    quality_score: int
    project_id: str | None


@dataclass(frozen=True)
class ExperienceActivated:
    experience_id: str
    triggered_by: Literal["auto", "manual"]


@dataclass(frozen=True)
class ExperienceArchived:
    experience_id: str
    reason: str


@dataclass(frozen=True)
class EmbeddingRequested:
    experience_id: str
    text: str


@dataclass(frozen=True)
class FeedbackRecorded:
    experience_id: str
    helpful: bool
    session_id: str | None
    old_confidence: float
    new_confidence: float


@dataclass(frozen=True)
class ExperienceHit:
    experience_id: str
    session_id: str | None
    query: str


@dataclass(frozen=True)
class DuplicateDetected:
    new_experience_id: str
    existing_experience_id: str
    similarity: float
