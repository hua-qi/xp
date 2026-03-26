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


class ExperienceSource(str, Enum):
    AGENT = "agent"
    MANUAL = "manual"


@dataclass
class ExperienceMetadata:
    """用于检索的结构化元数据，人可读、模型无关"""
    tech_stack: list[str] = field(default_factory=list)      # 技术栈：["react", "typescript"]
    problem_type: str = ""                                    # 问题类型：bugfix/feature/pattern
    scene: list[str] = field(default_factory=list)           # 场景标签：["表单", "列表", "异步"]
    keywords: list[str] = field(default_factory=list)        # 关键词：["useEffect", "infinite loop"]


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


@dataclass
class Session:
    session_id: str
    task_description: str
    experience_ids_injected: list[str]
    iteration_count: int
    had_error_correction: bool
    user_accepted: bool
    created_at: str


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
