from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler


async def _retry_pending_experiences(backend, command_bus):
    if backend is None:
        return


async def _scan_promotion_candidates(backend, command_bus):
    if backend is None or command_bus is None:
        return
    from src.application.commands import ScanPromotionCandidatesCommand
    await command_bus.dispatch(ScanPromotionCandidatesCommand())


def build_scheduler(backend, command_bus) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _retry_pending_experiences,
        "interval",
        hours=12,
        args=[backend, command_bus],
        id="retry_pending",
    )
    scheduler.add_job(
        _scan_promotion_candidates,
        "interval",
        days=3,
        args=[backend, command_bus],
        id="scan_promotion",
    )
    return scheduler
