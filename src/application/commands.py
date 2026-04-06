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


@dataclass
class SearchCommand:
    query: str
    tags: list[str] | None = None
    top_k: int = 3
    session_id: str | None = None
    project_id: str | None = None


@dataclass
class RecordSessionCommand:
    session_id: str
    task_description: str
    experience_ids_injected: list[str] = field(default_factory=list)
    iteration_count: int = 1
    had_error_correction: bool = False
    user_accepted: bool = True
    ab_test_group: str = "treatment"
    ab_test_result_shown: bool = True


@dataclass
class GetStatsCommand:
    since_days: int | None = None
    project_id: str | None = None
    business_id: str | None = None
    team_id: str | None = None
    compare: bool = False


@dataclass
class InferAdoptionCommand:
    session_id: str
    final_response: str
    experience_ids_injected: list[str] = field(default_factory=list)


@dataclass
class ExtractExperienceCommand:
    task_description: str
    solution_summary: str
    key_decisions: str
    conversation_summary: str | None = None
    tags: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    project_id: str | None = None


@dataclass
class ListExperiencesCommand:
    status: str = "pending"


@dataclass
class DeleteExperienceCommand:
    prefix: str


@dataclass
class GetExperienceCommand:
    experience_id: str


@dataclass
class SearchV2Command:
    task_description: str
    project_id: str
    project_manifest: str
    session_id: str | None = None
    top_k: int = 5


@dataclass
class SaveCommand:
    task_description: str
    solution: str
    key_decisions: str
    tags: list[str]
    project_id: str
    outcome: str
    search_event_id: str | None = None


@dataclass
class FeedbackV2Command:
    search_event_id: str
    helpful_ids: list[str] = field(default_factory=list)
    unhelpful_ids: list[str] = field(default_factory=list)
    comment: str | None = None


@dataclass
class ScanPromotionCandidatesCommand:
    business_id: str | None = None
    dry_run: bool = False


@dataclass
class PromoteExperienceCommand:
    experience_id: str
    target_scope: str
    target_scope_id: str


@dataclass
class IgnorePromotionCommand:
    experience_id: str
