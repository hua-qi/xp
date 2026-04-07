from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ExperienceType(str, Enum):
    BUGFIX = "bugfix"
    FEATURE = "feature"
    PATTERN = "pattern"


class ExperienceLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ExperienceStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    ARCHIVED = "archived"
    NEEDS_FIX = "needs_fix"


class ExperienceSource(str, Enum):
    AGENT = "agent"
    MANUAL = "manual"


class ScopeType(str, Enum):
    PROJECT = "project"
    BUSINESS = "business"
    TEAM = "team"


@dataclass
class ExperienceMetadata:
    """用于检索的结构化元数据，人可读、模型无关"""
    tech_stack: list[str] = field(default_factory=list)      # 技术栈：["react", "typescript"]
    problem_type: str = ""                                    # 问题类型：bugfix/feature/pattern
    scene: list[str] = field(default_factory=list)           # 场景标签：["表单", "列表", "异步"]


@dataclass
class Experience:
    id: str
    type: ExperienceType
    level: ExperienceLevel
    title: str
    tags: list[str]  # 向后兼容，实际使用 metadata.keywords
    problem: str
    solution: str
    confidence: float
    status: ExperienceStatus
    source: ExperienceSource
    created_at: str
    related_files: list[str] = field(default_factory=list)
    reject_reason: Optional[str] = None
    similarity: Optional[float] = None  # 向后兼容
    metadata: ExperienceMetadata = field(default_factory=ExperienceMetadata)
    # Phase 3: 文件追踪
    file_hashes: dict[str, str] = field(default_factory=dict)  # 文件路径 -> hash
    project: str = "default"  # 所属项目
    last_hit_at: Optional[str] = None  # 最后使用时间，用于 TTL
    stale_reason: Optional[str] = None  # 失效原因
    key_decisions: str = ""
    scope_type: ScopeType = field(default_factory=lambda: ScopeType.PROJECT)
    scope_id: Optional[str] = None
    promoted_to: Optional[str] = None
    demoted_from: Optional[str] = None
    recall_count: int = 0
    adoption_rate: float = 0.0
    ab_group: str = "B"
    conflict_with: Optional[str] = None
    retry_count: int = 0
    raw_input: Optional[dict] = None


@dataclass
class ProjectConfig:
    """项目配置"""
    name: str
    tags: list[str] = field(default_factory=list)
    root_path: Optional[str] = None
    cloud_sync_enabled: bool = False
    cloud_provider: Optional[str] = None  # supabase/weaviate/elasticsearch
    cloud_config: dict = field(default_factory=dict)


@dataclass
class Session:
    session_id: str
    task_description: str
    experience_ids_injected: list[str]
    iteration_count: int
    had_error_correction: bool
    user_accepted: bool
    created_at: str
    ab_test_group: str = "control"  # A/B 测试分组: "control" | "treatment"
    ab_test_result_shown: bool = True  # 是否实际展示了经验结果


@dataclass
class Feedback:
    """经验反馈记录"""
    experience_id: str
    adopted: bool
    reason: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ExperienceStats:
    """经验的统计信息"""
    experience_id: str
    hit_count: int = 0
    adopted_count: int = 0
    rejected_count: int = 0
    last_used_at: Optional[str] = None
    last_adopted_at: Optional[str] = None
    adoption_rate: float = 0.0  # 采纳率 = adopted_count / hit_count

    def update_adoption_rate(self):
        if self.hit_count > 0:
            self.adoption_rate = round(self.adopted_count / self.hit_count, 3)


@dataclass
class Team:
    id: str
    name: str
    owner_email: Optional[str] = None


@dataclass
class Business:
    id: str
    team_id: str
    name: str
    owner_email: Optional[str] = None


@dataclass
class Project:
    id: str
    business_id: str
    name: str
    language: str = ""
    frameworks: list[str] = field(default_factory=list)


@dataclass
class SearchEvent:
    id: str
    session_id: str
    project_id: str
    query_text: str
    timestamp: str
    result_ids: list[str] = field(default_factory=list)
    query_embedding: Optional[list[float]] = None


@dataclass
class FeedbackEvent:
    id: str
    search_event_id: str
    timestamp: str
    helpful_ids: list[str] = field(default_factory=list)
    unhelpful_ids: list[str] = field(default_factory=list)
    comment: Optional[str] = None


@dataclass
class PromotionCandidate:
    id: str
    experience_id: str
    target_scope_type: str
    target_scope_id: str
    score: float
    status: str
    ignored_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ProjectBusinessLink:
    project_id: str
    business_id: str


@dataclass
class BusinessTeamLink:
    business_id: str
    team_id: str


@dataclass
class ConflictReview:
    id: str
    experience_id_a: str
    experience_id_b: str
    conflict_type: str
    status: str = "pending"
    resolution: Optional[str] = None
    condition_note: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str = ""


@dataclass
class CorrectionRequest:
    id: str
    experience_id: str
    session_id: str
    comment: str
    task_description: str
    outcome_description: str
    status: str = "pending"
    fixed_at: Optional[str] = None
    created_at: str = ""
