import uuid
from datetime import datetime
from typing import Optional

from .file_watcher import TTLManager, FileWatcher, calculate_files_hashes
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
from .project_config import ProjectManager
from .storage import ExperienceStore, MetricsStore, VectorStore


class KnowledgeService:
    def __init__(self, store: ExperienceStore, metrics: MetricsStore, project: str = "default"):
        self._store = store
        self._metrics = metrics
        self._project = project
        self._project_manager = ProjectManager()
        self._file_watcher = FileWatcher()
        self._ttl_manager = TTLManager()

    @property
    def current_project(self) -> str:
        return self._project

    def set_project(self, project: str):
        """切换当前项目"""
        self._project = project

    # Phase 3: 文件监听和失效检测
    async def check_stale_experiences(self) -> list[tuple[Experience, list[str]]]:
        """检查失效的经验

        Returns:
            [(经验, 变更文件列表), ...]
        """
        # 获取当前项目的 active 经验
        all_active = self._store.list_active()
        project_exps = [e for e in all_active if e.project == self._project]

        # 运行文件监听检查
        stale_list = self._file_watcher.run_check(project_exps)

        # 更新经验状态
        for exp, changed_files in stale_list:
            exp.stale_reason = f"Files changed: {', '.join(changed_files)}"
            self._store.update(exp)

        return stale_list

    async def mark_stale_resolved(self, exp_id: str) -> bool:
        """标记失效经验为已解决"""
        exp = self._store.get(exp_id)
        if not exp or not exp.stale_reason:
            return False

        # 重新计算文件 hash
        exp.file_hashes = calculate_files_hashes(exp.related_files)
        exp.stale_reason = None
        return self._store.update(exp)

    # Phase 3: TTL 管理
    async def run_ttl_check(self) -> list[Experience]:
        """运行 TTL 检查，归档过期经验

        Returns:
            被归档的经验列表
        """
        # 获取当前项目的 active 经验
        all_active = self._store.list_active()
        project_exps = [e for e in all_active if e.project == self._project]

        # 检查过期
        expired = self._ttl_manager.check_experiences(project_exps)

        # 归档过期经验
        for exp in expired:
            exp.status = ExperienceStatus.ARCHIVED
            exp.reject_reason = f"TTL expired (90 days no hit)"
            self._store.update(exp)

        return expired

    # Phase 3: 项目管理
    def create_project(self, name: str, tags: list[str] = None, root_path: str = None) -> "ProjectConfig":
        """创建新项目"""
        from .project_config import ProjectConfig
        config = self._project_manager.create(name, tags, root_path)
        return config

    def switch_project(self, name: str) -> bool:
        """切换到指定项目"""
        if name not in [p.name for p in self._project_manager.list()]:
            return False
        self._project_manager.set_current(name)
        self._project = name
        return True

    def get_current_project_config(self) -> Optional["ProjectConfig"]:
        """获取当前项目配置"""
        return self._project_manager.get(self._project)

    def list_projects(self) -> list["ProjectConfig"]:
        """列出所有项目"""
        return self._project_manager.list()

    # Phase 3: 云端同步
    async def enable_cloud_sync(self, provider: str, **config) -> bool:
        raise NotImplementedError("Cloud sync has been removed. Use the REST API for team sharing.")

    async def sync_to_cloud(self) -> dict:
        raise NotImplementedError("Cloud sync has been removed. Use the REST API for team sharing.")

    async def sync_from_cloud(self) -> dict:
        raise NotImplementedError("Cloud sync has been removed. Use the REST API for team sharing.")

    async def extract_experience(
        self,
        task_description: str,
        solution_summary: str,
        key_decisions: str,
        conversation_summary: Optional[str] = None,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
    ) -> Experience:
        from .domain.extraction import ExtractionService
        from .storage import VectorStore
        try:
            title = await self._llm_generate_title(task_description)
        except Exception:
            title = None
        svc = ExtractionService(self._store, VectorStore(), project=self._project)
        return await svc.extract(task_description, solution_summary, key_decisions,
                                 conversation_summary, tags, related_files, title=title)

    async def search(
        self,
        query: str,
        tags: Optional[list[str]] = None,
        top_k: int = 3,
        threshold: float = 0.5,
        cross_project: bool = False,
        session_id: Optional[str] = None,
        enable_ab_test: bool = True,
        enable_strategy_ab_test: bool = True,
    ) -> tuple[list[Experience], dict]:
        from .domain.search import SearchService
        from .embeddings import get_provider
        from .storage import VectorStore
        svc = SearchService(
            self._store, VectorStore(), self._metrics,
            get_provider(), project=self._project
        )
        return await svc.search(query, tags, top_k, threshold,
                                cross_project, session_id, enable_ab_test)

    async def record_session(self, session: Session):
        self._metrics.record_session(session)

    async def finalize_task(
        self,
        session_id: str,
        task_description: str,
        solution_summary: str,
        key_decisions: str,
        final_response: str,
        conversation_summary: Optional[str] = None,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
        iteration_count: int = 1,
        had_error_correction: bool = False,
        user_accepted: bool = True,
    ) -> dict:
        result = {
            "session_id": session_id,
            "extract": {"status": "skipped", "id": None, "reason": None},
            "session": {"status": "skipped"},
            "adoption": {"status": "skipped", "results": []},
        }

        experience_id = None
        try:
            exp = await self.extract_experience(
                task_description=task_description,
                solution_summary=solution_summary,
                key_decisions=key_decisions,
                conversation_summary=conversation_summary,
                tags=tags or [],
                related_files=related_files or [],
            )
            experience_id = exp.id
            result["extract"] = {"status": "ok", "id": exp.id, "reason": None}
        except Exception as e:
            result["extract"] = {"status": "skipped", "id": None, "reason": str(e)}

        try:
            session = Session(
                session_id=session_id,
                task_description=task_description,
                experience_ids_injected=[experience_id] if experience_id else [],
                iteration_count=iteration_count,
                had_error_correction=had_error_correction,
                user_accepted=user_accepted,
                created_at=datetime.utcnow().isoformat(),
                ab_test_group="treatment",
                ab_test_result_shown=True,
            )
            await self.record_session(session)
            result["session"] = {"status": "ok"}
        except Exception as e:
            result["session"] = {"status": "error", "reason": str(e)}

        injected_ids = [experience_id] if experience_id else []
        if injected_ids:
            try:
                adoption_results = await self.infer_adoption(
                    session_id=session_id,
                    final_response=final_response,
                    experience_ids_injected=injected_ids,
                )
                result["adoption"] = {"status": "ok", "results": adoption_results}
            except Exception as e:
                result["adoption"] = {"status": "error", "reason": str(e)}

        return result

    async def infer_adoption(
        self,
        session_id: str,
        final_response: str,
        experience_ids_injected: list[str],
    ) -> list[dict]:
        """自动推断经验采纳情况
        
        通过计算 final_response 与经验文本的向量余弦相似度进行推断
        """
        if not experience_ids_injected:
            return []

        from .embeddings import get_provider, cosine_similarity
        from .storage import VectorStore
        import numpy as np

        provider = get_provider()
        v_resp = np.array(provider.embed_text(final_response), dtype=np.float32)

        v_store = VectorStore()
        ids, vecs = v_store.get_all_vectors(experience_ids_injected)

        # 补全可能缺失的向量
        missing_ids = [eid for eid in experience_ids_injected if eid not in ids]
        if missing_ids:
            missing_exps = []
            for eid in missing_ids:
                exp = self._store.get(eid)
                if exp:
                    missing_exps.append(exp)
            if missing_exps:
                missing_texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in missing_exps]
                missing_vecs = provider.embed_texts(missing_texts)
                v_store.save_vectors(list(zip([e.id for e in missing_exps], missing_vecs)))
                # 重新获取
                ids, vecs = v_store.get_all_vectors(experience_ids_injected)

        if len(vecs) == 0:
            return []

        scores = cosine_similarity(v_resp, vecs)

        results = []
        for exp_id, score in zip(ids, scores):
            score_float = float(score)
            if score_float >= 0.75:
                adopted = True
                confidence = score_float
            elif score_float >= 0.60:
                adopted = True
                confidence = score_float
            else:
                adopted = False
                confidence = 1 - score_float
            
            await self.record_feedback(exp_id, adopted, reason=f"Auto inferred: {score_float:.2f} cosine similarity")
            

            
            results.append({
                "experience_id": exp_id,
                "adopted": adopted,
                "confidence": round(confidence, 2),
                "matched_keywords": [],  # 兼容旧字段
                "match_rate": round(score_float, 2),
            })
        
        return results

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

        # 重新生成向量
        self._store.update(exp)
        
        from .embeddings import get_provider
        from .storage import VectorStore
        provider = get_provider()
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.key_decisions}"
        vec = provider.embed_text(exp_text)
        VectorStore().save_vector(exp.id, vec)
        self._metrics.record_review(exp_id, "confirmed")
        return True

    async def record_feedback(self, experience_id: str, adopted: bool, reason: Optional[str] = None) -> bool:
        from .domain.feedback import FeedbackService
        svc = FeedbackService(self._store, self._metrics)
        return await svc.record_feedback(experience_id, adopted, reason)

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
                "data": f"总反馈 {feedback_summary['total_feedback']}, 采纳率 {feedback_summary['adoption_rate']*100:.1f}%",
                "actions": [],
            })

        # 2. 低采纳率经验过多
        if feedback_summary["low_adoption_count"] > 0:
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

        # 3. 常见的拒绝原因
        if feedback_summary["reject_reasons"]:
            top_reason = max(feedback_summary["reject_reasons"].items(), key=lambda x: x[1])
            low_quality_patterns.append({
                "type": "reject_pattern",
                "issue": f"最常见的拒绝原因: '{top_reason[0]}' ({top_reason[1]} 次)",
                "suggestion": "针对性优化提取逻辑",
                "data": dict(feedback_summary["reject_reasons"]),
                "actions": [],
            })

        # 4. 90 天未命中的 Active 经验
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

        # 5. 有 query 但 0 结果的搜索
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

        # 6. 高相似度经验对（重复检测）
        active_exps = [e for e in all_exps if e.status == ExperienceStatus.ACTIVE]
        if len(active_exps) >= 2:
            from .embeddings import cosine_similarity
            v_store = VectorStore()
            active_ids = [e.id for e in active_exps[:200]]
            ids, vecs = v_store.get_all_vectors(active_ids)
            duplicates = []
            if len(ids) >= 2:
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        sim = float(cosine_similarity(vecs[i], vecs[j:j+1])[0])
                        if sim >= 0.92:
                            duplicates.append((ids[i], ids[j], sim))
            if duplicates:
                actions = []
                seen: set[str] = set()
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

        # 7. coverage_gap：高频搜索词在知识库中无对应经验
        recent_keywords = self._metrics.get_recent_query_keywords(since_days=30)
        all_exp_tags: set[str] = set()
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

    def archive_experience(self, prefix: str) -> Optional[Experience]:
        all_exps = []
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(self._store.list_by_status(status))
        matches = [e for e in all_exps if e.id.startswith(prefix)]
        if len(matches) != 1:
            return None
        exp = matches[0]
        exp.status = ExperienceStatus.ARCHIVED
        self._store.update(exp)
        return exp

    def delete_experience(self, prefix: str) -> Optional[str]:
        all_exps = []
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(self._store.list_by_status(status))
        matches = [e for e in all_exps if e.id.startswith(prefix)]
        if len(matches) != 1:
            return None
        exp = matches[0]
        self._store.delete(exp.id)
        return exp.id

    def get_stats(self, since_days: Optional[int] = None) -> dict:
        process = self._metrics.get_stats(since_days)
        all_active = self._store.list_active()
        process["active_count"] = len(all_active)
        process["pending_count"] = len(self.list_pending())

        archived_exps = self._store.list_by_status(ExperienceStatus.ARCHIVED)
        process["archived_count"] = len(archived_exps)

        type_dist = {}
        for exp in all_active:
            t = exp.type.value
            type_dist[t] = type_dist.get(t, 0) + 1
        process["type_distribution"] = type_dist

        if all_active:
            process["avg_confidence"] = round(
                sum(e.confidence for e in all_active) / len(all_active), 3
            )
        else:
            process["avg_confidence"] = 0.0

        from .storage import _get_metrics_conn
        conn = _get_metrics_conn()
        hitted_ids = set(
            r["experience_id"]
            for r in conn.execute("SELECT experience_id FROM experience_stats WHERE hit_count > 0").fetchall()
        )
        conn.close()
        process["zombie_count"] = sum(1 for e in all_active if e.id not in hitted_ids)

        top_adopted_raw = process.get("top_adopted_experiences", [])
        enriched = []
        for item in top_adopted_raw:
            exp = self._store.get(item["experience_id"])
            enriched.append({
                **item,
                "title": exp.title[:30] if exp else item["experience_id"][:8],
            })
        process["top_adopted_experiences"] = enriched

        process["top_miss_queries"] = self._metrics.get_search_miss_queries(since_days=30, limit=5)

        from datetime import timedelta
        cutoff_30 = (datetime.utcnow() - timedelta(days=30)).isoformat()
        all_exps_all_status = (
            all_active
            + self.list_pending()
            + archived_exps
        )
        new_exps_30d = sum(1 for e in all_exps_all_status if e.created_at >= cutoff_30)
        process["trend_30d"] = {
            "new_experiences": new_exps_30d,
            "new_sessions": process["new_sessions_30d"],
        }

        return process



    def _infer_level(self, task: str, decisions: str) -> ExperienceLevel:
        from .domain.metadata import infer_level
        return infer_level(task, decisions)

    def _infer_type(self, task: str, decisions: str) -> ExperienceType:
        from .domain.metadata import infer_type
        return infer_type(task, decisions)

    def _infer_tech_stack(self, text: str) -> list[str]:
        from .domain.metadata import infer_tech_stack
        return infer_tech_stack(text)

    def _infer_scene(self, text: str) -> list[str]:
        from .domain.metadata import infer_scene
        return infer_scene(text)

    async def _check_duplicate(self, task_description: str, solution_summary: str):
        from .embeddings import get_provider, cosine_similarity
        from .storage import VectorStore
        import numpy as np

        candidates = self._store.list_active()
        if not candidates:
            return

        provider = get_provider()
        check_text = f"{task_description}\n{solution_summary}"
        query_vec = np.array(provider.embed_text(check_text), dtype=np.float32)

        v_store = VectorStore()
        candidate_ids = [e.id for e in candidates]
        ids, vecs = v_store.get_all_vectors(candidate_ids)

        if len(vecs) == 0:
            return

        scores = cosine_similarity(query_vec, vecs)
        for exp_id, score in zip(ids, scores):
            if float(score) >= 0.85:
                id_to_exp = {e.id: e for e in candidates}
                dup_exp = id_to_exp.get(exp_id)
                dup_title = dup_exp.title if dup_exp else exp_id[:8]
                raise ValueError(
                    f"已存在高度相似的经验（相似度 {score:.2f}）：[{exp_id[:8]}] {dup_title}。"
                    f"建议复用或用 `xp edit {exp_id[:8]}` 更新已有经验，而非新增。"
                )

    async def _llm_generate_title(self, task_description: str) -> str:
        import os
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("XP_LLM_API_KEY")
        api_base = os.getenv("XP_LLM_API_BASE")
        model = os.getenv("XP_LLM_MODEL", "gpt-4o-mini")
        if not api_key:
            raise RuntimeError("No LLM API key configured")
        import openai
        client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base)
        prompt = f"用10-15个字总结以下任务，只输出标题，不加标点：\n{task_description}"
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()

    def _make_title(self, task: str) -> str:
        return task[:60] + ("..." if len(task) > 60 else "")

    def _compute_quality_score(self, key_decisions, solution_summary, related_files, tech_stack, duplicate_similarity=0.0):
        from .domain.quality import compute_quality_score
        return compute_quality_score(key_decisions, solution_summary, related_files, tech_stack, duplicate_similarity)

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

        # 自动提取技术栈和场景标签
        all_text = f"{title}\n{problem}\n{solution}"
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
            ),
        )
