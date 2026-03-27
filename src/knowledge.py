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
from .storage import ExperienceStore, MetricsStore, _extract_keywords


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
        """启用云端同步"""
        from .cloud_providers import CloudSyncManager
        sync_manager = CloudSyncManager()

        if not await sync_manager.connect(provider, **config):
            return False

        # 更新项目配置
        self._project_manager.enable_cloud_sync(self._project, provider, **config)
        return True

    async def sync_to_cloud(self) -> dict:
        """同步本地经验到云端"""
        from .cloud_providers import CloudSyncManager

        config = self.get_current_project_config()
        if not config or not config.cloud_sync_enabled:
            return {"error": "Cloud sync not enabled"}

        sync_manager = CloudSyncManager()
        if not await sync_manager.connect(config.cloud_provider, **config.cloud_config):
            return {"error": "Failed to connect to cloud"}

        # 获取当前项目的所有经验
        all_exps = []
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(self._store.list_by_status(status))

        project_exps = [e for e in all_exps if e.project == self._project]

        result = await sync_manager.sync_upload_all(project_exps)
        await sync_manager.disconnect()
        return result

    async def sync_from_cloud(self) -> dict:
        """从云端同步经验到本地"""
        from .cloud_providers import CloudSyncManager

        config = self.get_current_project_config()
        if not config or not config.cloud_sync_enabled:
            return {"error": "Cloud sync not enabled", "count": 0}

        sync_manager = CloudSyncManager()
        if not await sync_manager.connect(config.cloud_provider, **config.cloud_config):
            return {"error": "Failed to connect to cloud", "count": 0}

        # 下载云端经验
        cloud_exps = await sync_manager.sync_download_all(self._project)

        # 合并到本地
        merged = 0
        new = 0
        for exp in cloud_exps:
            existing = self._store.get(exp.id)
            if existing:
                # 更新现有经验
                self._store.update(exp)
                merged += 1
            else:
                # 新增经验
                self._store.add(exp)
                new += 1

        await sync_manager.disconnect()
        return {"merged": merged, "new": new, "total": len(cloud_exps)}

    async def extract_experience(
        self,
        task_description: str,
        solution_summary: str,
        key_decisions: str,
        conversation_summary: Optional[str] = None,
        tags: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
    ) -> Experience:
        tags = tags or []
        related_files = related_files or []

        level = self._infer_level(task_description, key_decisions)
        exp_type = self._infer_type(task_description, key_decisions)

        # 自动提取关键词（包含对话摘要以获取更多上下文）
        all_text = f"{task_description}\n{solution_summary}\n{key_decisions}"
        if conversation_summary:
            all_text = f"{all_text}\n{conversation_summary}"
        keywords = _extract_keywords(all_text)

        # 自动推断技术栈标签
        tech_stack = self._infer_tech_stack(all_text)

        # 自动推断场景标签
        scene = self._infer_scene(all_text)

        # Phase 3: 计算相关文件的 hash
        file_hashes = calculate_files_hashes(related_files)

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
            file_hashes=file_hashes,
            project=self._project,
        )

        return self._store.add(exp)

    async def search(
        self,
        query: str,
        tags: Optional[list[str]] = None,
        top_k: int = 3,
        threshold: float = 0.1,
        cross_project: bool = False,
        session_id: Optional[str] = None,
        enable_ab_test: bool = True,
        enable_strategy_ab_test: bool = True,
    ) -> tuple[list[Experience], dict]:
        """
        混合检索：BM25 + Embedding，支持 A/B 测试

        参数:
            query: 查询文本（任务描述或问题描述）
            tags: 技术栈标签过滤（可选）
            top_k: 返回条数
            threshold: BM25 分数阈值
            cross_project: 是否跨项目检索
            session_id: 会话 ID，用于 A/B 测试分组
            enable_ab_test: 是否启用整体 A/B 测试（有经验 vs 无经验）
            enable_strategy_ab_test: 是否启用检索策略 A/B 测试（BM25 vs Embedding）

        Returns:
            (经验列表, 元数据字典包含 ab_test_group, strategy)
        """
        # A/B 测试分组1：10% 对照组（不展示经验），90% 实验组（正常展示）
        ab_test_group = "treatment"
        show_results = True
        if enable_ab_test and session_id:
            import hashlib
            hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
            if hash_val % 10 == 0:  # 10% 对照组
                ab_test_group = "control"
                show_results = False

        # 获取所有 active 经验
        candidates = self._store.list_active()

        # Phase 3: 项目过滤
        if not cross_project:
            candidates = [e for e in candidates if e.project == self._project]

        # Phase 3: 过滤已过期和已失效的经验
        valid_candidates = []
        for exp in candidates:
            # 跳过 TTL 过期的
            if self._ttl_manager.is_expired(exp.last_hit_at):
                continue
            # 跳过已标记为 stale 的
            if exp.stale_reason:
                continue
            valid_candidates.append(exp)

        # 执行 BM25 搜索
        from .storage import _tokenize
        from rank_bm25 import BM25Okapi

        # A/B 测试：对照组直接返回空结果（但仍记录检索事件）
        if not show_results:
            self._metrics.record_search(query, 0)
            return [], {"ab_test_group": ab_test_group, "show_results": False, "strategy": None}

        if not valid_candidates:
            self._metrics.record_search(query, 0)
            return [], {"ab_test_group": ab_test_group, "show_results": True, "strategy": None}

        # 标签过滤
        if tags:
            valid_candidates = [
                exp for exp in valid_candidates
                if any(t in exp.metadata.tech_stack for t in tags)
            ]

        if not valid_candidates:
            self._metrics.record_search(query, 0)
            return [], {"ab_test_group": ab_test_group, "show_results": True, "strategy": None}

        # A/B 测试分组2：检索策略对比（50% BM25, 50% Embedding）
        strategy = "hybrid"  # 默认混合
        if enable_strategy_ab_test and session_id:
            import hashlib
            hash_val = int(hashlib.md5((session_id + "_strategy").encode()).hexdigest(), 16)
            if hash_val % 2 == 0:
                strategy = "bm25_only"
            else:
                strategy = "embedding_only"

        # BM25 排序（所有策略都需要先算 BM25 分数作为基础）
        corpus = []
        for exp in valid_candidates:
            text = f"{exp.title}\n{exp.problem}\n{exp.solution}\n{' '.join(exp.metadata.keywords)}"
            corpus.append(_tokenize(text))

        bm25 = BM25Okapi(corpus)
        query_tokens = _tokenize(query)
        scores = bm25.get_scores(query_tokens)

        # 组合 BM25 结果
        bm25_results = []
        for exp, score in zip(valid_candidates, scores):
            if score >= threshold:
                exp.similarity = round(score, 3)
                bm25_results.append((exp, score))

        # 如果 BM25 结果太少，直接返回
        if len(bm25_results) < 2:
            results = bm25_results[:top_k]
            now = datetime.utcnow().isoformat()
            for exp, _ in results:
                exp.last_hit_at = now
                self._store.update(exp)
            self._metrics.record_search(query, len(results))
            self._metrics.record_search_strategy(
                session_id or "no_session", query, "bm25_only", len(results), [exp.id for exp, _ in results]
            )
            return [exp for exp, _ in results], {"ab_test_group": ab_test_group, "show_results": True, "strategy": "bm25_only"}

        results = []
        
        if strategy == "bm25_only":
            # 仅使用 BM25 排序
            bm25_results.sort(key=lambda x: x[1], reverse=True)
            results = bm25_results[:top_k]
            
        elif strategy == "embedding_only":
            # 仅使用 Embedding 排序
            try:
                from .embeddings import get_cache, cosine_similarity
                cache = get_cache()
                query_vec = cache.get_or_compute(query)
                
                candidate_texts = [f"{exp.title}\n{exp.problem}\n{exp.solution}" for exp, _ in bm25_results]
                doc_vecs = cache.get_or_compute_batch(candidate_texts)
                semantic_scores = cosine_similarity(query_vec, doc_vecs)
                
                embedding_results = []
                for i, (exp, _) in enumerate(bm25_results):
                    embedding_results.append((exp, semantic_scores[i]))
                embedding_results.sort(key=lambda x: x[1], reverse=True)
                results = embedding_results[:top_k]
            except Exception:
                # Embedding 失败时回退到 BM25
                bm25_results.sort(key=lambda x: x[1], reverse=True)
                results = bm25_results[:top_k]
                strategy = "bm25_only"
                
        else:  # hybrid
            # 混合排序：BM25 + Embedding
            try:
                from .embeddings import get_cache, cosine_similarity
                cache = get_cache()
                query_vec = cache.get_or_compute(query)
                
                candidate_texts = [f"{exp.title}\n{exp.problem}\n{exp.solution}" for exp, _ in bm25_results]
                doc_vecs = cache.get_or_compute_batch(candidate_texts)
                semantic_scores = cosine_similarity(query_vec, doc_vecs)
                
                max_bm25 = max(score for _, score in bm25_results)
                min_bm25 = min(score for _, score in bm25_results)
                bm25_range = max_bm25 - min_bm25 if max_bm25 > min_bm25 else 1
                
                hybrid_results = []
                for i, (exp, bm25_score) in enumerate(bm25_results):
                    bm25_norm = (bm25_score - min_bm25) / bm25_range
                    hybrid_score = 0.7 * bm25_norm + 0.3 * semantic_scores[i]
                    hybrid_results.append((exp, hybrid_score))
                hybrid_results.sort(key=lambda x: x[1], reverse=True)
                results = hybrid_results[:top_k]
            except Exception:
                # Embedding 失败时回退到纯 BM25
                bm25_results.sort(key=lambda x: x[1], reverse=True)
                results = bm25_results[:top_k]
                strategy = "bm25_only"

        # Phase 3: 更新最后使用时间
        now = datetime.utcnow().isoformat()
        for exp, _ in results:
            exp.last_hit_at = now
            self._store.update(exp)

        # 记录检索策略 A/B 测试数据
        experience_ids = [exp.id for exp, _ in results]
        self._metrics.record_search(query, len(results))
        self._metrics.record_search_strategy(
            session_id or "no_session", query, strategy, len(results), experience_ids
        )

        return [exp for exp, _ in results], {"ab_test_group": ab_test_group, "show_results": True, "strategy": strategy}

    async def record_session(self, session: Session):
        self._metrics.record_session(session)

    async def infer_adoption(
        self,
        session_id: str,
        final_response: str,
        experience_ids_injected: list[str],
    ) -> list[dict]:
        """自动推断经验采纳情况
        
        通过检查最终回复是否包含经验中的关键代码、方案或决策点来判断采纳情况。
        
        Returns:
            每条经验的采纳推断结果 [{experience_id, adopted, confidence, matched_keywords}, ...]
        """
        results = []
        final_lower = final_response.lower()
        
        for exp_id in experience_ids_injected:
            exp = self._store.get(exp_id)
            if not exp:
                continue
            
            # 提取经验中的关键内容
            exp_content = f"{exp.title} {exp.problem} {exp.solution}"
            exp_keywords = exp.metadata.keywords if exp.metadata.keywords else _extract_keywords(exp_content)
            
            # 匹配关键词
            matched = []
            for kw in exp_keywords:
                if len(kw) > 2 and kw.lower() in final_lower:  # 过滤短词
                    matched.append(kw)
            
            # 计算匹配率
            match_rate = len(matched) / len(exp_keywords) if exp_keywords else 0
            
            # 推断逻辑
            if match_rate >= 0.3:  # 30% 以上关键词匹配
                adopted = True
                confidence = min(match_rate * 2, 0.95)  # 最高 0.95
            elif match_rate >= 0.1:  # 10-30% 可能采纳
                adopted = True
                confidence = match_rate
            else:
                adopted = False
                confidence = 1 - match_rate
            
            # 记录反馈
            await self.record_feedback(exp_id, adopted, reason=f"Auto inferred: {match_rate:.1%} keywords matched")
            
            # 更新检索策略效果指标（通过 session_id 关联到检索策略）
            # 这里简化处理：如果有采纳，认为所有策略都受益
            # 实际应该通过 session 记录查询具体策略
            if adopted and match_rate >= 0.3:
                self._metrics.update_search_strategy_metrics("hybrid", True, True)
                self._metrics.update_search_strategy_metrics("bm25_only", True, True)
                self._metrics.update_search_strategy_metrics("embedding_only", True, True)
            
            results.append({
                "experience_id": exp_id,
                "adopted": adopted,
                "confidence": round(confidence, 2),
                "matched_keywords": matched[:5],  # 最多返回 5 个
                "match_rate": round(match_rate, 2),
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

    def get_search_strategy_comparison(self, since_days: Optional[int] = None) -> dict:
        """获取检索策略对比数据"""
        return self._metrics.get_search_strategy_comparison(since_days)

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
            # 前端 UI 场景
            "表单": ["表单", "form", "input", "validation", "校验"],
            "列表": ["列表", "list", "table", "grid", "pagination"],
            "异步": ["异步", "async", "await", "promise", "fetch", "api"],
            "状态管理": ["状态", "state", "redux", "vuex", "pinia", "mobx"],
            "路由": ["路由", "router", "navigation", "route", "页面跳转"],
            "性能优化": ["性能", "优化", "performance", "lazy", "cache", "memo"],
            "测试": ["测试", "test", "jest", "vitest", "cypress", "e2e"],
            "部署": ["部署", "deploy", "ci/cd", "pipeline", "build"],
            "UI 组件": ["组件", "component", "ui", "界面", "布局", "layout"],
            "样式": ["样式", "style", "css", "scss", "less", "tailwind", "styled"],
            "弹窗/模态": ["弹窗", "模态", "modal", "dialog", "popup", "overlay"],
            # CLI/终端场景
            "CLI 工具": ["cli", "命令行", "command line", "终端", "terminal", "shell", "prompt"],
            "快捷键": ["快捷键", "keybinding", "shortcut", "按键", "hotkey"],
            "输入处理": ["输入", "input", "多行", "multiline", "换行", "enter"],
            "跨平台": ["跨平台", "兼容", "windows", "linux", "macos", "mac", "跨终端"],
            # 后端/基础设施场景
            "数据库": ["数据库", "database", "sql", "query", "orm", "prisma"],
            "API 设计": ["api", "接口", "endpoint", "rest", "graphql"],
            "认证授权": ["认证", "授权", "auth", "login", "token", "jwt", "oauth"],
            "错误处理": ["错误", "error", "exception", "catch", "try", "debug", "排查"],
            "日志监控": ["日志", "log", "监控", "monitor", "trace", "metrics"],
            "配置管理": ["配置", "config", "env", "environment", "variable", "设置"],
            "文件操作": ["文件", "file", "目录", "folder", "path", "读写"],
            # 工程化场景
            "依赖管理": ["依赖", "dependency", "npm", "pip", "package", "install"],
            "构建工具": ["构建", "build", "webpack", "vite", "rollup", "esbuild"],
            "类型系统": ["类型", "type", "typescript", "typecheck", "interface"],
            "代码规范": ["lint", "format", "prettier", "eslint", "规范", "风格"],
            "版本控制": ["git", "版本", "commit", "merge", "branch", "rebase"],
            # 文档编写场景
            "API 文档": ["api 文档", "api doc", "swagger", "openapi", "接口文档"],
            "README": ["readme", "项目介绍", "快速开始", "quick start"],
            "技术文档": ["技术文档", "tech doc", "documentation", "wiki", "指南", "guide"],
            "代码注释": ["注释", "comment", "docstring", "jsdoc", "typedoc"],
            # 运维/基础设施场景
            "容器化": ["docker", "容器", "container", "镜像", "image", "compose"],
            "K8s": ["kubernetes", "k8s", "pod", "deployment", "service", "helm"],
            "云服务": ["aws", "azure", "gcp", "阿里云", "腾讯云", "云服务器"],
            "CI/CD": ["ci/cd", "jenkins", "github actions", "gitlab ci", "自动化部署"],
            "监控告警": ["监控", "告警", "alert", "prometheus", "grafana", "sentry"],
            # 数据分析场景
            "数据处理": ["数据处理", "etl", "pipeline", "清洗", "transform"],
            "数据分析": ["数据分析", "analysis", "pandas", "jupyter", "可视化"],
            "算法模型": ["算法", "模型", "机器学习", "ml", "深度学习", "训练"],
            # 通用场景
            "环境配置": ["环境", "environment", "setup", "安装", "初始化", "配置"],
            "权限管理": ["权限", "permission", "role", "rbac", "访问控制"],
            "安全措施": ["安全", "security", "加密", "xss", "csrf", "注入", "漏洞"],
            "性能调优": ["性能", "perf", "优化", "慢", "卡顿", "内存泄漏"],
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
