# Experience Extraction 质量优化实现计划

**Goal:** 提升经验沉淀质量——通过 LLM 生成标题、写入去重、质量门槛拦截、key_decisions 独立存储，改善知识库信噪比和检索精度。

**Architecture:** 在 `extract_experience` 入口加质量门槛（拒绝低质量输入），用 LLM 生成更好的 title，写入前做向量去重检测，`key_decisions` 独立存为 `Experience` 字段并单独参与向量化（替换原来的 `title+problem+solution` 方案）。

**Tech Stack:** Python, SQLite, sentence-transformers (BGE-small-zh), OpenAI API (可选，LLM title 生成)

---

### Task 1: Experience 模型新增 key_decisions 字段

**Files:**
- Modify: `src/models.py`
- Modify: `src/storage.py`

背景：当前 `key_decisions` 被拼接进 `solution` 字段，无法单独利用。需要在 `Experience` 数据类上独立存储。

**Step 1: 在 Experience dataclass 新增字段**

打开 `src/models.py`，在 `Experience` 的 `stale_reason` 字段之后，新增一行：

```python
key_decisions: str = ""
```

即在 `stale_reason: Optional[str] = None` 后加入（保持在 `__post_init__` 之前，如果有的话）。

完整字段末尾部分应该是：
```python
    last_hit_at: Optional[str] = None
    stale_reason: Optional[str] = None
    key_decisions: str = ""
```

**Step 2: 更新 _to_dict 添加序列化**

在 `src/storage.py` 的 `ExperienceStore._to_dict` 方法末尾，`stale_reason` 的下面加入：

```python
            "key_decisions": exp.key_decisions,
```

**Step 3: 更新 _from_dict 添加反序列化（向后兼容）**

在 `src/storage.py` 的 `ExperienceStore._from_dict` 方法中，`return Experience(...)` 的参数列表里，`stale_reason=d.get("stale_reason"),` 之后加入：

```python
            key_decisions=d.get("key_decisions", ""),
```

**Step 4: 写单元测试**

在 `tests/test_extraction_refactor.py` 中创建新文件，写以下测试：

```python
import pytest


def make_store(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore
    return ExperienceStore()


def test_key_decisions_roundtrip(tmp_path, monkeypatch):
    """key_decisions 能正常序列化和反序列化"""
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
    )
    import uuid
    from datetime import datetime

    store = make_store(tmp_path, monkeypatch)
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="测试标题",
        tags=[],
        problem="测试问题",
        solution="测试解决方案",
        confidence=0.8,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        key_decisions="这是关键决策，不要在 useEffect 直接 setState",
    )
    store.add(exp)
    loaded = store.get(exp.id)
    assert loaded is not None
    assert loaded.key_decisions == "这是关键决策，不要在 useEffect 直接 setState"


def test_key_decisions_backward_compat(tmp_path, monkeypatch):
    """旧数据（无 key_decisions 字段）反序列化时默认为空字符串"""
    import json
    import uuid
    from datetime import datetime

    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    exp_id = str(uuid.uuid4())
    old_data = {
        exp_id: {
            "id": exp_id,
            "type": "bugfix",
            "level": "L2",
            "title": "旧经验",
            "tags": [],
            "problem": "旧问题",
            "solution": "旧解决方案",
            "confidence": 0.8,
            "status": "active",
            "source": "agent",
            "created_at": datetime.utcnow().isoformat(),
        }
    }
    knowledge_file = tmp_path / "knowledge.json"
    knowledge_file.write_text(json.dumps(old_data), encoding="utf-8")

    from src.storage import ExperienceStore
    store = ExperienceStore()
    loaded = store.get(exp_id)
    assert loaded is not None
    assert loaded.key_decisions == ""
```

**Step 5: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py -v
```

预期：2 个测试全部 PASS

---

### Task 2: 质量门槛 — 拒绝低质量输入

**Files:**
- Modify: `src/knowledge.py`
- Test: `tests/test_extraction_refactor.py`

背景：当前任何调用都写入，导致知识库充斥无价值的经验。需要在 `extract_experience` 入口加前置校验。

**Step 1: 写失败测试**

在 `tests/test_extraction_refactor.py` 末尾追加：

```python
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


@pytest.mark.asyncio
async def test_quality_gate_rejects_empty_key_decisions(service):
    """key_decisions 为空时应拒绝写入"""
    with pytest.raises(ValueError, match="key_decisions"):
        await service.extract_experience(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码",
            key_decisions="",
        )


@pytest.mark.asyncio
async def test_quality_gate_rejects_short_key_decisions(service):
    """key_decisions 少于 10 字时应拒绝写入"""
    with pytest.raises(ValueError, match="key_decisions"):
        await service.extract_experience(
            task_description="修复登录 bug",
            solution_summary="找到了根本原因并修复了代码",
            key_decisions="注意一下",
        )


@pytest.mark.asyncio
async def test_quality_gate_rejects_short_solution(service):
    """solution_summary 少于 20 字时应拒绝写入"""
    with pytest.raises(ValueError, match="solution_summary"):
        await service.extract_experience(
            task_description="修复登录 bug",
            solution_summary="改了代码",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        )
```

注意：需要 `pytest-asyncio`。检查 `requirements.txt` 是否已有。

**Step 2: 运行确认测试失败**

```
pytest tests/test_extraction_refactor.py::test_quality_gate_rejects_empty_key_decisions -v
```

预期：FAIL（因为 `extract_experience` 目前不会抛 ValueError）

**Step 3: 在 extract_experience 开头加质量校验**

在 `src/knowledge.py` 的 `async def extract_experience` 方法体最开始（`tags = tags or []` 之前）加入：

```python
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
```

**Step 4: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py -v -k "quality_gate"
```

预期：3 个质量门槛测试全部 PASS

---

### Task 3: key_decisions 独立存储（不再拼接进 solution）

**Files:**
- Modify: `src/knowledge.py`
- Test: `tests/test_extraction_refactor.py`

背景：当前 `extract_experience` 把 `key_decisions` 拼接进 `solution` 字段（`solution=f"{solution_summary}\n\n关键决策：{key_decisions}"`），导致语义混用，向量匹配噪音大。

**Step 1: 写失败测试**

在 `tests/test_extraction_refactor.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_key_decisions_stored_separately(service, monkeypatch):
    """key_decisions 应独立存储，solution 只含 solution_summary"""
    from src.embeddings import EmbeddingProvider, set_provider
    import numpy as np

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    assert exp.key_decisions == "不要在 useEffect 里直接调用 setState，会导致无限循环"
    assert "关键决策" not in exp.solution
    assert exp.solution == "在 token 过期时自动刷新，并存入 localStorage，确保状态持久化"
```

**Step 2: 运行确认测试失败**

```
pytest tests/test_extraction_refactor.py::test_key_decisions_stored_separately -v
```

预期：FAIL（因为当前 solution 还是拼接的）

**Step 3: 修改 extract_experience 中 Experience 构建部分**

在 `src/knowledge.py` 的 `extract_experience` 方法中，找到 `Experience(...)` 构建代码：

将：
```python
            solution=f"{solution_summary}\n\n关键决策：{key_decisions}",
```

改为：
```python
            solution=solution_summary,
            key_decisions=key_decisions,
```

**Step 4: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py::test_key_decisions_stored_separately -v
```

预期：PASS

---

### Task 4: 向量化改用 title + problem + key_decisions

**Files:**
- Modify: `src/knowledge.py`
- Test: `tests/test_extraction_refactor.py`

背景：当前经验向量内容是 `title + problem + solution`，solution 的存在会干扰匹配精度。改为 `title + problem + key_decisions`，聚焦"这个问题是什么、关键坑在哪"。

需要同步修改 3 处：
1. `extract_experience` 中保存向量时
2. `search` 中补全缺失向量时
3. `infer_adoption` 中补全缺失向量时
4. `edit_and_confirm` 中重新生成向量时

**Step 1: 写失败测试（验证向量化文本内容）**

在 `tests/test_extraction_refactor.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_vectorization_uses_key_decisions_not_solution(service, monkeypatch):
    """向量化应使用 title+problem+key_decisions，而非 solution"""
    from src.embeddings import EmbeddingProvider, set_provider
    from src.storage import VectorStore

    captured_texts = []

    class CapturingProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            captured_texts.extend(texts)
            return [[0.1] * 64 for _ in texts]

    set_provider(CapturingProvider())

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    # 向量化文本应包含 key_decisions，不应包含 solution_summary
    assert any("不要在 useEffect" in t for t in captured_texts), \
        f"向量文本应包含 key_decisions，实际: {captured_texts}"
    assert not any("localStorage" in t for t in captured_texts), \
        f"向量文本不应包含 solution_summary，实际: {captured_texts}"
```

**Step 2: 运行确认测试失败**

```
pytest tests/test_extraction_refactor.py::test_vectorization_uses_key_decisions_not_solution -v
```

预期：FAIL（当前向量包含 solution）

**Step 3: 修改 extract_experience 中向量化文本**

在 `src/knowledge.py` 的 `extract_experience` 末尾，找到：

```python
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.solution}"
```

改为：

```python
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.key_decisions}"
```

**Step 4: 修改 search 中补全缺失向量的文本**

在 `search` 方法中，找到：

```python
            missing_texts = [f"{e.title}\n{e.problem}\n{e.solution}" for e in missing_exps]
```

改为：

```python
            missing_texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in missing_exps]
```

**Step 5: 修改 infer_adoption 中补全缺失向量的文本**

在 `infer_adoption` 方法中，找到：

```python
                missing_texts = [f"{e.title}\n{e.problem}\n{e.solution}" for e in missing_exps]
```

改为：

```python
                missing_texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in missing_exps]
```

**Step 6: 修改 edit_and_confirm 中重新生成向量的文本**

在 `edit_and_confirm` 方法中，找到：

```python
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.solution}"
```

改为：

```python
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.key_decisions}"
```

**Step 7: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py::test_vectorization_uses_key_decisions_not_solution -v
```

预期：PASS

---

### Task 5: LLM 生成 title（失败降级）

**Files:**
- Modify: `src/knowledge.py`
- Test: `tests/test_extraction_refactor.py`

背景：当前 `_make_title` 直接截断 task_description 前 60 字，生成的标题质量差。改为调用 LLM 生成 10-15 字标题，LLM 调用失败时降级为截断逻辑。

**Step 1: 写测试**

在 `tests/test_extraction_refactor.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_llm_title_generation_success(service, monkeypatch):
    """LLM 调用成功时，title 应使用 LLM 生成的值"""
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def fake_llm_title(text):
        return "登录状态不保持修复"

    monkeypatch.setattr(service, "_llm_generate_title", fake_llm_title)

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    assert exp.title == "登录状态不保持修复"


@pytest.mark.asyncio
async def test_llm_title_generation_fallback(service, monkeypatch):
    """LLM 调用失败时，title 应降级为截断 task_description"""
    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    async def failing_llm_title(text):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(service, "_llm_generate_title", failing_llm_title)

    exp = await service.extract_experience(
        task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
    )

    assert exp.title.startswith("修复登录后状态不保持")
```

**Step 2: 运行确认测试失败**

```
pytest tests/test_extraction_refactor.py -v -k "llm_title"
```

预期：FAIL（服务没有 `_llm_generate_title` 方法）

**Step 3: 在 KnowledgeService 添加 _llm_generate_title 方法**

在 `src/knowledge.py` 的 `KnowledgeService` 类中，`_make_title` 方法之前，新增：

```python
    async def _llm_generate_title(self, task_description: str) -> str:
        import os
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("XP_LLM_API_KEY")
        api_base = os.getenv("XP_LLM_API_BASE")
        model = os.getenv("XP_LLM_MODEL", "gpt-4o-mini")
        if not api_key:
            raise RuntimeError("No LLM API key configured")
        import openai
        client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base)
        prompt = f"用10-15个字总结以下任务，只输出标题，不加标点：\n{task_description}"
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()
```

**Step 4: 修改 extract_experience 中 title 生成逻辑**

在 `extract_experience` 方法中，找到构建 `Experience` 的地方，`title=self._make_title(task_description),` 改为先用 LLM 生成，失败时降级：

在 `exp = Experience(...)` 之前加入：

```python
        try:
            title = await self._llm_generate_title(task_description)
        except Exception:
            title = self._make_title(task_description)
```

并将 `Experience(...)` 中的：

```python
            title=self._make_title(task_description),
```

改为：

```python
            title=title,
```

**Step 5: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py -v -k "llm_title"
```

预期：2 个 LLM title 测试 PASS

---

### Task 6: 写入时去重检测

**Files:**
- Modify: `src/knowledge.py`
- Test: `tests/test_extraction_refactor.py`

背景：相同经验被重复提取是噪音主要来源。在 `extract_experience` 存入前，用 `title + problem` 向量检索，若找到相似度 >= 0.85 的已有经验，返回重复提示而非新建。

**Step 1: 写失败测试**

在 `tests/test_extraction_refactor.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_dedup_raises_on_similar_experience(service, monkeypatch):
    """写入与已有经验高度相似的经验时，应抛出 ValueError 包含重复 ID"""
    from src.embeddings import EmbeddingProvider, set_provider
    from src.models import ExperienceStatus

    call_count = [0]

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            call_count[0] += 1
            # 所有文本返回相同向量，模拟高度相似
            return [[0.9] * 64 for _ in texts]

    set_provider(FakeProvider())

    # 先写入一条 active 经验
    import uuid
    from datetime import datetime
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
    )
    from src.storage import VectorStore

    exp_id = str(uuid.uuid4())
    existing = Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L2,
        title="登录状态不保持修复",
        tags=[],
        problem="修复登录后状态不保持的 bug",
        solution="token 自动刷新",
        key_decisions="不要在 useEffect 里直接 setState",
        confidence=0.8,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
    )
    service._store.add(existing)
    VectorStore().save_vector(exp_id, [0.9] * 64)

    with pytest.raises(ValueError, match=exp_id[:8]):
        await service.extract_experience(
            task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
            solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        )
```

**Step 2: 运行确认测试失败**

```
pytest tests/test_extraction_refactor.py::test_dedup_raises_on_similar_experience -v
```

预期：FAIL（目前没有去重逻辑）

**Step 3: 在 extract_experience 中添加去重检查**

在质量校验之后，`title` 生成之前，加入去重检查逻辑。在 `try: title = await self._llm_generate_title(...)` 的上方插入：

```python
        await self._check_duplicate(task_description, solution_summary)
```

然后在 `KnowledgeService` 中新增 `_check_duplicate` 方法（放在 `_llm_generate_title` 之前）：

```python
    async def _check_duplicate(self, task_description: str, solution_summary: str):
        from .embeddings import get_provider, cosine_similarity
        from .storage import VectorStore
        import numpy as np

        candidates = self._store.list_active()
        if not candidates:
            return

        provider = get_provider()
        check_text = f"{task_description}\n{solution_summary}"
        query_vec = np.array(provider.embed_text(check_text), dtype=np.float32)

        v_store = VectorStore()
        candidate_ids = [e.id for e in candidates]
        ids, vecs = v_store.get_all_vectors(candidate_ids)

        if len(vecs) == 0:
            return

        scores = cosine_similarity(query_vec, vecs)
        for exp_id, score in zip(ids, scores):
            if float(score) >= 0.85:
                id_to_exp = {e.id: e for e in candidates}
                dup_exp = id_to_exp.get(exp_id)
                dup_title = dup_exp.title if dup_exp else exp_id[:8]
                raise ValueError(
                    f"已存在高度相似的经验（相似度 {score:.2f}）：[{exp_id[:8]}] {dup_title}。"
                    f"建议复用或用 `xp edit {exp_id[:8]}` 更新已有经验，而非新增。"
                )
```

**Step 4: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py::test_dedup_raises_on_similar_experience -v
```

预期：PASS

---

### Task 7: xp review 单独展示 key_decisions

**Files:**
- Modify: `src/cli.py`
- Test: `tests/test_extraction_refactor.py`

背景：`xp review` 目前只展示 `solution` 字段（里面当前拼着 key_decisions），需要单独展示 `key_decisions` 字段，突出"坑"的信息。

**Step 1: 写测试**

在 `tests/test_extraction_refactor.py` 末尾追加：

```python
def test_review_shows_key_decisions(tmp_path, monkeypatch, capsys):
    """xp review 应单独展示 key_decisions 字段"""
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.storage import ExperienceStore, MetricsStore
    import uuid
    from datetime import datetime
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
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
        confidence=0.8,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
    )
    store.add(exp)

    # 模拟用户输入 'q' 退出
    monkeypatch.setattr("builtins.input", lambda _: "q")

    from src.cli import cmd_review
    cmd_review([])

    captured = capsys.readouterr()
    assert "关键决策" in captured.out
    assert "重要坑：不要直接修改 state" in captured.out
```

**Step 2: 运行确认测试失败**

```
pytest tests/test_extraction_refactor.py::test_review_shows_key_decisions -v
```

预期：FAIL（当前 review 没有展示 key_decisions）

**Step 3: 修改 cmd_review 添加 key_decisions 展示**

在 `src/cli.py` 的 `cmd_review` 函数中，找到：

```python
        print(f"\n  解决方案:\n  {exp.solution[:500]}")
```

在其后面加入：

```python
        if exp.key_decisions:
            print(f"\n  关键决策/踩坑点:\n  {exp.key_decisions[:300]}")
```

**Step 4: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py::test_review_shows_key_decisions -v
```

预期：PASS

---

### Task 8: server.py 响应中透出 key_decisions

**Files:**
- Modify: `src/server.py`
- Test: `tests/test_extraction_refactor.py`

背景：`extract_experience` 工具的 MCP 响应中目前没有返回 `key_decisions` 字段，agent 无法确认自己的 key_decisions 是否被独立存储。

**Step 1: 写测试**

在 `tests/test_extraction_refactor.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_server_extract_response_includes_key_decisions(tmp_path, monkeypatch):
    """server 的 extract_experience 响应应包含 key_decisions 字段"""
    import json
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.embeddings import EmbeddingProvider, set_provider

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    import src.server as server_mod
    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService

    async def fake_llm_title(self, text):
        raise RuntimeError("no llm")

    monkeypatch.setattr(KnowledgeService, "_llm_generate_title", fake_llm_title)

    service = KnowledgeService(ExperienceStore(), MetricsStore())
    monkeypatch.setattr(server_mod, "_service", service)

    result = await server_mod.call_tool("extract_experience", {
        "task_description": "修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
        "solution_summary": "在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
        "key_decisions": "不要在 useEffect 里直接调用 setState，会导致无限循环",
    })

    data = json.loads(result[0].text)
    assert "key_decisions" in data
    assert data["key_decisions"] == "不要在 useEffect 里直接调用 setState，会导致无限循环"
```

**Step 2: 运行确认测试失败**

```
pytest tests/test_extraction_refactor.py::test_server_extract_response_includes_key_decisions -v
```

预期：FAIL

**Step 3: 修改 server.py 的 extract_experience 响应**

在 `src/server.py` 的 `call_tool` 函数中，找到 `extract_experience` 分支的 `return [TextContent(...)]`，在 JSON 响应中加入 `key_decisions`：

找到：
```python
                "message": "经验已提取，等待人工 review。运行 `xp review` 查看并确认。",
```

在其之前，`"level": exp.level.value,` 下面加入：

```python
                "key_decisions": exp.key_decisions,
```

**Step 4: 运行测试确认通过**

```
pytest tests/test_extraction_refactor.py::test_server_extract_response_includes_key_decisions -v
```

预期：PASS

---

### Task 9: 运行全部测试，确认无回归

**Files:** 无新增文件

**Step 1: 运行新测试文件全部测试**

```
pytest tests/test_extraction_refactor.py -v
```

预期：全部 PASS（约 12 个测试）

**Step 2: 运行原有测试确认无回归**

```
pytest tests/ -v
```

预期：全部 PASS，无 FAIL

**Step 3: 如有失败，修复后重新运行直至全部通过**

注意：
- `test_stats_metrics.py` 中的测试使用 `monkeypatch` 隔离 storage，不受影响
- 若遇到 `pytest-asyncio` 未安装，运行 `pip install pytest-asyncio` 并在 `tests/test_extraction_refactor.py` 顶部加入：
  ```python
  import pytest
  pytestmark = pytest.mark.asyncio
  ```
  或在根目录添加 `pytest.ini`：
  ```ini
  [pytest]
  asyncio_mode = auto
  ```

---

### Task 10: migrate 命令支持重新向量化

**Files:**
- Modify: `src/cli.py`

背景：改变了向量化文本（从 `title+problem+solution` 改为 `title+problem+key_decisions`），旧经验的向量需要重新生成。`xp migrate` 命令已存在，需要更新其向量化文本逻辑使其与新逻辑一致，并支持强制全量重建（`--force` flag）。

**Step 1: 找到 cmd_migrate 函数**

在 `src/cli.py` 中，找到 `cmd_migrate` 函数，其中有：

```python
        texts = [f"{e.title}\n{e.problem}\n{e.solution}" for e in batch]
```

**Step 2: 改为新的向量化文本**

将上面那行改为：

```python
        texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in batch]
```

**Step 3: 添加 --force 参数支持全量重建**

在 `cmd_migrate` 函数的 `async def run():` 内，在 `ids, _ = v_store.get_all_vectors()` 之前，加入对 `--force` 参数的处理：

将 `cmd_migrate` 函数签名改为接受 args 并解析：

```python
def cmd_migrate(args):
    force = "--force" in args

    async def run():
        from .knowledge import KnowledgeService
        from .project_config import ProjectManager
        from .storage import ExperienceStore, MetricsStore
        service = KnowledgeService(ExperienceStore(), MetricsStore(), ProjectManager().get_current())
        from src.embeddings import get_provider
        from src.storage import VectorStore
        
        provider = get_provider()
        v_store = VectorStore()
        
        all_exps = []
        from src.models import ExperienceStatus
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(service._store.list_by_status(status))
            
        print(f"总经验数量: {len(all_exps)}")
        
        if force:
            missing_exps = all_exps
            print(f"--force 模式：全量重新生成 {len(missing_exps)} 条经验的向量")
        else:
            ids, _ = v_store.get_all_vectors()
            missing_exps = [e for e in all_exps if e.id not in ids]
        
        if not missing_exps:
            print("所有经验均已生成向量，无需迁移。")
            return
            
        print(f"发现 {len(missing_exps)} 条缺失向量的经验，开始生成...")
        batch_size = 50
        for i in range(0, len(missing_exps), batch_size):
            batch = missing_exps[i:i+batch_size]
            texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in batch]
            vecs = provider.embed_texts(texts)
            v_store.save_vectors(list(zip([e.id for e in batch], vecs)))
            print(f"进度: {min(i+batch_size, len(missing_exps))}/{len(missing_exps)}")
            
        print("迁移完成。")
        
    import asyncio
    asyncio.run(run())
```

注意：原来的 `cmd_migrate` 代码中有 `get_service()` 调用（未定义的 bug），这里一并修正为直接创建 `KnowledgeService`。

**Step 4: 运行测试，确保无回归**

```
pytest tests/ -v
```

预期：全部 PASS
