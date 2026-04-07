# XP 完整改造实施计划

**Goal:** 将 XP 从"4 工具分散调用 + 全人工 review + 单机 JSON 存储"改造为"单工具容错调用 + 质量评分自动激活 + PostgreSQL 服务化存储"。

**Architecture:** 分三个独立阶段渐进实施：第一阶段在现有代码上新增 `finalize_task` 工具（内部容错编排），第二阶段在 `KnowledgeService` 中引入质量评分系统并改造 `cmd_review`，第三阶段抽象 `StorageBackend` 接口并实现 `PostgresBackend`。每个阶段均不破坏已有集成，旧工具/接口保留至迁移完成。

**Tech Stack:** Python 3.11+, MCP SDK, pytest-asyncio, asyncpg, FastAPI (第三阶段), pgvector, sentence-transformers

---

## 前置知识

### 代码库结构速览

```
src/
  server.py      # MCP 工具注册与路由（list_tools / call_tool）
  knowledge.py   # KnowledgeService：所有业务逻辑
  storage.py     # ExperienceStore（JSON）+ MetricsStore（SQLite）+ VectorStore（SQLite BLOB）
  models.py      # 数据类：Experience, Session, Feedback, ExperienceStatus 等
  cli.py         # xp 命令行：add / review / stats / analyze …
tests/
  test_extraction_refactor.py   # 现有测试模式参考
```

### 测试运行方式

```bash
pytest tests/ -v                   # 运行所有测试
pytest tests/test_foo.py::test_bar -v  # 运行单个测试
```

### 隔离存储的 fixture 模式（所有测试必须用）

```python
@pytest.fixture
def service(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    return KnowledgeService(ExperienceStore(), MetricsStore())
```

---

## 第一阶段：finalize_task 工具（估时 2 周）

**目标：** 将 4 个工具合并为 1 个，内部三步独立容错，extract 失败不中断 record_session 和 infer_adoption。

**涉及文件：**
- 新增：`tests/test_finalize_task.py`
- 修改：`src/server.py`（新增工具注册 + call_tool 分支）
- 修改：`src/knowledge.py`（新增 `finalize_task` 方法）

---

### Task 1: 为 `finalize_task` 写失败测试

**Files:**
- Create: `tests/test_finalize_task.py`

**Step 1: 写第一个失败测试**

```python
# tests/test_finalize_task.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def service(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    return KnowledgeService(ExperienceStore(), MetricsStore())


async def test_finalize_task_method_exists(service):
    assert hasattr(service, "finalize_task")
```

**Step 2: 运行，验证失败**

```bash
pytest tests/test_finalize_task.py::test_finalize_task_method_exists -v
```

期望输出：`FAILED` 带 `AttributeError: 'KnowledgeService' object has no attribute 'finalize_task'`

---

### Task 2: 在 `KnowledgeService` 中实现 `finalize_task`

**Files:**
- Modify: `src/knowledge.py`（在 `record_session` 方法之后新增）

**Step 1: 在 `knowledge.py` 末尾（`_infer_level` 之前）新增方法**

```python
async def finalize_task(
    self,
    session_id: str,
    task_description: str,
    solution_summary: str,
    key_decisions: str,
    final_response: str,
    conversation_summary: Optional[str] = None,
    tags: Optional[list[str]] = None,
    related_files: Optional[list[str]] = None,
    iteration_count: int = 1,
    had_error_correction: bool = False,
    user_accepted: bool = True,
) -> dict:
    result = {
        "session_id": session_id,
        "extract": {"status": "skipped", "id": None, "reason": None},
        "session": {"status": "skipped"},
        "adoption": {"status": "skipped", "results": []},
    }

    # Step 1: extract_experience（失败不中断）
    experience_id = None
    try:
        exp = await self.extract_experience(
            task_description=task_description,
            solution_summary=solution_summary,
            key_decisions=key_decisions,
            conversation_summary=conversation_summary,
            tags=tags or [],
            related_files=related_files or [],
        )
        experience_id = exp.id
        result["extract"] = {"status": "ok", "id": exp.id, "reason": None}
    except Exception as e:
        result["extract"] = {"status": "skipped", "id": None, "reason": str(e)}

    # Step 2: record_session（无论 extract 成功与否）
    try:
        session = Session(
            session_id=session_id,
            task_description=task_description,
            experience_ids_injected=[experience_id] if experience_id else [],
            iteration_count=iteration_count,
            had_error_correction=had_error_correction,
            user_accepted=user_accepted,
            created_at=datetime.utcnow().isoformat(),
            ab_test_group="treatment",
            ab_test_result_shown=True,
        )
        await self.record_session(session)
        result["session"] = {"status": "ok"}
    except Exception as e:
        result["session"] = {"status": "error", "reason": str(e)}

    # Step 3: infer_adoption（仅当有注入经验时执行）
    injected_ids = [experience_id] if experience_id else []
    if injected_ids:
        try:
            adoption_results = await self.infer_adoption(
                session_id=session_id,
                final_response=final_response,
                experience_ids_injected=injected_ids,
            )
            result["adoption"] = {"status": "ok", "results": adoption_results}
        except Exception as e:
            result["adoption"] = {"status": "error", "reason": str(e)}

    return result
```

**注意：** `Session` 和 `datetime` 在 `knowledge.py` 顶部已导入，直接使用。

**Step 2: 运行测试，验证通过**

```bash
pytest tests/test_finalize_task.py::test_finalize_task_method_exists -v
```

期望输出：`PASSED`

---

### Task 3: 写核心容错测试（extract 失败，session 仍执行）

**Files:**
- Modify: `tests/test_finalize_task.py`

**Step 1: 追加核心容错测试**

```python
async def test_finalize_task_extract_fails_session_still_runs(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    # 让 extract_experience 抛出异常（key_decisions 太短会触发 ValueError）
    result = await service.finalize_task(
        session_id="test-session-001",
        task_description="测试任务",
        solution_summary="解决方案摘要超过二十个字符的内容",
        key_decisions="短",           # 故意太短，触发 ValueError
        final_response="最终回复内容",
    )

    assert result["extract"]["status"] == "skipped"
    assert "key_decisions" in result["extract"]["reason"]
    assert result["session"]["status"] == "ok"   # session 必须成功
```

**Step 2: 运行测试，验证失败**

```bash
pytest tests/test_finalize_task.py::test_finalize_task_extract_fails_session_still_runs -v
```

期望：`FAILED`（因为方法逻辑还没写，或者 session 实际抛出了别的问题）

**Step 3: 运行测试，验证通过（Task 2 实现后）**

```bash
pytest tests/test_finalize_task.py::test_finalize_task_extract_fails_session_still_runs -v
```

期望：`PASSED`

---

### Task 4: 写 extract 成功时三步全走的测试

**Files:**
- Modify: `tests/test_finalize_task.py`

**Step 1: 追加成功路径测试**

```python
async def test_finalize_task_all_steps_succeed(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def fake_llm_title(text):
        raise RuntimeError("no llm")

    monkeypatch.setattr(service, "_llm_generate_title", fake_llm_title)

    result = await service.finalize_task(
        session_id="test-session-002",
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        final_response="实现了 token 自动刷新逻辑",
    )

    assert result["extract"]["status"] == "ok"
    assert result["extract"]["id"] is not None
    assert result["session"]["status"] == "ok"
    assert result["adoption"]["status"] == "ok"
```

**Step 2: 运行测试**

```bash
pytest tests/test_finalize_task.py::test_finalize_task_all_steps_succeed -v
```

期望：`PASSED`

---

### Task 5: 在 `server.py` 注册 `finalize_task` MCP 工具

**Files:**
- Modify: `src/server.py`

**Step 1: 在 `list_tools` 返回的列表末尾追加（在 `infer_adoption` Tool 定义之后）**

在 `list_tools` 函数的 `return [` 列表末尾，`infer_adoption` Tool 的 `),` 后面，追加：

```python
        Tool(
            name="finalize_task",
            description=(
                "【任务完成后一键完成】替代原有的 extract_experience + record_session + infer_adoption 三步调用。"
                "内部三步独立容错：提取失败不影响会话记录；无需手动调用其他工具。"
                "每次任务完成后只需调用这一个工具即可。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID，与 search_best_practices 中传入的 session_id 一致",
                    },
                    "task_description": {
                        "type": "string",
                        "description": "【必填】你要解决什么问题？一句话说清",
                    },
                    "solution_summary": {
                        "type": "string",
                        "description": "【必填】最终怎么解决的？核心思路",
                    },
                    "key_decisions": {
                        "type": "string",
                        "description": "【必填】有什么坑要注意？这是最有价值的部分",
                    },
                    "final_response": {
                        "type": "string",
                        "description": "【必填】任务的最终回复内容，用于推断经验采纳情况",
                    },
                    "conversation_summary": {
                        "type": "string",
                        "description": "【推荐】对话过程摘要，包含关键排查步骤",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "技术栈标签",
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "涉及的关键文件路径",
                    },
                    "iteration_count": {
                        "type": "integer",
                        "description": "对话轮数，默认 1",
                        "default": 1,
                    },
                    "had_error_correction": {
                        "type": "boolean",
                        "description": "是否出现过报错修正",
                        "default": False,
                    },
                    "user_accepted": {
                        "type": "boolean",
                        "description": "用户是否接受结果",
                        "default": True,
                    },
                },
                "required": ["session_id", "task_description", "solution_summary", "key_decisions", "final_response"],
            },
        ),
```

**Step 2: 在 `call_tool` 函数末尾（`return [TextContent(type="text", text=f"未知工具: {name}")]` 之前）追加分支**

```python
    elif name == "finalize_task":
        result = await service.finalize_task(
            session_id=arguments["session_id"],
            task_description=arguments["task_description"],
            solution_summary=arguments["solution_summary"],
            key_decisions=arguments["key_decisions"],
            final_response=arguments["final_response"],
            conversation_summary=arguments.get("conversation_summary"),
            tags=arguments.get("tags", []),
            related_files=arguments.get("related_files", []),
            iteration_count=arguments.get("iteration_count", 1),
            had_error_correction=arguments.get("had_error_correction", False),
            user_accepted=arguments.get("user_accepted", True),
        )
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "ok",
                **result,
                "message": (
                    f"经验已提取 [{result['extract']['id'][:8] if result['extract']['id'] else '跳过'}]，"
                    f"会话已记录，"
                    f"采纳推断完成（{len(result['adoption'].get('results', []))} 条）。"
                    if result['extract']['status'] == 'ok'
                    else f"会话已记录（提取跳过：{result['extract']['reason']}）"
                ),
            }, ensure_ascii=False, indent=2),
        )]
```

---

### Task 6: 写 server 层 finalize_task 集成测试

**Files:**
- Modify: `tests/test_finalize_task.py`

**Step 1: 追加 server 层测试**

```python
async def test_server_finalize_task_extract_fails_session_recorded(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    import src.server as server_mod
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    svc = KnowledgeService(ExperienceStore(), MetricsStore())
    monkeypatch.setattr(server_mod, "_service", svc)

    result = await server_mod.call_tool("finalize_task", {
        "session_id": "server-test-001",
        "task_description": "测试任务描述",
        "solution_summary": "解决方案摘要超过二十个字符的内容",
        "key_decisions": "短",
        "final_response": "最终回复",
    })

    import json
    data = json.loads(result[0].text)
    assert data["extract"]["status"] == "skipped"
    assert data["session"]["status"] == "ok"
```

**Step 2: 运行所有 Task 1 阶段测试**

```bash
pytest tests/test_finalize_task.py -v
```

期望：全部 `PASSED`

**Step 3: 确认不破坏现有测试**

```bash
pytest tests/ -v
```

期望：所有测试 `PASSED`

---

## 第二阶段：质量评分 + Review 改造（估时 2 周）

**目标：** 引入 5 维质量评分，高分自动激活（`>= 80`），低分直接拒绝（`< 40`），`cmd_review` 新增 `[e]` 编辑确认和 `[b]` 批量确认，Admin 权限校验。

**涉及文件：**
- 新增：`tests/test_quality_score.py`
- 修改：`src/knowledge.py`（新增 `_compute_quality_score` + 修改 `extract_experience`）
- 修改：`src/cli.py`（改造 `cmd_review`）
- 修改：`src/models.py`（`ExperienceStatus` 新增处理逻辑 + 可选 Admin 字段）

---

### Task 7: 写质量评分失败测试

**Files:**
- Create: `tests/test_quality_score.py`

**Step 1: 写测试**

```python
# tests/test_quality_score.py
import pytest


@pytest.fixture
def service(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    return KnowledgeService(ExperienceStore(), MetricsStore())


def test_quality_score_method_exists(service):
    assert hasattr(service, "_compute_quality_score")
```

**Step 2: 运行，验证失败**

```bash
pytest tests/test_quality_score.py::test_quality_score_method_exists -v
```

期望：`FAILED`

---

### Task 8: 实现 `_compute_quality_score`

**Files:**
- Modify: `src/knowledge.py`

评分权重规则（总分 100 分）：
- `key_decisions` 长度：`>= 50` 字得 40 分，`>= 20` 字得 20 分，否则 0
- `solution_summary` 长度：`>= 50` 字得 20 分，`>= 20` 字得 10 分，否则 0
- `related_files` 非空：得 15 分
- 技术栈推断成功（`tech_stack` 非空）：得 15 分
- 重复距离 `>= 0.4`（即无高度相似经验，相似度 `<= 0.6`）：得 10 分

**Step 1: 在 `_make_title` 方法之后新增**

```python
def _compute_quality_score(
    self,
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

**Step 2: 运行测试，验证通过**

```bash
pytest tests/test_quality_score.py::test_quality_score_method_exists -v
```

期望：`PASSED`

---

### Task 9: 写质量评分边界用例测试

**Files:**
- Modify: `tests/test_quality_score.py`

**Step 1: 追加测试**

```python
def test_quality_score_high(service):
    score = service._compute_quality_score(
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环，应该使用 useCallback 包裹",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化，不影响用户体验",
        related_files=["src/hooks/useAuth.ts"],
        tech_stack=["react", "typescript"],
        duplicate_similarity=0.1,
    )
    assert score >= 80


def test_quality_score_medium(service):
    score = service._compute_quality_score(
        key_decisions="注意不要直接 setState",
        solution_summary="修改了代码，状态正常了，效果好",
        related_files=[],
        tech_stack=[],
        duplicate_similarity=0.5,
    )
    assert 40 <= score < 80


def test_quality_score_low(service):
    score = service._compute_quality_score(
        key_decisions="短",
        solution_summary="改了",
        related_files=[],
        tech_stack=[],
        duplicate_similarity=0.5,
    )
    assert score < 40
```

**Step 2: 运行，验证通过**

```bash
pytest tests/test_quality_score.py -v
```

期望：全部 `PASSED`

---

### Task 10: 在 `extract_experience` 中集成质量评分三级策略

**Files:**
- Modify: `src/knowledge.py`

当前 `extract_experience` 最底部（`exp = self._store.add(exp)` 之前）进行修改：

**Step 1: 在生成 `tech_stack` 之后、创建 `exp` 对象之前，插入评分逻辑**

找到 `knowledge.py` 中 `extract_experience` 方法里的以下代码段：

```python
        # Phase 3: 计算相关文件的 hash
        file_hashes = calculate_files_hashes(related_files)
```

在这一行**之前**插入：

```python
        quality_score = self._compute_quality_score(
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
```

在 `exp = self._store.add(exp)` 之后、生成向量之前插入：

```python
        if quality_score >= 80:
            exp.status = ExperienceStatus.ACTIVE
            exp.confidence = 0.65
```

**Step 2: 运行现有测试，确保不破坏**

```bash
pytest tests/ -v
```

期望：所有测试 `PASSED`（注意 `test_quality_gate_rejects_short_key_decisions` 等测试会因评分 < 40 触发拒绝，与现有行为一致）

---

### Task 11: 写 `extract_experience` 质量评分集成测试

**Files:**
- Modify: `tests/test_quality_score.py`

**Step 1: 追加集成测试**

```python
async def test_high_quality_auto_activates(service, monkeypatch):
    from src.embeddings import EmbeddingProvider, set_provider
    from src.models import ExperienceStatus

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def fake_llm_title(text):
        raise RuntimeError("no llm")

    monkeypatch.setattr(service, "_llm_generate_title", fake_llm_title)

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化，不影响用户体验",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环，应该使用 useCallback 包裹回调函数",
        related_files=["src/hooks/useAuth.ts"],
        tags=["react", "typescript"],
    )

    assert exp.status == ExperienceStatus.ACTIVE
    assert exp.confidence == 0.65


async def test_low_quality_rejected(service):
    with pytest.raises(ValueError, match="质量评分过低"):
        await service.extract_experience(
            task_description="改了个东西",
            solution_summary="改好了",
            key_decisions="注意",
        )
```

**Step 2: 运行测试**

```bash
pytest tests/test_quality_score.py -v
```

期望：全部 `PASSED`

---

### Task 12: 改造 `cmd_review`，新增 `[e]` 和 `[b]` 操作

**Files:**
- Modify: `src/cli.py`

找到 `cmd_review` 函数中的操作提示行：

```python
        print("\n  操作: [y] 确认  [n] 拒绝  [s] 跳过  [q] 退出")
```

**Step 1: 替换为新提示**

```python
        print("\n  操作: [y] 确认  [e] 编辑后确认  [n] 拒绝（原因必填）  [b] 批量确认剩余  [s] 跳过  [q] 退出")
```

**Step 2: 在 `while True:` 循环的 `if choice == "y":` 分支之后，`elif choice == "n":` 之前插入**

```python
            elif choice == "e":
                import tempfile, subprocess
                with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
                    f.write(f"# {exp.title}\n\n")
                    f.write(f"**问题:**\n{exp.problem}\n\n")
                    f.write(f"**解决方案:**\n{exp.solution}\n\n")
                    f.write(f"**关键决策:**\n{exp.key_decisions}\n\n")
                    f.write(f"**标签:** {', '.join(exp.tags)}\n")
                    tmp_path_name = f.name
                editor = os.environ.get("EDITOR", "vi")
                subprocess.call([editor, tmp_path_name])
                content = open(tmp_path_name, encoding="utf-8").read()
                lines = content.splitlines()
                if lines:
                    exp.title = lines[0].lstrip("# ").strip() or exp.title
                exp.status = ExperienceStatus.ACTIVE
                exp.confidence = 1.0
                store.update(exp)
                import asyncio
                from src.knowledge import KnowledgeService
                from src.storage import MetricsStore
                svc = KnowledgeService(store, MetricsStore())
                asyncio.run(svc.edit_and_confirm(exp.id))
                metrics.record_review(exp.id, "confirmed")
                print("  已编辑并确认，confidence = 1.0。")
                break
```

**Step 3: 在 `elif choice == "n":` 分支中，确保 reason 必填**

找到：

```python
            elif choice == "n":
                reason = input("  拒绝原因（可直接回车跳过）: ").strip() or None
```

替换为：

```python
            elif choice == "n":
                reason = ""
                while not reason:
                    reason = input("  拒绝原因（必填）: ").strip()
                    if not reason:
                        print("  拒绝原因不能为空，请重新输入。")
```

**Step 4: 在 `elif choice == "s":` 之前插入 `[b]` 批量确认**

```python
            elif choice == "b":
                remaining = pending[i-1:]
                for r_exp in remaining:
                    r_exp.status = ExperienceStatus.ACTIVE
                    r_exp.confidence = 0.65
                    store.update(r_exp)
                    metrics.record_review(r_exp.id, "confirmed")
                print(f"  已批量确认剩余 {len(remaining)} 条经验（confidence = 0.65）。")
                return
```

---

### Task 13: 写 `cmd_review` 改造测试

**Files:**
- Create: `tests/test_review_refactor.py`

**Step 1: 写测试**

```python
# tests/test_review_refactor.py
import uuid
from datetime import datetime
import pytest


@pytest.fixture
def store_with_pending(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    store = ExperienceStore()
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="测试标题",
        tags=[],
        problem="测试问题",
        solution="测试解决方案",
        key_decisions="重要坑：不要直接修改 state",
        confidence=0.6,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
    )
    store.add(exp)
    return store, exp


def test_review_reject_requires_reason(store_with_pending, monkeypatch, capsys):
    _, exp = store_with_pending
    inputs = iter(["n", "", "测试拒绝原因", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    from src.cli import cmd_review
    cmd_review([])
    captured = capsys.readouterr()
    assert "拒绝原因不能为空" in captured.out


def test_review_batch_confirm(tmp_path, monkeypatch, capsys):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    store = ExperienceStore()
    exp_ids = []
    for i in range(3):
        exp = Experience(
            id=str(uuid.uuid4()),
            type=ExperienceType.BUGFIX,
            level=ExperienceLevel.L2,
            title=f"测试标题{i}",
            tags=[],
            problem="测试问题",
            solution="测试解决方案",
            key_decisions="关键决策内容",
            confidence=0.6,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.AGENT,
            created_at=datetime.utcnow().isoformat(),
        )
        store.add(exp)
        exp_ids.append(exp.id)

    inputs = iter(["b"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    from src.cli import cmd_review
    cmd_review([])

    from src.models import ExperienceStatus
    for eid in exp_ids:
        loaded = store.get(eid)
        assert loaded.status == ExperienceStatus.ACTIVE
        assert loaded.confidence == 0.65
```

**Step 2: 运行测试**

```bash
pytest tests/test_review_refactor.py -v
```

期望：全部 `PASSED`

---

### Task 14: 实现 Admin 权限校验

**Files:**
- Modify: `src/cli.py`

**背景：** Admin 权限通过环境变量 `XP_ADMIN_KEY` 控制，若设置了该变量，则 `xp review` 入口需要验证 `XP_USER_KEY` 是否匹配。若 `XP_ADMIN_KEY` 未设置，则跳过校验（单机模式）。

**Step 1: 在 `cmd_review` 函数最开头（`from .storage import ...` 之前）插入**

```python
def cmd_review(args):
    admin_key = os.environ.get("XP_ADMIN_KEY")
    if admin_key:
        user_key = os.environ.get("XP_USER_KEY", "")
        if user_key != admin_key:
            print("错误：xp review 需要 Admin 权限。请设置 XP_USER_KEY 环境变量。")
            sys.exit(1)
    # ... 原有代码 ...
```

**Step 2: 写权限校验测试**

在 `tests/test_review_refactor.py` 追加：

```python
def test_review_admin_only_blocked(monkeypatch, capsys):
    monkeypatch.setenv("XP_ADMIN_KEY", "secret123")
    monkeypatch.setenv("XP_USER_KEY", "wrongkey")
    with pytest.raises(SystemExit):
        from src.cli import cmd_review
        cmd_review([])


def test_review_admin_only_allowed(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setenv("XP_ADMIN_KEY", "secret123")
    monkeypatch.setenv("XP_USER_KEY", "secret123")
    monkeypatch.setattr("builtins.input", lambda _: "q")
    from src.cli import cmd_review
    cmd_review([])
```

**Step 3: 运行所有第二阶段测试**

```bash
pytest tests/test_quality_score.py tests/test_review_refactor.py -v
```

期望：全部 `PASSED`

**Step 4: 确认不破坏已有测试**

```bash
pytest tests/ -v
```

期望：所有测试 `PASSED`

---

## 第三阶段：存储服务化（估时 4-6 周）

**目标：** 抽象 `StorageBackend` 接口，渐进式迁移到 PostgreSQL + pgvector，FastAPI 中心化服务 + 本地轻量 HTTP Proxy，完整权限管理。

**涉及文件：**
- 新增：`src/backends/__init__.py`
- 新增：`src/backends/base.py`（抽象接口）
- 新增：`src/backends/local.py`（现有 JSON/SQLite 实现接口）
- 新增：`src/backends/postgres.py`（PostgreSQL + pgvector 实现）
- 新增：`src/api/main.py`（FastAPI 服务）
- 新增：`src/proxy/main.py`（本地 HTTP Proxy）
- 新增：`scripts/migrate_to_postgres.py`（数据迁移脚本）
- 新增：`tests/test_backends.py`
- 新增：`tests/test_migration.py`
- 修改：`src/storage.py`（将 ExperienceStore 改为使用 backend）
- 修改：`src/knowledge.py`（接入新 backend）

**前置依赖（需先安装）：**
- `asyncpg>=0.29.0`
- `fastapi>=0.110.0`
- `uvicorn>=0.29.0`
- `pgvector>=0.2.0`

---

### Task 15: 定义 `StorageBackend` 抽象接口

**Files:**
- Create: `src/backends/__init__.py`
- Create: `src/backends/base.py`

**Step 1: 创建 `src/backends/__init__.py`（空文件）**

```python
```

**Step 2: 创建 `src/backends/base.py`**

```python
# src/backends/base.py
from abc import ABC, abstractmethod
from typing import Optional
from ..models import Experience, ExperienceStatus, Session, Feedback, ExperienceStats


class StorageBackend(ABC):

    @abstractmethod
    def add_experience(self, exp: Experience) -> Experience:
        ...

    @abstractmethod
    def get_experience(self, exp_id: str) -> Optional[Experience]:
        ...

    @abstractmethod
    def update_experience(self, exp: Experience) -> bool:
        ...

    @abstractmethod
    def delete_experience(self, exp_id: str) -> bool:
        ...

    @abstractmethod
    def list_by_status(self, status: ExperienceStatus) -> list[Experience]:
        ...

    @abstractmethod
    def record_session(self, session: Session):
        ...

    @abstractmethod
    def record_feedback(self, feedback: Feedback):
        ...

    @abstractmethod
    def get_experience_stats(self, exp_id: str) -> Optional[ExperienceStats]:
        ...

    @abstractmethod
    def save_vector(self, exp_id: str, vector: list[float]):
        ...

    @abstractmethod
    def get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> tuple[list[str], "np.ndarray"]:
        ...
```

**Step 3: 写接口存在性测试**

```python
# tests/test_backends.py
def test_storage_backend_is_abstract():
    from src.backends.base import StorageBackend
    import inspect
    assert inspect.isabstract(StorageBackend)
```

**Step 4: 运行测试**

```bash
pytest tests/test_backends.py::test_storage_backend_is_abstract -v
```

期望：`PASSED`

---

### Task 16: 实现 `LocalBackend`（包装现有 ExperienceStore）

**Files:**
- Create: `src/backends/local.py`

**Step 1: 创建 `src/backends/local.py`**

```python
# src/backends/local.py
from typing import Optional
import numpy as np

from .base import StorageBackend
from ..models import Experience, ExperienceStatus, Session, Feedback, ExperienceStats
from ..storage import ExperienceStore, MetricsStore, VectorStore


class LocalBackend(StorageBackend):
    def __init__(self):
        self._exp_store = ExperienceStore()
        self._metrics = MetricsStore()
        self._vectors = VectorStore()

    def add_experience(self, exp: Experience) -> Experience:
        return self._exp_store.add(exp)

    def get_experience(self, exp_id: str) -> Optional[Experience]:
        return self._exp_store.get(exp_id)

    def update_experience(self, exp: Experience) -> bool:
        return self._exp_store.update(exp)

    def delete_experience(self, exp_id: str) -> bool:
        return self._exp_store.delete(exp_id)

    def list_by_status(self, status: ExperienceStatus) -> list[Experience]:
        return self._exp_store.list_by_status(status)

    def record_session(self, session: Session):
        self._metrics.record_session(session)

    def record_feedback(self, feedback: Feedback):
        self._metrics.record_feedback(feedback)

    def get_experience_stats(self, exp_id: str) -> Optional[ExperienceStats]:
        return self._metrics.get_experience_stats(exp_id)

    def save_vector(self, exp_id: str, vector: list[float]):
        self._vectors.save_vector(exp_id, vector)

    def get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> tuple[list[str], np.ndarray]:
        return self._vectors.get_all_vectors(exp_ids)
```

**Step 2: 写 LocalBackend 测试**

在 `tests/test_backends.py` 追加：

```python
def test_local_backend_implements_interface(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.backends.local import LocalBackend
    from src.backends.base import StorageBackend
    backend = LocalBackend()
    assert isinstance(backend, StorageBackend)
```

**Step 3: 运行测试**

```bash
pytest tests/test_backends.py -v
```

期望：全部 `PASSED`

---

### Task 17: 实现 `PostgresBackend`

**Files:**
- Create: `src/backends/postgres.py`

**前置：确认 asyncpg 已安装**

```bash
python -c "import asyncpg; print(asyncpg.__version__)"
```

若报错，在 `pyproject.toml` 的 `dependencies` 中添加 `"asyncpg>=0.29.0"` 后运行 `pip install -e .`

**Step 1: 创建 `src/backends/postgres.py`**

```python
# src/backends/postgres.py
import json
import struct
from typing import Optional
from datetime import datetime

import asyncpg
import numpy as np

from .base import StorageBackend
from ..models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceMetadata,
    ExperienceSource, ExperienceStatus, Session, Feedback, ExperienceStats,
)

CREATE_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]',
    problem TEXT NOT NULL,
    solution TEXT NOT NULL,
    key_decisions TEXT NOT NULL DEFAULT '',
    confidence FLOAT NOT NULL DEFAULT 0.6,
    status TEXT NOT NULL DEFAULT 'pending',
    source TEXT NOT NULL DEFAULT 'agent',
    created_at TEXT NOT NULL,
    related_files JSONB NOT NULL DEFAULT '[]',
    reject_reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',
    file_hashes JSONB NOT NULL DEFAULT '{}',
    project TEXT NOT NULL DEFAULT 'default',
    last_hit_at TEXT,
    stale_reason TEXT,
    embedding vector(512)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    task_description TEXT NOT NULL,
    experience_ids_injected JSONB NOT NULL DEFAULT '[]',
    iteration_count INTEGER NOT NULL DEFAULT 1,
    had_error_correction BOOLEAN NOT NULL DEFAULT FALSE,
    user_accepted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TEXT NOT NULL,
    ab_test_group TEXT NOT NULL DEFAULT 'treatment',
    ab_test_result_shown BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    experience_id TEXT NOT NULL,
    adopted BOOLEAN NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experience_stats (
    experience_id TEXT PRIMARY KEY,
    hit_count INTEGER DEFAULT 0,
    adopted_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,
    last_used_at TEXT,
    last_adopted_at TEXT,
    adoption_rate FLOAT DEFAULT 0.0
);
"""


class PostgresBackend(StorageBackend):
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(self._dsn)
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_SCHEMA_SQL)

    async def close(self):
        if self._pool:
            await self._pool.close()

    def _pool_required(self):
        if not self._pool:
            raise RuntimeError("PostgresBackend not connected. Call await backend.connect() first.")

    def add_experience(self, exp: Experience) -> Experience:
        raise NotImplementedError("Use async_add_experience for PostgresBackend")

    async def async_add_experience(self, exp: Experience) -> Experience:
        self._pool_required()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO experiences
                   (id, type, level, title, tags, problem, solution, key_decisions,
                    confidence, status, source, created_at, related_files,
                    reject_reason, metadata, file_hashes, project, last_hit_at, stale_reason)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)""",
                exp.id, exp.type.value, exp.level.value, exp.title,
                json.dumps(exp.tags, ensure_ascii=False),
                exp.problem, exp.solution, exp.key_decisions,
                exp.confidence, exp.status.value, exp.source.value, exp.created_at,
                json.dumps(exp.related_files, ensure_ascii=False),
                exp.reject_reason,
                json.dumps({
                    "tech_stack": exp.metadata.tech_stack,
                    "problem_type": exp.metadata.problem_type,
                    "scene": exp.metadata.scene,
                }, ensure_ascii=False),
                json.dumps(exp.file_hashes, ensure_ascii=False),
                exp.project, exp.last_hit_at, exp.stale_reason,
            )
        return exp

    def get_experience(self, exp_id: str) -> Optional[Experience]:
        raise NotImplementedError("Use async_get_experience for PostgresBackend")

    async def async_get_experience(self, exp_id: str) -> Optional[Experience]:
        self._pool_required()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM experiences WHERE id = $1", exp_id)
        if not row:
            return None
        return self._row_to_experience(row)

    def update_experience(self, exp: Experience) -> bool:
        raise NotImplementedError("Use async_update_experience for PostgresBackend")

    async def async_update_experience(self, exp: Experience) -> bool:
        self._pool_required()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE experiences SET
                   title=$2, problem=$3, solution=$4, key_decisions=$5,
                   confidence=$6, status=$7, reject_reason=$8, metadata=$9,
                   related_files=$10, last_hit_at=$11, stale_reason=$12, tags=$13
                   WHERE id=$1""",
                exp.id, exp.title, exp.problem, exp.solution, exp.key_decisions,
                exp.confidence, exp.status.value, exp.reject_reason,
                json.dumps({
                    "tech_stack": exp.metadata.tech_stack,
                    "problem_type": exp.metadata.problem_type,
                    "scene": exp.metadata.scene,
                }, ensure_ascii=False),
                json.dumps(exp.related_files, ensure_ascii=False),
                exp.last_hit_at, exp.stale_reason,
                json.dumps(exp.tags, ensure_ascii=False),
            )
        return result != "UPDATE 0"

    def delete_experience(self, exp_id: str) -> bool:
        raise NotImplementedError("Use async_delete_experience for PostgresBackend")

    async def async_delete_experience(self, exp_id: str) -> bool:
        self._pool_required()
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM experiences WHERE id = $1", exp_id)
        return result != "DELETE 0"

    def list_by_status(self, status: ExperienceStatus) -> list[Experience]:
        raise NotImplementedError("Use async_list_by_status for PostgresBackend")

    async def async_list_by_status(self, status: ExperienceStatus) -> list[Experience]:
        self._pool_required()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM experiences WHERE status = $1", status.value)
        return [self._row_to_experience(r) for r in rows]

    def record_session(self, session: Session):
        raise NotImplementedError("Use async_record_session for PostgresBackend")

    async def async_record_session(self, session: Session):
        self._pool_required()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO sessions
                   (session_id, task_description, experience_ids_injected,
                    iteration_count, had_error_correction, user_accepted,
                    created_at, ab_test_group, ab_test_result_shown)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (session_id) DO NOTHING""",
                session.session_id, session.task_description,
                json.dumps(session.experience_ids_injected),
                session.iteration_count, session.had_error_correction,
                session.user_accepted, session.created_at,
                session.ab_test_group, session.ab_test_result_shown,
            )

    def record_feedback(self, feedback: Feedback):
        raise NotImplementedError("Use async_record_feedback for PostgresBackend")

    async def async_record_feedback(self, feedback: Feedback):
        self._pool_required()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO feedback (experience_id, adopted, reason, created_at) VALUES ($1,$2,$3,$4)",
                feedback.experience_id, feedback.adopted, feedback.reason, feedback.created_at,
            )
            await conn.execute(
                """INSERT INTO experience_stats (experience_id, hit_count, adopted_count, rejected_count)
                   VALUES ($1, 1, $2, $3)
                   ON CONFLICT (experience_id) DO UPDATE SET
                   hit_count = experience_stats.hit_count + 1,
                   adopted_count = experience_stats.adopted_count + $2,
                   rejected_count = experience_stats.rejected_count + $3,
                   last_used_at = $4,
                   adoption_rate = ROUND(
                       (experience_stats.adopted_count + $2)::FLOAT /
                       NULLIF(experience_stats.hit_count + 1, 0), 3
                   )""",
                feedback.experience_id,
                1 if feedback.adopted else 0,
                0 if feedback.adopted else 1,
                feedback.created_at,
            )

    def get_experience_stats(self, exp_id: str) -> Optional[ExperienceStats]:
        raise NotImplementedError("Use async_get_experience_stats for PostgresBackend")

    async def async_get_experience_stats(self, exp_id: str) -> Optional[ExperienceStats]:
        self._pool_required()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM experience_stats WHERE experience_id = $1", exp_id)
        if not row:
            return None
        return ExperienceStats(
            experience_id=row["experience_id"],
            hit_count=row["hit_count"],
            adopted_count=row["adopted_count"],
            rejected_count=row["rejected_count"],
            last_used_at=row["last_used_at"],
            last_adopted_at=row["last_adopted_at"],
            adoption_rate=row["adoption_rate"],
        )

    def save_vector(self, exp_id: str, vector: list[float]):
        raise NotImplementedError("Use async_save_vector for PostgresBackend")

    async def async_save_vector(self, exp_id: str, vector: list[float]):
        self._pool_required()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE experiences SET embedding = $2 WHERE id = $1",
                exp_id, vector,
            )

    def get_all_vectors(self, exp_ids: Optional[list[str]] = None):
        raise NotImplementedError("Use async_get_all_vectors for PostgresBackend")

    async def async_get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> tuple[list[str], np.ndarray]:
        self._pool_required()
        async with self._pool.acquire() as conn:
            if exp_ids is not None:
                if not exp_ids:
                    return [], np.array([])
                rows = await conn.fetch(
                    f"SELECT id, embedding FROM experiences WHERE id = ANY($1) AND embedding IS NOT NULL",
                    exp_ids,
                )
            else:
                rows = await conn.fetch("SELECT id, embedding FROM experiences WHERE embedding IS NOT NULL")
        if not rows:
            return [], np.array([])
        ids = [r["id"] for r in rows]
        vecs = np.array([list(r["embedding"]) for r in rows], dtype=np.float32)
        return ids, vecs

    def _row_to_experience(self, row) -> Experience:
        meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
        return Experience(
            id=row["id"],
            type=ExperienceType(row["type"]),
            level=ExperienceLevel(row["level"]),
            title=row["title"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else list(row["tags"]),
            problem=row["problem"],
            solution=row["solution"],
            key_decisions=row["key_decisions"],
            confidence=row["confidence"],
            status=ExperienceStatus(row["status"]),
            source=ExperienceSource(row["source"]),
            created_at=row["created_at"],
            related_files=json.loads(row["related_files"]) if isinstance(row["related_files"], str) else list(row["related_files"]),
            reject_reason=row["reject_reason"],
            metadata=ExperienceMetadata(
                tech_stack=meta.get("tech_stack", []),
                problem_type=meta.get("problem_type", ""),
                scene=meta.get("scene", []),
            ),
            file_hashes=json.loads(row["file_hashes"]) if isinstance(row["file_hashes"], str) else dict(row["file_hashes"]),
            project=row["project"],
            last_hit_at=row["last_hit_at"],
            stale_reason=row["stale_reason"],
        )
```

**Step 2: 写 PostgresBackend 集成测试（需要本地 PostgreSQL）**

```python
# tests/test_backends.py 追加
import os
import pytest


POSTGRES_DSN = os.environ.get("TEST_POSTGRES_DSN", "")


@pytest.mark.skipif(not POSTGRES_DSN, reason="TEST_POSTGRES_DSN not set")
async def test_postgres_backend_add_and_get(tmp_path):
    from src.backends.postgres import PostgresBackend
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource,
    )
    import uuid
    from datetime import datetime

    backend = PostgresBackend(POSTGRES_DSN)
    await backend.connect()

    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="PostgreSQL 测试经验",
        tags=["python"],
        problem="测试问题",
        solution="测试解决方案",
        key_decisions="测试关键决策",
        confidence=0.8,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
    )

    await backend.async_add_experience(exp)
    loaded = await backend.async_get_experience(exp.id)

    assert loaded is not None
    assert loaded.title == exp.title
    assert loaded.key_decisions == exp.key_decisions

    await backend.async_delete_experience(exp.id)
    await backend.close()
```

**Step 3: 运行单元测试（跳过 PG 集成测试）**

```bash
pytest tests/test_backends.py -v -k "not postgres"
```

期望：`PASSED`

---

### Task 18: 实现数据迁移脚本

**Files:**
- Create: `scripts/migrate_to_postgres.py`

**Step 1: 创建迁移脚本**

```python
#!/usr/bin/env python3
# scripts/migrate_to_postgres.py
"""
将本地 JSON + SQLite 数据迁移到 PostgreSQL。
支持续跑（checkpoint），支持回滚（切换 XP_BACKEND 即可）。

用法:
    python scripts/migrate_to_postgres.py --dsn postgresql://user:pass@host/dbname
    python scripts/migrate_to_postgres.py --dsn ... --dry-run   # 只预检，不写入
"""
import argparse
import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


async def preflight_check(json_path: Path) -> dict:
    if not json_path.exists():
        return {"total": 0, "missing_vectors": [], "ok": True}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    total = len(data)
    missing_vectors = [eid for eid, v in data.items() if not v.get("solution")]
    return {"total": total, "missing_vectors": missing_vectors, "ok": True}


async def backup_source(xp_home: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = xp_home / "backup" / f"migrate_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["knowledge.json", "metrics.db"]:
        src = xp_home / fname
        if src.exists():
            shutil.copy2(src, backup_dir / fname)
    return backup_dir


async def migrate(dsn: str, xp_home: Path, dry_run: bool = False, batch_size: int = 100):
    from src.backends.postgres import PostgresBackend
    from src.storage import ExperienceStore, VectorStore
    from src.models import ExperienceStatus

    json_path = xp_home / "knowledge.json"
    checkpoint_path = xp_home / "migrate_checkpoint.json"

    # Pre-flight check
    print("=== Pre-flight check ===")
    result = await preflight_check(json_path)
    print(f"Source total: {result['total']} experiences")
    if result["missing_vectors"]:
        print(f"Warning: {len(result['missing_vectors'])} experiences missing solution field")

    if dry_run:
        print("[DRY RUN] No data will be written.")
        return

    # Backup
    print("\n=== Backing up source data ===")
    backup_dir = await backup_source(xp_home)
    print(f"Backup saved to: {backup_dir}")

    # Load checkpoint
    migrated_ids: set[str] = set()
    if checkpoint_path.exists():
        migrated_ids = set(json.loads(checkpoint_path.read_text())["migrated"])
        print(f"Resuming from checkpoint: {len(migrated_ids)} already migrated")

    # Connect to PG
    backend = PostgresBackend(dsn)
    await backend.connect()

    # Load all experiences
    exp_store = ExperienceStore()
    v_store = VectorStore()
    all_exps = []
    for status in ExperienceStatus:
        all_exps.extend(exp_store.list_by_status(status))

    to_migrate = [e for e in all_exps if e.id not in migrated_ids]
    print(f"\n=== Migrating {len(to_migrate)} experiences ===")

    # Batch write
    for i in range(0, len(to_migrate), batch_size):
        batch = to_migrate[i:i + batch_size]
        for exp in batch:
            await backend.async_add_experience(exp)
            # Migrate vector
            vec = v_store.get_vector(exp.id)
            if vec is not None:
                await backend.async_save_vector(exp.id, vec.tolist())
            migrated_ids.add(exp.id)

        # Save checkpoint
        checkpoint_path.write_text(json.dumps({"migrated": list(migrated_ids)}))
        print(f"Progress: {min(i + batch_size, len(to_migrate))}/{len(to_migrate)}")

    # Post-migration check
    print("\n=== Post-migration check ===")
    pg_count = len(await backend.async_list_by_status(ExperienceStatus.ACTIVE))
    local_count = len(exp_store.list_by_status(ExperienceStatus.ACTIVE))
    print(f"Local active count: {local_count}")
    print(f"PG active count:    {pg_count}")
    if pg_count != local_count:
        print("WARNING: Count mismatch! Check logs and consider rollback.")
    else:
        print("Count check PASSED")

    await backend.close()
    print(f"\nMigration complete. To switch backend: export XP_BACKEND=postgres")
    print(f"To rollback: export XP_BACKEND=local  (source files preserved for 30 days)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    xp_home = Path(os.environ.get("XP_HOME", "/Users/lianzimeng/workspace/xp-data"))
    asyncio.run(migrate(args.dsn, xp_home, args.dry_run, args.batch_size))


if __name__ == "__main__":
    main()
```

**Step 2: 写迁移脚本预检测试**

```python
# tests/test_migration.py
import json
import pytest


async def test_preflight_check_empty():
    from scripts.migrate_to_postgres import preflight_check
    from pathlib import Path
    result = await preflight_check(Path("/nonexistent/knowledge.json"))
    assert result["total"] == 0
    assert result["ok"] is True


async def test_preflight_check_with_data(tmp_path):
    from scripts.migrate_to_postgres import preflight_check
    import uuid
    data = {
        str(uuid.uuid4()): {"solution": "some solution"},
        str(uuid.uuid4()): {},  # missing solution
    }
    json_path = tmp_path / "knowledge.json"
    json_path.write_text(json.dumps(data))
    result = await preflight_check(json_path)
    assert result["total"] == 2
    assert len(result["missing_vectors"]) == 1
```

**Step 3: 运行迁移测试**

```bash
pytest tests/test_migration.py -v
```

期望：全部 `PASSED`

---

### Task 19: 配置切换逻辑（XP_BACKEND 环境变量）

**Files:**
- Modify: `src/storage.py`
- Modify: `src/knowledge.py`

**目标：** 在 `storage.py` 新增 `get_backend()` 工厂函数，根据 `XP_BACKEND` 环境变量返回 `LocalBackend` 或 `PostgresBackend`。

**Step 1: 在 `src/storage.py` 末尾追加**

```python
def get_backend():
    backend_type = os.environ.get("XP_BACKEND", "local")
    if backend_type == "postgres":
        dsn = os.environ.get("XP_POSTGRES_DSN", "")
        if not dsn:
            raise RuntimeError("XP_BACKEND=postgres 但未设置 XP_POSTGRES_DSN")
        from ..backends.postgres import PostgresBackend
        return PostgresBackend(dsn)
    from ..backends.local import LocalBackend
    return LocalBackend()
```

**Step 2: 写配置切换测试**

```python
# tests/test_backends.py 追加
def test_get_backend_defaults_to_local(monkeypatch):
    monkeypatch.delenv("XP_BACKEND", raising=False)
    monkeypatch.delenv("XP_POSTGRES_DSN", raising=False)
    from src.storage import get_backend
    from src.backends.local import LocalBackend
    # 注意：需要 monkeypatch XP_HOME 避免污染真实数据
    backend = get_backend()
    assert isinstance(backend, LocalBackend)


def test_get_backend_postgres_requires_dsn(monkeypatch):
    monkeypatch.setenv("XP_BACKEND", "postgres")
    monkeypatch.delenv("XP_POSTGRES_DSN", raising=False)
    from src.storage import get_backend
    with pytest.raises(RuntimeError, match="XP_POSTGRES_DSN"):
        get_backend()
```

**Step 3: 运行全量测试**

```bash
pytest tests/ -v
```

期望：所有测试 `PASSED`

---

### Task 20: 最终验收

**Step 1: 运行完整测试套件**

```bash
pytest tests/ -v --tb=short
```

期望：所有测试 `PASSED`，覆盖以下场景：
- `test_finalize_task.py`：finalize_task 容错路径 100%
- `test_quality_score.py`：质量评分三级策略
- `test_review_refactor.py`：review `[e]`/`[b]`/`[n]` + Admin 权限
- `test_backends.py`：StorageBackend 接口 + LocalBackend
- `test_migration.py`：迁移预检 + 分批写入逻辑

**Step 2: 检查 finalize_task 工具在 MCP 中可见**

```bash
python -c "import asyncio; from src.server import list_tools; tools = asyncio.run(list_tools()); print([t.name for t in tools])"
```

期望输出包含：`['extract_experience', 'search_best_practices', 'record_session', 'record_feedback', 'infer_adoption', 'finalize_task']`

**Step 3: 手动验收 `xp review` 新操作**

```bash
xp add   # 添加一条经验
xp review  # 验证 [e]/[b] 选项出现
```

---

## 注意事项

### 第一阶段常见坑
- `finalize_task` 内部的 `extract_experience` 调用抛出的是 `ValueError`（质量门控）或 `RuntimeError`（重复检测），两者都需要 `except Exception` 捕获
- `Session` 的 `ab_test_group` 默认值在 `models.py` 里是 `"control"`，但 `finalize_task` 写入时应传 `"treatment"`

### 第二阶段常见坑
- `_compute_quality_score` 在 `extract_experience` 中调用时，`duplicate_similarity` 参数无法预先知道（还没做重复检测），默认传 `0.0` 即可（得 10 分）
- `[e]` 编辑确认调用 `edit_and_confirm` 时，该方法是 `async` 的，在 `cmd_review`（同步函数）中需要 `asyncio.run()`

### 第三阶段常见坑
- `asyncpg` 的 vector 类型需要额外注册解码器，或通过 `pgvector` 库处理；推荐使用 `python-pgvector` 包的 `register_vector(conn)` 方法
- 迁移脚本中 `VectorStore.get_vector` 返回 `np.ndarray`，写入 PG 前需要调用 `.tolist()` 转为 Python list
- `PostgresBackend` 的同步方法（`add_experience` 等）主动 raise `NotImplementedError` 是设计决策，确保调用方使用 async 版本
