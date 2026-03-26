import uuid
from datetime import datetime
from typing import Optional

from .models import (
    Experience,
    ExperienceLevel,
    ExperienceMetadata,
    ExperienceSource,
    ExperienceStatus,
    ExperienceType,
    Feedback,
    Session,
)
from .storage import ExperienceStore, MetricsStore, _extract_keywords


class KnowledgeService:
    def __init__(self, store: ExperienceStore, metrics: MetricsStore):
        self._store = store
        self._metrics = metrics

    async def extract_experience(
        self,
        task_description: str,
        solution_summary: str,
        key_decisions: str,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
    ) -> Experience:
        tags = tags or []
        related_files = related_files or []

        level = self._infer_level(task_description, key_decisions)
        exp_type = self._infer_type(task_description, key_decisions)

        # 自动提取关键词
        all_text = f"{task_description}\n{solution_summary}\n{key_decisions}"
        keywords = _extract_keywords(all_text)

        # 自动推断技术栈标签
        tech_stack = self._infer_tech_stack(all_text)
        
        # 自动推断场景标签
        scene = self._infer_scene(all_text)

        exp = Experience(
            id=str(uuid.uuid4()),
            type=exp_type,
            level=level,
            title=self._make_title(task_description),
            tags=tags,  # 向后兼容
            problem=task_description,
            solution=f"{solution_summary}\n\n关键决策：{key_decisions}",
            confidence=0.6,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.AGENT,
            created_at=datetime.utcnow().isoformat(),
            related_files=related_files,
            metadata=ExperienceMetadata(
                tech_stack=tech_stack if tech_stack else tags,  # 优先使用推断的技术栈
                problem_type=exp_type.value,
                scene=scene,
                keywords=keywords,
            ),
        )

        return self._store.add(exp)

    async def search(
        self,
        query: str,
        tags: Optional[list[str]] = None,
        top_k: int = 3,
        threshold: float = 0.1,
    ) -> list[Experience]:
        """
        纯文本标签 + BM25 检索
        
        参数:
            query: 查询文本（任务描述或问题描述）
            tags: 技术栈标签过滤（可选）
            top_k: 返回条数
            threshold: BM25 分数阈值
        """
        results = self._store.search(
            query=query,
            tech_stack=tags,  # 向后兼容：tags 作为 tech_stack 过滤
            top_k=top_k,
            threshold=threshold,
        )

        self._metrics.record_search(query, len(results))
        return results

    async def record_session(self, session: Session):
        self._metrics.record_session(session)

    def confirm_experience(self, exp_id: str) -> bool:
        exp = self._store.get(exp_id)
        if not exp:
            return False
        exp.status = ExperienceStatus.ACTIVE
        exp.confidence = 0.8
        self._store.update(exp)
        self._metrics.record_review(exp_id, "confirmed")
        return True

    def reject_experience(self, exp_id: str, reason: Optional[str] = None) -> bool:
        exp = self._store.get(exp_id)
        if not exp:
            return False
        exp.status = ExperienceStatus.ARCHIVED
        exp.reject_reason = reason
        self._store.update(exp)
        self._metrics.record_review(exp_id, "rejected", reason)
        return True

    async def edit_and_confirm(
        self,
        exp_id: str,
        title: Optional[str] = None,
        problem: Optional[str] = None,
        solution: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> bool:
        exp = self._store.get(exp_id)
        if not exp:
            return False

        if title:
            exp.title = title
        if problem:
            exp.problem = problem
        if solution:
            exp.solution = solution
        if tags is not None:
            exp.tags = tags
            exp.metadata.tech_stack = tags

        exp.status = ExperienceStatus.ACTIVE
        exp.confidence = 1.0

        # 重新提取关键词
        all_text = f"{exp.title}\n{exp.problem}\n{exp.solution}"
        exp.metadata.keywords = _extract_keywords(all_text)

        self._store.update(exp)
        self._metrics.record_review(exp_id, "confirmed")
        return True

    async def record_feedback(self, experience_id: str, adopted: bool, reason: Optional[str] = None) -> bool:
        """记录经验反馈并更新 confidence
        
        Args:
            experience_id: 经验 ID
            adopted: 是否被采纳
            reason: 未采纳原因（可选）
            
        Returns:
            是否成功记录
        """
        exp = self._store.get(experience_id)
        if not exp:
            return False

        # 记录反馈
        feedback = Feedback(
            experience_id=experience_id,
            adopted=adopted,
            reason=reason,
        )
        self._metrics.record_feedback(feedback)

        # 获取最新统计
        stats = self._metrics.get_experience_stats(experience_id)
        if stats:
            # 动态更新 confidence: 旧值 * 0.9 + 采纳率 * 0.1
            new_confidence = exp.confidence * 0.9 + stats.adoption_rate * 0.1
            exp.confidence = round(new_confidence, 3)

            # confidence < 0.1 自动归档
            if exp.confidence < 0.1:
                exp.status = ExperienceStatus.ARCHIVED
                exp.reject_reason = "Low adoption rate, auto archived"

            self._store.update(exp)

        return True

    async def auto_activate_high_confidence(self, exp_id: str) -> bool:
        """高置信自动激活
        
        条件: 当前经验与相似历史经验的采纳率都 > 0.8
        
        Returns:
            是否自动激活
        """
        exp = self._store.get(exp_id)
        if not exp:
            return False

        # 查找相似且已 active 的经验
        similar_exps = self._store.search(
            query=f"{exp.title}\n{exp.problem}",
            tech_stack=exp.metadata.tech_stack,
            top_k=5,
            threshold=0.5,
        )

        # 筛选出与当前经验最相关的
        related_exps = [
            e for e in similar_exps
            if e.id != exp.id and e.status == ExperienceStatus.ACTIVE
        ]

        if not related_exps:
            return False

        # 检查相似经验的采纳率
        all_high_adoption = True
        for related in related_exps:
            stats = self._metrics.get_experience_stats(related.id)
            if not stats or stats.adoption_rate <= 0.8:
                all_high_adoption = False
                break

        if all_high_adoption:
            exp.status = ExperienceStatus.ACTIVE
            exp.confidence = 0.6  # 自动激活初始 confidence 较低
            self._store.update(exp)
            return True

        return False

    async def analyze_quality(self) -> dict:
        """分析经验质量并生成报告
        
        Returns:
            质量分析报告
        """
        # 获取反馈汇总
        feedback_summary = self._metrics.get_feedback_summary()

        # 获取 review 统计
        all_exps = []
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(self._store.list_by_status(status))

        pending_count = len([e for e in all_exps if e.status == ExperienceStatus.PENDING])
        active_count = len([e for e in all_exps if e.status == ExperienceStatus.ACTIVE])
        archived_count = len([e for e in all_exps if e.status == ExperienceStatus.ARCHIVED])

        # 获取被拒绝的 review 原因（通过 MetricsStore 方法获取）
        # 这里直接使用 storage 模块的函数
        from .storage import _get_metrics_conn
        conn = _get_metrics_conn()
        reject_reasons = conn.execute(
            """SELECT reject_reason, COUNT(*) as cnt FROM review_events
               WHERE action = 'rejected' AND reject_reason IS NOT NULL
               GROUP BY reject_reason ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()
        conn.close()

        # 识别低质量模式
        low_quality_patterns = []
        
        # 1. 高提取但低采纳（提取质量问题）
        if feedback_summary["total_feedback"] > 0 and feedback_summary["adoption_rate"] < 0.5:
            low_quality_patterns.append({
                "type": "extraction_quality",
                "issue": "提取的经验采纳率偏低",
                "suggestion": "优化 extract_experience 的 prompt，让 agent 更准确地判断什么值得提取",
                "data": f"总反馈 {feedback_summary['total_feedback']}, 采纳率 {feedback_summary['adoption_rate']*100:.1f}%"
            })

        # 2. 低采纳率经验过多
        if feedback_summary["low_adoption_count"] > 0:
            low_quality_patterns.append({
                "type": "low_adoption",
                "issue": f"有 {feedback_summary['low_adoption_count']} 条经验采纳率低于 30%",
                "suggestion": "考虑归档这些经验或检查是否与当前代码库脱节",
                "data": f"经验 ID: {', '.join(feedback_summary['low_adoption_ids'][:5])}"
            })

        # 3. 常见的拒绝原因
        if feedback_summary["reject_reasons"]:
            top_reason = max(feedback_summary["reject_reasons"].items(), key=lambda x: x[1])
            low_quality_patterns.append({
                "type": "reject_pattern",
                "issue": f"最常见的拒绝原因: '{top_reason[0]}' ({top_reason[1]} 次)",
                "suggestion": "针对性优化提取逻辑",
                "data": dict(feedback_summary["reject_reasons"])
            })

        return {
            "summary": {
                "total_experiences": len(all_exps),
                "pending_count": pending_count,
                "active_count": active_count,
                "archived_count": archived_count,
            },
            "feedback_stats": {
                "total_feedback": feedback_summary["total_feedback"],
                "adoption_rate": feedback_summary["adoption_rate"],
                "adopted_count": feedback_summary["adopted_count"],
            },
            "low_adoption_experiences": {
                "count": feedback_summary["low_adoption_count"],
                "ids": feedback_summary["low_adoption_ids"],
            },
            "reject_reasons": feedback_summary["reject_reasons"],
            "review_reject_reasons": {r["reject_reason"]: r["cnt"] for r in reject_reasons},
            "low_quality_patterns": low_quality_patterns,
            "recommendations": [
                "定期运行 xp analyze 检查经验质量" if len(low_quality_patterns) > 0 else "当前经验质量良好",
                f"关注 {feedback_summary['low_adoption_count']} 条低采纳率经验" if feedback_summary["low_adoption_count"] > 0 else "",
                "考虑优化提取 prompt" if feedback_summary["adoption_rate"] < 0.6 else "",
            ]
        }

    async def import_from_markdown(self, content: str) -> list[Experience]:
        sections = content.strip().split("\n---\n")
        imported = []
        for section in sections:
            exp = self._parse_markdown_section(section.strip())
            if exp:
                imported.append(self._store.add(exp))
        return imported

    def list_pending(self) -> list[Experience]:
        return self._store.list_by_status(ExperienceStatus.PENDING)

    def get_stats(self, since_days: Optional[int] = None) -> dict:
        process = self._metrics.get_stats(since_days)
        process["active_count"] = len(self._store.list_active())
        process["pending_count"] = len(self.list_pending())
        return process

    def _infer_level(self, task: str, decisions: str) -> ExperienceLevel:
        text = (task + decisions).lower()
        if any(k in text for k in ["架构", "模式", "pattern", "设计", "architecture"]):
            return ExperienceLevel.L1
        if any(k in text for k in ["bug", "fix", "修复", "报错", "error", "exception"]):
            return ExperienceLevel.L3
        return ExperienceLevel.L2

    def _infer_type(self, task: str, decisions: str) -> ExperienceType:
        text = (task + decisions).lower()
        if any(k in text for k in ["bug", "fix", "修复", "报错", "error"]):
            return ExperienceType.BUGFIX
        if any(k in text for k in ["模式", "pattern", "架构", "规范"]):
            return ExperienceType.PATTERN
        return ExperienceType.FEATURE

    def _infer_tech_stack(self, text: str) -> list[str]:
        """从文本中推断技术栈标签"""
        text_lower = text.lower()
        tech_keywords = {
            "react": ["react", "useeffect", "usestate", "hooks"],
            "vue": ["vue", "composition api", "ref", "reactive"],
            "typescript": ["typescript", "ts", "类型", "type"],
            "javascript": ["javascript", "js", "es6", "async", "await"],
            "python": ["python", "django", "flask", "fastapi"],
            "css": ["css", "scss", "less", "tailwind", "styled"],
            "node": ["node", "nodejs", "npm", "express"],
            "database": ["sql", "mysql", "postgresql", "mongodb", "redis"],
            "docker": ["docker", "container", "k8s", "kubernetes"],
            "git": ["git", "github", "gitlab", "commit", "merge"],
        }
        
        found = []
        for tech, indicators in tech_keywords.items():
            if any(ind in text_lower for ind in indicators):
                found.append(tech)
        return found

    def _infer_scene(self, text: str) -> list[str]:
        """从文本中推断场景标签"""
        text_lower = text.lower()
        scene_keywords = {
            "表单": ["表单", "form", "input", "validation", "校验"],
            "列表": ["列表", "list", "table", "grid", "pagination"],
            "异步": ["异步", "async", "await", "promise", "fetch", "api"],
            "状态管理": ["状态", "state", "redux", "vuex", "pinia", "mobx"],
            "路由": ["路由", "router", "navigation", "route", "页面跳转"],
            "性能优化": ["性能", "优化", "performance", "lazy", "cache", "memo"],
            "测试": ["测试", "test", "jest", "vitest", "cypress", "e2e"],
            "部署": ["部署", "deploy", "ci/cd", "pipeline", "build"],
        }
        
        found = []
        for scene, indicators in scene_keywords.items():
            if any(ind in text_lower for ind in indicators):
                found.append(scene)
        return found

    def _make_title(self, task: str) -> str:
        return task[:60] + ("..." if len(task) > 60 else "")

    def _parse_markdown_section(self, section: str) -> Optional[Experience]:
        lines = section.splitlines()
        if not lines:
            return None

        title = lines[0].lstrip("#").strip()
        if not title:
            return None

        problem = ""
        solution = ""
        tags: list[str] = []
        current_key = None

        for line in lines[1:]:
            lower = line.lower().strip()
            if lower.startswith("**问题**") or lower.startswith("**problem**"):
                current_key = "problem"
            elif lower.startswith("**解决方案**") or lower.startswith("**solution**"):
                current_key = "solution"
            elif lower.startswith("**标签**") or lower.startswith("**tags**"):
                tag_part = line.split(":", 1)[-1].strip()
                tags = [t.strip() for t in tag_part.replace("，", ",").split(",") if t.strip()]
                current_key = None
            elif current_key == "problem":
                problem += line + "\n"
            elif current_key == "solution":
                solution += line + "\n"

        if not problem:
            problem = title
        if not solution:
            return None

        # 自动提取关键词和标签
        all_text = f"{title}\n{problem}\n{solution}"
        keywords = _extract_keywords(all_text)
        tech_stack = self._infer_tech_stack(all_text)
        scene = self._infer_scene(all_text)

        return Experience(
            id=str(uuid.uuid4()),
            type=self._infer_type(title, problem),
            level=self._infer_level(title, problem),
            title=title,
            tags=tags,
            problem=problem.strip(),
            solution=solution.strip(),
            confidence=1.0,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.MANUAL,
            created_at=datetime.utcnow().isoformat(),
            metadata=ExperienceMetadata(
                tech_stack=tech_stack if tech_stack else tags,
                problem_type=self._infer_type(title, problem).value,
                scene=scene,
                keywords=keywords,
            ),
        )
