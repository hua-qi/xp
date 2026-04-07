# Phase 2: 数据模型

---

## Task 05: 领域模型扩展

**Files:**
- Modify: `src/models.py`
- Create: `tests/unit/test_models_cs.py`

**Step 1: 阅读现有 models.py，了解已有字段**

```bash
# 阅读 src/models.py
```

**Step 2: 写失败测试**

```python
# tests/unit/test_models_cs.py
from src.models import Experience, ExperienceStatus

def test_experience_has_ab_group_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "ab_group" in fields

def test_experience_has_conflict_with_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "conflict_with" in fields

def test_experience_has_retry_count_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "retry_count" in fields

def test_experience_has_raw_input_field():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Experience)}
    assert "raw_input" in fields

def test_experience_status_has_needs_fix():
    values = {s.value for s in ExperienceStatus}
    assert "needs_fix" in values
```

**Step 3: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_models_cs.py -v
```

预期：FAIL

**Step 4: 在 Experience dataclass 中新增字段**

在 `src/models.py` 的 `Experience` dataclass 末尾新增：

```python
ab_group: str = "B"
conflict_with: str | None = None
retry_count: int = 0
raw_input: dict | None = None
```

在 `ExperienceStatus` enum 中新增：

```python
NEEDS_FIX = "needs_fix"
```

**Step 5: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_models_cs.py -v
```

预期：PASS（5 个测试）

**Step 6: 在 models.py 中新增 ConflictReview 和 CorrectionRequest dataclass**

```python
@dataclass
class ConflictReview:
    id: str
    experience_id_a: str
    experience_id_b: str
    conflict_type: str
    status: str = "pending"
    resolution: str | None = None
    condition_note: str | None = None
    resolved_at: str | None = None
    created_at: str = ""


@dataclass
class CorrectionRequest:
    id: str
    experience_id: str
    session_id: str
    comment: str
    task_description: str
    outcome_description: str
    status: str = "pending"
    fixed_at: str | None = None
    created_at: str = ""
```

**Step 7: 运行全量单元测试确认无回归**

```bash
python -m pytest tests/unit/ -q
```

预期：原有测试全通过

**Step 8: 提交**

```bash
git add src/models.py tests/unit/test_models_cs.py
git commit -m "feat: extend Experience model for CS arch"
```

---

## Task 06: MySQL 建表 SQL

**Files:**
- Create: `src/infrastructure/backends/mysql_schema.sql`
- Create: `tests/unit/test_mysql_schema.py`

**Step 1: 写失败测试（验证 SQL 文件存在且包含关键表名）**

```python
# tests/unit/test_mysql_schema.py
from pathlib import Path

SCHEMA_FILE = Path("src/infrastructure/backends/mysql_schema.sql")

def test_schema_file_exists():
    assert SCHEMA_FILE.exists()

def test_schema_contains_required_tables():
    sql = SCHEMA_FILE.read_text()
    for table in ["experiences", "sessions", "feedbacks", "conflict_reviews",
                  "correction_requests", "prompt_configs", "experience_stats"]:
        assert table in sql, f"Missing table: {table}"

def test_schema_experiences_has_embedding_column():
    sql = SCHEMA_FILE.read_text()
    assert "embedding" in sql

def test_schema_experiences_has_ab_group_column():
    sql = SCHEMA_FILE.read_text()
    assert "ab_group" in sql
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_mysql_schema.py -v
```

预期：FAIL（文件不存在）

**Step 3: 创建 mysql_schema.sql**

```sql
-- src/infrastructure/backends/mysql_schema.sql
CREATE TABLE IF NOT EXISTS experiences (
    id              VARCHAR(36)     PRIMARY KEY,
    type            VARCHAR(32)     NOT NULL,
    level           VARCHAR(16)     NOT NULL,
    title           TEXT            NOT NULL,
    tags            JSON            NOT NULL DEFAULT (JSON_ARRAY()),
    problem         TEXT            NOT NULL,
    solution        TEXT            NOT NULL,
    key_decisions   TEXT            NOT NULL DEFAULT '',
    confidence      FLOAT           NOT NULL DEFAULT 0.6,
    status          VARCHAR(32)     NOT NULL DEFAULT 'pending',
    source          VARCHAR(32)     NOT NULL DEFAULT 'agent',
    created_at      VARCHAR(32)     NOT NULL,
    related_files   JSON            NOT NULL DEFAULT (JSON_ARRAY()),
    reject_reason   TEXT,
    metadata        JSON            NOT NULL DEFAULT (JSON_OBJECT()),
    project         VARCHAR(36)     NOT NULL DEFAULT 'default',
    scope_type      VARCHAR(32)     NOT NULL DEFAULT 'project',
    scope_id        VARCHAR(36),
    promoted_to     VARCHAR(36),
    demoted_from    VARCHAR(36),
    recall_count    INT             NOT NULL DEFAULT 0,
    adoption_rate   FLOAT           NOT NULL DEFAULT 0.0,
    last_hit_at     VARCHAR(32),
    stale_reason    TEXT,
    ab_group        ENUM('A','B')   NOT NULL DEFAULT 'B',
    conflict_with   VARCHAR(36),
    retry_count     INT             NOT NULL DEFAULT 0,
    raw_input       JSON,
    embedding       MEDIUMBLOB
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sessions (
    session_id              VARCHAR(36)     PRIMARY KEY,
    task_description        TEXT            NOT NULL,
    experience_ids_injected JSON            NOT NULL DEFAULT (JSON_ARRAY()),
    iteration_count         INT             NOT NULL DEFAULT 1,
    had_error_correction    TINYINT(1)      NOT NULL DEFAULT 0,
    user_accepted           TINYINT(1)      NOT NULL DEFAULT 1,
    ab_test_group           VARCHAR(16)     NOT NULL DEFAULT 'B',
    created_at              VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feedbacks (
    id              VARCHAR(36)     PRIMARY KEY,
    experience_id   VARCHAR(36)     NOT NULL,
    session_id      VARCHAR(36),
    helpful         TINYINT(1)      NOT NULL,
    comment         TEXT,
    created_at      VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS experience_stats (
    experience_id   VARCHAR(36)     PRIMARY KEY,
    hit_count       INT             NOT NULL DEFAULT 0,
    adopted_count   INT             NOT NULL DEFAULT 0,
    rejected_count  INT             NOT NULL DEFAULT 0,
    adoption_rate   FLOAT           NOT NULL DEFAULT 0.0,
    last_adopted_at VARCHAR(32)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS conflict_reviews (
    id              VARCHAR(36)     PRIMARY KEY,
    experience_id_a VARCHAR(36)     NOT NULL,
    experience_id_b VARCHAR(36)     NOT NULL,
    conflict_type   VARCHAR(32)     NOT NULL,
    status          ENUM('pending','resolved') NOT NULL DEFAULT 'pending',
    resolution      VARCHAR(32),
    condition_note  TEXT,
    resolved_at     VARCHAR(32),
    created_at      VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS correction_requests (
    id                  VARCHAR(36)     PRIMARY KEY,
    experience_id       VARCHAR(36)     NOT NULL,
    session_id          VARCHAR(36)     NOT NULL,
    comment             TEXT            NOT NULL,
    task_description    TEXT            NOT NULL,
    outcome_description TEXT            NOT NULL,
    status              ENUM('pending','fixed','dismissed') NOT NULL DEFAULT 'pending',
    fixed_at            VARCHAR(32),
    created_at          VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prompt_configs (
    `key`       VARCHAR(64)     PRIMARY KEY,
    content     TEXT            NOT NULL,
    updated_at  VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO prompt_configs (`key`, content, updated_at) VALUES
('extraction_prompt',
'你是一个工程经验提炼助手。根据以下任务信息，提炼出结构化的工程经验。\n\n## 输入\n任务描述：{task_description}\n任务结果：{outcome_description}\n结果状态：{outcome}\n\n## 输出要求\n严格按照以下 JSON 格式输出，不要输出其他内容：\n{\n  "title": "10-20字的经验标题，概括核心问题和解法",\n  "problem": "清晰描述问题场景和背景，50字以上",\n  "solution": "具体的解决方案和步骤，50字以上",\n  "key_decisions": "关键决策点和踩坑点，30字以上",\n  "tags": ["技术栈标签", "最多5个"],\n  "type": "bugfix 或 feature 或 pattern 三选一"\n}',
NOW()),
('conflict_type_prompt',
'以下两条工程经验针对相似问题给出了不同方案，请判断冲突类型。\n\n## 已有经验\n问题：{existing_problem}\n方案：{existing_solution}\n\n## 新经验\n问题：{new_problem}\n方案：{new_solution}\n\n## 冲突类型\n请从以下类型中选择一个，只输出类型名称：\n- outdated\n- alternative\n- version_diff\n- new_may_wrong\n- condition_diff',
NOW()),
('rerank_prompt',
'根据以下任务描述，从候选经验中选出最相关的至多3条。\n\n## 任务\n{task_description}\n\n## 候选经验\n{candidates}\n\n## 输出要求\n只输出 JSON 数组，包含最相关的经验 ID，按相关度降序排列：\n["id-1", "id-2", "id-3"]\n若没有相关经验，输出：[]',
NOW()),
('comment_analysis_prompt',
'以下是用户对一条工程经验的反馈 comment，请判断反馈语义类型。\n\n## 反馈内容\n{comment}\n\n## 判断规则\n- 如果反馈表达"经验完全不适用、方向错误、和当前问题无关"，输出：irrelevant\n- 如果反馈表达"经验思路/方向是对的，但某些细节、版本、参数有误"，输出：needs_fix\n\n只输出一个词：irrelevant 或 needs_fix',
NOW());
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_mysql_schema.py -v
```

预期：PASS（4 个测试）

**Step 5: 在本地 MySQL 执行建表**

```bash
docker exec -i xp-mysql mysql -uroot -proot xp < src/infrastructure/backends/mysql_schema.sql
```

预期：无报错

**Step 6: 提交**

```bash
git add src/infrastructure/backends/mysql_schema.sql tests/unit/test_mysql_schema.py
git commit -m "feat: add MySQL schema for CS arch"
```

---

## Task 07: MySQL 后端实现

**Files:**
- Create: `src/infrastructure/backends/mysql.py`
- Modify: `src/infrastructure/backends/__init__.py`
- Create: `tests/unit/test_mysql_backend.py`

> **背景**：现有 `StorageBackend` 抽象接口在 `src/infrastructure/backends/base.py`。MySQL 后端需实现同一接口，但新增了 `embedding` BLOB 存取、A/B 分组查询、冲突检测等 MySQL 专有方法。

**Step 1: 写失败测试（用 AsyncMock 模拟 aiomysql 连接）**

```python
# tests/unit/test_mysql_backend.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.infrastructure.backends.mysql import MySQLBackend


@pytest.fixture
def backend():
    return MySQLBackend(dsn="mysql+aiomysql://root:root@localhost:3306/xp")


def test_mysql_backend_instantiation(backend):
    assert backend is not None


async def test_get_experiences_by_project_returns_list(backend):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    with patch.object(backend, "_conn", mock_conn):
        result = await backend.async_get_experiences_by_project("proj-1")
    assert isinstance(result, list)


async def test_save_vector_stores_blob(backend):
    import numpy as np
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    vec = np.zeros(1024, dtype=np.float32)
    with patch.object(backend, "_conn", mock_conn):
        await backend.async_save_vector("exp-1", vec.tolist())
    mock_conn.execute.assert_called_once()
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_mysql_backend.py -v
```

预期：FAIL（模块不存在）

**Step 3: 实现 MySQLBackend 骨架**

```python
# src/infrastructure/backends/mysql.py
from __future__ import annotations
import json
import struct
from typing import Optional
import numpy as np

from .base import StorageBackend
from ...models import Experience, ExperienceStatus, Session, Feedback, ExperienceStats


class MySQLBackend(StorageBackend):
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool = None

    async def connect(self):
        import aiomysql
        # dsn: mysql+aiomysql://user:pass@host:port/db
        from urllib.parse import urlparse
        url = urlparse(self._dsn.replace("mysql+aiomysql://", "mysql://"))
        self._pool = await aiomysql.create_pool(
            host=url.hostname,
            port=url.port or 3306,
            user=url.username,
            password=url.password,
            db=url.path.lstrip("/"),
            autocommit=True,
            charset="utf8mb4",
        )

    async def disconnect(self):
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    def _vec_to_blob(self, vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    def _blob_to_vec(self, blob: bytes) -> list[float]:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))

    async def async_get_experiences_by_project(
        self,
        project_id: str,
        status: str = "active",
    ) -> list[Experience]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM experiences WHERE project=%s AND status=%s",
                    (project_id, status),
                )
                rows = await cur.fetchall()
        return [self._row_to_experience(r) for r in rows]

    async def async_save_vector(self, exp_id: str, vector: list[float]) -> None:
        blob = self._vec_to_blob(vector)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE experiences SET embedding=%s WHERE id=%s",
                    (blob, exp_id),
                )

    async def async_get_vectors_by_project(
        self, project_id: str
    ) -> tuple[list[str], np.ndarray]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, embedding FROM experiences "
                    "WHERE project=%s AND status='active' AND embedding IS NOT NULL",
                    (project_id,),
                )
                rows = await cur.fetchall()
        if not rows:
            return [], np.array([])
        ids = [r[0] for r in rows]
        vecs = np.array([self._blob_to_vec(r[1]) for r in rows], dtype=np.float32)
        return ids, vecs

    async def async_get_ab_group(self, project_id: str) -> str:
        h = hash(project_id)
        return "A" if h % 2 == 0 else "B"

    async def async_fulltext_search(
        self, query: str, project_id: str, limit: int = 20
    ) -> list[Experience]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM experiences "
                    "WHERE project=%s AND status='active' "
                    "AND MATCH(title, problem, solution) AGAINST (%s IN BOOLEAN MODE) "
                    "LIMIT %s",
                    (project_id, query, limit),
                )
                rows = await cur.fetchall()
        return [self._row_to_experience(r) for r in rows]

    async def async_add_experience(self, exp: Experience) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO experiences
                    (id, type, level, title, tags, problem, solution,
                     key_decisions, confidence, status, source, created_at,
                     related_files, metadata, project, scope_type, scope_id,
                     ab_group, conflict_with, retry_count, raw_input)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        exp.id,
                        exp.type.value if hasattr(exp.type, "value") else exp.type,
                        exp.level.value if hasattr(exp.level, "value") else exp.level,
                        exp.title,
                        json.dumps(exp.tags, ensure_ascii=False),
                        exp.problem,
                        exp.solution,
                        exp.key_decisions,
                        exp.confidence,
                        exp.status.value if hasattr(exp.status, "value") else exp.status,
                        exp.source.value if hasattr(exp.source, "value") else exp.source,
                        exp.created_at,
                        json.dumps(exp.related_files, ensure_ascii=False),
                        json.dumps(
                            exp.metadata.__dict__ if hasattr(exp.metadata, "__dict__") else {},
                            ensure_ascii=False,
                        ),
                        exp.project,
                        getattr(exp, "scope_type", "project"),
                        getattr(exp, "scope_id", None),
                        getattr(exp, "ab_group", "B"),
                        getattr(exp, "conflict_with", None),
                        getattr(exp, "retry_count", 0),
                        json.dumps(getattr(exp, "raw_input", None), ensure_ascii=False)
                        if getattr(exp, "raw_input", None)
                        else None,
                    ),
                )

    async def async_update_experience(self, exp: Experience) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE experiences SET
                    status=%s, confidence=%s, conflict_with=%s,
                    retry_count=%s, raw_input=%s
                    WHERE id=%s""",
                    (
                        exp.status.value if hasattr(exp.status, "value") else exp.status,
                        exp.confidence,
                        getattr(exp, "conflict_with", None),
                        getattr(exp, "retry_count", 0),
                        json.dumps(getattr(exp, "raw_input", None), ensure_ascii=False)
                        if getattr(exp, "raw_input", None)
                        else None,
                        exp.id,
                    ),
                )

    async def async_update_experience_stats(
        self,
        exp_id: str,
        hit: bool = False,
        adopted: bool = False,
        rejected: bool = False,
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO experience_stats (experience_id) VALUES (%s) "
                    "ON DUPLICATE KEY UPDATE experience_id=experience_id",
                    (exp_id,),
                )
                if hit:
                    await cur.execute(
                        "UPDATE experience_stats SET hit_count=hit_count+1 WHERE experience_id=%s",
                        (exp_id,),
                    )
                if adopted:
                    await cur.execute(
                        "UPDATE experience_stats SET adopted_count=adopted_count+1, "
                        "last_adopted_at=NOW() WHERE experience_id=%s",
                        (exp_id,),
                    )
                if rejected:
                    await cur.execute(
                        "UPDATE experience_stats SET rejected_count=rejected_count+1 "
                        "WHERE experience_id=%s",
                        (exp_id,),
                    )
                await cur.execute(
                    "UPDATE experience_stats SET "
                    "adoption_rate=IF(hit_count>0, adopted_count/hit_count, 0) "
                    "WHERE experience_id=%s",
                    (exp_id,),
                )

    async def async_get_prompt(self, key: str) -> Optional[str]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT content FROM prompt_configs WHERE `key`=%s", (key,)
                )
                row = await cur.fetchone()
        return row[0] if row else None

    async def async_set_conflict(
        self, exp_id_a: str, exp_id_b: str, conflict_type: str
    ) -> None:
        from ...models import ConflictReview
        import uuid
        from datetime import datetime, timezone
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE experiences SET conflict_with=%s WHERE id=%s",
                    (exp_id_b, exp_id_a),
                )
                await cur.execute(
                    "UPDATE experiences SET conflict_with=%s WHERE id=%s",
                    (exp_id_a, exp_id_b),
                )
                await cur.execute(
                    "INSERT INTO conflict_reviews "
                    "(id, experience_id_a, experience_id_b, conflict_type, created_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (
                        str(uuid.uuid4()),
                        exp_id_a,
                        exp_id_b,
                        conflict_type,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    async def async_add_correction_request(
        self,
        experience_id: str,
        session_id: str,
        comment: str,
        task_description: str,
        outcome_description: str,
    ) -> None:
        import uuid
        from datetime import datetime, timezone
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO correction_requests "
                    "(id, experience_id, session_id, comment, "
                    "task_description, outcome_description, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        str(uuid.uuid4()),
                        experience_id,
                        session_id,
                        comment,
                        task_description,
                        outcome_description,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    async def async_record_session(self, session: Session) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO sessions "
                    "(session_id, task_description, experience_ids_injected, "
                    "iteration_count, had_error_correction, user_accepted, "
                    "ab_test_group, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        session.session_id,
                        session.task_description,
                        json.dumps(session.experience_ids_injected),
                        session.iteration_count,
                        int(session.had_error_correction),
                        int(session.user_accepted),
                        getattr(session, "ab_test_group", "B"),
                        session.created_at
                        if hasattr(session, "created_at")
                        else "",
                    ),
                )

    async def async_record_feedback(self, feedback: Feedback) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO feedbacks "
                    "(id, experience_id, session_id, helpful, comment, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        feedback.id if hasattr(feedback, "id") else str(uuid.uuid4()),
                        feedback.experience_id,
                        getattr(feedback, "session_id", None),
                        int(feedback.helpful),
                        getattr(feedback, "comment", None),
                        feedback.created_at
                        if hasattr(feedback, "created_at")
                        else "",
                    ),
                )

    def _row_to_experience(self, row: dict) -> Experience:
        from ...models import ExperienceType, ExperienceLevel, ExperienceStatus, ExperienceMetadata, ExperienceSource
        tags = json.loads(row["tags"]) if isinstance(row["tags"], str) else (row["tags"] or [])
        meta_raw = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {})
        return Experience(
            id=row["id"],
            type=ExperienceType(row["type"]),
            level=ExperienceLevel(row["level"]),
            title=row["title"],
            tags=tags,
            problem=row["problem"],
            solution=row["solution"],
            key_decisions=row.get("key_decisions", ""),
            confidence=float(row["confidence"]),
            status=ExperienceStatus(row["status"]),
            source=ExperienceSource(row.get("source", "agent")),
            created_at=row["created_at"],
            related_files=json.loads(row["related_files"]) if isinstance(row["related_files"], str) else [],
            metadata=ExperienceMetadata(**meta_raw) if meta_raw else ExperienceMetadata(),
            project=row.get("project", "default"),
            ab_group=row.get("ab_group", "B"),
            conflict_with=row.get("conflict_with"),
            retry_count=int(row.get("retry_count", 0)),
            raw_input=json.loads(row["raw_input"]) if row.get("raw_input") else None,
        )

    # ---- 以下为继承自 StorageBackend 的同步方法（本项目已全面 async，保留空实现）----

    def add_experience(self, exp): raise NotImplementedError
    def get_experience(self, exp_id): raise NotImplementedError
    def update_experience(self, exp): raise NotImplementedError
    def delete_experience(self, exp_id): raise NotImplementedError
    def list_by_status(self, status): raise NotImplementedError
    def record_session(self, session): raise NotImplementedError
    def record_feedback(self, feedback): raise NotImplementedError
    def get_experience_stats(self, exp_id): raise NotImplementedError
    def save_vector(self, exp_id, vector): raise NotImplementedError
    def get_all_vectors(self, exp_ids=None): raise NotImplementedError
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_mysql_backend.py -v
```

预期：PASS（3 个测试，全为单元级无真实 DB）

**Step 5: 运行全量单元测试**

```bash
python -m pytest tests/unit/ -q
```

预期：全绿

**Step 6: 提交**

```bash
git add src/infrastructure/backends/mysql.py tests/unit/test_mysql_backend.py
git commit -m "feat: implement MySQLBackend"
```
