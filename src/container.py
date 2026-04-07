from __future__ import annotations
from .application.command_bus import CommandBus
from .application.commands import (
    SearchV2Command,
    SaveCommand,
    FeedbackV2Command,
    ScanPromotionCandidatesCommand,
)
from .application.handlers.search_v2_handler import SearchV2Handler
from .application.handlers.save_handler import SaveHandler
from .application.handlers.feedback_v2_handler import FeedbackV2Handler
from .application.handlers.promotion_handler import PromotionScanHandler
from .infrastructure.unit_of_work import UnitOfWork


def build_command_bus(
    backend=None,
    llm=None,
    embedding_provider=None,
) -> CommandBus:
    bus = CommandBus()

    if backend is not None:
        def uow_factory():
            return UnitOfWork(backend=backend)

        bus.register(
            SearchV2Command,
            SearchV2Handler(backend=backend, llm=llm, embedding_provider=embedding_provider).handle,
        )
        bus.register(
            SaveCommand,
            SaveHandler(uow_factory=uow_factory, llm=llm).handle,
        )
        bus.register(
            FeedbackV2Command,
            FeedbackV2Handler(uow_factory=uow_factory, backend=backend, llm=llm).handle,
        )
        bus.register(
            ScanPromotionCandidatesCommand,
            PromotionScanHandler(uow_factory=uow_factory, embedding_provider=embedding_provider).handle,
        )

    return bus
