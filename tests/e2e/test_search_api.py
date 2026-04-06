import pytest
from unittest.mock import AsyncMock


class TestSearchAPI:
    def test_search_returns_200(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=([], {"ab_test_group": "treatment", "strategy": "embedding_only"}))
        response = client.get("/api/experiences/search?q=防抖&top_k=3")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "metadata" in data

    def test_empty_query_returns_422(self, client):
        response = client.get("/api/experiences/search")
        assert response.status_code == 422

    def test_search_result_structure(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=([], {"ab_test_group": "treatment", "strategy": "embedding_only"}))
        response = client.get("/api/experiences/search?q=react hooks")
        data = response.json()
        assert isinstance(data["results"], list)
        assert "ab_test_group" in data["metadata"]
