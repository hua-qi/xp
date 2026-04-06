from __future__ import annotations
from typing import Callable
from ..commands import GetStatsCommand
from ..unit_of_work import AbstractUnitOfWork


class StatsHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    async def handle_get_stats(self, cmd: GetStatsCommand) -> dict:
        from ...models import ExperienceStatus
        from datetime import datetime, timedelta

        async with self._uow_factory() as uow:
            process = await uow.analytics.get_stats(cmd.since_days)
            all_active = await uow.experiences.alist_by_status("active")
            pending = await uow.experiences.alist_by_status("pending")
            archived = await uow.experiences.alist_by_status("archived")
            hitted_ids = set(await uow.analytics.get_hitted_experience_ids())
            miss_queries = await uow.analytics.get_search_miss_queries(since_days=30, limit=5)

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

        process["zombie_count"] = sum(1 for e in all_active if e.id not in hitted_ids)
        process["top_miss_queries"] = miss_queries

        cutoff_30 = (datetime.utcnow() - timedelta(days=30)).isoformat()
        all_exps = all_active + pending + archived
        new_exps_30d = sum(1 for e in all_exps if e.created_at >= cutoff_30)
        process["trend_30d"] = {
            "new_experiences": new_exps_30d,
            "new_sessions": process.get("new_sessions_30d", 0),
        }

        return process
