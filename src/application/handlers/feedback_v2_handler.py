from __future__ import annotations
from typing import Callable, Any

from ..commands import FeedbackV2Command
from ..unit_of_work import AbstractUnitOfWork
from ...domain.feedback_v2 import (
    compute_confidence_after_helpful,
    compute_confidence_after_unhelpful,
    validate_feedback_ids,
    should_archive,
)
from ...models import ExperienceStatus


class FeedbackV2Handler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], search_event_store: Any):
        self._uow_factory = uow_factory
        self._event_store = search_event_store

    async def handle(self, cmd: FeedbackV2Command) -> dict:
        event = self._event_store.get(cmd.search_event_id)
        if event is None:
            return {"status": "error", "message": f"search_event {cmd.search_event_id} 不存在"}

        errors = validate_feedback_ids(
            helpful_ids=cmd.helpful_ids,
            unhelpful_ids=cmd.unhelpful_ids,
            result_ids=event.result_ids,
        )
        if errors:
            return {"status": "error", "message": "; ".join(errors)}

        async with self._uow_factory() as uow:
            for exp_id in cmd.helpful_ids:
                exp = await uow.experiences.aget(exp_id)
                if exp is None:
                    continue
                exp.confidence = compute_confidence_after_helpful(exp.confidence)
                if should_archive(exp.confidence):
                    exp.status = ExperienceStatus.ARCHIVED
                await uow.experiences.aupdate(exp)

            for exp_id in cmd.unhelpful_ids:
                exp = await uow.experiences.aget(exp_id)
                if exp is None:
                    continue
                exp.confidence = compute_confidence_after_unhelpful(exp.confidence)
                if should_archive(exp.confidence):
                    exp.status = ExperienceStatus.ARCHIVED
                await uow.experiences.aupdate(exp)

        return {"status": "ok", "search_event_id": cmd.search_event_id}
