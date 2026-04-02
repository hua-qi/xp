from __future__ import annotations
from typing import Callable
from ..commands import GetStatsCommand
from ..unit_of_work import AbstractUnitOfWork


class StatsHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    def handle_get_stats(self, cmd: GetStatsCommand) -> dict:
        from ...storage import ExperienceStore, MetricsStore
        from ...models import ExperienceStatus
        from datetime import datetime, timedelta

        store = ExperienceStore()
        metrics = MetricsStore()

        process = metrics.get_stats(cmd.since_days)

        all_active = store.list_active()
        pending = store.list_by_status(ExperienceStatus.PENDING)
        archived = store.list_by_status(ExperienceStatus.ARCHIVED)

        process["active_count"] = len(all_active)
        process["pending_count"] = len(pending)
        process["archived_count"] = len(archived)

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

        hitted_ids = set(metrics.get_hitted_experience_ids())
        process["zombie_count"] = sum(1 for e in all_active if e.id not in hitted_ids)

        top_adopted_raw = process.get("top_adopted_experiences", [])
        enriched = []
        for item in top_adopted_raw:
            exp = store.get(item["experience_id"])
            enriched.append({
                **item,
                "title": exp.title[:30] if exp else item["experience_id"][:8],
            })
        process["top_adopted_experiences"] = enriched
        process["top_miss_queries"] = metrics.get_search_miss_queries(since_days=30, limit=5)

        cutoff_30 = (datetime.utcnow() - timedelta(days=30)).isoformat()
        all_exps = all_active + pending + archived
        new_exps_30d = sum(1 for e in all_exps if e.created_at >= cutoff_30)
        process["trend_30d"] = {
            "new_experiences": new_exps_30d,
            "new_sessions": process.get("new_sessions_30d", 0),
        }

        return process
