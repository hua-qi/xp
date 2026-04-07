# Phase 3: Application 层

---

## Task 08: Command 定义更新

**Files:**
- Modify: `src/application/commands.py`
- Create: `tests/contract/test_commands_cs.py`

**Step 1: 写失败测试（契约测试）**

```python
# tests/contract/test_commands_cs.py
import dataclasses
from src.application.commands import SaveCommand, SearchV2Command, FeedbackV2Command


def test_save_command_has_minimal_fields():
    fields = {f.name for f in dataclasses.fields(SaveCommand)}
    assert "task_description" in fields
    assert "outcome_description" in fields
    assert "outcome" in fields
    assert "project_id" in fields


def test_save_command_no_longer_requires_solution():
    cmd = SaveCommand(
        task_description="task",
        outcome_description="outcome",
        outcome="success",
        project_id="p-1",
    )
    assert cmd.task_description == "task"


def test_search_v2_command_fields():
    fields = {f.name for f in dataclasses.fields(SearchV2Command)}
    assert "task_description" in fields
    assert "project_id" in fields


def test_feedback_v2_command_has_adopted_rejected():
    fields = {f.name for f in dataclasses.fields(FeedbackV2Command)}
    assert "adopted_ids" in fields
    assert "rejected_ids" in fields
    assert "comment" in fields
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/contract/test_commands_cs.py -v
```

预期：FAIL（`SaveCommand` 字段不同；`FeedbackV2Command` 字段名不同）

**Step 3: 更新 commands.py**

将 `SaveCommand` 替换为：

```python
@dataclass
class SaveCommand:
    task_description: str
    outcome_description: str
    outcome: str
    project_id: str
    session_id: str | None = None
```

将 `FeedbackV2Command` 替换为：

```python
@dataclass
class FeedbackV2Command:
    session_id: str
    adopted_ids: list[str] = field(default_factory=list)
    rejected_ids: list[str] = field(default_factory=list)
    comment: str | None = None
```

`SearchV2Command` 简化为（删除 `project_manifest` 字段）：

```python
@dataclass
class SearchV2Command:
    task_description: str
    project_id: str
    session_id: str | None = None
    top_k: int = 3
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/contract/test_commands_cs.py -v
```

预期：PASS（4 个测试）

**Step 5: 运行全量测试，修复因 Command 字段变更导致的现有测试报错**

```bash
python -m pytest tests/ -q -k "not postgres and not server"
```

预期：找出并修复所有因 `SaveCommand` / `FeedbackV2Command` 字段变更导致的失败。

> 提示：主要影响 `tests/unit/` 和 `tests/integration/` 中使用旧字段构造 Command 的地方，逐一修改为新字段。

**Step 6: 提交**

```bash
git add src/application/commands.py tests/contract/test_commands_cs.py
git commit -m "feat: update SaveCommand/FeedbackV2Command/SearchV2Command for CS arch"
```

---

## Task 09: SaveHandler 重写

**Files:**
- Modify: `src/application/handlers/save_handler.py`
- Create: `tests/integration/test_save_handler_cs.py`

> **背景**：新 SaveHandler 流程：LLM 提炼结构化字段 → 冲突/重复检测 → 质量评分 → 向量存储（B 组）→ 写 MySQL。
> 测试使用 `InMemoryUnitOfWork` + 假 LLMClient，不需要真实 DB。

**Step 1: 写集成测试（使用 InMemoryUoW + mock LLM）**

```python
# tests/integration/test_save_handler_cs.py
import pytest
from unittest.mock import AsyncMock
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.commands import SaveCommand
from src.application.handlers.save_handler import SaveHandler


def make_llm_success(content: str):
    llm = AsyncMock()
    llm.call = AsyncMock(return_value=content)
    return llm


VALID_LLM_JSON = '''{
  "title": "MySQL 连接池超时处理",
  "problem": "生产环境 MySQL 连接池在高并发下频繁超时，影响接口响应",
  "solution": "调整连接池 max_size 和 pool_timeout 参数，增加重试逻辑",
  "key_decisions": "pool_timeout 设为 10s，max_retries=3，指数退避",
  "tags": ["MySQL", "连接池", "高并发"],
  "type": "bugfix"
}'''


@pytest.mark.asyncio
async def test_save_handler_creates_experience_on_llm_success():
    uow = InMemoryUnitOfWork()
    llm = make_llm_success(VALID_LLM_JSON)
    handler = SaveHandler(uow_factory=lambda: uow, llm=llm)
    cmd = SaveCommand(
        task_description="修复 MySQL 连接超时",
        outcome_description="调整连接池参数后超时率降至 0.1%",
        outcome="success",
        project_id="proj-1",
    )
    result = await handler.handle(cmd)
    assert result["status"] == "saved"
    assert result["experience_id"] is not None


@pytest.mark.asyncio
async def test_save_handler_marks_pending_on_llm_failure():
    uow = InMemoryUnitOfWork()
    llm = make_llm_success(None)
    handler = SaveHandler(uow_factory=lambda: uow, llm=llm)
    cmd = SaveCommand(
        task_description="test",
        outcome_description="test",
        outcome="success",
        project_id="proj-1",
    )
    result = await handler.handle(cmd)
    assert result["status"] == "pending_retry"
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/integration/test_save_handler_cs.py -v
```

预期：FAIL（Handler 接口不兼容）

**Step 3: 重写 save_handler.py**

```python
# src/application/handlers/save_handler.py
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ...models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceMetadata, ExperienceStatus, ExperienceSource,
)
from ...domain.quality import compute_save_quality_score
from ..commands import SaveCommand
from ..unit_of_work import AbstractUnitOfWork


EXTRACTION_PROMPT_TEMPLATE = """你是一个工程经验提炼助手。根据以下任务信息，提炼出结构化的工程经验。

## 输入
任务描述：{task_description}
任务结果：{outcome_description}
结果状态：{outcome}

## 输出要求
严格按照以下 JSON 格式输出，不要输出其他内容：
{{
  "title": "10-20字的经验标题，概括核心问题和解法",
  "problem": "清晰描述问题场景和背景，50字以上",
  "solution": "具体的解决方案和步骤，50字以上",
  "key_decisions": "关键决策点和踩坑点，30字以上",
  "tags": ["技术栈标签", "最多5个"],
  "type": "bugfix 或 feature 或 pattern 三选一"
}}"""


class SaveHandler:
    def __init__(self, uow_factory, llm):
        self._uow_factory = uow_factory
        self._llm = llm

    async def handle(self, cmd: SaveCommand) -> dict[str, Any]:
        extracted = await self._extract(cmd)
        if extracted is None:
            return await self._save_pending(cmd)
        return await self._save_active(cmd, extracted)

    async def _extract(self, cmd: SaveCommand) -> Optional[dict]:
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            task_description=cmd.task_description,
            outcome_description=cmd.outcome_description,
            outcome=cmd.outcome,
        )
        raw = await self._llm.call(prompt)
        if not raw:
            return None
        try:
            data = json.loads(raw.strip())
            for key in ("title", "problem", "solution", "key_decisions", "tags", "type"):
                if key not in data:
                    return None
            return data
        except (json.JSONDecodeError, KeyError):
            return None

    async def _save_pending(self, cmd: SaveCommand) -> dict[str, Any]:
        exp_id = str(uuid.uuid4())
        exp = Experience(
            id=exp_id,
            type=ExperienceType.PATTERN,
            level=ExperienceLevel.PROJECT,
            title="(待 LLM 提炼)",
            tags=[],
            problem=cmd.task_description,
            solution=cmd.outcome_description,
            key_decisions="",
            confidence=0.5,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.AGENT,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=ExperienceMetadata(),
            project=cmd.project_id,
            retry_count=3,
            raw_input={
                "task_description": cmd.task_description,
                "outcome_description": cmd.outcome_description,
                "outcome": cmd.outcome,
            },
        )
        async with self._uow_factory() as uow:
            await uow.experiences.aadd(exp)
        return {"status": "pending_retry", "experience_id": exp_id}

    async def _save_active(self, cmd: SaveCommand, extracted: dict) -> dict[str, Any]:
        exp_id = str(uuid.uuid4())
        type_map = {"bugfix": ExperienceType.BUGFIX, "feature": ExperienceType.FEATURE}
        exp_type = type_map.get(extracted["type"], ExperienceType.PATTERN)
        exp = Experience(
            id=exp_id,
            type=exp_type,
            level=ExperienceLevel.PROJECT,
            title=extracted["title"],
            tags=extracted.get("tags", []),
            problem=extracted["problem"],
            solution=extracted["solution"],
            key_decisions=extracted.get("key_decisions", ""),
            confidence=0.6,
            status=ExperienceStatus.ACTIVE,
            source=ExperienceSource.AGENT,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=ExperienceMetadata(),
            project=cmd.project_id,
        )
        quality = compute_save_quality_score(exp)
        if quality < 80:
            exp.status = ExperienceStatus.PENDING
        async with self._uow_factory() as uow:
            await uow.experiences.aadd(exp)
        return {"status": "saved", "experience_id": exp_id, "quality": quality}
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/integration/test_save_handler_cs.py -v
```

预期：PASS（2 个测试）

**Step 5: 提交**

```bash
git add src/application/handlers/save_handler.py tests/integration/test_save_handler_cs.py
git commit -m "feat: rewrite SaveHandler for CS arch (LLM extraction)"
```

---

## Task 10: SearchV2Handler 重写

**Files:**
- Modify: `src/application/handlers/search_v2_handler.py`
- Create: `tests/integration/test_search_v2_handler_cs.py`

> **背景**：新 SearchV2Handler 按 `project_id hash % 2` 决定 A/B 组，A 组走全文搜索 + LLM rerank，B 组走向量余弦相似度。

**Step 1: 写集成测试**

```python
# tests/integration/test_search_v2_handler_cs.py
import pytest
import numpy as np
from unittest.mock import AsyncMock, patch
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.commands import SearchV2Command
from src.application.handlers.search_v2_handler import SearchV2Handler


def make_fake_backend(experiences=None, vectors=None):
    backend = AsyncMock()
    backend.async_get_ab_group = AsyncMock(return_value="B")
    backend.async_get_experiences_by_project = AsyncMock(return_value=experiences or [])
    backend.async_get_vectors_by_project = AsyncMock(
        return_value=(
            [e.id for e in (experiences or [])],
            np.array([[1.0, 0.0]] * len(experiences or []), dtype=np.float32),
        )
    )
    backend.async_record_session = AsyncMock()
    return backend


@pytest.mark.asyncio
async def test_search_v2_returns_session_id():
    backend = make_fake_backend()
    llm = AsyncMock()
    handler = SearchV2Handler(backend=backend, llm=llm, embedding_provider=AsyncMock())
    cmd = SearchV2Command(task_description="MySQL 超时", project_id="proj-1")
    result = await handler.handle(cmd)
    assert "session_id" in result
    assert isinstance(result["experiences"], list)


@pytest.mark.asyncio
async def test_search_v2_b_group_uses_cosine_similarity(monkeypatch):
    import src.application.handlers.search_v2_handler as mod

    called = []

    async def fake_cosine(handler_self, task_desc, exp_ids, vecs):
        called.append("cosine")
        return []

    monkeypatch.setattr(mod.SearchV2Handler, "_b_group_search", fake_cosine)
    backend = make_fake_backend()
    llm = AsyncMock()
    handler = mod.SearchV2Handler(backend=backend, llm=llm, embedding_provider=AsyncMock())
    cmd = SearchV2Command(task_description="test", project_id="proj-1")
    await handler.handle(cmd)
    assert "cosine" in called
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/integration/test_search_v2_handler_cs.py -v
```

预期：FAIL

**Step 3: 重写 search_v2_handler.py**

```python
# src/application/handlers/search_v2_handler.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..commands import SearchV2Command


class SearchV2Handler:
    def __init__(self, backend, llm, embedding_provider):
        self._backend = backend
        self._llm = llm
        self._embed = embedding_provider

    async def handle(self, cmd: SearchV2Command) -> dict[str, Any]:
        ab_group = await self._backend.async_get_ab_group(cmd.project_id)
        session_id = str(uuid.uuid4())

        if ab_group == "A":
            results = await self._a_group_search(cmd)
        else:
            exp_ids, vecs = await self._backend.async_get_vectors_by_project(cmd.project_id)
            results = await self._b_group_search(cmd.task_description, exp_ids, vecs)

        await self._backend.async_record_session(
            _make_session(session_id, cmd.task_description, [r["id"] for r in results], ab_group)
        )
        return {"session_id": session_id, "experiences": results[:cmd.top_k]}

    async def _a_group_search(self, cmd: SearchV2Command) -> list[dict]:
        exps = await self._backend.async_fulltext_search(
            cmd.task_description, cmd.project_id, limit=20
        )
        if not exps:
            return []
        candidates = "\n".join(
            f"ID: {e.id}\n标题: {e.title}\n问题: {e.problem}\n方案: {e.solution}"
            for e in exps[:10]
        )
        prompt = (
            f"根据以下任务描述，从候选经验中选出最相关的至多3条。\n\n"
            f"## 任务\n{cmd.task_description}\n\n"
            f"## 候选经验\n{candidates}\n\n"
            f"只输出 JSON 数组，包含最相关的经验 ID，按相关度降序排列。"
        )
        raw = await self._llm.call(prompt)
        if not raw:
            return []
        import json
        try:
            ids = json.loads(raw.strip())
            id_map = {e.id: e for e in exps}
            return [
                {"id": eid, "title": id_map[eid].title, "problem": id_map[eid].problem}
                for eid in ids
                if eid in id_map
            ]
        except Exception:
            return []

    async def _b_group_search(
        self, task_description: str, exp_ids: list[str], vecs: np.ndarray
    ) -> list[dict]:
        if len(exp_ids) == 0 or vecs.size == 0:
            return []
        query_vec = np.array(
            self._embed.embed_text(task_description), dtype=np.float32
        )
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-9)
        scores = vecs @ query_vec
        top_indices = np.argsort(scores)[::-1]
        results = []
        for idx in top_indices:
            if float(scores[idx]) >= 0.5:
                results.append({"id": exp_ids[idx], "score": float(scores[idx])})
        return results[:3]


def _make_session(session_id: str, task_description: str, exp_ids: list[str], ab_group: str):
    from ...models import Session
    return Session(
        session_id=session_id,
        task_description=task_description,
        experience_ids_injected=exp_ids,
        iteration_count=1,
        had_error_correction=False,
        user_accepted=True,
        ab_test_group=ab_group,
        ab_test_result_shown=True,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/integration/test_search_v2_handler_cs.py -v
```

预期：PASS（2 个测试）

**Step 5: 提交**

```bash
git add src/application/handlers/search_v2_handler.py tests/integration/test_search_v2_handler_cs.py
git commit -m "feat: rewrite SearchV2Handler with A/B routing"
```

---

## Task 11: FeedbackV2Handler 重写

**Files:**
- Modify: `src/application/handlers/feedback_v2_handler.py`
- Create: `tests/integration/test_feedback_v2_handler_cs.py`

**Step 1: 写集成测试**

```python
# tests/integration/test_feedback_v2_handler_cs.py
import pytest
from unittest.mock import AsyncMock
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.application.commands import FeedbackV2Command
from src.application.handlers.feedback_v2_handler import FeedbackV2Handler
from src.models import Experience, ExperienceType, ExperienceLevel, ExperienceStatus, ExperienceSource, ExperienceMetadata
from datetime import datetime, timezone


def make_exp(exp_id: str) -> Experience:
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.PROJECT,
        title="test",
        tags=[],
        problem="test problem",
        solution="test solution",
        key_decisions="",
        confidence=0.6,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata=ExperienceMetadata(),
        project="proj-1",
    )


@pytest.mark.asyncio
async def test_feedback_adopted_increases_confidence():
    uow = InMemoryUnitOfWork()
    exp = make_exp("exp-1")
    uow.experiences._committed["exp-1"] = exp
    backend = AsyncMock()
    backend.async_update_experience_stats = AsyncMock()
    backend.async_update_experience = AsyncMock()
    llm = AsyncMock()
    llm.call = AsyncMock(return_value=None)
    handler = FeedbackV2Handler(uow_factory=lambda: uow, backend=backend, llm=llm)
    cmd = FeedbackV2Command(
        session_id="sess-1",
        adopted_ids=["exp-1"],
        rejected_ids=[],
    )
    await handler.handle(cmd)
    updated = uow.experiences.get("exp-1")
    assert updated.confidence > 0.6


@pytest.mark.asyncio
async def test_feedback_rejected_decreases_confidence():
    uow = InMemoryUnitOfWork()
    exp = make_exp("exp-2")
    uow.experiences._committed["exp-2"] = exp
    backend = AsyncMock()
    backend.async_update_experience_stats = AsyncMock()
    backend.async_update_experience = AsyncMock()
    llm = AsyncMock()
    llm.call = AsyncMock(return_value=None)
    handler = FeedbackV2Handler(uow_factory=lambda: uow, backend=backend, llm=llm)
    cmd = FeedbackV2Command(
        session_id="sess-1",
        adopted_ids=[],
        rejected_ids=["exp-2"],
    )
    await handler.handle(cmd)
    updated = uow.experiences.get("exp-2")
    assert updated.confidence < 0.6


@pytest.mark.asyncio
async def test_feedback_needs_fix_creates_correction_request():
    uow = InMemoryUnitOfWork()
    exp = make_exp("exp-3")
    uow.experiences._committed["exp-3"] = exp
    backend = AsyncMock()
    backend.async_update_experience_stats = AsyncMock()
    backend.async_update_experience = AsyncMock()
    backend.async_add_correction_request = AsyncMock()
    llm = AsyncMock()
    llm.call = AsyncMock(return_value="needs_fix")
    handler = FeedbackV2Handler(uow_factory=lambda: uow, backend=backend, llm=llm)
    cmd = FeedbackV2Command(
        session_id="sess-1",
        adopted_ids=[],
        rejected_ids=["exp-3"],
        comment="方向对但版本号有误",
    )
    await handler.handle(cmd)
    backend.async_add_correction_request.assert_called_once()
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/integration/test_feedback_v2_handler_cs.py -v
```

预期：FAIL

**Step 3: 重写 feedback_v2_handler.py**

```python
# src/application/handlers/feedback_v2_handler.py
from __future__ import annotations
from typing import Any

from ..commands import FeedbackV2Command
from ...models import ExperienceStatus

CONFIDENCE_ADOPTED_DELTA = 0.1
CONFIDENCE_REJECTED_DELTA = -0.05
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0
CONFIDENCE_ARCHIVE_THRESHOLD = 0.2


class FeedbackV2Handler:
    def __init__(self, uow_factory, backend, llm):
        self._uow_factory = uow_factory
        self._backend = backend
        self._llm = llm

    async def handle(self, cmd: FeedbackV2Command) -> dict[str, Any]:
        comment_type = None
        if cmd.comment:
            comment_type = await self._analyze_comment(cmd.comment)

        all_ids = list(set(cmd.adopted_ids + cmd.rejected_ids))

        async with self._uow_factory() as uow:
            for exp_id in all_ids:
                exp = await uow.experiences.aget(exp_id)
                if exp is None:
                    continue

                is_adopted = exp_id in cmd.adopted_ids
                is_rejected = exp_id in cmd.rejected_ids
                is_needs_fix = (
                    is_rejected and comment_type == "needs_fix" and cmd.comment
                )

                if is_adopted:
                    exp.confidence = min(CONFIDENCE_MAX, exp.confidence + CONFIDENCE_ADOPTED_DELTA)
                elif is_rejected and not is_needs_fix:
                    exp.confidence = max(CONFIDENCE_MIN, exp.confidence + CONFIDENCE_REJECTED_DELTA)
                    if exp.confidence < CONFIDENCE_ARCHIVE_THRESHOLD:
                        exp.status = ExperienceStatus.ARCHIVED

                if is_needs_fix:
                    exp.status = ExperienceStatus.NEEDS_FIX
                    await self._backend.async_add_correction_request(
                        experience_id=exp_id,
                        session_id=cmd.session_id,
                        comment=cmd.comment,
                        task_description="",
                        outcome_description="",
                    )

                await uow.experiences.aupdate(exp)
                await self._backend.async_update_experience_stats(
                    exp_id,
                    hit=True,
                    adopted=is_adopted,
                    rejected=is_rejected and not is_needs_fix,
                )

        return {"status": "ok"}

    async def _analyze_comment(self, comment: str) -> str:
        prompt = (
            f"以下是用户对一条工程经验的反馈 comment，请判断反馈语义类型。\n\n"
            f"## 反馈内容\n{comment}\n\n"
            f"## 判断规则\n"
            f"- 如果反馈表达\"经验完全不适用、方向错误、和当前问题无关\"，输出：irrelevant\n"
            f"- 如果反馈表达\"经验思路/方向是对的，但某些细节、版本、参数有误\"，输出：needs_fix\n\n"
            f"只输出一个词：irrelevant 或 needs_fix"
        )
        raw = await self._llm.call(prompt)
        if raw and raw.strip() in ("irrelevant", "needs_fix"):
            return raw.strip()
        return "irrelevant"
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/integration/test_feedback_v2_handler_cs.py -v
```

预期：PASS（3 个测试）

**Step 5: 提交**

```bash
git add src/application/handlers/feedback_v2_handler.py tests/integration/test_feedback_v2_handler_cs.py
git commit -m "feat: rewrite FeedbackV2Handler with comment analysis"
```
