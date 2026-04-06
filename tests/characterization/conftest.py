import pytest
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.embeddings import EmbeddingProvider, set_provider
import numpy as np


class _FakeProvider(EmbeddingProvider):
    def embed_text(self, text):
        v = np.random.rand(64).astype(np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def embed_texts(self, texts):
        return [self.embed_text(t) for t in texts]


@pytest.fixture(autouse=True)
def fake_embedding():
    set_provider(_FakeProvider())


@pytest.fixture
def uow():
    return InMemoryUnitOfWork()


class _SvcAdapter:
    def __init__(self, uow_instance):
        self._uow = uow_instance

    async def extract_experience(self, task_description, solution_summary, key_decisions,
                                  conversation_summary=None, tags=None, related_files=None):
        from src.application.handlers.extract_handler import ExtractHandler
        from src.application.commands import ExtractExperienceCommand
        handler = ExtractHandler(uow_factory=lambda: self._uow)
        return await handler.handle_extract(ExtractExperienceCommand(
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
        handler = FeedbackHandler(uow_factory=lambda: self._uow)
        return await handler.handle_feedback(RecordFeedbackCommand(
            experience_id=experience_id,
            helpful=adopted,
        ))

    async def search(self, query, tags=None, top_k=3, threshold=0.5,
                     cross_project=False, session_id=None, enable_ab_test=True):
        from src.application.handlers.search_handler import SearchHandler
        from src.application.commands import SearchCommand
        handler = SearchHandler(uow_factory=lambda: self._uow)
        return await handler.handle_search(SearchCommand(
            query=query,
            tags=tags,
            top_k=top_k,
            session_id=session_id,
        ))


@pytest.fixture
def svc(uow):
    return _SvcAdapter(uow)
