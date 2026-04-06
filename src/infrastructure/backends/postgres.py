import json
from typing import Optional, TYPE_CHECKING
from datetime import datetime

from .base import StorageBackend
from ...models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceMetadata,
    ExperienceSource, ExperienceStatus, Session, Feedback, ExperienceStats,
)

if TYPE_CHECKING:
    import numpy as np

try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import numpy as _np
except ImportError:
    _np = None

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
    scope_type TEXT NOT NULL DEFAULT 'project',
    scope_id TEXT,
    promoted_to TEXT,
    demoted_from TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    adoption_rate FLOAT NOT NULL DEFAULT 0.0,
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

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS businesses (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(id),
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(id),
    name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    frameworks JSONB NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS search_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    query_embedding vector(512),
    result_ids JSONB NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_events (
    id TEXT PRIMARY KEY,
    search_event_id TEXT NOT NULL REFERENCES search_events(id),
    helpful_ids JSONB NOT NULL DEFAULT '[]',
    unhelpful_ids JSONB NOT NULL DEFAULT '[]',
    comment TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_business (
    project_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    PRIMARY KEY (project_id, business_id)
);

CREATE TABLE IF NOT EXISTS business_team (
    business_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    PRIMARY KEY (business_id, team_id)
);

CREATE TABLE IF NOT EXISTS user_business (
    user_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    PRIMARY KEY (user_id, business_id)
);

ALTER TABLE teams ADD COLUMN IF NOT EXISTS owner_email TEXT;
ALTER TABLE businesses ADD COLUMN IF NOT EXISTS owner_email TEXT;

CREATE TABLE IF NOT EXISTS user_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    email TEXT,
    database_url TEXT
);

CREATE TABLE IF NOT EXISTS promotion_candidates (
    id TEXT PRIMARY KEY,
    experience_id TEXT NOT NULL,
    target_scope_type TEXT NOT NULL,
    target_scope_id TEXT NOT NULL,
    score FLOAT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    ignored_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
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

    async def async_get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> "tuple[list[str], np.ndarray]":
        self._pool_required()
        async with self._pool.acquire() as conn:
            if exp_ids is not None:
                if not exp_ids:
                    return [], _np.array([])
                rows = await conn.fetch(
                    "SELECT id, embedding FROM experiences WHERE id = ANY($1) AND embedding IS NOT NULL",
                    exp_ids,
                )
            else:
                rows = await conn.fetch("SELECT id, embedding FROM experiences WHERE embedding IS NOT NULL")
        if not rows:
            return [], _np.array([])
        ids = [r["id"] for r in rows]
        vecs = _np.array([list(r["embedding"]) for r in rows], dtype=_np.float32)
        return ids, vecs

    async def async_get_stats(self, since_days: int | None = None) -> dict:
        self._pool_required()
        from datetime import datetime, timedelta
        async with self._pool.acquire() as conn:
            date_filter = ""
            params: list = []
            if since_days:
                cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
                date_filter = "WHERE created_at >= $1"
                params = [cutoff]

            search_total = await conn.fetchval(
                f"SELECT COUNT(*) FROM search_events {date_filter}", *params
            ) or 0
            search_hit = await conn.fetchval(
                f"SELECT COUNT(*) FROM search_events {date_filter} {'AND' if date_filter else 'WHERE'} result_ids != '[]'",
                *params
            ) or 0
            session_total = await conn.fetchval(
                f"SELECT COUNT(*) FROM sessions {date_filter}", *params
            ) or 0
            top_adopted_rows = await conn.fetch(
                "SELECT experience_id, adoption_rate, hit_count FROM experience_stats WHERE hit_count >= 3 ORDER BY adoption_rate DESC LIMIT 3"
            )
            cutoff_30 = (datetime.utcnow() - timedelta(days=30)).isoformat()
            new_sessions_30d = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE created_at >= $1", cutoff_30
            ) or 0

        return {
            "search_total": search_total,
            "search_hit_rate": round(search_hit / search_total, 3) if search_total else 0,
            "review_confirmed": 0,
            "review_rejected": 0,
            "review_pass_rate": 0.0,
            "session_total": session_total,
            "result_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
            "result_not_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
            "avg_result_count": 0.0,
            "query_adoption_rate": 0.0,
            "top_adopted_experiences": [
                {"experience_id": r["experience_id"], "adoption_rate": r["adoption_rate"], "hit_count": r["hit_count"]}
                for r in top_adopted_rows
            ],
            "zombie_count_db": 0,
            "ab_test_groups": {},
            "new_sessions_30d": new_sessions_30d,
        }

    async def async_get_feedback_summary(self, since_days: int | None = None) -> dict:
        self._pool_required()
        from datetime import datetime, timedelta
        async with self._pool.acquire() as conn:
            date_filter = ""
            params: list = []
            if since_days:
                cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
                date_filter = "WHERE created_at >= $1"
                params = [cutoff]

            total = await conn.fetchval(f"SELECT COUNT(*) FROM feedback {date_filter}", *params) or 0
            adopted = await conn.fetchval(
                f"SELECT COUNT(*) FROM feedback {date_filter} {'AND' if date_filter else 'WHERE'} adopted = true",
                *params
            ) or 0
            low_rows = await conn.fetch(
                "SELECT experience_id FROM experience_stats WHERE adoption_rate < 0.3"
            )

        return {
            "total_feedback": total,
            "adopted_count": adopted,
            "adoption_rate": round(adopted / total, 3) if total else 0.0,
            "low_adoption_count": len(low_rows),
            "low_adoption_ids": [r["experience_id"] for r in low_rows],
            "reject_reasons": {},
        }

    async def async_get_search_miss_queries(self, since_days: int = 30, limit: int = 10) -> list[dict]:
        self._pool_required()
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT query_text, COUNT(*) as cnt FROM search_events WHERE result_ids = '[]' AND timestamp >= $1 GROUP BY query_text ORDER BY cnt DESC LIMIT $2",
                cutoff, limit
            )
        return [{"query": r["query_text"], "count": r["cnt"]} for r in rows]

    async def async_get_recent_query_keywords(self, since_days: int = 30, top_k: int = 20) -> list[str]:
        self._pool_required()
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT query_text FROM search_events WHERE timestamp >= $1", cutoff
            )
        word_count: dict[str, int] = {}
        for r in rows:
            for word in r["query_text"].split():
                if len(word) >= 2:
                    word_count[word] = word_count.get(word, 0) + 1
        return sorted(word_count, key=lambda w: -word_count[w])[:top_k]

    async def async_get_hitted_experience_ids(self) -> list[str]:
        self._pool_required()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT experience_id FROM experience_stats WHERE hit_count > 0"
            )
        return [r["experience_id"] for r in rows]

    async def async_get_review_reject_reasons(self, limit: int = 10) -> dict[str, int]:
        return {}


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
