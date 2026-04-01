import json
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
                    "SELECT id, embedding FROM experiences WHERE id = ANY($1) AND embedding IS NOT NULL",
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
