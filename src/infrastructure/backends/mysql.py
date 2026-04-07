from __future__ import annotations
import json
import struct
from typing import Optional
import numpy as np

from .base import StorageBackend
from ...models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, Session, Feedback, ExperienceStats,
    ConflictReview, CorrectionRequest,
)


class MySQLBackend(StorageBackend):
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool = None

    async def connect(self):
        import aiomysql
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

    def _row_to_experience(self, row: dict) -> Experience:
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
            related_files=json.loads(row["related_files"]) if isinstance(row.get("related_files"), str) else [],
            metadata=ExperienceMetadata(**meta_raw) if meta_raw else ExperienceMetadata(),
            project=row.get("project", "default"),
            ab_group=row.get("ab_group", "B"),
            conflict_with=row.get("conflict_with"),
            retry_count=int(row.get("retry_count", 0)),
            raw_input=json.loads(row["raw_input"]) if row.get("raw_input") else None,
        )

    async def async_get_experiences_by_project(
        self,
        project_id: str,
        status: str = "active",
    ) -> list[Experience]:
        import aiomysql
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
        return "A" if hash(project_id) % 2 == 0 else "B"

    async def async_fulltext_search(
        self, query: str, project_id: str, limit: int = 20
    ) -> list[Experience]:
        import aiomysql
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
                        getattr(session, "created_at", ""),
                    ),
                )

    async def async_record_feedback(self, feedback: Feedback) -> None:
        import uuid
        from datetime import datetime, timezone
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO feedbacks "
                    "(id, experience_id, session_id, helpful, comment, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        getattr(feedback, "id", str(uuid.uuid4())),
                        feedback.experience_id,
                        getattr(feedback, "session_id", None),
                        int(feedback.helpful if hasattr(feedback, "helpful") else feedback.adopted),
                        getattr(feedback, "comment", None),
                        getattr(feedback, "created_at", datetime.now(timezone.utc).isoformat()),
                    ),
                )

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
