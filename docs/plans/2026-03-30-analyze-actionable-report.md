# xp analyze 可操作报告 Implementation Plan

**Goal:** 将 `xp analyze` 的输出从"固定文字建议"升级为"动态数据 + 内联可执行命令"，并将归因维度从 3 个扩展到 7 个。

**Architecture:** 改动分两层：`knowledge.py` 的 `analyze_quality()` 负责计算新增的 4 个 pattern 数据并在所有 pattern 中填充动态数据（ID、数量、天数等）；`cli.py` 的 `cmd_analyze()` 负责将每个 pattern 的 `actions` 列表渲染成内联命令，并删去底部固定建议中的"优化提取 prompt"一条。

**Tech Stack:** Python 3.10+, SQLite (via `storage.py`), `knowledge.json` (via `ExperienceStore`)

---

## 背景知识

### 文件职责
- `src/knowledge.py` — `KnowledgeService.analyze_quality()` 生成报告 dict，包含 `low_quality_patterns` 列表
- `src/storage.py` — `MetricsStore.get_feedback_summary()` 提供反馈统计；`ExperienceStore` 读 knowledge.json；SQLite `search_events` 表记录每次搜索
- `src/cli.py` — `cmd_analyze()` 消费报告 dict，print 到终端
- `src/models.py` — `Experience` dataclass，关键字段：`id`, `tags`, `last_hit_at`, `status`, `created_at`

### 现有 pattern 结构（`low_quality_patterns` 中每项）
```python
{
    "type": "extraction_quality",   # str
    "issue": "...",                 # str，问题描述
    "suggestion": "...",            # str，建议文字（现在是固定文本）
    "data": "...",                  # str，数据摘要
}
```
改造后新增字段：
```python
    "actions": [                    # list[str]，可直接复制执行的命令
        "xp archive f223f5a5",
        "xp edit ccfe7dc1",
    ]
```

### 现有数据库表（SQLite，`METRICS_DB`）
- `search_events(id, query, result_count, created_at)` — 每次 `search_best_practices` 调用记录一条
- `experience_stats(experience_id, hit_count, adoption_rate, last_used_at, ...)` — 每次 feedback 更新
- `feedback(experience_id, adopted, reason, created_at)`

### `Experience.last_hit_at`
存在 `knowledge.json` 中，每次经验被检索到时更新（见 `knowledge.py` search 逻辑）。值为 ISO 8601 字符串或 `None`。

---

## Task 1: 在 pattern 结构中增加 `actions` 字段，改造现有 3 个 pattern

**Files:**
- Modify: `src/knowledge.py`（`analyze_quality` 方法，约 561-640 行）

### Step 1: 阅读并确认现有 3 个 pattern 的生成逻辑

阅读 `src/knowledge.py` 第 561-640 行，确认：
- `extraction_quality` pattern：无具体 ID，无法给命令 → 只保留建议文字，删去 actions
- `low_adoption` pattern：有 `low_adoption_ids` → 每个 ID 生成 `xp archive` + `xp edit` 命令
- `reject_pattern` pattern：无具体 ID → 只保留建议文字，无 actions

### Step 2: 修改 `low_adoption` pattern，填充 actions

在 `analyze_quality` 中找到 `low_adoption` pattern 的构建处，改为：

```python
low_ids = feedback_summary["low_adoption_ids"]
actions = []
for eid in low_ids[:5]:
    short = eid[:8]
    actions.append(f"xp archive {short}  # 归档")
    actions.append(f"xp edit {short}     # 编辑优化后重新激活")

low_quality_patterns.append({
    "type": "low_adoption",
    "issue": f"有 {feedback_summary['low_adoption_count']} 条经验采纳率低于 30%",
    "suggestion": "以下经验长期未被采纳，建议归档或重新编辑",
    "data": f"经验 ID: {', '.join(low_ids[:5])}",
    "actions": actions,
})
```

### Step 3: 为其余 2 个 pattern 加空 actions 字段（保持结构一致）

`extraction_quality` 和 `reject_pattern` 的 dict 中加 `"actions": []`。

### Step 4: 手动验证结构

运行：
```
python3 -c "
import asyncio, json, sys
sys.path.insert(0, 'src')
from knowledge import KnowledgeService
from storage import ExperienceStore, MetricsStore
svc = KnowledgeService(ExperienceStore(), MetricsStore())
report = asyncio.run(svc.analyze_quality())
print(json.dumps(report['low_quality_patterns'], ensure_ascii=False, indent=2))
"
```
预期：`low_adoption` pattern 的 `actions` 不为空列表（如果有低采纳经验的话）。

---

## Task 2: 新增 `staleness` pattern（90 天未命中）

**Files:**
- Modify: `src/knowledge.py`（`analyze_quality` 方法）

### Step 1: 在 `analyze_quality` 中查询 last_hit_at

在现有 3 个 pattern 检测之后，加入以下逻辑：

```python
from datetime import timedelta
cutoff_90 = (datetime.utcnow() - timedelta(days=90)).isoformat()

stale_exps = [
    e for e in all_exps
    if e.status == ExperienceStatus.ACTIVE
    and (e.last_hit_at is None or e.last_hit_at < cutoff_90)
]

if stale_exps:
    actions = []
    for e in stale_exps[:5]:
        short = e.id[:8]
        actions.append(f"xp archive {short}  # 90天未命中，归档")
    low_quality_patterns.append({
        "type": "staleness",
        "issue": f"有 {len(stale_exps)} 条 Active 经验超过 90 天未被检索",
        "suggestion": f"最近一次命中时间最早的：{stale_exps[0].last_hit_at or '从未命中'}",
        "data": f"经验 ID: {', '.join(e.id[:8] for e in stale_exps[:5])}",
        "actions": actions,
    })
```

### Step 2: 手动验证

```
python3 -c "
import asyncio, json, sys
sys.path.insert(0, 'src')
from knowledge import KnowledgeService
from storage import ExperienceStore, MetricsStore
svc = KnowledgeService(ExperienceStore(), MetricsStore())
report = asyncio.run(svc.analyze_quality())
patterns = report['low_quality_patterns']
types = [p['type'] for p in patterns]
print('patterns found:', types)
"
```
预期：`types` 中包含 `staleness`（若有符合条件的经验）。

---

## Task 3: 新增 `search_miss` pattern（有 query 但 0 结果）

**Files:**
- Modify: `src/knowledge.py`（`analyze_quality` 方法）
- Modify: `src/storage.py`（`MetricsStore`，新增查询方法）

### Step 1: 在 `MetricsStore` 中新增 `get_search_miss_queries` 方法

```python
def get_search_miss_queries(self, since_days: int = 30, limit: int = 10) -> list[dict]:
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
    conn = _get_metrics_conn()
    rows = conn.execute(
        """SELECT query, COUNT(*) as cnt FROM search_events
           WHERE result_count = 0 AND created_at >= ?
           GROUP BY query ORDER BY cnt DESC LIMIT ?""",
        (cutoff, limit)
    ).fetchall()
    conn.close()
    return [{"query": r["query"], "count": r["cnt"]} for r in rows]
```

### Step 2: 在 `analyze_quality` 中调用并生成 pattern

```python
miss_queries = self._metrics.get_search_miss_queries(since_days=30)
if miss_queries:
    top_queries = [f'"{q["query"]}" ({q["count"]} 次)' for q in miss_queries[:5]]
    low_quality_patterns.append({
        "type": "search_miss",
        "issue": f"近 30 天有 {len(miss_queries)} 个 query 未检索到任何经验",
        "suggestion": "以下 query 对应的知识空白，建议补充相关经验",
        "data": "；".join(top_queries),
        "actions": ["xp add  # 补充新经验"],
    })
```

### Step 3: 手动验证

```
python3 -c "
import asyncio, json, sys
sys.path.insert(0, 'src')
from storage import MetricsStore
m = MetricsStore()
print(m.get_search_miss_queries())
"
```
预期：返回 list（可为空列表）。

---

## Task 4: 新增 `duplicate_cluster` pattern（高相似度经验对）

**Files:**
- Modify: `src/knowledge.py`（`analyze_quality` 方法）

### Step 1: 在 `analyze_quality` 中计算 Active 经验之间的 cosine 相似度

注意：如果 Active 经验数量很大（>500），全量计算 O(n²) 会很慢，这里只取前 200 条。

```python
from .embeddings import get_provider, cosine_similarity
from .storage import VectorStore
import numpy as np

active_exps = [e for e in all_exps if e.status == ExperienceStatus.ACTIVE]
if len(active_exps) >= 2:
    v_store = VectorStore()
    active_ids = [e.id for e in active_exps[:200]]
    ids, vecs = v_store.get_all_vectors(active_ids)

    duplicates = []
    if len(ids) >= 2:
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                sim = float(cosine_similarity(
                    vecs[i].reshape(1, -1), vecs[j].reshape(1, -1)
                )[0])
                if sim >= 0.92:
                    duplicates.append((ids[i], ids[j], sim))

    if duplicates:
        actions = []
        seen = set()
        for id_a, id_b, sim in duplicates[:5]:
            if id_b not in seen:
                actions.append(f"xp delete {id_b[:8]}  # 与 {id_a[:8]} 相似度 {sim:.2f}，建议删除")
                seen.add(id_b)
        low_quality_patterns.append({
            "type": "duplicate_cluster",
            "issue": f"发现 {len(duplicates)} 对经验余弦相似度 >= 0.92",
            "suggestion": "高度相似的经验建议合并或删除冗余项",
            "data": f"共 {len(duplicates)} 对重复",
            "actions": actions,
        })
```

### Step 2: 注意 `cosine_similarity` 的调用方式

查看 `src/embeddings.py` 确认 `cosine_similarity(a, b)` 的参数形状。现有代码（`infer_adoption`）的用法是：
```python
scores = cosine_similarity(v_resp, vecs)  # v_resp shape (dim,) or (1, dim), vecs shape (n, dim)
```
所以计算两个向量相似度时传 `vecs[i:i+1]`（保持二维）和 `vecs[j:j+1]`。

### Step 3: 手动验证

```
python3 -c "
import asyncio, json, sys
sys.path.insert(0, 'src')
from knowledge import KnowledgeService
from storage import ExperienceStore, MetricsStore
svc = KnowledgeService(ExperienceStore(), MetricsStore())
report = asyncio.run(svc.analyze_quality())
types = [p['type'] for p in report['low_quality_patterns']]
print('all pattern types:', types)
"
```

---

## Task 5: 新增 `coverage_gap` pattern（有 query 但某 tag 经验数为 0）

**Files:**
- Modify: `src/knowledge.py`（`analyze_quality` 方法）
- Modify: `src/storage.py`（`MetricsStore`，新增查询方法）

### Step 1: 在 `MetricsStore` 中新增 `get_recent_query_keywords` 方法

从最近 30 天的 search_events 中提取高频词（简单按空格切词，过滤长度 < 2 的词）：

```python
def get_recent_query_keywords(self, since_days: int = 30, top_k: int = 20) -> list[str]:
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
    conn = _get_metrics_conn()
    rows = conn.execute(
        "SELECT query FROM search_events WHERE created_at >= ?", (cutoff,)
    ).fetchall()
    conn.close()

    word_count: dict[str, int] = {}
    for r in rows:
        for word in r["query"].split():
            if len(word) >= 2:
                word_count[word] = word_count.get(word, 0) + 1
    return sorted(word_count, key=lambda w: -word_count[w])[:top_k]
```

### Step 2: 在 `analyze_quality` 中检测 tag 覆盖空白

```python
recent_keywords = self._metrics.get_recent_query_keywords(since_days=30)
all_exp_tags = set()
for e in all_exps:
    if e.status == ExperienceStatus.ACTIVE:
        all_exp_tags.update(e.tags)
        all_exp_tags.update(e.metadata.tech_stack)

gap_keywords = [kw for kw in recent_keywords if kw not in all_exp_tags]

if gap_keywords:
    low_quality_patterns.append({
        "type": "coverage_gap",
        "issue": f"近 30 天有 {len(gap_keywords)} 个高频搜索词在知识库中无对应经验",
        "suggestion": "以下关键词对应知识空白，建议在下次遇到相关问题时主动提取经验",
        "data": "空白关键词: " + "、".join(gap_keywords[:8]),
        "actions": ["xp add  # 补充新经验"],
    })
```

### Step 3: 手动验证

```
python3 -c "
import asyncio, json, sys
sys.path.insert(0, 'src')
from knowledge import KnowledgeService
from storage import ExperienceStore, MetricsStore
svc = KnowledgeService(ExperienceStore(), MetricsStore())
report = asyncio.run(svc.analyze_quality())
for p in report['low_quality_patterns']:
    print(p['type'], '-', p['issue'])
"
```

---

## Task 6: 改造 `cli.py` 渲染逻辑

**Files:**
- Modify: `src/cli.py`（`cmd_analyze` 函数，约 202-258 行）

### Step 1: 在每个 pattern 块中渲染 `actions`

找到打印 pattern 的循环：
```python
for i, pattern in enumerate(report["low_quality_patterns"], 1):
    print(f"\n  [{i}] {pattern['type']}")
    print(f"      问题: {pattern['issue']}")
    print(f"      建议: {pattern['suggestion']}")
    print(f"      数据: {pattern['data']}")
```

改为：
```python
for i, pattern in enumerate(report["low_quality_patterns"], 1):
    print(f"\n  [{i}] {pattern['type']}")
    print(f"      问题: {pattern['issue']}")
    print(f"      建议: {pattern['suggestion']}")
    print(f"      数据: {pattern['data']}")
    actions = pattern.get("actions", [])
    if actions:
        print(f"      操作:")
        for action in actions:
            print(f"        {action}")
```

### Step 2: 在报告末尾添加「下一步操作汇总」区域

在 `cmd_analyze` 中收集所有 pattern 的 actions，在底部统一展示：

```python
all_actions = []
for p in report["low_quality_patterns"]:
    all_actions.extend(p.get("actions", []))

if all_actions:
    print(f"\n--- 下一步操作汇总（可直接复制执行）---")
    seen = set()
    for action in all_actions:
        cmd = action.split("#")[0].strip()
        if cmd not in seen:
            print(f"  {action}")
            seen.add(cmd)
```

### Step 3: 修改底部「优化建议」区域

找到 recommendations 打印逻辑，删去包含"优化提取 prompt"的条目（在 `knowledge.py` 的 `analyze_quality` 末尾 `recommendations` 列表中删除该项）。

在 `knowledge.py` 的 `recommendations` 列表中：
```python
# 删除这一行：
"考虑优化提取 prompt" if feedback_summary["adoption_rate"] < 0.6 else "",
```

### Step 4: 手动运行完整命令验证输出

```
python3 -m src.cli analyze
```
或者（取决于项目入口方式）：
```
xp analyze
```

预期输出：每个 pattern 下有"操作:"区域，底部有"下一步操作汇总"，无"优化提取 prompt"建议。

---

## Task 7: 回归测试（手动）

由于项目无自动化测试目录，逐一验证：

### Step 1: 验证空数据场景不崩溃

```
python3 -c "
import asyncio, sys
sys.path.insert(0, 'src')
from knowledge import KnowledgeService
from storage import ExperienceStore, MetricsStore
svc = KnowledgeService(ExperienceStore(), MetricsStore())
report = asyncio.run(svc.analyze_quality())
for p in report['low_quality_patterns']:
    assert 'actions' in p, f'missing actions in {p[\"type\"]}'
    assert isinstance(p['actions'], list)
print('OK: all patterns have actions field')
"
```

### Step 2: 验证 `get_search_miss_queries` 返回值类型

```
python3 -c "
import sys; sys.path.insert(0, 'src')
from storage import MetricsStore
result = MetricsStore().get_search_miss_queries()
assert isinstance(result, list)
print('OK:', result)
"
```

### Step 3: 验证 `get_recent_query_keywords` 返回值类型

```
python3 -c "
import sys; sys.path.insert(0, 'src')
from storage import MetricsStore
result = MetricsStore().get_recent_query_keywords()
assert isinstance(result, list)
print('OK:', result)
"
```

### Step 4: 运行 lint（如果项目配置了）

```
ruff check src/
```
或：
```
python3 -m py_compile src/knowledge.py src/storage.py src/cli.py && echo "syntax OK"
```
