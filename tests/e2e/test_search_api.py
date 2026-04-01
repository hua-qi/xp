import pytest
from unittest.mock import MagicMock
import numpy as np


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch):
    import src.embeddings as emb_mod
    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]
    monkeypatch.setattr(emb_mod, "get_provider", lambda: mock_provider)


class TestSearchAPI:
    def test_search_returns_200(self, client):
        response = client.get("/api/experiences/search?q=防抖&top_k=3")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "metadata" in data

    def test_empty_query_returns_422(self, client):
        response = client.get("/api/experiences/search")
        assert response.status_code == 422

    def test_search_result_structure(self, client):
        response = client.get("/api/experiences/search?q=react hooks")
        data = response.json()
        assert isinstance(data["results"], list)
        assert "ab_test_group" in data["metadata"]
