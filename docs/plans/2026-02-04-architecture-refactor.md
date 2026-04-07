# 架构重构 Implementation Plan

**Goal:** 将 727 行上帝类 `KnowledgeService` 拆解为事件驱动 + Unit of Work 架构，实现 domain/application/infrastructure 三层分离。

**Architecture:** domain 层只含纯函数（零 I/O），application 层通过 CommandBus 分发给各 Handler，Handler 通过注入的 UnitOfWork 协调三存储原子提交。interfaces 层（CLI/REST）只做参数转换，统一调用 `CommandBus.dispatch()`。

**Tech Stack:** Python 3.9+、pytest、FastAPI、SQLite、numpy（已有）

---

## 背景：现有代码结构

重构前，读懂这几个文件：

| 文件 | 行数 | 说明 |
|------|------|------|
| `src/knowledge.py` | 727 | 上帝类，所有业务逻辑都在这里 |
| `src/domain/quality.py` | 32 | 已是纯函数，无需改 |
| `src/domain/metadata.py` | 90 | 已是纯函数，无需改 |
| `src/domain/extraction.py` | 132 | ExtractionService，仍混有 I/O |
| `src/domain/feedback.py` | 28 | FeedbackService，仍混有 I/O |
| `src/domain/search.py` | 98 | SearchService，仍混有 I/O |
| `src/storage.py` | 703 | ExperienceStore + MetricsStore + VectorStore |
| `src/models.py` | 110 | 现有 dataclass（Experience、Session 等） |
| `src/interfaces/rest_api.py` | 187 | FastAPI 路由，直接 import KnowledgeService |
| `src/cli.py` | 714 | CLI，直接 import KnowledgeService |

测试运行命令（先跑一遍确认当前状态）：
```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```

---

## Phase 1：建骨架

**目标**：新建目录结构，原有代码不动，保证全量测试通过。

### Task 1.1：创建 domain 层新文件

**Files:**
- Create: `src/domain/models.py`
- Create: `src/domain/events.py`
- Create: `src/domain/constants.py`

**Step 1：创建 `src/domain/constants.py`**

```python
QUALITY_SCORE_AUTO_ACTIVATE = 80
QUALITY_SCORE_MIN_ACCEPT = 40
DUPLICATE_SIMILARITY_THRESHOLD = 0.85
EXPERIENCE_TTL_DAYS = 90
SEARCH_DEFAULT_LIMIT = 10
CONFIDENCE_HELPFUL_DELTA = 0.1
CONFIDENCE_UNHELPFUL_DELTA = -0.05
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0
CONFIDENCE_AUTO_ACTIVATE_INITIAL = 0.65
CONFIDENCE_CONFIRM_VALUE = 0.8
AB_TEST_CONTROL_MODULO = 10
DUPLICATE_VECTOR_CLUSTER_THRESHOLD = 0.92
LOW_ADOPTION_THRESHOLD = 0.3
AUTO_ARCHIVE_ADOPTION_THRESHOLD = 0.1
INFER_ADOPTION_SIMILARITY_THRESHOLD = 0.60
STALE_EXPERIENCE_DAYS = 90
```

**Step 2：运行测试，验证没有破坏现有代码**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过（新文件不会影响现有代码）

**Step 3：创建 `src/domain/events.py`**

```python
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
```

**Step 4：运行测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 5：创建 `src/domain/models.py`**

> 注意：这是新的 domain 层模型，与 `src/models.py`（旧模型）并存，Phase 5 才删旧的。

```python
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
```

**Step 6：运行测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 7：Commit**

```bash
git add src/domain/constants.py src/domain/events.py src/domain/models.py
git commit -m "feat: add domain constants, events, models skeleton"
```

---

### Task 1.2：创建 application 层骨架

**Files:**
- Create: `src/application/__init__.py`
- Create: `src/application/commands.py`
- Create: `src/application/command_bus.py`
- Create: `src/application/unit_of_work.py`
- Create: `src/application/handlers/__init__.py`

**Step 1：创建目录和 `src/application/__init__.py`**

```python
# 空文件
```

**Step 2：创建 `src/application/commands.py`**

```python
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
```

**Step 3：创建 `src/application/command_bus.py`**

```python
from __future__ import annotations
from typing import Any, Callable


class UnregisteredCommandError(Exception):
    pass


class CommandBus:
    def __init__(self):
        self._handlers: dict[type, Callable] = {}

    def register(self, command_type: type, handler_fn: Callable) -> None:
        self._handlers[command_type] = handler_fn

    def dispatch(self, command: Any) -> Any:
        handler = self._handlers.get(type(command))
        if handler is None:
            raise UnregisteredCommandError(f"No handler for {type(command).__name__}")
        return handler(command)
```

**Step 4：创建 `src/application/unit_of_work.py`**

```python
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
```

**Step 5：创建 `src/application/handlers/__init__.py`**

```python
# 空文件
```

**Step 6：运行测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 7：Commit**

```bash
git add src/application/
git commit -m "feat: add application layer skeleton (commands, command_bus, unit_of_work)"
```

---

### Task 1.3：创建 infrastructure 层骨架

**Files:**
- Create: `src/infrastructure/__init__.py`
- Create: `src/infrastructure/stores/__init__.py`
- Create: `src/infrastructure/stores/experience_store.py`
- Create: `src/infrastructure/stores/vector_store.py`
- Create: `src/infrastructure/stores/metrics_store.py`
- Create: `src/infrastructure/unit_of_work.py`

**Step 1：创建所有 `__init__.py`（均为空文件）**

**Step 2：创建 `src/infrastructure/stores/experience_store.py`**

> 这是对 `src/storage.py` 中 `ExperienceStore` 的包装，让它实现 `AbstractExperienceStore` 接口。暂时只 delegate 给旧的。

```python
from __future__ import annotations
from ...application.unit_of_work import AbstractExperienceStore
from ...storage import ExperienceStore as _LegacyStore
from ...models import ExperienceStatus


class ExperienceStoreAdapter(AbstractExperienceStore):
    def __init__(self):
        self._store = _LegacyStore()

    def add(self, exp) -> None:
        self._store.add(exp)

    def get(self, exp_id: str):
        return self._store.get(exp_id)

    def update(self, exp) -> None:
        self._store.update(exp)

    def list_by_status(self, status: str) -> list:
        status_map = {
            "PENDING": ExperienceStatus.PENDING,
            "ACTIVE": ExperienceStatus.ACTIVE,
            "ARCHIVED": ExperienceStatus.ARCHIVED,
        }
        return self._store.list_by_status(status_map[status])
```

**Step 3：创建 `src/infrastructure/stores/vector_store.py`**

```python
from __future__ import annotations
from ...application.unit_of_work import AbstractVectorStore
from ...storage import VectorStore as _LegacyVectorStore


class VectorStoreAdapter(AbstractVectorStore):
    def __init__(self):
        self._store = _LegacyVectorStore()

    def save_vector(self, exp_id: str, vector: list[float]) -> None:
        self._store.save_vector(exp_id, vector)

    def get_all_vectors(self, exp_ids=None):
        return self._store.get_all_vectors(exp_ids)
```

**Step 4：创建 `src/infrastructure/stores/metrics_store.py`**

```python
from __future__ import annotations
from ...application.unit_of_work import AbstractMetricsStore
from ...storage import MetricsStore as _LegacyMetricsStore


class MetricsStoreAdapter(AbstractMetricsStore):
    def __init__(self):
        self._store = _LegacyMetricsStore()

    def record_search(self, query: str, result_count: int) -> None:
        self._store.record_search(query, result_count)

    def record_feedback(self, feedback) -> None:
        self._store.record_feedback(feedback)

    def get_experience_stats(self, exp_id: str):
        return self._store.get_experience_stats(exp_id)
```

**Step 5：创建 `src/infrastructure/unit_of_work.py`**

```python
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
```

**Step 6：运行测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 7：Commit**

```bash
git add src/infrastructure/
git commit -m "feat: add infrastructure layer skeleton (store adapters, unit_of_work)"
```

---

### Task 1.4：创建 InMemory 测试辅助工具

**Files:**
- Create: `tests/helpers/__init__.py`
- Create: `tests/helpers/fake_uow.py`

**Step 1：创建 `tests/helpers/__init__.py`（空文件）**

**Step 2：创建 `tests/helpers/fake_uow.py`**

```python
from __future__ import annotations
from src.application.unit_of_work import (
    AbstractUnitOfWork,
    AbstractExperienceStore,
    AbstractVectorStore,
    AbstractMetricsStore,
)
import numpy as np


class InMemoryExperienceStore(AbstractExperienceStore):
    def __init__(self):
        self._data: dict = {}

    def add(self, exp) -> None:
        self._data[exp.id] = exp

    def get(self, exp_id: str):
        return self._data.get(exp_id)

    def update(self, exp) -> None:
        self._data[exp.id] = exp

    def list_by_status(self, status: str) -> list:
        return [e for e in self._data.values() if e.status == status]


class InMemoryVectorStore(AbstractVectorStore):
    def __init__(self):
        self._data: dict[str, list[float]] = {}

    def save_vector(self, exp_id: str, vector: list[float]) -> None:
        self._data[exp_id] = vector

    def get_all_vectors(self, exp_ids=None):
        if exp_ids is not None:
            items = [(eid, v) for eid, v in self._data.items() if eid in exp_ids]
        else:
            items = list(self._data.items())
        if not items:
            return [], np.array([])
        ids, vecs = zip(*items)
        return list(ids), np.array(vecs, dtype=np.float32)


class InMemoryMetricsStore(AbstractMetricsStore):
    def __init__(self):
        self._searches: list = []
        self._feedbacks: list = []
        self._stats: dict = {}

    def record_search(self, query: str, result_count: int) -> None:
        self._searches.append({"query": query, "result_count": result_count})

    def record_feedback(self, feedback) -> None:
        self._feedbacks.append(feedback)

    def get_experience_stats(self, exp_id: str):
        return self._stats.get(exp_id)


class InMemoryUnitOfWork(AbstractUnitOfWork):
    def __init__(self):
        super().__init__()
        self.experiences = InMemoryExperienceStore()
        self.vectors = InMemoryVectorStore()
        self.metrics = InMemoryMetricsStore()
        self.committed = False

    def __enter__(self) -> "InMemoryUnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.committed = True
```

**Step 3：写一个冒烟测试验证 InMemoryUoW 可用**

文件：`tests/helpers/test_fake_uow_smoke.py`

```python
from tests.helpers.fake_uow import InMemoryUnitOfWork


def test_inmemory_uow_commits_on_success():
    with InMemoryUnitOfWork() as uow:
        uow.committed  # 尚未提交
    assert uow.committed is True


def test_inmemory_uow_does_not_commit_on_exception():
    uow = InMemoryUnitOfWork()
    try:
        with uow:
            raise ValueError("fail")
    except ValueError:
        pass
    assert uow.committed is False
```

**Step 4：运行冒烟测试**

```bash
python3 -m pytest tests/helpers/test_fake_uow_smoke.py -v
```
Expected: 2 passed

**Step 5：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 6：Commit**

```bash
git add tests/helpers/
git commit -m "test: add InMemoryUnitOfWork and fake stores for integration tests"
```

---

## Phase 2：迁移领域逻辑

**目标**：将 `domain/` 中仍混有 I/O 的业务逻辑提取为纯函数，`KnowledgeService` 原有行为不变。

### Task 2.1：将置信度更新逻辑提取为纯函数

**Files:**
- Modify: `src/domain/feedback.py`
- Test: `tests/unit/test_feedback.py`（新增）

当前 `feedback.py` 中 `FeedbackService.record_feedback()` 混有 I/O（读存储、写存储）。目标：提取纯函数 `compute_new_confidence(current: float, adopted: bool) -> float`。

**Step 1：写失败测试**

文件：`tests/unit/test_feedback.py`

```python
from src.domain.feedback import compute_new_confidence
from src.domain.constants import (
    CONFIDENCE_HELPFUL_DELTA,
    CONFIDENCE_UNHELPFUL_DELTA,
    CONFIDENCE_MIN,
    CONFIDENCE_MAX,
)


def test_helpful_feedback_increases_confidence():
    result = compute_new_confidence(0.5, helpful=True)
    assert result == round(0.5 + CONFIDENCE_HELPFUL_DELTA, 3)


def test_unhelpful_feedback_decreases_confidence():
    result = compute_new_confidence(0.5, helpful=False)
    assert result == round(0.5 + CONFIDENCE_UNHELPFUL_DELTA, 3)


def test_confidence_never_exceeds_max():
    result = compute_new_confidence(0.95, helpful=True)
    assert result <= CONFIDENCE_MAX


def test_confidence_never_below_min():
    result = compute_new_confidence(0.02, helpful=False)
    assert result >= CONFIDENCE_MIN


def test_helpful_at_max_stays_at_max():
    result = compute_new_confidence(1.0, helpful=True)
    assert result == CONFIDENCE_MAX
```

**Step 2：运行测试，确认失败**

```bash
python3 -m pytest tests/unit/test_feedback.py -v
```
Expected: FAIL with `ImportError: cannot import name 'compute_new_confidence'`

**Step 3：在 `src/domain/feedback.py` 顶部添加纯函数**

在文件开头（`from typing import Optional` 之前）添加：

```python
from .constants import (
    CONFIDENCE_HELPFUL_DELTA,
    CONFIDENCE_UNHELPFUL_DELTA,
    CONFIDENCE_MIN,
    CONFIDENCE_MAX,
)


def compute_new_confidence(current: float, helpful: bool) -> float:
    delta = CONFIDENCE_HELPFUL_DELTA if helpful else CONFIDENCE_UNHELPFUL_DELTA
    return round(max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, current + delta)), 3)
```

**Step 4：运行单元测试，确认通过**

```bash
python3 -m pytest tests/unit/test_feedback.py -v
```
Expected: 5 passed

**Step 5：运行全量测试，确认没有回归**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 6：Commit**

```bash
git add src/domain/feedback.py tests/unit/test_feedback.py
git commit -m "feat: extract compute_new_confidence pure function from FeedbackService"
```

---

### Task 2.2：将重复检测逻辑提取为纯函数

**Files:**
- Create: `src/domain/experience.py`
- Test: `tests/unit/test_experience.py`（新增）

当前重复检测在 `extraction.py` 的 `_check_duplicate()` 内，混有向量 I/O。目标：提取 `check_duplicate(query_vec, all_vecs, all_ids) -> tuple[bool, str, float]`。

**Step 1：写失败测试**

文件：`tests/unit/test_experience.py`

```python
import numpy as np
from src.domain.experience import check_duplicate
from src.domain.constants import DUPLICATE_SIMILARITY_THRESHOLD


def _make_vec(val: float, dim: int = 4) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[0] = val
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def test_no_duplicate_when_vectors_empty():
    is_dup, _, _ = check_duplicate(
        query_vec=_make_vec(1.0),
        all_vecs=np.array([], dtype=np.float32),
        all_ids=[],
    )
    assert is_dup is False


def test_high_similarity_detected_as_duplicate():
    vec = _make_vec(1.0)
    is_dup, exp_id, sim = check_duplicate(
        query_vec=vec,
        all_vecs=np.array([vec]),
        all_ids=["exp-001"],
    )
    assert is_dup is True
    assert exp_id == "exp-001"
    assert sim >= DUPLICATE_SIMILARITY_THRESHOLD


def test_low_similarity_not_duplicate():
    query = _make_vec(1.0, dim=4)
    other = np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
    other = other / np.linalg.norm(other)
    is_dup, _, sim = check_duplicate(
        query_vec=query,
        all_vecs=other,
        all_ids=["exp-002"],
    )
    assert is_dup is False
    assert sim < DUPLICATE_SIMILARITY_THRESHOLD
```

**Step 2：运行测试，确认失败**

```bash
python3 -m pytest tests/unit/test_experience.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3：创建 `src/domain/experience.py`**

```python
from __future__ import annotations
import numpy as np
from .constants import DUPLICATE_SIMILARITY_THRESHOLD


def cosine_similarity_1d(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    normalized = matrix / norms
    q_norm = np.linalg.norm(query)
    q_unit = query / q_norm if q_norm > 0 else query
    return normalized @ q_unit


def check_duplicate(
    query_vec: np.ndarray,
    all_vecs: np.ndarray,
    all_ids: list[str],
) -> tuple[bool, str, float]:
    if len(all_ids) == 0 or all_vecs.size == 0:
        return False, "", 0.0
    scores = cosine_similarity_1d(query_vec, all_vecs)
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    if best_score >= DUPLICATE_SIMILARITY_THRESHOLD:
        return True, all_ids[best_idx], best_score
    return False, "", best_score
```

**Step 4：运行单元测试**

```bash
python3 -m pytest tests/unit/test_experience.py -v
```
Expected: 3 passed

**Step 5：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 6：Commit**

```bash
git add src/domain/experience.py tests/unit/test_experience.py
git commit -m "feat: add check_duplicate pure function in domain/experience.py"
```

---

### Task 2.3：将搜索排序逻辑提取为纯函数

**Files:**
- Create: `src/domain/search_domain.py`
- Test: `tests/unit/test_search_domain.py`（新增）

当前搜索在 `domain/search.py` 的 `SearchService` 内，混有 I/O。目标：提取 `rank_results(candidates, scores, limit) -> list` 和 `ab_assign(session_id) -> str`。

**Step 1：写失败测试**

文件：`tests/unit/test_search_domain.py`

```python
from src.domain.search_domain import rank_results, ab_assign


def _make_candidate(exp_id: str):
    class FakeExp:
        id = exp_id
        similarity = 0.0
    return FakeExp()


def test_rank_results_sorted_by_score():
    c1 = _make_candidate("a")
    c2 = _make_candidate("b")
    c3 = _make_candidate("c")
    candidates = [c1, c2, c3]
    scores = [0.7, 0.9, 0.5]
    result = rank_results(candidates, scores, limit=3)
    assert [r.id for r in result] == ["b", "a", "c"]


def test_rank_results_respects_limit():
    candidates = [_make_candidate(str(i)) for i in range(5)]
    scores = [float(i) / 10 for i in range(5)]
    result = rank_results(candidates, scores, limit=2)
    assert len(result) == 2


def test_rank_results_similarity_set_on_exp():
    c = _make_candidate("x")
    result = rank_results([c], [0.88], limit=5)
    assert result[0].similarity == round(0.88, 3)


def test_ab_assign_returns_treatment_for_most_sessions():
    groups = {ab_assign(f"session-{i}") for i in range(20)}
    assert "treatment" in groups


def test_ab_assign_same_session_always_same_group():
    g1 = ab_assign("fixed-session-abc")
    g2 = ab_assign("fixed-session-abc")
    assert g1 == g2


def test_rank_results_empty_input():
    result = rank_results([], [], limit=10)
    assert result == []
```

**Step 2：运行测试，确认失败**

```bash
python3 -m pytest tests/unit/test_search_domain.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3：创建 `src/domain/search_domain.py`**

```python
from __future__ import annotations
import hashlib
from .constants import AB_TEST_CONTROL_MODULO


def rank_results(candidates: list, scores: list[float], limit: int) -> list:
    paired = list(zip(candidates, scores))
    paired.sort(key=lambda x: x[1], reverse=True)
    paired = paired[:limit]
    for exp, score in paired:
        exp.similarity = round(float(score), 3)
    return [exp for exp, _ in paired]


def ab_assign(session_id: str) -> str:
    hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
    if hash_val % AB_TEST_CONTROL_MODULO == 0:
        return "control"
    return "treatment"
```

**Step 4：运行单元测试**

```bash
python3 -m pytest tests/unit/test_search_domain.py -v
```
Expected: 6 passed

**Step 5：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 6：Commit**

```bash
git add src/domain/search_domain.py tests/unit/test_search_domain.py
git commit -m "feat: extract rank_results and ab_assign pure functions"
```

---

### Task 2.4：验证单元测试覆盖率达标

**Step 1：检查 domain 层覆盖率**

```bash
python3 -m pytest tests/unit/ --cov=src/domain --cov-report=term-missing -q
```
Expected: `src/domain` 整体覆盖率 ≥ 90%

如果不足，检查 `term-missing` 输出中哪些行未被覆盖，补充对应测试。

**Step 2：Commit**

```bash
git commit -m "test: ensure domain layer unit test coverage >= 90%"
```

---

## Phase 3：引入 Unit of Work

**目标**：Handler 通过 `AbstractUnitOfWork` 操作存储，实现三存储原子提交语义，并在集成测试中用 `InMemoryUnitOfWork` 验证。

### Task 3.1：实现 FeedbackHandler

**Files:**
- Create: `src/application/handlers/feedback_handler.py`
- Test: `tests/integration/test_feedback_handler.py`（新增）

**Step 1：创建 `tests/integration/__init__.py`（空文件）**

**Step 2：写失败集成测试**

文件：`tests/integration/test_feedback_handler.py`

> 注意：集成测试使用 `InMemoryUnitOfWork`，不访问文件系统。需要先构造一个 Experience 放入 InMemory 存储中。

```python
import pytest
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.handlers.feedback_handler import FeedbackHandler
from src.application.commands import RecordFeedbackCommand
from src.domain.events import FeedbackRecorded
from src.domain.constants import CONFIDENCE_HELPFUL_DELTA, CONFIDENCE_UNHELPFUL_DELTA


def _make_fake_exp(exp_id: str, confidence: float = 0.5):
    class FakeExp:
        id = exp_id
        status = "ACTIVE"
        reject_reason = None

        def __init__(self, conf):
            self.confidence = conf

    return FakeExp(confidence)


def test_helpful_feedback_raises_confidence():
    uow = InMemoryUnitOfWork()
    exp = _make_fake_exp("exp-001", confidence=0.5)
    uow.experiences._data["exp-001"] = exp

    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="exp-001", helpful=True)
    handler.handle_feedback(cmd)

    updated = uow.experiences.get("exp-001")
    assert updated.confidence == round(0.5 + CONFIDENCE_HELPFUL_DELTA, 3)


def test_unhelpful_feedback_lowers_confidence():
    uow = InMemoryUnitOfWork()
    exp = _make_fake_exp("exp-002", confidence=0.5)
    uow.experiences._data["exp-002"] = exp

    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="exp-002", helpful=False)
    handler.handle_feedback(cmd)

    updated = uow.experiences.get("exp-002")
    assert updated.confidence == round(0.5 + CONFIDENCE_UNHELPFUL_DELTA, 3)


def test_feedback_recorded_event_published():
    uow = InMemoryUnitOfWork()
    exp = _make_fake_exp("exp-003", confidence=0.5)
    uow.experiences._data["exp-003"] = exp

    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="exp-003", helpful=True)
    handler.handle_feedback(cmd)

    events = uow.get_events()
    feedback_events = [e for e in events if isinstance(e, FeedbackRecorded)]
    assert len(feedback_events) == 1
    assert feedback_events[0].experience_id == "exp-003"
    assert feedback_events[0].helpful is True


def test_feedback_for_nonexistent_experience_returns_false():
    uow = InMemoryUnitOfWork()
    handler = FeedbackHandler(lambda: uow)
    cmd = RecordFeedbackCommand(experience_id="not-exist", helpful=True)
    result = handler.handle_feedback(cmd)
    assert result is False
```

**Step 3：运行测试，确认失败**

```bash
python3 -m pytest tests/integration/test_feedback_handler.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 4：创建 `src/application/handlers/feedback_handler.py`**

```python
from __future__ import annotations
from typing import Callable
from ..commands import RecordFeedbackCommand
from ..unit_of_work import AbstractUnitOfWork
from ...domain.feedback import compute_new_confidence
from ...domain.events import FeedbackRecorded
from ...domain.constants import CONFIDENCE_MIN, AUTO_ARCHIVE_ADOPTION_THRESHOLD


class FeedbackHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    def handle_feedback(self, cmd: RecordFeedbackCommand):
        with self._uow_factory() as uow:
            exp = uow.experiences.get(cmd.experience_id)
            if exp is None:
                return False

            old_confidence = exp.confidence
            new_confidence = compute_new_confidence(old_confidence, cmd.helpful)
            exp.confidence = new_confidence

            if new_confidence <= AUTO_ARCHIVE_ADOPTION_THRESHOLD:
                exp.status = "ARCHIVED"
                exp.reject_reason = "Low adoption rate, auto archived"

            uow.experiences.update(exp)
            uow.collect_event(FeedbackRecorded(
                experience_id=cmd.experience_id,
                helpful=cmd.helpful,
                session_id=cmd.session_id,
                old_confidence=old_confidence,
                new_confidence=new_confidence,
            ))
        return True
```

**Step 5：运行集成测试**

```bash
python3 -m pytest tests/integration/test_feedback_handler.py -v
```
Expected: 4 passed

**Step 6：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 7：Commit**

```bash
git add src/application/handlers/feedback_handler.py tests/integration/test_feedback_handler.py
git commit -m "feat: implement FeedbackHandler with UoW integration test"
```

---

### Task 3.2：实现 ExperienceHandler（创建经验）

**Files:**
- Create: `src/application/handlers/experience_handler.py`
- Test: `tests/integration/test_experience_handler.py`（新增）

**Step 1：写失败集成测试**

文件：`tests/integration/test_experience_handler.py`

```python
import pytest
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.handlers.experience_handler import ExperienceHandler
from src.application.commands import CreateExperienceCommand, ActivateExperienceCommand, ArchiveExperienceCommand
from src.domain.events import ExperienceCreated, ExperienceActivated, ExperienceArchived
from src.domain.constants import QUALITY_SCORE_AUTO_ACTIVATE


class FakeLLM:
    def generate_title(self, text: str) -> str:
        return "测试标题"


class FakeMetadata:
    def infer(self, text: str) -> dict:
        return {"tech_stack": ["python"], "scene": ["测试"], "level": "L2"}


def _make_handler(uow):
    return ExperienceHandler(
        uow_factory=lambda: uow,
        llm=FakeLLM(),
        metadata_inferrer=FakeMetadata(),
    )


def test_create_high_quality_experience_auto_activates():
    uow = InMemoryUnitOfWork()
    handler = _make_handler(uow)
    cmd = CreateExperienceCommand(
        task_output="问题描述\n" + "解决方案" * 20 + "\n" + "关键决策" * 10,
    )
    exp = handler.handle_create(cmd)

    assert exp is not None
    assert exp.status == "ACTIVE"

    events = uow.get_events()
    created_events = [e for e in events if isinstance(e, ExperienceCreated)]
    activated_events = [e for e in events if isinstance(e, ExperienceActivated)]
    assert len(created_events) == 1
    assert len(activated_events) == 1
    assert activated_events[0].triggered_by == "auto"


def test_create_low_quality_experience_stays_pending():
    uow = InMemoryUnitOfWork()
    handler = _make_handler(uow)
    cmd = CreateExperienceCommand(
        task_output="短描述\n短方案ab\n短决策ab",
    )
    exp = handler.handle_create(cmd)

    assert exp is not None
    assert exp.status == "PENDING"

    events = uow.get_events()
    activated_events = [e for e in events if isinstance(e, ExperienceActivated)]
    assert len(activated_events) == 0


def test_activate_experience_manually():
    uow = InMemoryUnitOfWork()

    class FakeExp:
        id = "exp-100"
        status = "PENDING"
        confidence = 0.5
        reject_reason = None

    uow.experiences._data["exp-100"] = FakeExp()
    handler = _make_handler(uow)
    from src.application.commands import ActivateExperienceCommand
    handler.handle_activate(ActivateExperienceCommand(experience_id="exp-100"))

    exp = uow.experiences.get("exp-100")
    assert exp.status == "ACTIVE"

    events = uow.get_events()
    activated_events = [e for e in events if isinstance(e, ExperienceActivated)]
    assert len(activated_events) == 1
    assert activated_events[0].triggered_by == "manual"


def test_archive_experience():
    uow = InMemoryUnitOfWork()

    class FakeExp:
        id = "exp-200"
        status = "ACTIVE"
        confidence = 0.5
        reject_reason = None

    uow.experiences._data["exp-200"] = FakeExp()
    handler = _make_handler(uow)
    from src.application.commands import ArchiveExperienceCommand
    handler.handle_archive(ArchiveExperienceCommand(experience_id="exp-200", reason="手动归档"))

    exp = uow.experiences.get("exp-200")
    assert exp.status == "ARCHIVED"

    events = uow.get_events()
    archived_events = [e for e in events if isinstance(e, ExperienceArchived)]
    assert len(archived_events) == 1
    assert archived_events[0].reason == "手动归档"
```

**Step 2：运行测试，确认失败**

```bash
python3 -m pytest tests/integration/test_experience_handler.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3：创建 `src/application/handlers/experience_handler.py`**

```python
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Callable
from ..commands import (
    CreateExperienceCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
)
from ..unit_of_work import AbstractUnitOfWork
from ...domain.events import ExperienceCreated, ExperienceActivated, ExperienceArchived, EmbeddingRequested
from ...domain.constants import (
    QUALITY_SCORE_AUTO_ACTIVATE,
    QUALITY_SCORE_MIN_ACCEPT,
    CONFIDENCE_AUTO_ACTIVATE_INITIAL,
)
from ...domain.quality import compute_quality_score
from ...domain.metadata import infer_tech_stack, infer_scene, infer_type, infer_level


class ExperienceHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], llm, metadata_inferrer):
        self._uow_factory = uow_factory
        self._llm = llm
        self._metadata = metadata_inferrer

    def handle_create(self, cmd: CreateExperienceCommand):
        parts = cmd.task_output.split("\n", 2)
        task_desc = parts[0] if len(parts) > 0 else cmd.task_output
        solution = parts[1] if len(parts) > 1 else ""
        key_decisions = parts[2] if len(parts) > 2 else ""

        meta = self._metadata.infer(cmd.task_output)
        tech_stack = meta.get("tech_stack", [])
        scene = meta.get("scene", [])
        level = meta.get("level", "L2")
        title = self._llm.generate_title(cmd.task_output)

        quality_score = compute_quality_score(
            key_decisions=key_decisions,
            solution_summary=solution,
            related_files=[],
            tech_stack=tech_stack,
        )

        if quality_score < QUALITY_SCORE_MIN_ACCEPT:
            raise ValueError(f"质量评分过低（{quality_score}/100），提取已拒绝。")

        exp_id = str(uuid.uuid4())
        status = "PENDING"
        confidence = 0.6

        class _Exp:
            pass

        exp = _Exp()
        exp.id = exp_id
        exp.title = title
        exp.problem = task_desc
        exp.solution = solution
        exp.key_decisions = key_decisions
        exp.status = status
        exp.confidence = confidence
        exp.tech_stack = tech_stack
        exp.scene = scene
        exp.level = level
        exp.source = "agent"
        exp.project_id = cmd.project_id
        exp.created_at = datetime.utcnow().isoformat()
        exp.tags = []
        exp.related_files = []
        exp.last_hit_at = None
        exp.reject_reason = None

        events = [
            ExperienceCreated(
                experience_id=exp_id,
                title=title,
                content=cmd.task_output,
                tech_stack=tech_stack,
                scene=scene,
                level=level,
                quality_score=quality_score,
                project_id=cmd.project_id,
            ),
            EmbeddingRequested(experience_id=exp_id, text=f"{title}\n{task_desc}\n{key_decisions}"),
        ]

        if quality_score >= QUALITY_SCORE_AUTO_ACTIVATE:
            exp.status = "ACTIVE"
            exp.confidence = CONFIDENCE_AUTO_ACTIVATE_INITIAL
            events.append(ExperienceActivated(experience_id=exp_id, triggered_by="auto"))

        with self._uow_factory() as uow:
            uow.experiences.add(exp)
            for event in events:
                uow.collect_event(event)

        return exp

    def handle_activate(self, cmd: ActivateExperienceCommand):
        with self._uow_factory() as uow:
            exp = uow.experiences.get(cmd.experience_id)
            if exp is None:
                return False
            exp.status = "ACTIVE"
            uow.experiences.update(exp)
            uow.collect_event(ExperienceActivated(
                experience_id=cmd.experience_id,
                triggered_by="manual",
            ))
        return True

    def handle_archive(self, cmd: ArchiveExperienceCommand):
        with self._uow_factory() as uow:
            exp = uow.experiences.get(cmd.experience_id)
            if exp is None:
                return False
            exp.status = "ARCHIVED"
            exp.reject_reason = cmd.reason
            uow.experiences.update(exp)
            uow.collect_event(ExperienceArchived(
                experience_id=cmd.experience_id,
                reason=cmd.reason,
            ))
        return True
```

**Step 4：运行集成测试**

```bash
python3 -m pytest tests/integration/test_experience_handler.py -v
```
Expected: 4 passed

**Step 5：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 6：Commit**

```bash
git add src/application/handlers/experience_handler.py tests/integration/test_experience_handler.py
git commit -m "feat: implement ExperienceHandler with create/activate/archive"
```

---

### Task 3.3：验证回滚场景（存储失败时主数据不污染）

**Files:**
- Modify: `tests/helpers/fake_uow.py`
- Test: `tests/integration/test_rollback.py`（新增）

**Step 1：在 `InMemoryUnitOfWork` 中添加 rollback 支持**

在 `tests/helpers/fake_uow.py` 的 `InMemoryUnitOfWork.__exit__` 中，异常时不设置 `committed`（已经是这样），但还需要确保 `experiences` 数据不被写入：修改为写时先暂存。

**更新 `tests/helpers/fake_uow.py`**（在 `InMemoryExperienceStore` 中添加事务支持）：

```python
class InMemoryExperienceStore(AbstractExperienceStore):
    def __init__(self):
        self._committed: dict = {}
        self._pending: dict = {}

    def add(self, exp) -> None:
        self._pending[exp.id] = exp

    def get(self, exp_id: str):
        return self._pending.get(exp_id) or self._committed.get(exp_id)

    def update(self, exp) -> None:
        self._pending[exp.id] = exp

    def list_by_status(self, status: str) -> list:
        merged = {**self._committed, **self._pending}
        return [e for e in merged.values() if e.status == status]

    def _commit(self):
        self._committed.update(self._pending)
        self._pending = {}

    def _rollback(self):
        self._pending = {}
```

同时更新 `InMemoryUnitOfWork.__exit__`：
```python
def __exit__(self, exc_type, exc_val, exc_tb) -> None:
    if exc_type is None:
        self.experiences._commit()
        self.committed = True
    else:
        self.experiences._rollback()
```

**Step 2：写回滚测试**

文件：`tests/integration/test_rollback.py`

```python
from tests.helpers.fake_uow import InMemoryUnitOfWork


def test_experience_not_persisted_when_exception_raised():
    uow = InMemoryUnitOfWork()

    try:
        with uow:
            class FakeExp:
                id = "exp-rollback"
                status = "ACTIVE"

            uow.experiences.add(FakeExp())
            raise RuntimeError("模拟存储失败")
    except RuntimeError:
        pass

    assert uow.experiences.get("exp-rollback") is None
    assert uow.committed is False


def test_experience_persisted_on_success():
    uow = InMemoryUnitOfWork()

    with uow:
        class FakeExp:
            id = "exp-success"
            status = "ACTIVE"

        uow.experiences.add(FakeExp())

    assert uow.experiences.get("exp-success") is not None
    assert uow.committed is True
```

**Step 3：运行回滚测试**

```bash
python3 -m pytest tests/integration/test_rollback.py -v
```
Expected: 2 passed

**Step 4：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 5：Commit**

```bash
git add tests/helpers/fake_uow.py tests/integration/test_rollback.py
git commit -m "test: add rollback scenario tests for InMemoryUoW"
```

---

## Phase 4：建立 Command Bus

**目标**：实现所有 Handler，接口层（CLI/REST）改为调用 `CommandBus.dispatch()`。

### Task 4.1：创建 container.py（依赖组装）

**Files:**
- Create: `src/container.py`

**Step 1：创建 `src/container.py`**

```python
from __future__ import annotations
from .application.command_bus import CommandBus
from .application.commands import (
    CreateExperienceCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
    RecordFeedbackCommand,
    AnalyzeQualityCommand,
)
from .application.handlers.experience_handler import ExperienceHandler
from .application.handlers.feedback_handler import FeedbackHandler
from .infrastructure.unit_of_work import UnitOfWork


class _SimpleLLM:
    def generate_title(self, text: str) -> str:
        import os
        try:
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("XP_LLM_API_KEY")
            if not api_key:
                return text[:60]
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=os.getenv("XP_LLM_API_BASE"))
            resp = client.chat.completions.create(
                model=os.getenv("XP_LLM_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": f"用10-15个字总结以下任务，只输出标题，不加标点：\n{text}"}],
                max_tokens=30,
                temperature=0,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return text[:60]


class _MetadataInferrer:
    def infer(self, text: str) -> dict:
        from .domain.metadata import infer_tech_stack, infer_scene, infer_level
        return {
            "tech_stack": infer_tech_stack(text),
            "scene": infer_scene(text),
            "level": infer_level(text, text).value,
        }


def build_command_bus() -> CommandBus:
    llm = _SimpleLLM()
    metadata = _MetadataInferrer()

    experience_handler = ExperienceHandler(
        uow_factory=UnitOfWork,
        llm=llm,
        metadata_inferrer=metadata,
    )
    feedback_handler = FeedbackHandler(uow_factory=UnitOfWork)

    bus = CommandBus()
    bus.register(CreateExperienceCommand, experience_handler.handle_create)
    bus.register(ActivateExperienceCommand, experience_handler.handle_activate)
    bus.register(ArchiveExperienceCommand, experience_handler.handle_archive)
    bus.register(RecordFeedbackCommand, feedback_handler.handle_feedback)

    return bus
```

**Step 2：运行测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 3：Commit**

```bash
git add src/container.py
git commit -m "feat: add container.py for dependency assembly"
```

---

### Task 4.2：添加契约测试

**Files:**
- Create: `tests/contract/__init__.py`
- Create: `tests/contract/test_commands.py`
- Create: `tests/contract/test_events.py`

**Step 1：创建 `tests/contract/__init__.py`（空文件）**

**Step 2：创建 `tests/contract/test_commands.py`**

```python
from dataclasses import fields
from src.application.commands import (
    CreateExperienceCommand,
    SearchExperienceCommand,
    RecordFeedbackCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
)


def test_create_experience_command_required_fields():
    cmd = CreateExperienceCommand(task_output="test")
    assert cmd.task_output == "test"
    assert cmd.project_id is None
    assert cmd.session_id is None


def test_search_experience_command_defaults():
    cmd = SearchExperienceCommand(query="test")
    assert cmd.limit == 10
    assert cmd.tech_stack == []


def test_record_feedback_command_fields():
    cmd = RecordFeedbackCommand(experience_id="exp-001", helpful=True)
    assert cmd.experience_id == "exp-001"
    assert cmd.helpful is True
    assert cmd.session_id is None


def test_activate_command_has_experience_id():
    cmd = ActivateExperienceCommand(experience_id="exp-001")
    assert cmd.experience_id == "exp-001"


def test_archive_command_has_reason():
    cmd = ArchiveExperienceCommand(experience_id="exp-001", reason="outdated")
    assert cmd.reason == "outdated"
```

**Step 3：创建 `tests/contract/test_events.py`**

```python
from src.domain.events import (
    ExperienceCreated,
    ExperienceActivated,
    ExperienceArchived,
    FeedbackRecorded,
    EmbeddingRequested,
    DuplicateDetected,
    ExperienceHit,
)


def test_experience_created_is_frozen():
    event = ExperienceCreated(
        experience_id="exp-001",
        title="test",
        content="content",
        tech_stack=["python"],
        scene=["测试"],
        level="L2",
        quality_score=85,
        project_id=None,
    )
    try:
        event.title = "modified"
        assert False, "Should raise FrozenInstanceError"
    except Exception:
        pass


def test_experience_activated_triggered_by_values():
    auto = ExperienceActivated(experience_id="exp-001", triggered_by="auto")
    manual = ExperienceActivated(experience_id="exp-001", triggered_by="manual")
    assert auto.triggered_by == "auto"
    assert manual.triggered_by == "manual"


def test_feedback_recorded_confidence_range():
    event = FeedbackRecorded(
        experience_id="exp-001",
        helpful=True,
        session_id=None,
        old_confidence=0.5,
        new_confidence=0.6,
    )
    assert 0.0 <= event.new_confidence <= 1.0


def test_duplicate_detected_has_similarity():
    event = DuplicateDetected(
        new_experience_id="new-001",
        existing_experience_id="old-001",
        similarity=0.92,
    )
    assert event.similarity == 0.92
```

**Step 4：运行契约测试**

```bash
python3 -m pytest tests/contract/ -v
```
Expected: 全部通过

**Step 5：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 6：Commit**

```bash
git add tests/contract/
git commit -m "test: add contract tests for commands and events"
```

---

### Task 4.3：CommandBus 单元测试

**Files:**
- Create: `tests/unit/test_command_bus.py`

**Step 1：写测试**

```python
import pytest
from src.application.command_bus import CommandBus, UnregisteredCommandError
from src.application.commands import RecordFeedbackCommand


def test_dispatch_registered_command():
    bus = CommandBus()
    bus.register(RecordFeedbackCommand, lambda cmd: "ok")
    result = bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
    assert result == "ok"


def test_dispatch_unregistered_command_raises():
    bus = CommandBus()
    with pytest.raises(UnregisteredCommandError):
        bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))


def test_register_overwrites_previous_handler():
    bus = CommandBus()
    bus.register(RecordFeedbackCommand, lambda cmd: "first")
    bus.register(RecordFeedbackCommand, lambda cmd: "second")
    result = bus.dispatch(RecordFeedbackCommand(experience_id="x", helpful=True))
    assert result == "second"
```

**Step 2：运行测试**

```bash
python3 -m pytest tests/unit/test_command_bus.py -v
```
Expected: 3 passed

**Step 3：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 4：Commit**

```bash
git add tests/unit/test_command_bus.py
git commit -m "test: add CommandBus unit tests"
```

---

## Phase 5：删除上帝类

> **警告**：Phase 5 只在 Phase 1-4 全部完成、且四层测试全绿后执行。

### Task 5.1：验证当前无 KnowledgeService 依赖的路径

**Step 1：检查还有哪些地方 import KnowledgeService**

```bash
rg "KnowledgeService" src/ --include="*.py" -l
```

**Step 2：对每个文件，将 `KnowledgeService` 调用替换为 `CommandBus.dispatch()`**

以 `src/interfaces/rest_api.py` 为例：

将：
```python
from ..knowledge import KnowledgeService
svc = KnowledgeService(ExperienceStore(), MetricsStore())
svc.record_feedback(...)
```

改为：
```python
from ..container import build_command_bus
from ..application.commands import RecordFeedbackCommand
bus = build_command_bus()
bus.dispatch(RecordFeedbackCommand(experience_id=..., helpful=...))
```

**Step 3：运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过

**Step 4：删除 `src/knowledge.py`**

```bash
git rm src/knowledge.py
```

**Step 5：再次运行全量测试**

```bash
python3 -m pytest tests/ -q -k "not server and not postgres"
```
Expected: 全部通过，无 `KnowledgeService` 引用

**Step 6：验证 domain 层无 I/O**

```bash
rg "open\(|sqlite|requests\." src/domain/ --include="*.py"
```
Expected: 空输出（无匹配）

**Step 7：Commit**

```bash
git add -A
git commit -m "refactor: delete KnowledgeService - Phase 5 complete"
```

---

## 验收检查清单

完成所有 Phase 后，逐项检查：

```bash
# 1. KnowledgeService 已删除
rg "KnowledgeService" src/ --include="*.py"
# Expected: 空

# 2. domain 层无 I/O
rg "open\(|sqlite|requests\." src/domain/ --include="*.py"
# Expected: 空

# 3. 全量单元测试
python3 -m pytest tests/unit/ -q
# Expected: 全部通过，覆盖率 >= 90%

# 4. 全量集成测试
python3 -m pytest tests/integration/ -q
# Expected: 全部通过

# 5. 契约测试
python3 -m pytest tests/contract/ -q
# Expected: 全部通过

# 6. 特征测试（防回归）
python3 -m pytest tests/characterization/ -q
# Expected: 与重构前输出一致

# 7. 全量测试
python3 -m pytest tests/ -q -k "not server and not postgres"
# Expected: 全部通过
```
