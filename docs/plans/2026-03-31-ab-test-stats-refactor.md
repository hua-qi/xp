# A/B 测试统计语义重构 Implementation Plan

**Goal:** 以"是否实际展示经验（`result_shown`）"替代当前两套混乱的统计维度（有注入/无注入 + treatment/control），使 `xp stats` 展示语义清晰、对比可信。

**Architecture:** `search_best_practices` 在返回值中追加 `result_shown` 字段；`record_session` 新增 `result_shown` 可选参数并写入 `sessions.ab_test_result_shown` 列；`get_stats` 删除旧双维度查询，改为按 `ab_test_result_shown` 单维度对比；`cmd_stats` 删除旧展示块，输出"展示经验 / 未展示经验"。

**Tech Stack:** Python 3.11, SQLite (via sqlite3), MCP Tools (mcp SDK), pytest

---

### Task 1: 在 sessions 表加 `ab_test_result_shown` 列（DDL 迁移）

**Files:**
- Modify: `src/storage.py`（`_init_metrics_schema` 函数）

**背景知识：**
`_init_metrics_schema` 在每次建立连接时执行，用 `CREATE TABLE IF NOT EXISTS` 保证幂等。对于已存在的表需要用 `ALTER TABLE ... ADD COLUMN` 兼容迁移，且要用 `try/except` 包裹（列已存在时 SQLite 会抛异常）。

---

**Step 1: 写失败测试**

```python
# tests/test_ab_test_refactor.py

import pytest

def test_sessions_table_has_ab_test_result_shown(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    conn = storage_mod._get_metrics_conn()
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = [row["name"] for row in cursor.fetchall()]
    conn.close()
    assert "ab_test_result_shown" in columns
```

**Step 2: 运行测试，确认失败**

```
pytest tests/test_ab_test_refactor.py::test_sessions_table_has_ab_test_result_shown -v
```

预期：`FAILED`，`AssertionError: assert 'ab_test_result_shown' in [...]`

---

**Step 3: 在 `_init_metrics_schema` 中加列**

在 `src/storage.py` 的 `_init_metrics_schema` 中，找到现有的 `try/except` 块（处理 `ab_test_group` 的那个），在其后追加：

```python
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN ab_test_result_shown INTEGER DEFAULT 1")
        conn.commit()
    except Exception:
        pass
```

**Step 4: 运行测试，确认通过**

```
pytest tests/test_ab_test_refactor.py::test_sessions_table_has_ab_test_result_shown -v
```

预期：`PASSED`

---

### Task 2: `Session` 模型确认有 `ab_test_result_shown` 字段

**Files:**
- Read: `src/models.py`（`Session` dataclass，确认字段已存在）

**背景知识：**
`Session` dataclass 在 `src/models.py` 中定义。查看当前内容后你会发现 `ab_test_result_shown: bool = True` 已经存在（在上一次 commit 中添加）。本 task 无需修改代码，只需验证。

---

**Step 1: 验证字段已存在**

```
grep -n "ab_test_result_shown" src/models.py
```

预期输出包含：`ab_test_result_shown: bool = True`

如果字段不存在，在 `Session` dataclass 的 `ab_test_group` 字段后追加：

```python
    ab_test_result_shown: bool = True
```

---

### Task 3: `MetricsStore.record_session` 写入 `ab_test_result_shown`

**Files:**
- Modify: `src/storage.py`（`MetricsStore.record_session` 方法，第 ~300 行）

**背景知识：**
`record_session` 当前只写 8 列（含 `ab_test_group`）。需要把 `ab_test_result_shown` 加入 INSERT 语句和 VALUES 绑定参数中。SQLite 中 `bool` 需要存为 `int`（`0`/`1`）。

---

**Step 1: 写失败测试**

```python
# 追加到 tests/test_ab_test_refactor.py

from datetime import datetime
from src.models import Session

def test_record_session_writes_result_shown(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.storage import MetricsStore
    store = MetricsStore()
    session = Session(
        session_id="test-001",
        task_description="test",
        experience_ids_injected=[],
        iteration_count=2,
        had_error_correction=False,
        user_accepted=True,
        created_at=datetime.utcnow().isoformat(),
        ab_test_group="treatment",
        ab_test_result_shown=False,
    )
    store.record_session(session)

    conn = storage_mod._get_metrics_conn()
    row = conn.execute("SELECT ab_test_result_shown FROM sessions WHERE session_id = ?", ("test-001",)).fetchone()
    conn.close()
    assert row["ab_test_result_shown"] == 0
```

**Step 2: 运行测试，确认失败**

```
pytest tests/test_ab_test_refactor.py::test_record_session_writes_result_shown -v
```

预期：`FAILED`（`ab_test_result_shown` 列为 `1`，因为 INSERT 没写入该字段，用了默认值）

---

**Step 3: 修改 `record_session` 方法**

在 `src/storage.py` 中找到 `record_session` 方法，将 INSERT 语句改为：

```python
    def record_session(self, session: Session):
        with _get_metrics_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, task_description, experience_ids_injected,
                    iteration_count, had_error_correction, user_accepted, created_at, ab_test_group, ab_test_result_shown)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.session_id,
                    session.task_description,
                    json.dumps(session.experience_ids_injected),
                    session.iteration_count,
                    int(session.had_error_correction),
                    int(session.user_accepted),
                    session.created_at,
                    session.ab_test_group,
                    int(session.ab_test_result_shown),
                ),
            )
```

**Step 4: 运行测试，确认通过**

```
pytest tests/test_ab_test_refactor.py::test_record_session_writes_result_shown -v
```

预期：`PASSED`

---

### Task 4: `server.py` 的 `search_best_practices` 返回值追加 `result_shown`

**Files:**
- Modify: `src/server.py`（`call_tool` 中 `search_best_practices` 分支）

**背景知识：**
`knowledge.search()` 返回 `(results, meta)`，其中 `meta` 已包含 `show_results` 键（布尔值）。需要在 server 的返回 JSON 中把它暴露为 `result_shown`，让 agent 能读取并传入 `record_session`。

---

**Step 1: 写失败测试**

此处是集成行为（JSON 序列化），直接检查返回 JSON 中存在 `result_shown` 字段：

```python
# 追加到 tests/test_ab_test_refactor.py
import json

def test_search_returns_result_shown_field(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    import asyncio

    service = KnowledgeService(ExperienceStore(), MetricsStore())

    results, meta = asyncio.run(service.search(query="test query", session_id="s-001"))
    assert "show_results" in meta
```

注意：这个测试实际上已经能通过（`meta` 已有 `show_results`）。真正需要验证的是 server 层暴露该字段。由于 server 层测试需要 MCP 环境，这里改为验证 server.py 里 no-results 和 has-results 两条路径都包含 `result_shown`：

```python
def test_server_search_result_shown_in_no_results(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    from src import server
    import asyncio

    service = KnowledgeService(ExperienceStore(), MetricsStore())
    server._service = service

    result = asyncio.run(server.call_tool("search_best_practices", {"query": "test"}))
    data = json.loads(result[0].text)
    assert "result_shown" in data
```

**Step 2: 运行测试，确认失败**

```
pytest tests/test_ab_test_refactor.py::test_server_search_result_shown_in_no_results -v
```

预期：`FAILED`，`KeyError: 'result_shown'`

---

**Step 3: 修改 `server.py` 的 `search_best_practices` 分支**

找到 `search_best_practices` 的两处 `return [TextContent(...)]`：

**无结果路径：**
```python
        if not results:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "ab_test_group": meta.get("ab_test_group", "treatment"),
                    "result_shown": meta.get("show_results", True),
                    "results": [],
                    "message": "暂无相关历史经验，请根据实际情况处理。"
                }, ensure_ascii=False),
            )]
```

**有结果路径：**
```python
        return [TextContent(type="text", text=json.dumps({
            "ab_test_group": meta.get("ab_test_group", "treatment"),
            "result_shown": meta.get("show_results", True),
            "results": data
        }, ensure_ascii=False, indent=2))]
```

**Step 4: 运行测试，确认通过**

```
pytest tests/test_ab_test_refactor.py::test_server_search_result_shown_in_no_results -v
```

预期：`PASSED`

---

### Task 5: `server.py` 的 `record_session` schema 新增 `result_shown` 参数

**Files:**
- Modify: `src/server.py`（`list_tools` 中 `record_session` 的 `inputSchema`，以及 `call_tool` 中 `record_session` 分支）

**背景知识：**
`record_session` 的 `inputSchema` 定义了 agent 可传入哪些参数。需要新增 `result_shown: bool`（可选，默认 `true`）。在 `call_tool` 中构建 `Session` 对象时，从 `arguments` 读取该字段。

---

**Step 1: 写失败测试**

```python
# 追加到 tests/test_ab_test_refactor.py

def test_record_session_tool_accepts_result_shown(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService
    from src import server
    import asyncio

    service = KnowledgeService(ExperienceStore(), MetricsStore())
    server._service = service

    result = asyncio.run(server.call_tool("record_session", {
        "session_id": "s-002",
        "task_description": "test",
        "experience_ids_injected": [],
        "iteration_count": 1,
        "had_error_correction": False,
        "user_accepted": True,
        "result_shown": False,
    }))
    data = json.loads(result[0].text)
    assert data["status"] == "recorded"

    conn = storage_mod._get_metrics_conn()
    row = conn.execute("SELECT ab_test_result_shown FROM sessions WHERE session_id = ?", ("s-002",)).fetchone()
    conn.close()
    assert row["ab_test_result_shown"] == 0
```

**Step 2: 运行测试，确认失败**

```
pytest tests/test_ab_test_refactor.py::test_record_session_tool_accepts_result_shown -v
```

预期：`FAILED`，`result_shown` 未被读取，数据库中字段为默认值 `1`

---

**Step 3: 修改 `server.py` 的 `record_session` schema 和构建逻辑**

在 `list_tools` 的 `record_session` `inputSchema.properties` 中追加：

```python
                    "result_shown": {
                        "type": "boolean",
                        "description": "是否实际展示了经验结果，从 search_best_practices 返回的 result_shown 字段获取，未调用则传 true",
                        "default": True,
                    },
```

在 `call_tool` 的 `record_session` 分支中，构建 `Session` 时追加：

```python
        session = Session(
            ...
            ab_test_group=arguments.get("ab_test_group", "treatment"),
            ab_test_result_shown=arguments.get("result_shown", True),
        )
```

**Step 4: 运行测试，确认通过**

```
pytest tests/test_ab_test_refactor.py::test_record_session_tool_accepts_result_shown -v
```

预期：`PASSED`

---

### Task 6: `MetricsStore.get_stats` 替换统计查询逻辑

**Files:**
- Modify: `src/storage.py`（`MetricsStore.get_stats` 方法）

**背景知识：**
当前 `get_stats` 有两组 session 查询：
1. `json_array_length(experience_ids_injected) > 0` vs `= 0` → 返回 `with_injection` / `without_injection`
2. `ab_test_group = 'treatment'` vs `'control'` → 返回 `ab_test_groups`

按设计文档方案 A：
- 删除两组旧查询
- 新增按 `ab_test_result_shown = 1` vs `= 0` 的对比查询
- 返回结构中用 `shown` / `not_shown` 替代 `with_injection` / `without_injection`
- 删除 `ab_test_groups` 字段
- 保留 `with_injection` / `without_injection` 键名（为了不破坏 `cli.py` 暂时保留，Task 7 一起替换）

实际做法：**直接同时更新键名**，因为 Task 7 会同步改 `cli.py`，两者在同一个实施计划中完成。

---

**Step 1: 写失败测试**

```python
# 追加到 tests/test_ab_test_refactor.py

def test_get_stats_result_shown_groups(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.storage import MetricsStore
    from src.models import Session
    from datetime import datetime

    store = MetricsStore()

    # 写入 result_shown=True 的 session
    store.record_session(Session(
        session_id="shown-001",
        task_description="shown session",
        experience_ids_injected=["exp-1"],
        iteration_count=2,
        had_error_correction=False,
        user_accepted=True,
        created_at=datetime.utcnow().isoformat(),
        ab_test_group="treatment",
        ab_test_result_shown=True,
    ))

    # 写入 result_shown=False 的 session
    store.record_session(Session(
        session_id="not-shown-001",
        task_description="not shown session",
        experience_ids_injected=[],
        iteration_count=5,
        had_error_correction=True,
        user_accepted=False,
        created_at=datetime.utcnow().isoformat(),
        ab_test_group="control",
        ab_test_result_shown=False,
    ))

    stats = store.get_stats()

    assert "shown" in stats
    assert "not_shown" in stats
    assert "ab_test_groups" not in stats
    assert "with_injection" not in stats
    assert "without_injection" not in stats

    assert stats["shown"]["avg_iterations"] == 2.0
    assert stats["not_shown"]["avg_iterations"] == 5.0
```

**Step 2: 运行测试，确认失败**

```
pytest tests/test_ab_test_refactor.py::test_get_stats_result_shown_groups -v
```

预期：`FAILED`，`stats` 中没有 `shown` 字段

---

**Step 3: 重写 `get_stats` 的 session 统计部分**

在 `src/storage.py` 的 `get_stats` 方法中，找到并**替换**以下四个查询块：

**删除：**
```python
        sessions_with = conn.execute(
            f"SELECT AVG(iteration_count) as avg_iter, ... WHERE ... json_array_length(experience_ids_injected) > 0",
            ...
        ).fetchone()

        sessions_without = conn.execute(
            f"SELECT AVG(iteration_count) as avg_iter, ... WHERE ... json_array_length(experience_ids_injected) = 0",
            ...
        ).fetchone()
```
以及：
```python
        ab_treatment = conn.execute(...).fetchone()
        ab_control = conn.execute(...).fetchone()
        ab_test_groups = { "treatment": {...}, "control": {...} }
```

**替换为：**
```python
        sessions_shown = conn.execute(
            f"""SELECT AVG(iteration_count) as avg_iter,
                       AVG(had_error_correction) as avg_err,
                       AVG(user_accepted) as avg_acc
                FROM sessions {date_filter}
                {'AND' if date_filter else 'WHERE'} ab_test_result_shown = 1""",
            params,
        ).fetchone()

        sessions_not_shown = conn.execute(
            f"""SELECT AVG(iteration_count) as avg_iter,
                       AVG(had_error_correction) as avg_err,
                       AVG(user_accepted) as avg_acc
                FROM sessions {date_filter}
                {'AND' if date_filter else 'WHERE'} ab_test_result_shown = 0""",
            params,
        ).fetchone()
```

**在 return 字典中替换：**

删除：
```python
            "with_injection": { ... sessions_with ... },
            "without_injection": { ... sessions_without ... },
            ...
            "ab_test_groups": ab_test_groups,
```

替换为：
```python
            "shown": {
                "avg_iterations": round(sessions_shown["avg_iter"] or 0, 2),
                "error_rate": round(sessions_shown["avg_err"] or 0, 3),
                "accept_rate": round(sessions_shown["avg_acc"] or 0, 3),
            },
            "not_shown": {
                "avg_iterations": round(sessions_not_shown["avg_iter"] or 0, 2),
                "error_rate": round(sessions_not_shown["avg_err"] or 0, 3),
                "accept_rate": round(sessions_not_shown["avg_acc"] or 0, 3),
            },
```

**Step 4: 运行测试，确认通过**

```
pytest tests/test_ab_test_refactor.py::test_get_stats_result_shown_groups -v
```

预期：`PASSED`

---

### Task 7: 更新 `KnowledgeService.get_stats` 和 `cmd_stats` 展示层

**Files:**
- Modify: `src/knowledge.py`（`get_stats` 方法）
- Modify: `src/cli.py`（`cmd_stats` 函数）

**背景知识：**
`knowledge.get_stats` 把 `MetricsStore.get_stats` 的结果直接 pass-through，不做转换，所以无需修改（Task 6 返回键名已改）。

`cmd_stats` 中有两块需要删除/改写：
1. `--- 效果对比 ---` 块：读了 `with_injection`/`without_injection`，要改为读 `shown`/`not_shown`，列名改为"展示经验 / 未展示经验"
2. `A/B 分组对比` 块（读 `ab_test_groups`）：整体删除

---

**Step 1: 写失败测试**

```python
# 追加到 tests/test_ab_test_refactor.py

def test_cmd_stats_shows_result_shown_labels(tmp_path, monkeypatch, capsys):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.cli import cmd_stats
    cmd_stats([])

    captured = capsys.readouterr()
    assert "展示经验" in captured.out
    assert "未展示经验" in captured.out
    assert "有经验注入" not in captured.out
    assert "无注入" not in captured.out
    assert "A/B 分组对比" not in captured.out
```

**Step 2: 运行测试，确认失败**

```
pytest tests/test_ab_test_refactor.py::test_cmd_stats_shows_result_shown_labels -v
```

预期：`FAILED`，输出中没有"展示经验"

---

**Step 3: 修改 `cmd_stats`**

在 `src/cli.py` 的 `cmd_stats` 函数中：

**删除：**
```python
    w = stats["with_injection"]
    wo = stats["without_injection"]
    print(f"\n--- 效果对比（共 {stats['session_total']} 次会话）---")
    print(f"                    有经验注入    无注入")
    print(f"  平均对话轮数      {w['avg_iterations']:<14.1f}{wo['avg_iterations']:.1f}")
    print(f"  报错率            {w['error_rate'] * 100:<14.1f}{wo['error_rate'] * 100:.1f}%")
    print(f"  用户接受率        {w['accept_rate'] * 100:<14.1f}{wo['accept_rate'] * 100:.1f}%")

    ab = stats.get("ab_test_groups", {})
    tr = ab.get("treatment", {})
    ct = ab.get("control", {})
    if tr and ct:
        print(f"\n  A/B 分组对比:       treatment     control")
        print(f"  平均对话轮数      {tr.get('avg_iterations', 0):<14.1f}{ct.get('avg_iterations', 0):.1f}")
        print(f"  报错率            {tr.get('error_rate', 0) * 100:<14.1f}{ct.get('error_rate', 0) * 100:.1f}%")
        print(f"  用户接受率        {tr.get('accept_rate', 0) * 100:<14.1f}{ct.get('accept_rate', 0) * 100:.1f}%")
```

**替换为：**
```python
    s = stats.get("shown", {})
    ns = stats.get("not_shown", {})
    print(f"\n--- 效果对比（共 {stats['session_total']} 次会话）---")
    print(f"                    展示经验      未展示经验")
    print(f"  平均对话轮数      {s.get('avg_iterations', 0):<14.1f}{ns.get('avg_iterations', 0):.1f}")
    print(f"  报错率            {s.get('error_rate', 0) * 100:<14.1f}{ns.get('error_rate', 0) * 100:.1f}%")
    print(f"  用户接受率        {s.get('accept_rate', 0) * 100:<14.1f}{ns.get('accept_rate', 0) * 100:.1f}%")
```

**Step 4: 运行测试，确认通过**

```
pytest tests/test_ab_test_refactor.py::test_cmd_stats_shows_result_shown_labels -v
```

预期：`PASSED`

---

### Task 8: 修复旧测试兼容性

**Files:**
- Modify: `tests/test_stats_metrics.py`

**背景知识：**
`test_get_stats_new_fields_exist` 和 `test_knowledge_get_stats_new_fields` 中断言了旧字段（`ab_test_groups`、`with_injection`、`without_injection`）的存在，Task 6 已删除这些字段，测试会失败。需要更新断言。

`test_cmd_stats_no_crash` 断言 `"效果对比"` 在输出中，这个字符串保留了，不需要修改。

---

**Step 1: 运行旧测试，确认哪些失败**

```
pytest tests/test_stats_metrics.py -v
```

预期：`test_get_stats_new_fields_exist` 和 `test_knowledge_get_stats_new_fields` 失败（如果断言了旧字段的话）

---

**Step 2: 更新 `test_get_stats_new_fields_exist`**

在 `tests/test_stats_metrics.py` 中，将：

```python
    assert "ab_test_groups" in stats
    assert "treatment" in stats["ab_test_groups"]
    assert "control" in stats["ab_test_groups"]
```

替换为：

```python
    assert "shown" in stats
    assert "not_shown" in stats
    assert "avg_iterations" in stats["shown"]
    assert "avg_iterations" in stats["not_shown"]
```

同时删除（如果存在）对 `with_injection`/`without_injection` 的断言，因为这些字段已移除。

---

**Step 3: 运行所有测试，确认全部通过**

```
pytest tests/ -v
```

预期：所有测试 `PASSED`

---

### Task 9: 端到端验证

**Step 1: 运行完整测试套件**

```
pytest tests/ -v
```

预期：所有测试 `PASSED`，无 `FAILED` 或 `ERROR`

**Step 2: 手动验证 CLI 输出（可选，无测试数据时会显示 0）**

```
xp stats
```

预期输出中应包含：
- `展示经验      未展示经验`
- 不包含 `有经验注入`、`无注入`、`A/B 分组对比`

**Step 3: 提交**

```
git add src/storage.py src/server.py src/cli.py tests/test_ab_test_refactor.py tests/test_stats_metrics.py
git commit -m "refactor: replace injection-based stats with result_shown dimension"
```
