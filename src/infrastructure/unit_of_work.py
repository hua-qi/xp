from __future__ import annotations
from ..application.unit_of_work import AbstractUnitOfWork, AbstractAnalyticsStore


class _PgExperienceStore:
    def __init__(self, backend):
        self._backend = backend

    def add(self, exp):
        raise NotImplementedError("Use async path")

    def get(self, exp_id: str):
        raise NotImplementedError("Use async path")

    def update(self, exp):
        raise NotImplementedError("Use async path")

    def list_by_status(self, status: str) -> list:
        raise NotImplementedError("Use async path")

    async def aadd(self, exp):
        return await self._backend.async_add_experience(exp)

    async def aget(self, exp_id: str):
        return await self._backend.async_get_experience(exp_id)

    async def aupdate(self, exp):
        return await self._backend.async_update_experience(exp)

    async def alist_by_status(self, status: str) -> list:
        from ..models import ExperienceStatus
        return await self._backend.async_list_by_status(ExperienceStatus(status))


class _PgVectorStore:
    def __init__(self, backend):
        self._backend = backend

    def save_vector(self, exp_id: str, vector: list[float]) -> None:
        raise NotImplementedError("Use async path")

    def get_all_vectors(self, exp_ids=None):
        raise NotImplementedError("Use async path")

    async def asave_vector(self, exp_id: str, vector: list[float]) -> None:
        await self._backend.async_save_vector(exp_id, vector)

    async def aget_all_vectors(self, exp_ids=None):
        return await self._backend.async_get_all_vectors(exp_ids)


class _PgMetricsStore:
    def __init__(self, backend):
        self._backend = backend

    def record_search(self, query: str, result_count: int) -> None:
        raise NotImplementedError("Use async path")

    def record_feedback(self, feedback) -> None:
        raise NotImplementedError("Use async path")

    def get_experience_stats(self, exp_id: str):
        raise NotImplementedError("Use async path")

    async def arecord_feedback(self, feedback):
        await self._backend.async_record_feedback(feedback)

    async def aget_experience_stats(self, exp_id: str):
        return await self._backend.async_get_experience_stats(exp_id)


class _PgAnalyticsStore(AbstractAnalyticsStore):
    def __init__(self, backend):
        self._backend = backend

    async def record_session(self, session) -> None:
        await self._backend.async_record_session(session)

    async def record_feedback(self, feedback) -> None:
        await self._backend.async_record_feedback(feedback)

    async def get_stats(self, since_days: int | None = None) -> dict:
        return await self._backend.async_get_stats(since_days)

    async def get_feedback_summary(self, since_days: int | None = None) -> dict:
        return await self._backend.async_get_feedback_summary(since_days)

    async def get_search_miss_queries(self, since_days: int = 30, limit: int = 10) -> list[dict]:
        return await self._backend.async_get_search_miss_queries(since_days, limit)

    async def get_recent_query_keywords(self, since_days: int = 30, top_k: int = 20) -> list[str]:
        return await self._backend.async_get_recent_query_keywords(since_days, top_k)

    async def get_hitted_experience_ids(self) -> list[str]:
        return await self._backend.async_get_hitted_experience_ids()

    async def get_review_reject_reasons(self, limit: int = 10) -> dict[str, int]:
        return await self._backend.async_get_review_reject_reasons(limit)


class UnitOfWork(AbstractUnitOfWork):
    def __init__(self, backend):
        super().__init__()
        self._backend = backend
        self.experiences = _PgExperienceStore(backend)
        self.vectors = _PgVectorStore(backend)
        self.metrics = _PgMetricsStore(backend)
        self.analytics = _PgAnalyticsStore(backend)

    def __enter__(self) -> "UnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def __aenter__(self) -> "UnitOfWork":
        await self._backend.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._backend.close()
