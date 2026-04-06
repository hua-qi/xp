from __future__ import annotations
from typing import Callable
from ..commands import SearchCommand
from ..unit_of_work import AbstractUnitOfWork


class SearchHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], project: str = "default"):
        self._uow_factory = uow_factory
        self._project = project

    async def handle_search(self, cmd: SearchCommand):
        from ...domain.search import SearchService
        from ...embeddings import get_provider

        provider = get_provider()

        async with self._uow_factory() as uow:
            svc = SearchService(uow.experiences, uow.vectors, uow.metrics, provider, project=self._project)
            results, meta = await svc.search(
                query=cmd.query,
                tags=cmd.tags,
                top_k=cmd.top_k,
                session_id=cmd.session_id,
            )
        return results, meta
