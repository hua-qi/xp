from __future__ import annotations
from typing import Callable
from ..commands import AnalyzeQualityCommand
from ..unit_of_work import AbstractUnitOfWork


class AnalyzeHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    def handle_analyze(self, cmd: AnalyzeQualityCommand) -> dict:
        from ...storage import ExperienceStore, MetricsStore, VectorStore
        from ...models import ExperienceStatus
        from datetime import datetime, timedelta

        store = ExperienceStore()
        metrics = MetricsStore()

        feedback_summary = metrics.get_feedback_summary()

        all_exps = []
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(store.list_by_status(status))

        pending_count = len([e for e in all_exps if e.status == ExperienceStatus.PENDING])
        active_count = len([e for e in all_exps if e.status == ExperienceStatus.ACTIVE])
        archived_count = len([e for e in all_exps if e.status == ExperienceStatus.ARCHIVED])

        review_reject_reasons = metrics.get_review_reject_reasons()
        low_quality_patterns = []

        if feedback_summary["total_feedback"] > 0 and feedback_summary["adoption_rate"] < 0.5:
            low_quality_patterns.append({
                "type": "extraction_quality",
                "issue": "提取的经验采纳率偏低",
                "suggestion": "优化 extract_experience 的 prompt，让 agent 更准确地判断什么值得提取",
                "data": f"总反馈 {feedback_summary['total_feedback']}, 采纳率 {feedback_summary['adoption_rate']*100:.1f}%",
                "actions": [],
            })

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

        if feedback_summary["reject_reasons"]:
            top_reason = max(feedback_summary["reject_reasons"].items(), key=lambda x: x[1])
            low_quality_patterns.append({
                "type": "reject_pattern",
                "issue": f"最常见的拒绝原因: '{top_reason[0]}' ({top_reason[1]} 次)",
                "suggestion": "针对性优化提取逻辑",
                "data": dict(feedback_summary["reject_reasons"]),
                "actions": [],
            })

        cutoff_90 = (datetime.utcnow() - timedelta(days=90)).isoformat()
        stale_exps = [
            e for e in all_exps
            if e.status == ExperienceStatus.ACTIVE
            and (e.last_hit_at is None or e.last_hit_at < cutoff_90)
        ]
        if stale_exps:
            actions = [f"xp archive {e.id[:8]}  # 90天未命中，归档" for e in stale_exps[:5]]
            low_quality_patterns.append({
                "type": "staleness",
                "issue": f"有 {len(stale_exps)} 条 Active 经验超过 90 天未被检索",
                "suggestion": f"最近一次命中时间最早的：{stale_exps[0].last_hit_at or '从未命中'}",
                "data": f"经验 ID: {', '.join(e.id[:8] for e in stale_exps[:5])}",
                "actions": actions,
            })

        miss_queries = metrics.get_search_miss_queries(since_days=30)
        if miss_queries:
            top_queries = [f'"{q["query"]}" ({q["count"]} 次)' for q in miss_queries[:5]]
            low_quality_patterns.append({
                "type": "search_miss",
                "issue": f"近 30 天有 {len(miss_queries)} 个 query 未检索到任何经验",
                "suggestion": "以下 query 对应的知识空白，建议补充相关经验",
                "data": "；".join(top_queries),
                "actions": ["xp add  # 补充新经验"],
            })

        active_exps = [e for e in all_exps if e.status == ExperienceStatus.ACTIVE]
        if len(active_exps) >= 2:
            from ...embeddings import cosine_similarity
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

        recent_keywords = metrics.get_recent_query_keywords(since_days=30)
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
            "review_reject_reasons": review_reject_reasons,
            "low_quality_patterns": low_quality_patterns,
            "recommendations": [
                "定期运行 xp analyze 检查经验质量" if len(low_quality_patterns) > 0 else "当前经验质量良好",
                f"关注 {feedback_summary['low_adoption_count']} 条低采纳率经验" if feedback_summary["low_adoption_count"] > 0 else "",
            ]
        }
