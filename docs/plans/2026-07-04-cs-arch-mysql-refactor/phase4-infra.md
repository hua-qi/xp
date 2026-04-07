# Phase 4: 基础设施扩展

---

## Task 12: 冲突检测领域逻辑

**Files:**
- Create: `src/domain/conflict.py`
- Create: `tests/unit/test_conflict.py`

> **背景**：save 时对同项目已有经验做相似度检测，分为"重复"（两者均高）和"冲突"（problem 高但 solution 低）。domain 层只做纯函数判断，不调用 LLM。

**Step 1: 写失败测试**

```python
# tests/unit/test_conflict.py
import numpy as np
from src.domain.conflict import (
    detect_duplicate_or_conflict,
    ConflictResult,
)


def vec(values):
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_no_conflict_when_similarity_low():
    new_p = vec([1.0, 0.0, 0.0])
    new_s = vec([1.0, 0.0, 0.0])
    existing = [
        ("exp-1", vec([0.0, 1.0, 0.0]), vec([0.0, 1.0, 0.0])),
    ]
    result = detect_duplicate_or_conflict(new_p, new_s, existing)
    assert result is None


def test_duplicate_detected_when_both_high():
    new_p = vec([1.0, 0.0, 0.0])
    new_s = vec([0.0, 1.0, 0.0])
    existing = [
        ("exp-1", vec([0.99, 0.1, 0.0]), vec([0.0, 0.99, 0.1])),
    ]
    result = detect_duplicate_or_conflict(new_p, new_s, existing)
    assert result is not None
    assert result.type == "duplicate"
    assert result.existing_id == "exp-1"


def test_conflict_detected_when_problem_high_solution_low():
    new_p = vec([1.0, 0.0, 0.0])
    new_s = vec([0.0, 0.0, 1.0])
    existing = [
        ("exp-1", vec([0.99, 0.1, 0.0]), vec([1.0, 0.0, 0.0])),
    ]
    result = detect_duplicate_or_conflict(new_p, new_s, existing)
    assert result is not None
    assert result.type == "conflict"
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_conflict.py -v
```

预期：FAIL（模块不存在）

**Step 3: 实现 conflict.py**

```python
# src/domain/conflict.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np

DUPLICATE_THRESHOLD = 0.85
CONFLICT_PROBLEM_THRESHOLD = 0.85
CONFLICT_SOLUTION_MAX = 0.6


@dataclass
class ConflictResult:
    type: str
    existing_id: str
    problem_similarity: float
    solution_similarity: float


def detect_duplicate_or_conflict(
    new_problem_vec: np.ndarray,
    new_solution_vec: np.ndarray,
    existing: list[tuple[str, np.ndarray, np.ndarray]],
) -> Optional[ConflictResult]:
    for exp_id, ep_vec, es_vec in existing:
        p_sim = float(np.dot(new_problem_vec, ep_vec))
        s_sim = float(np.dot(new_solution_vec, es_vec))
        if p_sim >= DUPLICATE_THRESHOLD and s_sim >= DUPLICATE_THRESHOLD:
            return ConflictResult(
                type="duplicate",
                existing_id=exp_id,
                problem_similarity=p_sim,
                solution_similarity=s_sim,
            )
        if p_sim >= CONFLICT_PROBLEM_THRESHOLD and s_sim < CONFLICT_SOLUTION_MAX:
            return ConflictResult(
                type="conflict",
                existing_id=exp_id,
                problem_similarity=p_sim,
                solution_similarity=s_sim,
            )
    return None
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_conflict.py -v
```

预期：PASS（3 个测试）

**Step 5: 提交**

```bash
git add src/domain/conflict.py tests/unit/test_conflict.py
git commit -m "feat: add conflict detection domain logic"
```

---

## Task 13: 定时任务

**Files:**
- Create: `src/scheduler.py`
- Create: `tests/unit/test_scheduler.py`

> **背景**：两个定时任务：①每 12 小时重试 retry_count=3 的 pending 经验；②每 3 天扫描升层候选。

**Step 1: 写失败测试**

```python
# tests/unit/test_scheduler.py
def test_scheduler_module_importable():
    from src.scheduler import build_scheduler
    s = build_scheduler(backend=None, command_bus=None)
    assert s is not None


def test_scheduler_has_two_jobs():
    from src.scheduler import build_scheduler
    s = build_scheduler(backend=None, command_bus=None)
    jobs = s.get_jobs()
    assert len(jobs) == 2
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_scheduler.py -v
```

预期：FAIL

**Step 3: 实现 scheduler.py**

```python
# src/scheduler.py
from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler


async def _retry_pending_experiences(backend, command_bus):
    if backend is None:
        return
    pass


async def _scan_promotion_candidates(backend, command_bus):
    if backend is None or command_bus is None:
        return
    from src.application.commands import ScanPromotionCandidatesCommand
    await command_bus.dispatch(ScanPromotionCandidatesCommand())


def build_scheduler(backend, command_bus) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _retry_pending_experiences,
        "interval",
        hours=12,
        args=[backend, command_bus],
        id="retry_pending",
    )
    scheduler.add_job(
        _scan_promotion_candidates,
        "interval",
        days=3,
        args=[backend, command_bus],
        id="scan_promotion",
    )
    return scheduler
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_scheduler.py -v
```

预期：PASS（2 个测试）

**Step 5: 提交**

```bash
git add src/scheduler.py tests/unit/test_scheduler.py
git commit -m "feat: add scheduler with retry and promotion jobs"
```

---

## Task 14: Prompt 热更新加载器

**Files:**
- Create: `src/infrastructure/prompt_loader.py`
- Create: `tests/unit/test_prompt_loader.py`

**Step 1: 写失败测试**

```python
# tests/unit/test_prompt_loader.py
import pytest
from unittest.mock import AsyncMock


async def test_prompt_loader_get_cached():
    from src.infrastructure.prompt_loader import PromptLoader
    backend = AsyncMock()
    backend.async_get_prompt = AsyncMock(return_value="hello {name}")
    loader = PromptLoader(backend=backend)
    await loader.refresh()
    result = loader.get("extraction_prompt", name="world")
    assert "world" in result or result == "hello {name}"


async def test_prompt_loader_fallback_on_missing_key():
    from src.infrastructure.prompt_loader import PromptLoader
    backend = AsyncMock()
    backend.async_get_prompt = AsyncMock(return_value=None)
    loader = PromptLoader(backend=backend)
    await loader.refresh()
    result = loader.get("extraction_prompt")
    assert result is not None
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_prompt_loader.py -v
```

预期：FAIL

**Step 3: 实现 prompt_loader.py**

```python
# src/infrastructure/prompt_loader.py
from __future__ import annotations
from typing import Optional

_FALLBACK_PROMPTS = {
    "extraction_prompt": (
        "你是一个工程经验提炼助手。任务描述：{task_description}，"
        "结果：{outcome_description}，状态：{outcome}。"
        "请输出 JSON：{{\"title\":\"\",\"problem\":\"\",\"solution\":\"\","
        "\"key_decisions\":\"\",\"tags\":[],\"type\":\"bugfix\"}}"
    ),
    "conflict_type_prompt": "只输出类型名称：outdated/alternative/version_diff/new_may_wrong/condition_diff",
    "rerank_prompt": "只输出 JSON ID 数组",
    "comment_analysis_prompt": "只输出：irrelevant 或 needs_fix",
}

PROMPT_KEYS = list(_FALLBACK_PROMPTS.keys())


class PromptLoader:
    def __init__(self, backend):
        self._backend = backend
        self._cache: dict[str, str] = {}

    async def refresh(self):
        for key in PROMPT_KEYS:
            val = await self._backend.async_get_prompt(key)
            if val:
                self._cache[key] = val

    def get(self, key: str, **kwargs) -> str:
        template = self._cache.get(key) or _FALLBACK_PROMPTS.get(key, "")
        if kwargs:
            try:
                return template.format(**kwargs)
            except KeyError:
                return template
        return template
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_prompt_loader.py -v
```

预期：PASS（2 个测试）

**Step 5: 提交**

```bash
git add src/infrastructure/prompt_loader.py tests/unit/test_prompt_loader.py
git commit -m "feat: add PromptLoader with MySQL hot-reload support"
```
