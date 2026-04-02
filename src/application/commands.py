from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CreateExperienceCommand:
    task_output: str
    project_id: str | None = None
    session_id: str | None = None


@dataclass
class SearchExperienceCommand:
    query: str
    tech_stack: list[str] = field(default_factory=list)
    limit: int = 10
    session_id: str | None = None


@dataclass
class RecordFeedbackCommand:
    experience_id: str
    helpful: bool
    session_id: str | None = None


@dataclass
class ActivateExperienceCommand:
    experience_id: str


@dataclass
class ArchiveExperienceCommand:
    experience_id: str
    reason: str


@dataclass
class AnalyzeQualityCommand:
    project_id: str | None = None


@dataclass
class CreateProjectCommand:
    name: str


@dataclass
class StartSessionCommand:
    project_id: str | None = None
