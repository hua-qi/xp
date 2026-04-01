import pytest
import numpy as np
from unittest.mock import MagicMock
from src.domain.search import SearchService


@pytest.fixture
def mock_deps():
    mock_store = MagicMock()
    mock_store.list_active.return_value = []

    mock_vector_store = MagicMock()
    mock_vector_store.get_all_vectors.return_value = ([], np.array([]))
    mock_vector_store.save_vectors.return_value = None

    mock_metrics = MagicMock()
    mock_metrics.record_search.return_value = None

    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    mock_provider.embed_text.return_value = (vec / np.linalg.norm(vec)).tolist()

    return mock_store, mock_vector_store, mock_metrics, mock_provider


class TestSearchService:
    async def test_empty_store_returns_empty(self, mock_deps):
        store, v_store, metrics, provider = mock_deps
        svc = SearchService(store, v_store, metrics, provider, project="default")
        results, meta = await svc.search("query")
        assert results == []
        assert meta["strategy"] == "embedding_only"

    async def test_control_group_returns_empty(self, mock_deps):
        import hashlib
        store, v_store, metrics, provider = mock_deps
        svc = SearchService(store, v_store, metrics, provider, project="default")

        control_id = None
        for i in range(100):
            sid = f"s{i}"
            if int(hashlib.md5(sid.encode()).hexdigest(), 16) % 10 == 0:
                control_id = sid
                break

        results, meta = await svc.search("query", session_id=control_id)
        assert meta["ab_test_group"] == "control"
        assert results == []

    async def test_treatment_group_metadata(self, mock_deps):
        import hashlib
        store, v_store, metrics, provider = mock_deps
        svc = SearchService(store, v_store, metrics, provider, project="default")

        treat_id = None
        for i in range(100):
            sid = f"t{i}"
            if int(hashlib.md5(sid.encode()).hexdigest(), 16) % 10 != 0:
                treat_id = sid
                break

        _, meta = await svc.search("query", session_id=treat_id)
        assert meta["ab_test_group"] == "treatment"
        assert meta["show_results"] is True
