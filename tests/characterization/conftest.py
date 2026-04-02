import pytest
from pathlib import Path


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    return ExperienceStore(), MetricsStore()


class _SvcAdapter:
    def __init__(self, store, metrics, project="default"):
        self._store = store
        self._metrics = metrics
        self._project = project

    async def extract_experience(self, task_description, solution_summary, key_decisions,
                                  conversation_summary=None, tags=None, related_files=None):
        from src.application.handlers.extract_handler import ExtractHandler
        from src.application.commands import ExtractExperienceCommand
        from src.infrastructure.unit_of_work import UnitOfWork
        handler = ExtractHandler(uow_factory=UnitOfWork, project=self._project)
        return handler.handle_extract(ExtractExperienceCommand(
            task_description=task_description,
            solution_summary=solution_summary,
            key_decisions=key_decisions,
            conversation_summary=conversation_summary,
            tags=tags or [],
            related_files=related_files or [],
        ))

    async def record_feedback(self, experience_id, adopted, reason=None):
        from src.application.handlers.feedback_handler import FeedbackHandler
        from src.application.commands import RecordFeedbackCommand
        from src.infrastructure.unit_of_work import UnitOfWork
        handler = FeedbackHandler(uow_factory=UnitOfWork)
        return handler.handle_feedback(RecordFeedbackCommand(
            experience_id=experience_id,
            helpful=adopted,
        ))

    async def search(self, query, tags=None, top_k=3, threshold=0.5,
                     cross_project=False, session_id=None, enable_ab_test=True):
        from src.application.handlers.search_handler import SearchHandler
        from src.application.commands import SearchCommand
        from src.infrastructure.unit_of_work import UnitOfWork
        handler = SearchHandler(uow_factory=UnitOfWork, project=self._project)
        return handler.handle_search(SearchCommand(
            query=query,
            tags=tags,
            top_k=top_k,
            session_id=session_id,
        ))


@pytest.fixture
def svc(tmp_store):
    store, metrics = tmp_store
    return _SvcAdapter(store, metrics)
