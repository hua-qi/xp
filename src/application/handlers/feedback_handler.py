from __future__ import annotations
from typing import Callable
from ..commands import RecordFeedbackCommand
from ..unit_of_work import AbstractUnitOfWork
from ...domain.feedback import compute_new_confidence
from ...domain.events import FeedbackRecorded
from ...domain.constants import AUTO_ARCHIVE_ADOPTION_THRESHOLD


class FeedbackHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    async def handle_feedback(self, cmd: RecordFeedbackCommand):
        async with self._uow_factory() as uow:
            exp = await uow.experiences.aget(cmd.experience_id)
            if exp is None:
                return False

            old_confidence = exp.confidence
            new_confidence = compute_new_confidence(old_confidence, cmd.helpful)
            exp.confidence = new_confidence

            if new_confidence <= AUTO_ARCHIVE_ADOPTION_THRESHOLD:
                try:
                    from ...models import ExperienceStatus
                    exp.status = ExperienceStatus.ARCHIVED
                except Exception:
                    exp.status = "ARCHIVED"
                exp.reject_reason = "Low adoption rate, auto archived"

            await uow.experiences.aupdate(exp)
            uow.collect_event(FeedbackRecorded(
                experience_id=cmd.experience_id,
                helpful=cmd.helpful,
                session_id=cmd.session_id,
                old_confidence=old_confidence,
                new_confidence=new_confidence,
            ))
        return True
