from __future__ import annotations
from typing import Callable
from ..commands import RecordSessionCommand
from ..unit_of_work import AbstractUnitOfWork


class SessionHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    def handle_record_session(self, cmd: RecordSessionCommand):
        from ...storage import MetricsStore
        from ...models import Session
        from datetime import datetime

        metrics = MetricsStore()
        session = Session(
            session_id=cmd.session_id,
            task_description=cmd.task_description,
            experience_ids_injected=cmd.experience_ids_injected,
            iteration_count=cmd.iteration_count,
            had_error_correction=cmd.had_error_correction,
            user_accepted=cmd.user_accepted,
            created_at=datetime.utcnow().isoformat(),
            ab_test_group=cmd.ab_test_group,
            ab_test_result_shown=cmd.ab_test_result_shown,
        )
        metrics.record_session(session)
        return True
