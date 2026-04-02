# XP 云端化重构 TDD 实现计划

**Goal:** 将 XP 从单机 JSON 架构重构为团队共享的 FastAPI + PostgreSQL 服务，本地零状态

**Architecture:** 拆分 knowledge.py 为多个领域服务（domain/），用 PostgreSQL + pgvector 替代本地 JSON+SQLite，通过 FastAPI 暴露 REST API 和 MCP SSE 端点。CLI 改为纯 HTTP 客户端，MCP server 改为远程 SSE URL。

**Tech Stack:** Python 3.11+, FastAPI, asyncpg, pgvector, PostgreSQL, pytest, pytest-asyncio, sentence-transformers (BGE-small-zh-v1.5)

---

## 背景：代码库导航

在开始前，先了解现有代码布局：

```
src/
├── knowledge.py      # 1176 行"上帝类"—— 本次重构的主要目标
├── storage.py        # 644 行，三层存储（JSON + SQLite 向量 + SQLite 指标）
├── models.py         # 数据类定义（Experience, Session, Feedback 等）
├── embeddings.py     # BGE 向量化，cosine_similarity
├── config.py         # XP_HOME 路径配置
└── server.py         # MCP stdio 服务器（7 个 tools）

tests/
├── test_extraction_refactor.py   # 323 行，提取/质量相关测试
├── test_quality_score.py         # 85 行，质量评分
├── test_finalize_task.py         # 101 行
├── test_stats_metrics.py         # 61 行
├── test_review_refactor.py       # 105 行
└── test_backends.py              # 81 行
```

运行所有测试：`pytest tests/ -v`
运行单个测试：`pytest tests/test_extraction_refactor.py::test_name -v`

---

## Week 1：给现有代码穿安全网（特征测试）

**原则：本周不改一行业务逻辑，只写测试。**

特征测试的作用是捕捉现有行为（包括 bug），确保重构后行为不变。

---

### Task 1: 搭建特征测试目录和 fixture

**Files:**
- Create: `tests/characterization/conftest.py`
- Create: `tests/characterization/__init__.py`

**Step 1: 创建 conftest.py**

```python
# tests/characterization/conftest.py
import pytest
from pathlib import Path


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    return ExperienceStore(), MetricsStore()


@pytest.fixture
def svc(tmp_store):
    from src.knowledge import KnowledgeService
    store, metrics = tmp_store
    return KnowledgeService(store, metrics)
```

**Step 2: 创建 __init__.py（空文件）**

```python
# tests/characterization/__init__.py
```

**Step 3: 运行确认 fixture 可加载**

```
pytest tests/characterization/ -v
```

期望输出：`no tests ran`（目录存在，但还没有测试）

---

### Task 2: 质量评分特征测试

**Files:**
- Create: `tests/characterization/test_quality_score.py`

**背景知识：** `_compute_quality_score` 是私有方法，在 `KnowledgeService` 上直接调用（`svc._compute_quality_score(...)`）。

评分规则：
- `key_decisions` >= 50 字 → +40 分；>= 20 字 → +20 分
- `solution_summary` >= 50 字 → +20 分；>= 20 字 → +10 分
- `related_files` 非空 → +15 分
- `tech_stack` 非空 → +15 分
- `duplicate_similarity` <= 0.6 → +10 分

**Step 1: 写失败测试**

```python
# tests/characterization/test_quality_score.py
import pytest


class TestQualityScore:
    def test_max_score(self, svc):
        score = svc._compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["src/foo.py"],
            tech_stack=["python"],
            duplicate_similarity=0.0,
        )
        assert score == 100

    def test_min_passing_score(self, svc):
        score = svc._compute_quality_score(
            key_decisions="a" * 20,
            solution_summary="b" * 20,
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        )
        assert score == 40

    def test_key_decisions_short_gives_zero(self, svc):
        score = svc._compute_quality_score(
            key_decisions="短",
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.0,
        )
        assert score == 45

    def test_high_duplicate_similarity_loses_points(self, svc):
        score = svc._compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.9,
        )
        assert score == 90

    def test_empty_everything_zero(self, svc):
        score = svc._compute_quality_score(
            key_decisions="",
            solution_summary="",
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        )
        assert score == 0
```

**Step 2: 运行确认测试失败**

```
pytest tests/characterization/test_quality_score.py -v
```

期望：**FAILED**，报错 `fixture 'svc' not found`（因为 conftest 还没被 pytest 发现——确保 Task 1 已完成）

**Step 3: 运行确认测试通过**

```
pytest tests/characterization/test_quality_score.py -v
```

期望：**5 passed**

**Step 4: 提交**

```
git add tests/characterization/
git commit -m "test: add characterization tests for quality score"
```

---

### Task 3: 元数据推断特征测试

**Files:**
- Create: `tests/characterization/test_metadata_infer.py`

**背景知识：**
- `_infer_tech_stack(text)` → `list[str]`，关键词匹配，见 `knowledge.py:950`
- `_infer_scene(text)` → `list[str]`，关键词匹配
- `_infer_type(task, decisions)` → `ExperienceType`
- `_infer_level(task, decisions)` → `ExperienceLevel`

**Step 1: 写失败测试**

```python
# tests/characterization/test_metadata_infer.py
import pytest
from src.models import ExperienceType, ExperienceLevel


class TestTechStackInfer:
    def test_react_detected(self, svc):
        result = svc._infer_tech_stack("使用 useEffect 实现防抖")
        assert "react" in result

    def test_python_detected(self, svc):
        result = svc._infer_tech_stack("用 fastapi 写接口")
        assert "python" in result

    def test_no_match_returns_empty(self, svc):
        result = svc._infer_tech_stack("完全无关的文本xyzabc")
        assert result == []

    def test_multiple_techs(self, svc):
        result = svc._infer_tech_stack("用 typescript 和 react 写组件，部署用 docker")
        assert "react" in result
        assert "typescript" in result
        assert "docker" in result


class TestSceneInfer:
    def test_form_scene(self, svc):
        result = svc._infer_scene("处理表单 validation 逻辑")
        assert "表单" in result

    def test_async_scene(self, svc):
        result = svc._infer_scene("使用 async/await 处理 fetch 请求")
        assert "异步" in result

    def test_no_match_empty(self, svc):
        result = svc._infer_scene("完全无关内容zyxwvuts")
        assert result == []


class TestTypeInfer:
    def test_bugfix_type(self, svc):
        result = svc._infer_type("修复一个 bug", "error 处理")
        assert result == ExperienceType.BUGFIX

    def test_pattern_type(self, svc):
        result = svc._infer_type("设计模式", "architecture 规范")
        assert result == ExperienceType.PATTERN

    def test_default_feature(self, svc):
        result = svc._infer_type("新增功能", "实现步骤")
        assert result == ExperienceType.FEATURE


class TestLevelInfer:
    def test_l1_architecture(self, svc):
        result = svc._infer_level("整体架构设计", "架构选型")
        assert result == ExperienceLevel.L1

    def test_l3_bugfix(self, svc):
        result = svc._infer_level("修复 bug", "fix error")
        assert result == ExperienceLevel.L3

    def test_l2_default(self, svc):
        result = svc._infer_level("添加功能", "实现步骤")
        assert result == ExperienceLevel.L2
```

**Step 2: 运行确认测试通过**

```
pytest tests/characterization/test_metadata_infer.py -v
```

期望：**11 passed**

**Step 3: 提交**

```
git add tests/characterization/test_metadata_infer.py
git commit -m "test: add characterization tests for metadata inference"
```

---

### Task 4: 提取流程特征测试

**Files:**
- Create: `tests/characterization/test_extraction.py`

**背景知识：**
- `extract_experience()` 是 async 方法
- 它内部会调用 BGE embedding —— 需要 mock
- `knowledge.py:200` 附近：字段校验 → 重复检测 → 推断 → 质量评分 → 存储
- 质量分 < 40 → 抛 `ValueError`；>= 80 → 自动 active

**Step 1: 写失败测试**

```python
# tests/characterization/test_extraction.py
import pytest
from unittest.mock import patch, MagicMock
import numpy as np


def make_fake_embedding():
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()


@pytest.fixture
def mock_embedding(monkeypatch):
    fake_vec = make_fake_embedding()
    mock_provider = MagicMock()
    mock_provider.embed_text.return_value = fake_vec
    mock_provider.embed_texts.return_value = [fake_vec]
    import src.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "_provider", mock_provider)
    return mock_provider


class TestExtractExperience:
    async def test_valid_extraction_creates_pending(self, svc, mock_embedding):
        exp = await svc.extract_experience(
            task_description="实现防抖搜索框",
            solution_summary="使用 lodash debounce 包装 onChange，延迟 300ms 触发搜索",
            key_decisions="不能直接对 setState 防抖，需要对函数本身防抖，否则每次渲染会重建函数引用",
            tags=["react"],
            related_files=["src/SearchBox.tsx"],
        )
        assert exp.id is not None
        assert exp.status.value in ("pending", "active")
        assert exp.problem == "实现防抖搜索框"

    async def test_short_key_decisions_raises(self, svc, mock_embedding):
        with pytest.raises(ValueError, match="key_decisions"):
            await svc.extract_experience(
                task_description="任务",
                solution_summary="解决方案超过二十个字符的详细描述",
                key_decisions="太短",
            )

    async def test_short_solution_raises(self, svc, mock_embedding):
        with pytest.raises(ValueError, match="solution_summary"):
            await svc.extract_experience(
                task_description="任务",
                solution_summary="短",
                key_decisions="关键决策超过十个字符的描述",
            )

    async def test_high_quality_auto_activates(self, svc, mock_embedding):
        exp = await svc.extract_experience(
            task_description="实现 React 防抖 Hook",
            solution_summary="封装 useDebounce 自定义 hook，内部用 useRef 保持函数引用稳定，避免依赖数组问题",
            key_decisions="核心是用 useRef 保存最新的回调，避免 useEffect 频繁触发，这是 React hooks 闭包陷阱的标准解法",
            tags=["react", "typescript"],
            related_files=["src/hooks/useDebounce.ts", "src/SearchBox.tsx"],
        )
        assert exp.status.value == "active"
        assert exp.confidence == 0.65

    async def test_low_quality_raises(self, svc, mock_embedding):
        with pytest.raises(ValueError, match="质量评分过低"):
            await svc.extract_experience(
                task_description="任务",
                solution_summary="这是超过二十个字符的解决方案描述",
                key_decisions="这是超过十个字的决策",
            )
```

**Step 2: 运行确认测试通过**

```
pytest tests/characterization/test_extraction.py -v
```

期望：**5 passed**

**Step 3: 提交**

```
git add tests/characterization/test_extraction.py
git commit -m "test: add characterization tests for extract_experience"
```

---

### Task 5: 检索流程特征测试

**Files:**
- Create: `tests/characterization/test_search.py`

**背景知识：**
- `search()` 是 async 方法，返回 `(list[Experience], dict)`
- dict 包含 `ab_test_group`、`show_results`、`strategy`
- A/B 分组：`hash(session_id) % 10 == 0` → control 组，不返回结果
- 阈值默认 0.5，低于阈值的不返回

**Step 1: 写失败测试**

```python
# tests/characterization/test_search.py
import pytest
from unittest.mock import MagicMock, patch
import numpy as np


def unit_vec(seed=42):
    rng = np.random.default_rng(seed)
    v = rng.random(384).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def svc_with_exp(svc, monkeypatch):
    import src.embeddings as emb_mod
    vec = unit_vec(1)
    mock_provider = MagicMock()
    mock_provider.embed_text.return_value = vec
    mock_provider.embed_texts.return_value = [vec]
    monkeypatch.setattr(emb_mod, "_provider", mock_provider)
    return svc


class TestSearch:
    async def test_returns_tuple(self, svc_with_exp):
        results, meta = await svc_with_exp.search("防抖搜索框")
        assert isinstance(results, list)
        assert "ab_test_group" in meta
        assert "show_results" in meta
        assert "strategy" in meta

    async def test_empty_store_returns_empty_list(self, svc_with_exp):
        results, meta = await svc_with_exp.search("任意查询")
        assert results == []

    async def test_treatment_group_returns_results(self, svc_with_exp, monkeypatch):
        import hashlib
        session_id = "treatment-session"
        hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
        assert hash_val % 10 != 0, "该 session_id 应该是 treatment 组，请换一个"

        results, meta = await svc_with_exp.search("查询", session_id=session_id)
        assert meta["ab_test_group"] == "treatment"
        assert meta["show_results"] is True

    async def test_control_group_returns_empty(self, svc_with_exp):
        import hashlib
        for candidate in [f"s{i}" for i in range(100)]:
            h = int(hashlib.md5(candidate.encode()).hexdigest(), 16)
            if h % 10 == 0:
                control_session_id = candidate
                break

        results, meta = await svc_with_exp.search(
            "查询", session_id=control_session_id, enable_ab_test=True
        )
        assert meta["ab_test_group"] == "control"
        assert results == []

    async def test_strategy_is_embedding_only(self, svc_with_exp):
        _, meta = await svc_with_exp.search("test")
        assert meta["strategy"] == "embedding_only"
```

**Step 2: 运行确认测试通过**

```
pytest tests/characterization/test_search.py -v
```

期望：**5 passed**

**Step 3: 提交**

```
git add tests/characterization/test_search.py
git commit -m "test: add characterization tests for search"
```

---

### Task 6: 反馈与 confidence 更新特征测试

**Files:**
- Create: `tests/characterization/test_feedback.py`

**背景知识：**
- `record_feedback(exp_id, adopted, reason)` 是 async 方法
- confidence 更新公式：`new = old * 0.9 + adoption_rate * 0.1`
- confidence < 0.1 → 自动归档
- 先需要有一条经验才能测反馈

**Step 1: 写失败测试**

```python
# tests/characterization/test_feedback.py
import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock
import numpy as np
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)


def make_exp(store, status=ExperienceStatus.ACTIVE, confidence=0.6):
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="测试经验",
        tags=[],
        problem="测试问题描述",
        solution="测试解决方案描述",
        key_decisions="关键决策：注意这里的坑",
        confidence=confidence,
        status=status,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(),
    )
    return store.add(exp)


class TestRecordFeedback:
    async def test_returns_true_for_existing_exp(self, svc, tmp_store):
        store, _ = tmp_store
        exp = make_exp(store)
        result = await svc.record_feedback(exp.id, adopted=True)
        assert result is True

    async def test_returns_false_for_nonexistent(self, svc):
        result = await svc.record_feedback("nonexistent-id", adopted=True)
        assert result is False

    async def test_confidence_decreases_on_rejection(self, svc, tmp_store):
        store, _ = tmp_store
        exp = make_exp(store, confidence=0.6)
        original_confidence = exp.confidence

        await svc.record_feedback(exp.id, adopted=False)
        await svc.record_feedback(exp.id, adopted=False)

        updated = store.get(exp.id)
        assert updated.confidence < original_confidence

    async def test_auto_archive_when_confidence_too_low(self, svc, tmp_store):
        store, _ = tmp_store
        exp = make_exp(store, confidence=0.11)

        for _ in range(20):
            await svc.record_feedback(exp.id, adopted=False)

        updated = store.get(exp.id)
        assert updated.status == ExperienceStatus.ARCHIVED
```

**Step 2: 运行确认测试通过**

```
pytest tests/characterization/test_feedback.py -v
```

期望：**4 passed**

**Step 3: 提交**

```
git add tests/characterization/test_feedback.py
git commit -m "test: add characterization tests for record_feedback"
```

---

### Task 7: A/B 测试分组特征测试

**Files:**
- Create: `tests/characterization/test_abtest.py`

**背景知识：**
- 分组逻辑在 `knowledge.py:315`：`int(hashlib.md5(session_id.encode()).hexdigest(), 16) % 10 == 0`
- 这是纯确定性哈希，同一 session_id 永远同一组

**Step 1: 写失败测试**

```python
# tests/characterization/test_abtest.py
import pytest
import hashlib


class TestABTestGrouping:
    def test_deterministic_same_session_same_group(self, svc):
        session_id = "any-fixed-session-id"
        h = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
        expected = "control" if h % 10 == 0 else "treatment"

        async def get_group(sid):
            _, meta = await svc.search("test", session_id=sid, enable_ab_test=True)
            return meta["ab_test_group"]

        import asyncio
        group1 = asyncio.get_event_loop().run_until_complete(get_group(session_id))
        group2 = asyncio.get_event_loop().run_until_complete(get_group(session_id))
        assert group1 == expected
        assert group2 == expected

    def test_10_percent_control_distribution(self):
        control_count = 0
        total = 1000
        for i in range(total):
            h = int(hashlib.md5(f"session-{i}".encode()).hexdigest(), 16)
            if h % 10 == 0:
                control_count += 1
        ratio = control_count / total
        assert 0.05 <= ratio <= 0.15, f"Control 比例应接近 10%，实际 {ratio:.1%}"

    def test_no_session_id_defaults_to_treatment(self, svc):
        import asyncio
        async def run():
            _, meta = await svc.search("test", session_id=None, enable_ab_test=True)
            return meta
        meta = asyncio.get_event_loop().run_until_complete(run())
        assert meta["ab_test_group"] == "treatment"
        assert meta["show_results"] is True
```

**Step 2: 运行确认测试通过**

```
pytest tests/characterization/test_abtest.py -v
```

期望：**3 passed**

**Step 3: 运行全量特征测试**

```
pytest tests/characterization/ -v
```

期望：**所有测试绿**，knowledge.py 一行未动。

**Step 4: 提交**

```
git add tests/characterization/test_abtest.py
git commit -m "test: add characterization tests for A/B grouping - Week 1 complete"
```

---

## Week 2：拆分 knowledge.py（红→绿→重构）

**原则：每次只移动一个模块。移完立刻跑全量测试。每个 Step 一次 commit。**

---

### Task 8: 提取 quality.py（纯函数，无 IO）

**Files:**
- Create: `src/domain/quality.py`
- Create: `src/domain/__init__.py`
- Modify: `src/knowledge.py`（删除 `_compute_quality_score` 私有方法）
- Create: `tests/unit/test_quality.py`

**Step 1: 创建 `src/domain/__init__.py`（空文件）**

```python
# src/domain/__init__.py
```

**Step 2: 写接口测试（红）**

```python
# tests/unit/test_quality.py
from src.domain.quality import compute_quality_score


class TestComputeQualityScore:
    def test_max_score(self):
        assert compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.0,
        ) == 100

    def test_zero_score(self):
        assert compute_quality_score(
            key_decisions="",
            solution_summary="",
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        ) == 0

    def test_mid_key_decisions(self):
        score = compute_quality_score(
            key_decisions="a" * 20,
            solution_summary="b" * 50,
            related_files=[],
            tech_stack=[],
            duplicate_similarity=0.0,
        )
        assert score == 30

    def test_high_duplicate_loses_dedup_bonus(self):
        score = compute_quality_score(
            key_decisions="a" * 50,
            solution_summary="b" * 50,
            related_files=["f.py"],
            tech_stack=["python"],
            duplicate_similarity=0.9,
        )
        assert score == 90
```

**Step 3: 运行确认失败**

```
pytest tests/unit/test_quality.py -v
```

期望：`ModuleNotFoundError: No module named 'src.domain.quality'`

**Step 4: 实现 `src/domain/quality.py`**

```python
# src/domain/quality.py
def compute_quality_score(
    key_decisions: str,
    solution_summary: str,
    related_files: list[str],
    tech_stack: list[str],
    duplicate_similarity: float = 0.0,
) -> int:
    score = 0

    kd_len = len(key_decisions.strip())
    if kd_len >= 50:
        score += 40
    elif kd_len >= 20:
        score += 20

    ss_len = len(solution_summary.strip())
    if ss_len >= 50:
        score += 20
    elif ss_len >= 20:
        score += 10

    if related_files:
        score += 15

    if tech_stack:
        score += 15

    if duplicate_similarity <= 0.6:
        score += 10

    return score
```

**Step 5: 运行确认测试通过**

```
pytest tests/unit/test_quality.py -v
```

期望：**4 passed**

**Step 6: 修改 `src/knowledge.py`，把 `_compute_quality_score` 改为调用新函数**

找到 `knowledge.py` 中的 `_compute_quality_score` 方法（约 1090 行），替换为：

```python
def _compute_quality_score(self, key_decisions, solution_summary, related_files, tech_stack, duplicate_similarity=0.0):
    from .domain.quality import compute_quality_score
    return compute_quality_score(key_decisions, solution_summary, related_files, tech_stack, duplicate_similarity)
```

**Step 7: 运行全量测试**

```
pytest tests/ -v
```

期望：**所有测试仍然绿**

**Step 8: 提交**

```
git add src/domain/ tests/unit/
git commit -m "refactor: extract compute_quality_score to domain/quality.py"
```

---

### Task 9: 提取 metadata.py（纯函数，无 IO）

**Files:**
- Create: `src/domain/metadata.py`
- Create: `tests/unit/test_metadata.py`
- Modify: `src/knowledge.py`

**Step 1: 写接口测试（红）**

```python
# tests/unit/test_metadata.py
from src.models import ExperienceType, ExperienceLevel
from src.domain.metadata import infer_tech_stack, infer_scene, infer_type, infer_level


class TestInferTechStack:
    def test_react_hooks(self):
        assert "react" in infer_tech_stack("使用 useEffect 实现防抖")

    def test_python_fastapi(self):
        assert "python" in infer_tech_stack("用 fastapi 写 REST 接口")

    def test_empty_text(self):
        assert infer_tech_stack("") == []

    def test_multiple_techs(self):
        result = infer_tech_stack("typescript + react + docker")
        assert "typescript" in result
        assert "react" in result
        assert "docker" in result


class TestInferScene:
    def test_form_scene(self):
        assert "表单" in infer_scene("处理 form validation 逻辑")

    def test_async_scene(self):
        assert "异步" in infer_scene("async fetch 请求处理")

    def test_no_scene(self):
        assert infer_scene("xyzabc123") == []


class TestInferType:
    def test_bugfix(self):
        assert infer_type("修复 bug", "error 处理") == ExperienceType.BUGFIX

    def test_pattern(self):
        assert infer_type("架构模式", "设计规范") == ExperienceType.PATTERN

    def test_default_feature(self):
        assert infer_type("添加新功能", "实现步骤") == ExperienceType.FEATURE


class TestInferLevel:
    def test_l1(self):
        assert infer_level("整体架构设计", "架构选型") == ExperienceLevel.L1

    def test_l3(self):
        assert infer_level("修复 bug", "fix error exception") == ExperienceLevel.L3

    def test_l2_default(self):
        assert infer_level("普通功能", "实现") == ExperienceLevel.L2
```

**Step 2: 运行确认失败**

```
pytest tests/unit/test_metadata.py -v
```

**Step 3: 实现 `src/domain/metadata.py`**

从 `knowledge.py` 的 `_infer_tech_stack`、`_infer_scene`、`_infer_type`、`_infer_level` 方法中复制逻辑，改为纯函数（去掉 `self`）：

```python
# src/domain/metadata.py
from src.models import ExperienceType, ExperienceLevel


_TECH_KEYWORDS = {
    "react": ["react", "useeffect", "usestate", "hooks"],
    "vue": ["vue", "composition api", "ref", "reactive"],
    "typescript": ["typescript", "ts", "类型", "type"],
    "javascript": ["javascript", "js", "es6", "async", "await"],
    "python": ["python", "django", "flask", "fastapi"],
    "css": ["css", "scss", "less", "tailwind", "styled"],
    "node": ["node", "nodejs", "npm", "express"],
    "database": ["sql", "mysql", "postgresql", "mongodb", "redis"],
    "docker": ["docker", "container", "k8s", "kubernetes"],
    "git": ["git", "github", "gitlab", "commit", "merge"],
}

_SCENE_KEYWORDS = {
    "表单": ["表单", "form", "input", "validation", "校验"],
    "列表": ["列表", "list", "table", "grid", "pagination"],
    "异步": ["异步", "async", "await", "promise", "fetch", "api"],
    "状态管理": ["状态", "state", "redux", "vuex", "pinia", "mobx"],
    "路由": ["路由", "router", "navigation", "route", "页面跳转"],
    "性能优化": ["性能", "优化", "performance", "lazy", "cache", "memo"],
    "测试": ["测试", "test", "jest", "vitest", "cypress", "e2e"],
    "部署": ["部署", "deploy", "ci/cd", "pipeline", "build"],
    "错误处理": ["错误", "error", "exception", "catch", "try", "debug", "排查"],
    "数据库": ["数据库", "database", "sql", "query", "orm"],
    "API 设计": ["api", "接口", "endpoint", "rest", "graphql"],
    "认证授权": ["认证", "授权", "auth", "login", "token", "jwt", "oauth"],
    "配置管理": ["配置", "config", "env", "environment", "variable"],
    "文件操作": ["文件", "file", "目录", "folder", "path", "读写"],
}


def infer_tech_stack(text: str) -> list[str]:
    text_lower = text.lower()
    return [tech for tech, kws in _TECH_KEYWORDS.items() if any(k in text_lower for k in kws)]


def infer_scene(text: str) -> list[str]:
    text_lower = text.lower()
    return [scene for scene, kws in _SCENE_KEYWORDS.items() if any(k in text_lower for k in kws)]


def infer_type(task: str, decisions: str) -> ExperienceType:
    text = (task + decisions).lower()
    if any(k in text for k in ["bug", "fix", "修复", "报错", "error"]):
        return ExperienceType.BUGFIX
    if any(k in text for k in ["模式", "pattern", "架构", "规范"]):
        return ExperienceType.PATTERN
    return ExperienceType.FEATURE


def infer_level(task: str, decisions: str) -> ExperienceLevel:
    text = (task + decisions).lower()
    if any(k in text for k in ["架构", "模式", "pattern", "设计", "architecture"]):
        return ExperienceLevel.L1
    if any(k in text for k in ["bug", "fix", "修复", "报错", "error", "exception"]):
        return ExperienceLevel.L3
    return ExperienceLevel.L2
```

**Step 4: 修改 `src/knowledge.py`，4 个私有方法改为委托**

```python
def _infer_tech_stack(self, text: str) -> list[str]:
    from .domain.metadata import infer_tech_stack
    return infer_tech_stack(text)

def _infer_scene(self, text: str) -> list[str]:
    from .domain.metadata import infer_scene
    return infer_scene(text)

def _infer_type(self, task: str, decisions: str) -> ExperienceType:
    from .domain.metadata import infer_type
    return infer_type(task, decisions)

def _infer_level(self, task: str, decisions: str) -> ExperienceLevel:
    from .domain.metadata import infer_level
    return infer_level(task, decisions)
```

**Step 5: 运行全量测试**

```
pytest tests/ -v
```

期望：**全绿**

**Step 6: 提交**

```
git add src/domain/metadata.py tests/unit/test_metadata.py src/knowledge.py
git commit -m "refactor: extract metadata inference to domain/metadata.py"
```

---

### Task 10: 提取 SearchService

**Files:**
- Create: `src/domain/search.py`
- Create: `tests/unit/test_search_service.py`
- Modify: `src/knowledge.py`（`search()` 方法改为委托）

**Step 1: 写接口测试（红）**

```python
# tests/unit/test_search_service.py
import pytest
import numpy as np
from unittest.mock import MagicMock, AsyncMock
from src.domain.search import SearchService


@pytest.fixture
def mock_deps():
    mock_store = MagicMock()
    mock_store.list_active.return_value = []

    mock_vector_store = MagicMock()
    mock_vector_store.get_all_vectors.return_value = ([], np.array([]))
    mock_vector_store.save_vectors.return_value = None

    mock_metrics = MagicMock()
    mock_metrics.record_search.return_value = None

    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    mock_provider.embed_text.return_value = (vec / np.linalg.norm(vec)).tolist()

    return mock_store, mock_vector_store, mock_metrics, mock_provider


class TestSearchService:
    async def test_empty_store_returns_empty(self, mock_deps):
        store, v_store, metrics, provider = mock_deps
        svc = SearchService(store, v_store, metrics, provider, project="default")
        results, meta = await svc.search("query")
        assert results == []
        assert meta["strategy"] == "embedding_only"

    async def test_control_group_returns_empty(self, mock_deps):
        import hashlib
        store, v_store, metrics, provider = mock_deps
        svc = SearchService(store, v_store, metrics, provider, project="default")

        control_id = None
        for i in range(100):
            sid = f"s{i}"
            if int(hashlib.md5(sid.encode()).hexdigest(), 16) % 10 == 0:
                control_id = sid
                break

        results, meta = await svc.search("query", session_id=control_id)
        assert meta["ab_test_group"] == "control"
        assert results == []

    async def test_treatment_group_metadata(self, mock_deps):
        import hashlib
        store, v_store, metrics, provider = mock_deps
        svc = SearchService(store, v_store, metrics, provider, project="default")

        treat_id = None
        for i in range(100):
            sid = f"t{i}"
            if int(hashlib.md5(sid.encode()).hexdigest(), 16) % 10 != 0:
                treat_id = sid
                break

        _, meta = await svc.search("query", session_id=treat_id)
        assert meta["ab_test_group"] == "treatment"
        assert meta["show_results"] is True
```

**Step 2: 运行确认失败**

```
pytest tests/unit/test_search_service.py -v
```

**Step 3: 实现 `src/domain/search.py`**

将 `knowledge.py` 的 `search()` 方法中的逻辑提取为 `SearchService` 类，接受依赖注入：

```python
# src/domain/search.py
import hashlib
from datetime import datetime
from typing import Optional
import numpy as np

from src.models import Experience
from src.storage import ExperienceStore, VectorStore, MetricsStore
from src.embeddings import EmbeddingProvider, cosine_similarity
from src.file_watcher import TTLManager


class SearchService:
    def __init__(
        self,
        store: ExperienceStore,
        vector_store: VectorStore,
        metrics: MetricsStore,
        provider: EmbeddingProvider,
        project: str = "default",
    ):
        self._store = store
        self._vector_store = vector_store
        self._metrics = metrics
        self._provider = provider
        self._project = project
        self._ttl_manager = TTLManager()

    async def search(
        self,
        query: str,
        tags: Optional[list[str]] = None,
        top_k: int = 3,
        threshold: float = 0.5,
        cross_project: bool = False,
        session_id: Optional[str] = None,
        enable_ab_test: bool = True,
    ) -> tuple[list[Experience], dict]:
        ab_test_group = "treatment"
        show_results = True
        if enable_ab_test and session_id:
            hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
            if hash_val % 10 == 0:
                ab_test_group = "control"
                show_results = False

        candidates = self._store.list_active()
        if not cross_project:
            candidates = [e for e in candidates if e.project == self._project]

        valid_candidates = []
        for exp in candidates:
            if self._ttl_manager.is_expired(exp.last_hit_at):
                continue
            if exp.stale_reason:
                continue
            if tags and not any(t in exp.metadata.tech_stack for t in tags):
                continue
            valid_candidates.append(exp)

        if not show_results or not valid_candidates:
            self._metrics.record_search(query, 0)
            return [], {"ab_test_group": ab_test_group, "show_results": show_results, "strategy": "embedding_only"}

        query_vec = np.array(self._provider.embed_text(query), dtype=np.float32)
        candidate_ids = [e.id for e in valid_candidates]
        ids, vecs = self._vector_store.get_all_vectors(candidate_ids)

        missing_exps = [e for e in valid_candidates if e.id not in ids]
        if missing_exps:
            missing_texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in missing_exps]
            missing_vecs = self._provider.embed_texts(missing_texts)
            self._vector_store.save_vectors(list(zip([e.id for e in missing_exps], missing_vecs)))
            ids, vecs = self._vector_store.get_all_vectors(candidate_ids)

        if len(vecs) == 0:
            return [], {"ab_test_group": ab_test_group, "show_results": True, "strategy": "embedding_only"}

        scores = cosine_similarity(query_vec, vecs)
        results = []
        id_to_exp = {e.id: e for e in valid_candidates}
        for exp_id, score in zip(ids, scores):
            if score >= threshold:
                exp = id_to_exp[exp_id]
                exp.similarity = round(float(score), 3)
                results.append((exp, score))

        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top_k]

        now = datetime.utcnow().isoformat()
        for exp, _ in results:
            exp.last_hit_at = now
            self._store.update(exp)

        self._metrics.record_search(query, len(results))
        return [exp for exp, _ in results], {"ab_test_group": ab_test_group, "show_results": True, "strategy": "embedding_only"}
```

**Step 4: 修改 `knowledge.py` 的 `search()` 方法改为委托**

```python
async def search(self, query, tags=None, top_k=3, threshold=0.5,
                 cross_project=False, session_id=None,
                 enable_ab_test=True, enable_strategy_ab_test=True):
    from .domain.search import SearchService
    from .embeddings import get_provider
    from .storage import VectorStore
    svc = SearchService(
        self._store, VectorStore(), self._metrics,
        get_provider(), project=self._project
    )
    return await svc.search(query, tags, top_k, threshold,
                            cross_project, session_id, enable_ab_test)
```

**Step 5: 运行全量测试**

```
pytest tests/ -v
```

期望：**全绿**

**Step 6: 提交**

```
git add src/domain/search.py tests/unit/test_search_service.py src/knowledge.py
git commit -m "refactor: extract SearchService to domain/search.py"
```

---

### Task 11: 提取 ExtractionService

**Files:**
- Create: `src/domain/extraction.py`
- Create: `tests/unit/test_extraction_service.py`
- Modify: `src/knowledge.py`

**Step 1: 写接口测试（红）**

```python
# tests/unit/test_extraction_service.py
import pytest
from unittest.mock import MagicMock, AsyncMock
import numpy as np


@pytest.fixture
def mock_extraction_deps(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.storage import ExperienceStore, VectorStore
    store = ExperienceStore()
    v_store = VectorStore()

    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]

    import src.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "_provider", mock_provider)

    return store, v_store


class TestExtractionService:
    async def test_valid_input_returns_experience(self, mock_extraction_deps):
        from src.domain.extraction import ExtractionService
        store, v_store = mock_extraction_deps
        svc = ExtractionService(store, v_store)

        exp = await svc.extract(
            task_description="实现 React 防抖 Hook",
            solution_summary="封装 useDebounce 自定义 hook，用 useRef 保持函数引用稳定",
            key_decisions="核心是用 useRef 保存最新回调，避免 useEffect 频繁触发，这是 React hooks 闭包陷阱的标准解法",
            related_files=["src/hooks/useDebounce.ts"],
            tags=["react"],
        )
        assert exp.id is not None
        assert exp.problem == "实现 React 防抖 Hook"

    async def test_short_key_decisions_raises(self, mock_extraction_deps):
        from src.domain.extraction import ExtractionService
        store, v_store = mock_extraction_deps
        svc = ExtractionService(store, v_store)

        with pytest.raises(ValueError, match="key_decisions"):
            await svc.extract(
                task_description="任务",
                solution_summary="解决方案超过二十个字符",
                key_decisions="短",
            )
```

**Step 2: 运行确认失败**

```
pytest tests/unit/test_extraction_service.py -v
```

**Step 3: 实现 `src/domain/extraction.py`**

将 `knowledge.py` 的 `extract_experience()` 逻辑提取为 `ExtractionService.extract()`：

```python
# src/domain/extraction.py
import uuid
from datetime import datetime
from typing import Optional

from src.models import (
    Experience, ExperienceMetadata, ExperienceSource, ExperienceStatus,
)
from src.storage import ExperienceStore, VectorStore
from src.domain.quality import compute_quality_score
from src.domain.metadata import infer_tech_stack, infer_scene, infer_type, infer_level
from src.file_watcher import calculate_files_hashes


class ExtractionService:
    def __init__(self, store: ExperienceStore, vector_store: VectorStore, project: str = "default"):
        self._store = store
        self._vector_store = vector_store
        self._project = project

    async def extract(
        self,
        task_description: str,
        solution_summary: str,
        key_decisions: str,
        conversation_summary: Optional[str] = None,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
    ) -> Experience:
        tags = tags or []
        related_files = related_files or []

        if not key_decisions or len(key_decisions.strip()) < 10:
            raise ValueError(
                "key_decisions 不能为空且长度不得少于 10 字。"
                "请补充关键决策/踩坑点后重试。"
            )
        if not solution_summary or len(solution_summary.strip()) < 20:
            raise ValueError(
                "solution_summary 长度不得少于 20 字。"
                "请补充解决方案摘要后重试。"
            )

        await self._check_duplicate(task_description, solution_summary)

        all_text = f"{task_description}\n{solution_summary}\n{key_decisions}"
        if conversation_summary:
            all_text = f"{all_text}\n{conversation_summary}"

        tech_stack = infer_tech_stack(all_text)
        scene = infer_scene(all_text)
        level = infer_level(task_description, key_decisions)
        exp_type = infer_type(task_description, key_decisions)

        quality_score = compute_quality_score(
            key_decisions=key_decisions,
            solution_summary=solution_summary,
            related_files=related_files,
            tech_stack=tech_stack if tech_stack else tags,
        )

        if quality_score < 40:
            raise ValueError(
                f"经验质量评分过低（{quality_score}/100），提取已拒绝。"
                f"请补充：key_decisions（当前{len(key_decisions.strip())}字，建议>=50字）"
                f"，solution_summary（当前{len(solution_summary.strip())}字，建议>=50字）"
                f"，相关文件路径，技术栈标签。"
            )

        file_hashes = calculate_files_hashes(related_files)
        title = task_description[:60] + ("..." if len(task_description) > 60 else "")

        exp = Experience(
            id=str(uuid.uuid4()),
            type=exp_type,
            level=level,
            title=title,
            tags=tags,
            problem=task_description,
            solution=solution_summary,
            key_decisions=key_decisions,
            confidence=0.6,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.AGENT,
            created_at=datetime.utcnow().isoformat(),
            related_files=related_files,
            metadata=ExperienceMetadata(
                tech_stack=tech_stack if tech_stack else tags,
                problem_type=exp_type.value,
                scene=scene,
            ),
            file_hashes=file_hashes,
            project=self._project,
        )

        exp = self._store.add(exp)

        if quality_score >= 80:
            exp.status = ExperienceStatus.ACTIVE
            exp.confidence = 0.65

        from src.embeddings import get_provider
        provider = get_provider()
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.key_decisions}"
        vec = provider.embed_text(exp_text)
        self._vector_store.save_vector(exp.id, vec)

        return exp

    async def _check_duplicate(self, task_description: str, solution_summary: str):
        from src.embeddings import get_provider, cosine_similarity
        import numpy as np

        provider = get_provider()
        query_vec = np.array(provider.embed_text(f"{task_description}\n{solution_summary}"), dtype=np.float32)

        all_ids, all_vecs = self._vector_store.get_all_vectors()
        if len(all_vecs) == 0:
            return

        scores = cosine_similarity(query_vec, all_vecs)
        max_score = float(np.max(scores)) if len(scores) > 0 else 0.0

        if max_score >= 0.85:
            best_idx = int(np.argmax(scores))
            exp_id = all_ids[best_idx]
            raise ValueError(
                f"已存在高度相似的经验（相似度 {max_score:.2f}）：[{exp_id[:8]}]。"
                f"建议复用或用 `xp edit {exp_id[:8]}` 更新已有经验，而非新增。"
            )
```

**Step 4: 修改 `knowledge.py` 的 `extract_experience()` 改为委托**

```python
async def extract_experience(self, task_description, solution_summary, key_decisions,
                              conversation_summary=None, tags=None, related_files=None):
    from .domain.extraction import ExtractionService
    from .storage import VectorStore
    svc = ExtractionService(self._store, VectorStore(), project=self._project)
    return await svc.extract(task_description, solution_summary, key_decisions,
                             conversation_summary, tags, related_files)
```

**Step 5: 运行全量测试**

```
pytest tests/ -v
```

期望：**全绿**

**Step 6: 提交**

```
git add src/domain/extraction.py tests/unit/test_extraction_service.py src/knowledge.py
git commit -m "refactor: extract ExtractionService to domain/extraction.py"
```

---

### Task 12: 提取 FeedbackService

**Files:**
- Create: `src/domain/feedback.py`
- Create: `tests/unit/test_feedback_service.py`
- Modify: `src/knowledge.py`

**Step 1: 写接口测试（红）**

```python
# tests/unit/test_feedback_service.py
import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata, ExperienceStats,
)


def make_exp(confidence=0.6):
    return Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="t", tags=[], problem="p", solution="s",
        key_decisions="kd", confidence=confidence,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(),
    )


class TestFeedbackService:
    async def test_returns_false_for_nonexistent(self):
        from src.domain.feedback import FeedbackService
        mock_store = MagicMock()
        mock_store.get.return_value = None
        mock_metrics = MagicMock()
        svc = FeedbackService(mock_store, mock_metrics)
        result = await svc.record_feedback("nonexistent", adopted=True)
        assert result is False

    async def test_adopted_true_increases_confidence(self):
        from src.domain.feedback import FeedbackService
        exp = make_exp(confidence=0.6)
        mock_store = MagicMock()
        mock_store.get.return_value = exp
        mock_metrics = MagicMock()
        stats = ExperienceStats(
            experience_id=exp.id,
            hit_count=1, adopted_count=1, rejected_count=0,
            adoption_rate=1.0,
        )
        mock_metrics.get_experience_stats.return_value = stats
        svc = FeedbackService(mock_store, mock_metrics)

        await svc.record_feedback(exp.id, adopted=True)
        mock_store.update.assert_called_once()
        updated_exp = mock_store.update.call_args[0][0]
        assert updated_exp.confidence > 0.6

    async def test_low_confidence_auto_archives(self):
        from src.domain.feedback import FeedbackService
        exp = make_exp(confidence=0.05)
        mock_store = MagicMock()
        mock_store.get.return_value = exp
        mock_metrics = MagicMock()
        stats = ExperienceStats(
            experience_id=exp.id,
            hit_count=10, adopted_count=0, rejected_count=10,
            adoption_rate=0.0,
        )
        mock_metrics.get_experience_stats.return_value = stats
        svc = FeedbackService(mock_store, mock_metrics)

        await svc.record_feedback(exp.id, adopted=False)
        updated_exp = mock_store.update.call_args[0][0]
        assert updated_exp.status == ExperienceStatus.ARCHIVED
```

**Step 2: 运行确认失败**

```
pytest tests/unit/test_feedback_service.py -v
```

**Step 3: 实现 `src/domain/feedback.py`**

```python
# src/domain/feedback.py
from typing import Optional
from src.models import Feedback, ExperienceStatus
from src.storage import ExperienceStore, MetricsStore


class FeedbackService:
    def __init__(self, store: ExperienceStore, metrics: MetricsStore):
        self._store = store
        self._metrics = metrics

    async def record_feedback(self, experience_id: str, adopted: bool, reason: Optional[str] = None) -> bool:
        exp = self._store.get(experience_id)
        if not exp:
            return False

        feedback = Feedback(experience_id=experience_id, adopted=adopted, reason=reason)
        self._metrics.record_feedback(feedback)

        stats = self._metrics.get_experience_stats(experience_id)
        if stats:
            new_confidence = exp.confidence * 0.9 + stats.adoption_rate * 0.1
            exp.confidence = round(new_confidence, 3)
            if exp.confidence < 0.1:
                exp.status = ExperienceStatus.ARCHIVED
                exp.reject_reason = "Low adoption rate, auto archived"
            self._store.update(exp)

        return True
```

**Step 4: 修改 `knowledge.py` 的 `record_feedback()` 改为委托**

```python
async def record_feedback(self, experience_id: str, adopted: bool, reason=None) -> bool:
    from .domain.feedback import FeedbackService
    svc = FeedbackService(self._store, self._metrics)
    return await svc.record_feedback(experience_id, adopted, reason)
```

**Step 5: 运行全量测试**

```
pytest tests/ -v
```

期望：**全绿**

**Step 6: 提交**

```
git add src/domain/feedback.py tests/unit/test_feedback_service.py src/knowledge.py
git commit -m "refactor: extract FeedbackService to domain/feedback.py - Week 2 complete"
```

---

## Week 3：建 xp-server（FastAPI + PostgreSQL），测试先行

**前置条件：** 需要 Docker 来启动 PostgreSQL

```bash
docker run -d --name xp-postgres \
  -e POSTGRES_USER=xp \
  -e POSTGRES_PASSWORD=xp \
  -e POSTGRES_DB=xp \
  -p 5432:5432 \
  ankane/pgvector:latest
```

---

### Task 13: 搭建 FastAPI 基础骨架

**Files:**
- Create: `src/interfaces/__init__.py`
- Create: `src/interfaces/rest_api.py`
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/conftest.py`

**Step 1: 安装测试依赖**

检查 `pyproject.toml` 是否已有 `httpx`（FastAPI 测试客户端依赖）：

```
grep -r "httpx" pyproject.toml
```

若没有，在 `pyproject.toml` 的 `dependencies` 中添加 `"httpx>=0.27.0"`。

**Step 2: 创建 e2e conftest.py**

```python
# tests/e2e/conftest.py
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.interfaces.rest_api import create_app
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)
```

**Step 3: 写第一个端点的失败测试**

```python
# tests/e2e/test_health.py
def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

**Step 4: 运行确认失败**

```
pytest tests/e2e/test_health.py -v
```

期望：`ModuleNotFoundError: No module named 'src.interfaces.rest_api'`

**Step 5: 实现 `src/interfaces/rest_api.py`**

```python
# src/interfaces/rest_api.py
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="xp-server", version="0.3.0")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
```

**Step 6: 运行确认通过**

```
pytest tests/e2e/test_health.py -v
```

期望：**1 passed**

**Step 7: 提交**

```
git add src/interfaces/ tests/e2e/
git commit -m "feat: add FastAPI skeleton with health endpoint"
```

---

### Task 14: 实现 POST /api/experiences（提取经验）

**Files:**
- Modify: `src/interfaces/rest_api.py`
- Create: `tests/e2e/test_extract_api.py`

**Step 1: 写失败测试**

```python
# tests/e2e/test_extract_api.py
import pytest
from unittest.mock import patch, MagicMock
import numpy as np


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch):
    import src.embeddings as emb_mod
    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]
    monkeypatch.setattr(emb_mod, "_provider", mock_provider)


class TestExtractAPI:
    def test_valid_extraction_returns_201(self, client):
        response = client.post("/api/experiences", json={
            "task_description": "实现 React 防抖 Hook",
            "solution_summary": "封装 useDebounce 自定义 hook，用 useRef 保持函数引用稳定，避免依赖数组问题",
            "key_decisions": "核心是用 useRef 保存最新的回调，避免 useEffect 频繁触发，这是 React hooks 闭包陷阱的标准解法",
            "tags": ["react"],
            "related_files": ["src/hooks/useDebounce.ts"],
        })
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["status"] in ("pending", "active")

    def test_missing_key_decisions_returns_422(self, client):
        response = client.post("/api/experiences", json={
            "task_description": "任务",
            "solution_summary": "解决方案超过二十个字符的描述",
        })
        assert response.status_code == 422

    def test_low_quality_returns_400(self, client):
        response = client.post("/api/experiences", json={
            "task_description": "任务",
            "solution_summary": "这是超过二十个字符的解决方案描述",
            "key_decisions": "这是超过十个字的决策",
        })
        assert response.status_code == 400
        assert "质量评分过低" in response.json()["detail"]
```

**Step 2: 运行确认失败**

```
pytest tests/e2e/test_extract_api.py -v
```

期望：`404 Not Found`（端点不存在）

**Step 3: 实现端点**

在 `src/interfaces/rest_api.py` 中添加：

```python
# src/interfaces/rest_api.py（完整版）
import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.storage import ExperienceStore, VectorStore, MetricsStore
from src.knowledge import KnowledgeService


class ExtractRequest(BaseModel):
    task_description: str
    solution_summary: str
    key_decisions: str
    conversation_summary: Optional[str] = None
    tags: list[str] = []
    related_files: list[str] = []


def create_app() -> FastAPI:
    app = FastAPI(title="xp-server", version="0.3.0")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/experiences", status_code=201)
    async def extract_experience(req: ExtractRequest):
        store = ExperienceStore()
        metrics = MetricsStore()
        svc = KnowledgeService(store, metrics)
        try:
            exp = await svc.extract_experience(
                task_description=req.task_description,
                solution_summary=req.solution_summary,
                key_decisions=req.key_decisions,
                conversation_summary=req.conversation_summary,
                tags=req.tags,
                related_files=req.related_files,
            )
            return {
                "id": exp.id,
                "status": exp.status.value,
                "confidence": exp.confidence,
                "title": exp.title,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return app
```

**Step 4: 运行确认通过**

```
pytest tests/e2e/test_extract_api.py -v
```

期望：**3 passed**

**Step 5: 提交**

```
git add src/interfaces/rest_api.py tests/e2e/test_extract_api.py
git commit -m "feat: add POST /api/experiences endpoint"
```

---

### Task 15: 实现 GET /api/experiences/search（检索）

**Files:**
- Modify: `src/interfaces/rest_api.py`
- Create: `tests/e2e/test_search_api.py`

**Step 1: 写失败测试**

```python
# tests/e2e/test_search_api.py
import pytest
from unittest.mock import MagicMock
import numpy as np


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch):
    import src.embeddings as emb_mod
    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]
    monkeypatch.setattr(emb_mod, "_provider", mock_provider)


class TestSearchAPI:
    def test_search_returns_200(self, client):
        response = client.get("/api/experiences/search?q=防抖&top_k=3")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "metadata" in data

    def test_empty_query_returns_400(self, client):
        response = client.get("/api/experiences/search")
        assert response.status_code == 422

    def test_search_result_structure(self, client):
        response = client.get("/api/experiences/search?q=react hooks")
        data = response.json()
        assert isinstance(data["results"], list)
        assert "ab_test_group" in data["metadata"]
```

**Step 2: 运行确认失败**

```
pytest tests/e2e/test_search_api.py -v
```

**Step 3: 实现检索端点**

在 `create_app()` 中添加：

```python
@app.get("/api/experiences/search")
async def search_experiences(
    q: str,
    top_k: int = 3,
    session_id: Optional[str] = None,
    tags: Optional[str] = None,
):
    store = ExperienceStore()
    metrics = MetricsStore()
    svc = KnowledgeService(store, metrics)
    tag_list = tags.split(",") if tags else None
    exps, meta = await svc.search(
        query=q,
        tags=tag_list,
        top_k=top_k,
        session_id=session_id,
    )
    return {
        "results": [
            {
                "id": e.id,
                "title": e.title,
                "solution": e.solution,
                "key_decisions": e.key_decisions,
                "similarity": e.similarity,
                "confidence": e.confidence,
                "tags": e.tags,
            }
            for e in exps
        ],
        "metadata": meta,
    }
```

**Step 4: 运行确认通过**

```
pytest tests/e2e/test_search_api.py -v
```

**Step 5: 提交**

```
git add src/interfaces/rest_api.py tests/e2e/test_search_api.py
git commit -m "feat: add GET /api/experiences/search endpoint"
```

---

### Task 16: 实现剩余 REST 端点

**Files:**
- Modify: `src/interfaces/rest_api.py`
- Create: `tests/e2e/test_rest_api.py`

需要实现的端点（参考设计文档 REST API 设计节）：

**Step 1: 写失败测试**

```python
# tests/e2e/test_rest_api.py
import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock
import numpy as np
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch):
    import src.embeddings as emb_mod
    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]
    monkeypatch.setattr(emb_mod, "_provider", mock_provider)


@pytest.fixture
def seeded_client(client, tmp_path, monkeypatch):
    import src.storage as storage_mod
    from src.storage import ExperienceStore
    store = ExperienceStore()
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="防抖 Hook",
        tags=["react"],
        problem="防抖问题",
        solution="useDebounce 解决",
        key_decisions="用 useRef",
        confidence=0.7,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(tech_stack=["react"]),
    )
    store.add(exp)
    return client, exp.id


class TestRESTAPI:
    def test_list_pending_experiences(self, seeded_client):
        client, exp_id = seeded_client
        response = client.get("/api/experiences?status=pending")
        assert response.status_code == 200
        data = response.json()
        assert len(data["experiences"]) >= 1

    def test_review_activate(self, seeded_client):
        client, exp_id = seeded_client
        response = client.patch(f"/api/experiences/{exp_id}", json={"action": "activate"})
        assert response.status_code == 200

    def test_review_archive(self, seeded_client):
        client, exp_id = seeded_client
        response = client.patch(
            f"/api/experiences/{exp_id}",
            json={"action": "archive", "reason": "测试归档"}
        )
        assert response.status_code == 200

    def test_post_feedback(self, seeded_client):
        client, exp_id = seeded_client
        response = client.post("/api/feedback", json={
            "experience_id": exp_id,
            "adopted": True,
        })
        assert response.status_code == 200

    def test_post_session(self, client):
        response = client.post("/api/sessions", json={
            "session_id": "test-session-001",
            "task_description": "实现功能",
            "experience_ids_injected": [],
            "iteration_count": 3,
            "had_error_correction": False,
            "user_accepted": True,
        })
        assert response.status_code == 200

    def test_get_stats(self, client):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "active_count" in data
```

**Step 2: 运行确认失败**

```
pytest tests/e2e/test_rest_api.py -v
```

**Step 3: 实现所有端点**

在 `create_app()` 中继续添加（完整代码见下方）：

```python
# 添加到 src/interfaces/rest_api.py 的 create_app() 中

from pydantic import BaseModel
from typing import Optional

class ReviewRequest(BaseModel):
    action: str  # activate | archive
    reason: Optional[str] = None

class FeedbackRequest(BaseModel):
    experience_id: str
    adopted: bool
    reason: Optional[str] = None

class SessionRequest(BaseModel):
    session_id: str
    task_description: str
    experience_ids_injected: list[str] = []
    iteration_count: int = 1
    had_error_correction: bool = False
    user_accepted: bool = True
    ab_test_group: str = "treatment"
    result_shown: bool = True

@app.get("/api/experiences")
def list_experiences(status: str = "pending"):
    store = ExperienceStore()
    from src.models import ExperienceStatus
    try:
        status_enum = ExperienceStatus(status)
    except ValueError:
        raise HTTPException(400, f"Invalid status: {status}")
    exps = store.list_by_status(status_enum)
    return {"experiences": [{"id": e.id, "title": e.title, "status": e.status.value,
                              "confidence": e.confidence} for e in exps]}

@app.patch("/api/experiences/{exp_id}")
def review_experience(exp_id: str, req: ReviewRequest):
    store = ExperienceStore()
    metrics = MetricsStore()
    svc = KnowledgeService(store, metrics)
    if req.action == "activate":
        success = svc.confirm_experience(exp_id)
    elif req.action == "archive":
        success = svc.reject_experience(exp_id, req.reason)
    else:
        raise HTTPException(400, f"Unknown action: {req.action}")
    if not success:
        raise HTTPException(404, "Experience not found")
    return {"status": "ok"}

@app.post("/api/feedback")
async def record_feedback(req: FeedbackRequest):
    store = ExperienceStore()
    metrics = MetricsStore()
    svc = KnowledgeService(store, metrics)
    success = await svc.record_feedback(req.experience_id, req.adopted, req.reason)
    if not success:
        raise HTTPException(404, "Experience not found")
    return {"status": "ok"}

@app.post("/api/sessions")
async def record_session(req: SessionRequest):
    from src.models import Session
    from datetime import datetime
    store = ExperienceStore()
    metrics = MetricsStore()
    svc = KnowledgeService(store, metrics)
    session = Session(
        session_id=req.session_id,
        task_description=req.task_description,
        experience_ids_injected=req.experience_ids_injected,
        iteration_count=req.iteration_count,
        had_error_correction=req.had_error_correction,
        user_accepted=req.user_accepted,
        created_at=datetime.utcnow().isoformat(),
        ab_test_group=req.ab_test_group,
        ab_test_result_shown=req.result_shown,
    )
    await svc.record_session(session)
    return {"status": "ok"}

@app.get("/api/stats")
def get_stats(since: Optional[int] = None):
    store = ExperienceStore()
    metrics = MetricsStore()
    svc = KnowledgeService(store, metrics)
    return svc.get_stats(since)
```

**Step 4: 运行确认通过**

```
pytest tests/e2e/test_rest_api.py -v
```

期望：**6 passed**

**Step 5: 运行全量测试**

```
pytest tests/ -v
```

**Step 6: 提交**

```
git add src/interfaces/rest_api.py tests/e2e/test_rest_api.py
git commit -m "feat: implement all REST API endpoints - Week 3 complete"
```

---

## Week 4：数据迁移 + 删旧代码

---

### Task 17: 写迁移测试（红）

**Files:**
- Create: `tests/test_migration_v2.py`
- Create: `scripts/migrate_knowledge_to_server.py`

**背景知识：** 迁移脚本需要把 `~/.xp/knowledge.json` 中的所有经验通过 HTTP POST 到新的 `/api/experiences`，同时保留 ID。

**Step 1: 写失败测试**

```python
# tests/test_migration_v2.py
import json
import uuid
from datetime import datetime
import pytest
from unittest.mock import MagicMock, patch
import numpy as np


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch):
    import src.embeddings as emb_mod
    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]
    monkeypatch.setattr(emb_mod, "_provider", mock_provider)


def make_legacy_knowledge_json(tmp_path):
    exp_id = str(uuid.uuid4())
    data = {
        exp_id: {
            "id": exp_id,
            "type": "bugfix",
            "level": "L2",
            "title": "旧经验标题",
            "tags": ["python"],
            "problem": "旧问题描述",
            "solution": "旧解决方案描述",
            "key_decisions": "旧关键决策：注意事项",
            "confidence": 0.8,
            "status": "active",
            "source": "agent",
            "created_at": datetime.utcnow().isoformat(),
            "metadata": {"tech_stack": ["python"], "problem_type": "bugfix", "scene": []},
        }
    }
    knowledge_file = tmp_path / "knowledge.json"
    knowledge_file.write_text(json.dumps(data))
    return tmp_path, exp_id


class TestMigration:
    def test_migrate_preserves_all_experiences(self, tmp_path, monkeypatch):
        import src.storage as storage_mod
        legacy_path, exp_id = make_legacy_knowledge_json(tmp_path)

        target_path = tmp_path / "target"
        target_path.mkdir()
        monkeypatch.setattr(storage_mod, "XP_HOME", target_path)
        monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", target_path / "knowledge.json")
        monkeypatch.setattr(storage_mod, "METRICS_DB", target_path / "metrics.db")

        from scripts.migrate_knowledge_to_server import migrate
        migrated_count = migrate(source_path=legacy_path, dry_run=False)

        assert migrated_count == 1
        from src.storage import ExperienceStore
        store = ExperienceStore()
        exp = store.get(exp_id)
        assert exp is not None
        assert exp.title == "旧经验标题"

    def test_migrate_dry_run_does_not_write(self, tmp_path, monkeypatch):
        import src.storage as storage_mod
        legacy_path, exp_id = make_legacy_knowledge_json(tmp_path)

        target_path = tmp_path / "target"
        target_path.mkdir()
        monkeypatch.setattr(storage_mod, "XP_HOME", target_path)
        monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", target_path / "knowledge.json")
        monkeypatch.setattr(storage_mod, "METRICS_DB", target_path / "metrics.db")

        from scripts.migrate_knowledge_to_server import migrate
        migrated_count = migrate(source_path=legacy_path, dry_run=True)

        assert migrated_count == 1
        from src.storage import ExperienceStore
        store = ExperienceStore()
        assert store.get(exp_id) is None
```

**Step 2: 运行确认失败**

```
pytest tests/test_migration_v2.py -v
```

期望：`ModuleNotFoundError: No module named 'scripts.migrate_knowledge_to_server'`

**Step 3: 实现迁移脚本**

```python
# scripts/migrate_knowledge_to_server.py
import json
from pathlib import Path
from typing import Optional
import uuid
from datetime import datetime


def migrate(source_path: Path, dry_run: bool = True) -> int:
    knowledge_file = source_path / "knowledge.json"
    if not knowledge_file.exists():
        print(f"knowledge.json not found at {knowledge_file}")
        return 0

    with open(knowledge_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    from src.storage import ExperienceStore, VectorStore
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
    )

    count = 0
    for exp_id, exp_data in data.items():
        if dry_run:
            print(f"[dry-run] Would migrate: {exp_id[:8]} - {exp_data.get('title', '?')}")
            count += 1
            continue

        meta_data = exp_data.get("metadata", {})
        exp = Experience(
            id=exp_data["id"],
            type=ExperienceType(exp_data.get("type", "feature")),
            level=ExperienceLevel(exp_data.get("level", "L2")),
            title=exp_data.get("title", ""),
            tags=exp_data.get("tags", []),
            problem=exp_data.get("problem", ""),
            solution=exp_data.get("solution", ""),
            key_decisions=exp_data.get("key_decisions", ""),
            confidence=exp_data.get("confidence", 0.6),
            status=ExperienceStatus(exp_data.get("status", "pending")),
            source=ExperienceSource(exp_data.get("source", "agent")),
            created_at=exp_data.get("created_at", datetime.utcnow().isoformat()),
            related_files=exp_data.get("related_files", []),
            metadata=ExperienceMetadata(
                tech_stack=meta_data.get("tech_stack", []),
                problem_type=meta_data.get("problem_type", ""),
                scene=meta_data.get("scene", []),
            ),
            project=exp_data.get("project", "default"),
            last_hit_at=exp_data.get("last_hit_at"),
        )

        store = ExperienceStore()
        store.add(exp)

        from src.embeddings import get_provider
        from src.storage import VectorStore as VS
        provider = get_provider()
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.key_decisions}"
        vec = provider.embed_text(exp_text)
        VS().save_vector(exp.id, vec)

        count += 1
        print(f"Migrated: {exp_id[:8]} - {exp.title}")

    return count


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Migrate knowledge.json to new store")
    parser.add_argument("--source", default="~/.xp", help="Source XP_HOME path")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true", default=False)
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    dry = not args.execute
    count = migrate(source_path=source, dry_run=dry)
    print(f"\nTotal: {count} experiences {'(dry-run)' if dry else 'migrated'}")
```

**Step 4: 确保 scripts 目录有 `__init__.py`**

```python
# scripts/__init__.py
```

**Step 5: 运行确认测试通过**

```
pytest tests/test_migration_v2.py -v
```

期望：**2 passed**

**Step 6: 提交**

```
git add scripts/migrate_knowledge_to_server.py tests/test_migration_v2.py
git commit -m "feat: add migration script for knowledge.json"
```

---

### Task 18: 删除废弃代码

**Files:**
- Delete: `src/cloud_providers.py`（设计文档明确废弃：YAGNI）
- Delete: `src/backends/local.py`（将被 Repo 层替代）
- Modify: `src/backends/__init__.py`（移除已删文件的导入）

**Step 1: 确认全量测试仍然绿（删前备份）**

```
pytest tests/ -v
```

**Step 2: 检查 cloud_providers.py 被谁引用**

```
grep -r "cloud_providers" src/ tests/
```

若只在 `knowledge.py` 的 `sync_to_cloud` / `sync_from_cloud` 中延迟导入，可安全删除。

**Step 3: 检查 backends/local.py 被谁引用**

```
grep -r "backends" src/ tests/
```

**Step 4: 删除文件（用 git 跟踪）**

```
git rm src/cloud_providers.py
git rm src/backends/local.py
```

若有测试引用了这些文件，先修改测试再删除。

**Step 5: 运行全量测试确认全绿**

```
pytest tests/ -v
```

**Step 6: 提交**

```
git add -A
git commit -m "refactor: remove deprecated cloud_providers.py and backends/local.py - Week 4 complete"
```

---

## 最终验收

运行完整测试套件，确认所有测试绿：

```
pytest tests/ -v --tb=short
```

期望：
- `tests/characterization/` — Week 1 特征测试，全绿
- `tests/unit/` — Week 2 单元测试，全绿
- `tests/e2e/` — Week 3 端到端测试，全绿
- `tests/test_migration_v2.py` — Week 4 迁移测试，全绿

**Week 4 结束标准：**
- knowledge.py 的业务逻辑已全部委托给 `domain/` 层
- FastAPI 提供完整 REST API
- 迁移脚本可正常运行
- 废弃代码已删除
- 全量测试绿

---

## 附录：常见错误排查

| 错误 | 原因 | 解法 |
|------|------|------|
| `fixture 'svc' not found` | conftest.py 路径错误 | 确认 conftest 在 `tests/characterization/` 下 |
| `ModuleNotFoundError: src.domain.quality` | 文件未创建或 `__init__.py` 缺失 | 检查 `src/domain/__init__.py` 存在 |
| `AttributeError: '_provider' is not set` | BGE 模型未加载 | 确认 mock_embedding fixture 已激活 |
| embedding 测试挂起 | BGE 模型正在下载 | 使用 mock_embedding fixture 替代真实 BGE |
| `asyncpg.exceptions.ConnectionRefused` | PostgreSQL 未启动 | `docker start xp-postgres` |
