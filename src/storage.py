import json
import sqlite3
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import XP_HOME
from .models import (
    Experience,
    ExperienceLevel,
    ExperienceMetadata,
    ExperienceSource,
    ExperienceStatus,
    ExperienceStats,
    ExperienceType,
    Feedback,
    Session,
)

KNOWLEDGE_FILE = XP_HOME / "knowledge.json"
METRICS_DB = XP_HOME / "metrics.db"


def _ensure_home():
    XP_HOME.mkdir(parents=True, exist_ok=True)


def _load_knowledge() -> dict[str, dict]:
    if not KNOWLEDGE_FILE.exists():
        return {}
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_knowledge(data: dict[str, dict]):
    _ensure_home()
    with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_metrics_conn() -> sqlite3.Connection:
    _ensure_home()
    conn = sqlite3.connect(str(METRICS_DB))
    conn.row_factory = sqlite3.Row
    _init_metrics_schema(conn)
    return conn


def _init_metrics_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            task_description TEXT NOT NULL,
            experience_ids_injected TEXT NOT NULL,
            iteration_count INTEGER NOT NULL,
            had_error_correction INTEGER NOT NULL,
            user_accepted INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            ab_test_group TEXT DEFAULT 'treatment',
            ab_test_result_shown INTEGER DEFAULT 1,
            result_shown_recorded INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS search_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            result_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experience_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reject_reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experience_id TEXT NOT NULL,
            adopted INTEGER NOT NULL,
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
            adoption_rate REAL DEFAULT 0.0
        );



        -- Experience 向量表
        CREATE TABLE IF NOT EXISTS experience_vectors (
            experience_id TEXT PRIMARY KEY,
            vector BLOB NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.commit()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN ab_test_group TEXT DEFAULT 'treatment'")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN ab_test_result_shown INTEGER DEFAULT 1")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN result_shown_recorded INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass




import struct
import numpy as np

class VectorStore:
    def __init__(self):
        self._conn = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _get_metrics_conn()
        return self._conn

    def save_vector(self, exp_id: str, vector: list[float]):
        conn = self._get_conn()
        # Compress vector to binary
        blob = struct.pack(f"{len(vector)}f", *vector)
        conn.execute(
            """INSERT INTO experience_vectors (experience_id, vector, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(experience_id) DO UPDATE SET
               vector=excluded.vector, updated_at=excluded.updated_at""",
            (exp_id, blob, datetime.utcnow().isoformat())
        )
        conn.commit()

    def delete_vector(self, exp_id: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM experience_vectors WHERE experience_id = ?", (exp_id,))
        conn.commit()

    def save_vectors(self, items: list[tuple[str, list[float]]]):
        if not items:
            return
        conn = self._get_conn()
        data = []
        now = datetime.utcnow().isoformat()
        for exp_id, vector in items:
            blob = struct.pack(f"{len(vector)}f", *vector)
            data.append((exp_id, blob, now))
        conn.executemany(
            """INSERT INTO experience_vectors (experience_id, vector, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(experience_id) DO UPDATE SET
               vector=excluded.vector, updated_at=excluded.updated_at""",
            data
        )
        conn.commit()

    def get_vector(self, exp_id: str) -> Optional[np.ndarray]:
        conn = self._get_conn()
        row = conn.execute("SELECT vector FROM experience_vectors WHERE experience_id = ?", (exp_id,)).fetchone()
        if not row:
            return None
        blob = row["vector"]
        num_floats = len(blob) // 4
        vector = struct.unpack(f"{num_floats}f", blob)
        return np.array(vector, dtype=np.float32)

    def get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> tuple[list[str], np.ndarray]:
        conn = self._get_conn()
        if exp_ids is not None:
            if not exp_ids:
                return [], np.array([])
            placeholders = ",".join(["?"] * len(exp_ids))
            rows = conn.execute(f"SELECT experience_id, vector FROM experience_vectors WHERE experience_id IN ({placeholders})", exp_ids).fetchall()
        else:
            rows = conn.execute("SELECT experience_id, vector FROM experience_vectors").fetchall()
        
        if not rows:
            return [], np.array([])
            
        ids = []
        vecs = []
        for row in rows:
            ids.append(row["experience_id"])
            blob = row["vector"]
            num_floats = len(blob) // 4
            vector = struct.unpack(f"{num_floats}f", blob)
            vecs.append(vector)
            
        return ids, np.array(vecs, dtype=np.float32)

class ExperienceStore:
    def add(self, exp: Experience) -> Experience:
        data = _load_knowledge()
        data[exp.id] = self._to_dict(exp)
        _save_knowledge(data)
        return exp

    def get(self, exp_id: str) -> Optional[Experience]:
        data = _load_knowledge()
        if exp_id not in data:
            return None
        return self._from_dict(data[exp_id])

    def update(self, exp: Experience) -> bool:
        data = _load_knowledge()
        if exp.id not in data:
            return False
        data[exp.id] = self._to_dict(exp)
        _save_knowledge(data)
        return True

    def delete(self, exp_id: str) -> bool:
        data = _load_knowledge()
        if exp_id not in data:
            return False
        del data[exp_id]
        _save_knowledge(data)
        VectorStore().delete_vector(exp_id)
        return True

    def list_by_status(self, status: ExperienceStatus) -> list[Experience]:
        data = _load_knowledge()
        return [
            self._from_dict(v)
            for v in data.values()
            if v.get("status") == status.value
        ]

    def list_active(self) -> list[Experience]:
        return self.list_by_status(ExperienceStatus.ACTIVE)

    def count_by_status(self) -> dict[str, int]:
        data = _load_knowledge()
        counts: dict[str, int] = {}
        for v in data.values():
            s = v.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return counts


    def _to_dict(self, exp: Experience) -> dict:
        return {
            "id": exp.id,
            "type": exp.type.value,
            "level": exp.level.value,
            "title": exp.title,
            "tags": exp.tags,
            "problem": exp.problem,
            "solution": exp.solution,
            "confidence": exp.confidence,
            "status": exp.status.value,
            "source": exp.source.value,
            "created_at": exp.created_at,
            "related_files": exp.related_files,
            "reject_reason": exp.reject_reason,
            "metadata": {
                "tech_stack": exp.metadata.tech_stack,
                "problem_type": exp.metadata.problem_type,
                "scene": exp.metadata.scene,
            },
            "file_hashes": exp.file_hashes,
            "project": exp.project,
            "last_hit_at": exp.last_hit_at,
            "stale_reason": exp.stale_reason,
            "key_decisions": exp.key_decisions,
        }

    def _from_dict(self, d: dict) -> Experience:
        metadata_dict = d.get("metadata", {})
        metadata = ExperienceMetadata(
            tech_stack=metadata_dict.get("tech_stack", []),
            problem_type=metadata_dict.get("problem_type", ""),
            scene=metadata_dict.get("scene", []),
        )
        
        # 向后兼容：如果没有 metadata，从 tags 推断
        if not metadata.tech_stack and d.get("tags"):
            metadata.tech_stack = d["tags"]
        
        return Experience(
            id=d["id"],
            type=ExperienceType(d["type"]),
            level=ExperienceLevel(d["level"]),
            title=d["title"],
            tags=d.get("tags", []),
            problem=d["problem"],
            solution=d["solution"],
            confidence=d.get("confidence", 0.8),
            status=ExperienceStatus(d["status"]),
            source=ExperienceSource(d["source"]),
            created_at=d["created_at"],
            related_files=d.get("related_files", []),
            reject_reason=d.get("reject_reason"),
            metadata=metadata,
            file_hashes=d.get("file_hashes", {}),
            project=d.get("project", "default"),
            last_hit_at=d.get("last_hit_at"),
            stale_reason=d.get("stale_reason"),
            key_decisions=d.get("key_decisions", ""),
        )


class MetricsStore:
    def record_search(self, query: str, result_count: int):
        with _get_metrics_conn() as conn:
            conn.execute(
                "INSERT INTO search_events (query, result_count, created_at) VALUES (?, ?, ?)",
                (query, result_count, datetime.utcnow().isoformat()),
            )



    def record_review(self, experience_id: str, action: str, reject_reason: Optional[str] = None):
        with _get_metrics_conn() as conn:
            conn.execute(
                "INSERT INTO review_events (experience_id, action, reject_reason, created_at) VALUES (?, ?, ?, ?)",
                (experience_id, action, reject_reason, datetime.utcnow().isoformat()),
            )

    def record_session(self, session: Session):
        with _get_metrics_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, task_description, experience_ids_injected,
                    iteration_count, had_error_correction, user_accepted, created_at, ab_test_group, ab_test_result_shown, result_shown_recorded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
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

    def record_feedback(self, feedback: Feedback):
        """记录经验反馈"""
        with _get_metrics_conn() as conn:
            conn.execute(
                "INSERT INTO feedback (experience_id, adopted, reason, created_at) VALUES (?, ?, ?, ?)",
                (feedback.experience_id, int(feedback.adopted), feedback.reason, feedback.created_at),
            )
            # 更新统计
            self._update_exp_stats(conn, feedback)

    def _update_exp_stats(self, conn: sqlite3.Connection, feedback: Feedback):
        """更新经验统计信息"""
        conn.execute("""
            INSERT INTO experience_stats (experience_id, hit_count, adopted_count, rejected_count)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(experience_id) DO UPDATE SET
                hit_count = hit_count + 1,
                adopted_count = adopted_count + excluded.adopted_count,
                rejected_count = rejected_count + excluded.rejected_count,
                last_used_at = ?,
                last_adopted_at = CASE WHEN excluded.adopted_count > 0 THEN ? ELSE last_adopted_at END,
                adoption_rate = ROUND(
                    (adopted_count + excluded.adopted_count) * 1.0 / (hit_count + 1), 3
                )
        """, (
            feedback.experience_id,
            1 if feedback.adopted else 0,
            0 if feedback.adopted else 1,
            feedback.created_at,
            feedback.created_at if feedback.adopted else None,
        ))

    def get_experience_stats(self, exp_id: str) -> Optional[ExperienceStats]:
        """获取单条经验的统计信息"""
        conn = _get_metrics_conn()
        row = conn.execute(
            "SELECT * FROM experience_stats WHERE experience_id = ?", (exp_id,)
        ).fetchone()
        conn.close()
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

    def get_feedback_summary(self, since_days: Optional[int] = None) -> dict:
        """获取反馈汇总统计"""
        conn = _get_metrics_conn()
        date_filter = ""
        params: list = []
        if since_days:
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
            date_filter = "WHERE created_at >= ?"
            params = [cutoff]

        total_feedback = conn.execute(
            f"SELECT COUNT(*) as cnt FROM feedback {date_filter}", params
        ).fetchone()["cnt"]

        adopted_count = conn.execute(
            f"SELECT COUNT(*) as cnt FROM feedback {date_filter} {'AND' if date_filter else 'WHERE'} adopted = 1",
            params,
        ).fetchone()["cnt"]

        # 获取低采纳率经验（< 0.3）
        low_adoption = conn.execute(
            "SELECT experience_id, adoption_rate FROM experience_stats WHERE adoption_rate < 0.3"
        ).fetchall()

        # 获取被拒绝原因统计
        reject_reasons = conn.execute(
            f"""SELECT reason, COUNT(*) as cnt FROM feedback
               {date_filter} {'AND' if date_filter else 'WHERE'} adopted = 0 AND reason IS NOT NULL
               GROUP BY reason ORDER BY cnt DESC LIMIT 10""",
            params,
        ).fetchall()

        conn.close()

        return {
            "total_feedback": total_feedback,
            "adopted_count": adopted_count,
            "adoption_rate": round(adopted_count / total_feedback, 3) if total_feedback else 0,
            "low_adoption_count": len(low_adoption),
            "low_adoption_ids": [r["experience_id"] for r in low_adoption],
            "reject_reasons": {r["reason"]: r["cnt"] for r in reject_reasons},
        }

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

    def get_experience_feedback_history(self, exp_id: str) -> list[Feedback]:
        """获取单条经验的反馈历史"""
        conn = _get_metrics_conn()
        rows = conn.execute(
            "SELECT * FROM feedback WHERE experience_id = ? ORDER BY created_at DESC",
            (exp_id,)
        ).fetchall()
        conn.close()
        return [
            Feedback(
                experience_id=r["experience_id"],
                adopted=bool(r["adopted"]),
                reason=r["reason"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_review_reject_reasons(self, limit: int = 10) -> dict[str, int]:
        conn = _get_metrics_conn()
        rows = conn.execute(
            """SELECT reject_reason, COUNT(*) as cnt FROM review_events
               WHERE action = 'rejected' AND reject_reason IS NOT NULL
               GROUP BY reject_reason ORDER BY cnt DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()
        return {r["reject_reason"]: r["cnt"] for r in rows}

    def get_hitted_experience_ids(self) -> list[str]:
        conn = _get_metrics_conn()
        rows = conn.execute(
            "SELECT experience_id FROM experience_stats WHERE hit_count > 0"
        ).fetchall()
        conn.close()
        return [r["experience_id"] for r in rows]

    def get_stats(self, since_days: Optional[int] = None) -> dict:
        conn = _get_metrics_conn()
        date_filter = ""
        params: list = []
        if since_days:
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=since_days)).isoformat()
            date_filter = "WHERE created_at >= ?"
            params = [cutoff]

        search_total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM search_events {date_filter}", params
        ).fetchone()["cnt"]

        search_hit = conn.execute(
            f"SELECT COUNT(*) as cnt FROM search_events {date_filter} {'AND' if date_filter else 'WHERE'} result_count > 0",
            params,
        ).fetchone()["cnt"]

        review_rows = conn.execute(
            f"SELECT action, COUNT(*) as cnt FROM review_events {date_filter} GROUP BY action", params
        ).fetchall()
        review_counts = {r["action"]: r["cnt"] for r in review_rows}

        sessions_shown = conn.execute(
            f"SELECT COUNT(*) as cnt, AVG(iteration_count) as avg_iter, AVG(had_error_correction) as avg_err, AVG(user_accepted) as avg_acc FROM sessions {date_filter} {'AND' if date_filter else 'WHERE'} result_shown_recorded = 1 AND ab_test_result_shown = 1",
            params,
        ).fetchone()

        sessions_not_shown = conn.execute(
            f"SELECT COUNT(*) as cnt, AVG(iteration_count) as avg_iter, AVG(had_error_correction) as avg_err, AVG(user_accepted) as avg_acc FROM sessions {date_filter} {'AND' if date_filter else 'WHERE'} result_shown_recorded = 1 AND ab_test_result_shown = 0",
            params,
        ).fetchone()

        session_total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM sessions {date_filter}", params
        ).fetchone()["cnt"]

        avg_result_count_row = conn.execute(
            f"SELECT AVG(result_count) as avg_rc FROM search_events {date_filter}", params
        ).fetchone()
        avg_result_count = round(avg_result_count_row["avg_rc"] or 0, 2)

        feedback_total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM feedback {date_filter}", params
        ).fetchone()["cnt"]
        feedback_adopted = conn.execute(
            f"SELECT COUNT(*) as cnt FROM feedback {date_filter} {'AND' if date_filter else 'WHERE'} adopted = 1",
            params,
        ).fetchone()["cnt"]
        query_adoption_rate = round(feedback_adopted / feedback_total, 3) if feedback_total else 0

        top_adopted_rows = conn.execute(
            """SELECT experience_id, adoption_rate, hit_count FROM experience_stats
               WHERE hit_count >= 3
               ORDER BY adoption_rate DESC LIMIT 3"""
        ).fetchall()
        top_adopted_experiences = [
            {"experience_id": r["experience_id"], "adoption_rate": r["adoption_rate"], "hit_count": r["hit_count"]}
            for r in top_adopted_rows
        ]

        zombie_count_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM experience_stats WHERE hit_count = 0"
        ).fetchone()
        zombie_count = zombie_count_row["cnt"]

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

        from datetime import timedelta
        cutoff_30 = (datetime.utcnow() - timedelta(days=30)).isoformat()
        new_sessions_30d = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE created_at >= ?", (cutoff_30,)
        ).fetchone()["cnt"]

        conn.close()

        return {
            "search_total": search_total,
            "search_hit_rate": round(search_hit / search_total, 3) if search_total else 0,
            "review_confirmed": review_counts.get("confirmed", 0),
            "review_rejected": review_counts.get("rejected", 0),
            "review_pass_rate": round(
                review_counts.get("confirmed", 0) / max(review_counts.get("confirmed", 0) + review_counts.get("rejected", 0), 1), 3
            ),
            "session_total": session_total,
            "result_shown": {
                "count": sessions_shown["cnt"] or 0,
                "avg_iterations": round(sessions_shown["avg_iter"] or 0, 2),
                "error_rate": round(sessions_shown["avg_err"] or 0, 3),
                "accept_rate": round(sessions_shown["avg_acc"] or 0, 3),
            },
            "result_not_shown": {
                "count": sessions_not_shown["cnt"] or 0,
                "avg_iterations": round(sessions_not_shown["avg_iter"] or 0, 2),
                "error_rate": round(sessions_not_shown["avg_err"] or 0, 3),
                "accept_rate": round(sessions_not_shown["avg_acc"] or 0, 3),
            },
            "avg_result_count": avg_result_count,
            "query_adoption_rate": query_adoption_rate,
            "top_adopted_experiences": top_adopted_experiences,
            "zombie_count_db": zombie_count,
            "ab_test_groups": ab_test_groups,
            "new_sessions_30d": new_sessions_30d,
        }


class LocalBackend:
    """本地存储后端，实现 StorageBackend 接口"""

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

    def get_all_vectors(self, exp_ids: Optional[list[str]] = None) -> tuple[list[str], "np.ndarray"]:
        return self._vectors.get_all_vectors(exp_ids)


def get_backend():
    backend_type = os.environ.get("XP_BACKEND", "local")
    if backend_type == "postgres":
        dsn = os.environ.get("XP_POSTGRES_DSN", "")
        if not dsn:
            raise RuntimeError("XP_BACKEND=postgres 但未设置 XP_POSTGRES_DSN")
        from .backends.postgres import PostgresBackend
        return PostgresBackend(dsn)
    return LocalBackend()
