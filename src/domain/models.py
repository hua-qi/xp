from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Experience:
    id: str
    title: str
    problem: str
    solution: str
    key_decisions: str
    status: Literal["PENDING", "ACTIVE", "ARCHIVED"]
    confidence: float
    tech_stack: list[str]
    scene: list[str]
    level: str
    exp_type: str
    source: str
    project_id: str | None
    created_at: str
    tags: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    last_hit_at: str | None = None
    reject_reason: str | None = None

    def activate(self, triggered_by: Literal["auto", "manual"]) -> list:
        from .events import ExperienceActivated
        self.status = "ACTIVE"
        return [ExperienceActivated(experience_id=self.id, triggered_by=triggered_by)]

    def archive(self, reason: str) -> list:
        from .events import ExperienceArchived
        self.status = "ARCHIVED"
        self.reject_reason = reason
        return [ExperienceArchived(experience_id=self.id, reason=reason)]
