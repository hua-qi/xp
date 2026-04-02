from __future__ import annotations
from typing import Callable
from ..commands import SearchCommand
from ..unit_of_work import AbstractUnitOfWork


class SearchHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], project: str = "default"):
        self._uow_factory = uow_factory
        self._project = project

    def handle_search(self, cmd: SearchCommand):
        from ...domain.search import SearchService
        from ...embeddings import get_provider
        from ...storage import ExperienceStore, VectorStore, MetricsStore

        store = ExperienceStore()
        metrics = MetricsStore()
        vector_store = VectorStore()
        provider = get_provider()

        import asyncio
        svc = SearchService(store, vector_store, metrics, provider, project=self._project)
        coro = svc.search(
            query=cmd.query,
            tags=cmd.tags,
            top_k=cmd.top_k,
            session_id=cmd.session_id,
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    results, meta = future.result()
            else:
                results, meta = loop.run_until_complete(coro)
        except RuntimeError:
            results, meta = asyncio.run(coro)
        return results, meta
