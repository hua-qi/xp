# Stats Extended Metrics Implementation Plan

**Goal:** 扩展 `xp stats` 命令，新增 10 个指标，按"结果优先"顺序重排输出结构。

**Architecture:** 改动分三层：`storage.py` 的 `MetricsStore.get_stats()` 新增 SQL 查询返回新字段；`knowledge.py` 的 `get_stats()` 补充从 `ExperienceStore` 读取的知识库健康度字段；`cli.py` 的 `cmd_stats()` 按新结构重排并打印所有新 section。

**Tech Stack:** Python 3.9+, SQLite (via `storage.py`), `knowledge.json` (via `ExperienceStore`), pytest

---

## 背景知识

### 文件职责

- `src/storage.py` — `MetricsStore.get_stats()` 查 SQLite，返回指标 dict；`ExperienceStore` 读写 `knowledge.json`
- `src/knowledge.py` — `KnowledgeService.get_stats()` 组合 MetricsStore + ExperienceStore，是 CLI 的唯一数据入口
- `src/cli.py` — `cmd_stats()` 消费 dict，print 到终端
- `src/models.py` — `Experience` dataclass，关键字段：`id`, `type`, `confidence`, `status`, `last_hit_at`

### 现有数据库表（SQLite，`METRICS_DB`）

```
sessions(session_id, task_description, experience_ids_injected,
         iteration_count, had_error_correction, user_accepted, created_at)
search_events(id, query, result_count, created_at)
review_events(id, experience_id, action, reject_reason, created_at)
feedback(id, experience_id, adopted, reason, created_at)
experience_stats(experience_id, hit_count, adopted_count, rejected_count,
                 last_used_at, last_adopted_at, adoption_rate)
```

`sessions.experience_ids_injected` 是 JSON 数组字符串，例如 `["id1","id2"]` 或 `[]`。

`sessions` 表目前无 `ab_test_group` 列，需要新增。

### 当前 `get_stats()` 返回 dict 的 key

```python
{
  "search_total", "search_hit_rate",
  "review_confirmed", "review_rejected", "review_pass_rate",
  "session_total",
  "with_injection":    {"avg_iterations", "error_rate", "accept_rate"},
  "without_injection": {"avg_iterations", "error_rate", "accept_rate"},
  # knowledge.py 追加:
  "active_count", "pending_count",
}
```

### 新增字段规划

**MetricsStore.get_stats() 新增：**
- `archived_count` — `ExperienceStore` 统计，在 `knowledge.py` 追加
- `type_distribution` — `ExperienceStore` 统计，在 `knowledge.py` 追加
- `avg_confidence` — `ExperienceStore` 统计，在 `knowledge.py` 追加
- `avg_result_count` — `AVG(result_count)` from `search_events`
- `query_adoption_rate` — 有 feedback 的 search 中采纳比例（近似：feedback 中 adopted=1 / total feedback）
- `top_miss_queries` — result_count=0 的 top 5 query（复用已有 `get_search_miss_queries()`）
- `top_adopted_experiences` — `experience_stats` 按 `adoption_rate` DESC LIMIT 3
- `zombie_count` — active 经验中 hit_count=0 的数量
- `ab_test_groups` — treatment vs control 的三指标对比
- `trend_30d` — 近 30 天新增经验数、会话数

**sessions 表需迁移：** 新增 `ab_test_group TEXT DEFAULT 'treatment'` 列。

---

## Task 1: 迁移 sessions 表，新增 ab_test_group 列

**Files:**
- Modify: `src/storage.py`（`_init_metrics_schema` 函数，约第 52 行）

### Step 1: 在 `_init_metrics_schema` 的 executescript 中追加 ALTER TABLE

在 `_init_metrics_schema` 的 `conn.executescript(...)` 之后追加以下代码（ALTER TABLE 不支持在 executescript 中用 IF NOT EXISTS，需要单独 try/except）：

```python
try:
    conn.execute("ALTER TABLE sessions ADD COLUMN ab_test_group TEXT DEFAULT 'treatment'")
    conn.commit()
except Exception:
    pass
```

这段代码放在 `conn.executescript(...)` 的 `conn.commit()` 之后，`_init_metrics_schema` 函数末尾。

### Step 2: 验证迁移不破坏现有数据库

```bash
python3 -c "from src.storage import _get_metrics_conn; conn = _get_metrics_conn(); print([d[0] for d in conn.execute('PRAGMA table_info(sessions)').fetchall()])"
```

期望输出包含 `ab_test_group`。

---

## Task 2: MetricsStore.get_stats() 新增 SQL 指标

**Files:**
- Modify: `src/storage.py`（`MetricsStore.get_stats()` 方法，约第 390-440 行）

### Step 1: 新增 avg_result_count 查询

在 `get_stats()` 方法中，现有 `search_hit` 查询之后追加：

```python
avg_result_count_row = conn.execute(
    f"SELECT AVG(result_count) as avg_rc FROM search_events {date_filter}", params
).fetchone()
avg_result_count = round(avg_result_count_row["avg_rc"] or 0, 2)
```

### Step 2: 新增 query_adoption_rate 查询

```python
feedback_total = conn.execute(
    f"SELECT COUNT(*) as cnt FROM feedback {date_filter}", params
).fetchone()["cnt"]
feedback_adopted = conn.execute(
    f"SELECT COUNT(*) as cnt FROM feedback {date_filter} {'AND' if date_filter else 'WHERE'} adopted = 1",
    params,
).fetchone()["cnt"]
query_adoption_rate = round(feedback_adopted / feedback_total, 3) if feedback_total else 0
```

### Step 3: 新增 top_adopted_experiences 查询

```python
top_adopted_rows = conn.execute(
    """SELECT experience_id, adoption_rate, hit_count FROM experience_stats
       WHERE hit_count >= 3
       ORDER BY adoption_rate DESC LIMIT 3"""
).fetchall()
top_adopted_experiences = [
    {"experience_id": r["experience_id"], "adoption_rate": r["adoption_rate"], "hit_count": r["hit_count"]}
    for r in top_adopted_rows
]
```

`hit_count >= 3` 过滤掉样本量不足的经验，避免 1 次采纳就显示 100% 的误导。

### Step 4: 新增 zombie_count 查询

```python
zombie_count_row = conn.execute(
    "SELECT COUNT(*) as cnt FROM experience_stats WHERE hit_count = 0"
).fetchone()
zombie_count = zombie_count_row["cnt"]
```

注意：`experience_stats` 只有被 feedback 过的经验才有记录。未出现在该表中的经验视为"从未被采纳反馈"，另一部分僵尸计算在 `knowledge.py` 中补充（见 Task 3）。

### Step 5: 新增 ab_test_groups 查询

```python
ab_treatment = conn.execute(
    f"""SELECT AVG(iteration_count) as avg_iter,
               AVG(had_error_correction) as avg_err,
               AVG(user_accepted) as avg_acc
        FROM sessions {date_filter}
        {'AND' if date_filter else 'WHERE'} ab_test_group = 'treatment'""",
    params,
).fetchone()

ab_control = conn.execute(
    f"""SELECT AVG(iteration_count) as avg_iter,
               AVG(had_error_correction) as avg_err,
               AVG(user_accepted) as avg_acc
        FROM sessions {date_filter}
        {'AND' if date_filter else 'WHERE'} ab_test_group = 'control'""",
    params,
).fetchone()

ab_test_groups = {
    "treatment": {
        "avg_iterations": round(ab_treatment["avg_iter"] or 0, 2),
        "error_rate": round(ab_treatment["avg_err"] or 0, 3),
        "accept_rate": round(ab_treatment["avg_acc"] or 0, 3),
    },
    "control": {
        "avg_iterations": round(ab_control["avg_iter"] or 0, 2),
        "error_rate": round(ab_control["avg_err"] or 0, 3),
        "accept_rate": round(ab_control["avg_acc"] or 0, 3),
    },
}
```

### Step 6: 新增 trend_30d 查询

```python
from datetime import timedelta
cutoff_30 = (datetime.utcnow() - timedelta(days=30)).isoformat()
new_sessions_30d = conn.execute(
    "SELECT COUNT(*) as cnt FROM sessions WHERE created_at >= ?", (cutoff_30,)
).fetchone()["cnt"]
```

经验新增数在 `knowledge.py` 中统计（因为经验存储在 JSON 文件而非 SQLite）。

### Step 7: 将所有新字段加入返回 dict

在 `return {...}` 中追加：

```python
"avg_result_count": avg_result_count,
"query_adoption_rate": query_adoption_rate,
"top_adopted_experiences": top_adopted_experiences,
"zombie_count_db": zombie_count,
"ab_test_groups": ab_test_groups,
"new_sessions_30d": new_sessions_30d,
```

### Step 8: 编写测试验证新字段存在且类型正确

创建文件 `tests/test_stats_metrics.py`：

```python
import pytest
from unittest.mock import patch, MagicMock
from src.storage import MetricsStore


def test_get_stats_new_fields_exist(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    store = MetricsStore()
    stats = store.get_stats()

    assert "avg_result_count" in stats
    assert "query_adoption_rate" in stats
    assert "top_adopted_experiences" in stats
    assert isinstance(stats["top_adopted_experiences"], list)
    assert "zombie_count_db" in stats
    assert "ab_test_groups" in stats
    assert "treatment" in stats["ab_test_groups"]
    assert "control" in stats["ab_test_groups"]
    assert "new_sessions_30d" in stats
```

### Step 9: 运行测试确认通过

```bash
python3 -m pytest tests/test_stats_metrics.py::test_get_stats_new_fields_exist -v
```

期望：PASS

---

## Task 3: knowledge.py get_stats() 补充知识库健康度字段

**Files:**
- Modify: `src/knowledge.py`（`KnowledgeService.get_stats()` 方法，约第 560-565 行）

当前实现：

```python
def get_stats(self, since_days=None):
    process = self._metrics.get_stats(since_days)
    process["active_count"] = len(self._store.list_active())
    process["pending_count"] = len(self.list_pending())
    return process
```

### Step 1: 新增 archived_count

```python
archived_exps = self._store.list_by_status(ExperienceStatus.ARCHIVED)
process["archived_count"] = len(archived_exps)
```

### Step 2: 新增 type_distribution

```python
all_active = self._store.list_active()
type_dist = {}
for exp in all_active:
    t = exp.type.value
    type_dist[t] = type_dist.get(t, 0) + 1
process["type_distribution"] = type_dist
```

### Step 3: 新增 avg_confidence

```python
if all_active:
    process["avg_confidence"] = round(
        sum(e.confidence for e in all_active) / len(all_active), 3
    )
else:
    process["avg_confidence"] = 0.0
```

### Step 4: 新增僵尸经验数（hit_count=0 且 active）

从 `experience_stats` 表中只能拿到有 feedback 记录的经验。真正的僵尸是：active 且从未出现在 `experience_stats` 中，或 hit_count=0。

```python
from .storage import _get_metrics_conn
conn = _get_metrics_conn()
hitted_ids = set(
    r["experience_id"]
    for r in conn.execute("SELECT experience_id FROM experience_stats WHERE hit_count > 0").fetchall()
)
conn.close()
zombie_count = sum(1 for e in all_active if e.id not in hitted_ids)
process["zombie_count"] = zombie_count
```

这会覆盖 Task 2 中 `zombie_count_db` 的不完整统计，用更准确的值。

### Step 5: 新增 top_miss_queries（复用已有方法）

```python
process["top_miss_queries"] = self._metrics.get_search_miss_queries(since_days=30, limit=5)
```

### Step 6: 新增 trend_30d 经验新增数

```python
from datetime import datetime, timedelta
cutoff_30 = (datetime.utcnow() - timedelta(days=30)).isoformat()
all_exps_all_status = (
    all_active
    + self._store.list_by_status(ExperienceStatus.PENDING)
    + archived_exps
)
new_exps_30d = sum(1 for e in all_exps_all_status if e.created_at >= cutoff_30)
process["trend_30d"] = {
    "new_experiences": new_exps_30d,
    "new_sessions": process["new_sessions_30d"],
}
```

### Step 7: 编写测试

在 `tests/test_stats_metrics.py` 追加：

```python
def test_knowledge_get_stats_new_fields(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService

    service = KnowledgeService(ExperienceStore(), MetricsStore())
    stats = service.get_stats()

    assert "archived_count" in stats
    assert "type_distribution" in stats
    assert isinstance(stats["type_distribution"], dict)
    assert "avg_confidence" in stats
    assert "zombie_count" in stats
    assert "top_miss_queries" in stats
    assert "trend_30d" in stats
    assert "new_experiences" in stats["trend_30d"]
    assert "new_sessions" in stats["trend_30d"]
```

### Step 8: 运行测试

```bash
python3 -m pytest tests/test_stats_metrics.py -v
```

期望：全部 PASS

---

## Task 4: cmd_stats() 按新结构重排输出

**Files:**
- Modify: `src/cli.py`（`cmd_stats()` 函数，约第 128-165 行）

目标输出结构（对照设计）：

```
================================================
  XP 效果统计（全部时间）
================================================

--- 效果对比（共 N 次会话）---
  [现有] 有经验注入 vs 无注入
  [新] A/B 分组: treatment vs control

--- 知识库状态 ---
  [现有] Active / Pending
  [新] Archived / 类型分布 / 平均置信度

--- 检索质量 ---
  [现有] 检索触发次数 / 命中率
  [新] 平均返回结果数 / 查询后采纳率 / Top 未命中查询

--- 经验价值分布 ---
  [现有] 候选确认数 / 拒绝数 / 通过率
  [新] 高采纳率 TOP 3 / 僵尸经验数

--- 时间趋势（近 30 天）---
  [新] 新增经验 / 新增会话
```

### Step 1: 替换整个 cmd_stats() 函数体

将现有函数替换为以下实现：

```python
def cmd_stats(args):
    since_days: Optional[int] = None
    for i, arg in enumerate(args):
        if arg == "--since" and i + 1 < len(args):
            val = args[i + 1].rstrip("d")
            try:
                since_days = int(val)
            except ValueError:
                pass

    service = _get_service()
    stats = service.get_stats(since_days)

    period = f"最近 {since_days} 天" if since_days else "全部时间"

    print(f"\n{'=' * 50}")
    print(f"  XP 效果统计 ({period})")
    print(f"{'=' * 50}")

    # --- 效果对比（结果优先）---
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

    # --- 知识库状态 ---
    type_dist = stats.get("type_distribution", {})
    type_str = "  ".join(f"{k} {v}" for k, v in type_dist.items()) if type_dist else "暂无"
    print(f"\n--- 知识库状态 ---")
    print(f"  Active 经验数:     {stats['active_count']}")
    print(f"  Pending 待 review: {stats['pending_count']}")
    print(f"  Archived 归档:     {stats.get('archived_count', 0)}")
    print(f"  类型分布:          {type_str}")
    print(f"  平均置信度:        {stats.get('avg_confidence', 0):.2f}")

    # --- 检索质量 ---
    print(f"\n--- 检索质量 ---")
    print(f"  检索触发次数:      {stats['search_total']}")
    print(f"  检索命中率:        {stats['search_hit_rate'] * 100:.1f}%")
    print(f"  平均返回结果数:    {stats.get('avg_result_count', 0):.1f}")
    print(f"  查询后采纳率:      {stats.get('query_adoption_rate', 0) * 100:.1f}%")
    miss_queries = stats.get("top_miss_queries", [])
    if miss_queries:
        print(f"  Top 未命中查询（近30天）:")
        for q in miss_queries[:3]:
            print(f"    \"{q['query']}\" ({q['count']} 次)")

    # --- 经验价值分布 ---
    print(f"\n--- 经验价值分布 ---")
    print(f"  候选确认数:        {stats['review_confirmed']}")
    print(f"  候选拒绝数:        {stats['review_rejected']}")
    print(f"  候选通过率:        {stats['review_pass_rate'] * 100:.1f}%")
    top_adopted = stats.get("top_adopted_experiences", [])
    if top_adopted:
        print(f"  高采纳率 TOP {len(top_adopted)}:")
        for exp_stat in top_adopted:
            short_id = exp_stat["experience_id"][:8]
            print(f"    [{short_id}]  采纳率 {exp_stat['adoption_rate'] * 100:.0f}%  命中 {exp_stat['hit_count']} 次")
    zombie = stats.get("zombie_count", 0)
    if zombie:
        print(f"  僵尸经验（从未命中）: {zombie} 条")

    # --- 时间趋势 ---
    trend = stats.get("trend_30d", {})
    if trend:
        print(f"\n--- 时间趋势（近 30 天）---")
        print(f"  新增经验:          +{trend.get('new_experiences', 0)} 条")
        print(f"  新增会话:          +{trend.get('new_sessions', 0)} 次")

    if stats["session_total"] < 10:
        print(f"\n  注意: 当前会话数较少（{stats['session_total']} 次），对比数据仅供参考。")
    print()
```

### Step 2: 手动验证输出格式

```bash
python3 -m xp stats
```

确认各 section 正常显示，无 KeyError 报错。

### Step 3: 编写 cmd_stats 输出测试

在 `tests/test_stats_metrics.py` 追加：

```python
def test_cmd_stats_no_crash(tmp_path, monkeypatch, capsys):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.cli import cmd_stats
    cmd_stats([])

    captured = capsys.readouterr()
    assert "效果对比" in captured.out
    assert "知识库状态" in captured.out
    assert "检索质量" in captured.out
    assert "经验价值分布" in captured.out
    assert "时间趋势" in captured.out
```

### Step 4: 运行全部测试

```bash
python3 -m pytest tests/test_stats_metrics.py -v
```

期望：全部 PASS

---

## Task 5: 高采纳率 TOP 经验显示名称

**背景：** Task 4 中高采纳率 TOP 3 只显示了 ID 前缀，可读性差。需要从 ExperienceStore 查询经验标题。

**Files:**
- Modify: `src/knowledge.py`（`get_stats()` 方法）

### Step 1: 在 knowledge.py get_stats() 中补充标题查询

在追加 `process["zombie_count"]` 之后加入：

```python
top_adopted_raw = process.get("top_adopted_experiences", [])
enriched = []
for item in top_adopted_raw:
    exp = self._store.get(item["experience_id"])
    enriched.append({
        **item,
        "title": exp.title[:30] if exp else item["experience_id"][:8],
    })
process["top_adopted_experiences"] = enriched
```

### Step 2: 更新 cmd_stats() 中的打印逻辑

将 Task 4 中高采纳率打印部分替换为：

```python
if top_adopted:
    print(f"  高采纳率 TOP {len(top_adopted)}:")
    for exp_stat in top_adopted:
        short_id = exp_stat["experience_id"][:8]
        title = exp_stat.get("title", short_id)
        print(f"    [{short_id}] {title}  采纳率 {exp_stat['adoption_rate'] * 100:.0f}%")
```

### Step 3: 运行全部测试确认没有回归

```bash
python3 -m pytest tests/test_stats_metrics.py -v
```

期望：全部 PASS

---

## 完成验收

运行以下命令确认无报错、输出格式符合设计：

```bash
python3 -m pytest tests/test_stats_metrics.py -v
python3 -m xp stats
python3 -m xp stats --since 7d
```

预期 `xp stats` 输出的完整结构：

```
==================================================
  XP 效果统计 (全部时间)
==================================================

--- 效果对比（共 N 次会话）---
                    有经验注入    无注入
  平均对话轮数      X.X           X.X
  报错率            X.X           X.X%
  用户接受率        X.X           X.X%

  A/B 分组对比:       treatment     control
  平均对话轮数      X.X           X.X
  报错率            X.X           X.X%
  用户接受率        X.X           X.X%

--- 知识库状态 ---
  Active 经验数:     88
  Pending 待 review: 0
  Archived 归档:     12
  类型分布:          bugfix 45  feature 28  pattern 15
  平均置信度:        0.82

--- 检索质量 ---
  检索触发次数:      109
  检索命中率:        33.0%
  平均返回结果数:    2.3
  查询后采纳率:      61.5%
  Top 未命中查询（近30天）:
    "useEffect 无限循环" (5 次)
    "docker network 配置" (3 次)

--- 经验价值分布 ---
  候选确认数:        91
  候选拒绝数:        21
  候选通过率:        81.2%
  高采纳率 TOP 3:
    [abc123ab] React Hook 规范  采纳率 92%
    [def456de] TypeScript 泛型  采纳率 88%
  僵尸经验（从未命中）: 7 条

--- 时间趋势（近 30 天）---
  新增经验:          +12 条
  新增会话:          +23 次
```
