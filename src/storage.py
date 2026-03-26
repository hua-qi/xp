import json
import os
import sqlite3
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi

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

XP_HOME = Path(os.environ.get("XP_HOME", Path.home() / ".xp"))
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
            created_at TEXT NOT NULL
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
    """)
    conn.commit()


def _tokenize(text: str) -> list[str]:
    """简单分词：小写、去标点、按空格和常见分隔符分割"""
    text = text.lower()
    # 保留中英文、数字，其他字符作为分隔符
    tokens = re.findall(r'[a-z]+|[\u4e00-\u9fa5]+|\d+', text)
    return tokens


def _extract_keywords(text: str) -> list[str]:
    """从文本中提取关键词（用于自动生成 metadata.keywords）"""
    tokens = _tokenize(text)
    # 过滤常见停用词
    stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                 'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
                 'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
                 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above',
                 'below', 'between', 'under', 'again', 'further', 'then', 'once', '的',
                 '是', '在', '和', '有', '了', '对', '就', '都', '而', '及', '与',
                 '或', '但', '如果', '因为', '所以', '可以', '需要', '进行', '使用'}
    keywords = [t for t in tokens if len(t) > 1 and t not in stopwords]
    return list(set(keywords))  # 去重


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

    def search(
        self,
        query: str,
        tech_stack: Optional[list[str]] = None,
        problem_type: Optional[str] = None,
        scene: Optional[list[str]] = None,
        top_k: int = 5,
        threshold: float = 0.1,
    ) -> list[Experience]:
        """
        纯文本标签 + BM25 检索
        
        检索逻辑：
        1. 标签过滤（精确匹配 metadata 字段）
        2. BM25 排序（对 problem + solution 做关键词匹配）
        3. 返回结果附带匹配理由
        """
        data = _load_knowledge()
        
        # 筛选 active 状态的经验
        candidates = [
            self._from_dict(v)
            for v in data.values()
            if v.get("status") == ExperienceStatus.ACTIVE.value
        ]
        
        if not candidates:
            return []

        # 1. 标签过滤
        if tech_stack:
            candidates = [
                exp for exp in candidates
                if any(t in exp.metadata.tech_stack for t in tech_stack)
            ]
        
        if problem_type:
            candidates = [
                exp for exp in candidates
                if exp.metadata.problem_type == problem_type
            ]
        
        if scene:
            candidates = [
                exp for exp in candidates
                if any(s in exp.metadata.scene for s in scene)
            ]

        if not candidates:
            return []

        # 2. BM25 排序
        # 构建语料库：title + problem + solution + keywords
        corpus = []
        for exp in candidates:
            text = f"{exp.title}\n{exp.problem}\n{exp.solution}\n{' '.join(exp.metadata.keywords)}"
            corpus.append(_tokenize(text))
        
        bm25 = BM25Okapi(corpus)
        query_tokens = _tokenize(query)
        scores = bm25.get_scores(query_tokens)
        
        # 组合结果
        results = []
        for i, (exp, score) in enumerate(zip(candidates, scores)):
            if score >= threshold:
                exp.similarity = round(score, 3)  # 复用 similarity 字段存储 BM25 分数
                results.append((exp, score))
        
        # 按分数排序
        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top_k]
        
        return [exp for exp, _ in results]

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
                "keywords": exp.metadata.keywords,
            },
        }

    def _from_dict(self, d: dict) -> Experience:
        metadata_dict = d.get("metadata", {})
        metadata = ExperienceMetadata(
            tech_stack=metadata_dict.get("tech_stack", []),
            problem_type=metadata_dict.get("problem_type", ""),
            scene=metadata_dict.get("scene", []),
            keywords=metadata_dict.get("keywords", []),
        )
        
        # 向后兼容：如果没有 metadata，从 tags 推断
        if not metadata.keywords and d.get("tags"):
            metadata.keywords = d["tags"]
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
                    iteration_count, had_error_correction, user_accepted, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.session_id,
                    session.task_description,
                    json.dumps(session.experience_ids_injected),
                    session.iteration_count,
                    int(session.had_error_correction),
                    int(session.user_accepted),
                    session.created_at,
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

        sessions_with = conn.execute(
            f"SELECT AVG(iteration_count) as avg_iter, AVG(had_error_correction) as avg_err, AVG(user_accepted) as avg_acc FROM sessions {date_filter} {'AND' if date_filter else 'WHERE'} json_array_length(experience_ids_injected) > 0",
            params,
        ).fetchone()

        sessions_without = conn.execute(
            f"SELECT AVG(iteration_count) as avg_iter, AVG(had_error_correction) as avg_err, AVG(user_accepted) as avg_acc FROM sessions {date_filter} {'AND' if date_filter else 'WHERE'} json_array_length(experience_ids_injected) = 0",
            params,
        ).fetchone()

        session_total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM sessions {date_filter}", params
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
            "with_injection": {
                "avg_iterations": round(sessions_with["avg_iter"] or 0, 2),
                "error_rate": round(sessions_with["avg_err"] or 0, 3),
                "accept_rate": round(sessions_with["avg_acc"] or 0, 3),
            },
            "without_injection": {
                "avg_iterations": round(sessions_without["avg_iter"] or 0, 2),
                "error_rate": round(sessions_without["avg_err"] or 0, 3),
                "accept_rate": round(sessions_without["avg_acc"] or 0, 3),
            },
        }
