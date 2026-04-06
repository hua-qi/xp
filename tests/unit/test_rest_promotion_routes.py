from unittest.mock import patch, MagicMock, AsyncMock


class TestPromotionAPIRoutes:
    def _get_client(self):
        from fastapi.testclient import TestClient
        from src.interfaces.rest_api import create_app
        app = create_app()
        return TestClient(app)

    def _mock_bus(self, return_value):
        mock_bus = MagicMock()
        mock_bus.dispatch = AsyncMock(return_value=return_value)
        return mock_bus

    def test_scan_promotion_candidates_endpoint_exists(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus", new=AsyncMock(return_value=self._mock_bus({"candidates": []}))):
            response = client.post("/api/promotion/scan")
        assert response.status_code != 404

    def test_scan_returns_candidates_list(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus", new=AsyncMock(return_value=self._mock_bus({"candidates": []}))):
            response = client.post("/api/promotion/scan")
        assert response.status_code == 200
        assert "candidates" in response.json()

    def test_scan_dry_run_param_accepted(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus", new=AsyncMock(return_value=self._mock_bus({"candidates": []}))):
            response = client.post("/api/promotion/scan?dry_run=true")
        assert response.status_code == 200

    def test_promote_experience_endpoint_exists(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus", new=AsyncMock(return_value=self._mock_bus(True))):
            response = client.post(
                "/api/promotion/exp-001/promote",
                json={"target_scope": "business", "target_scope_id": "biz-001"},
            )
        assert response.status_code != 404

    def test_promote_experience_returns_ok(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus", new=AsyncMock(return_value=self._mock_bus(True))):
            response = client.post(
                "/api/promotion/exp-001/promote",
                json={"target_scope": "business", "target_scope_id": "biz-001"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["experience_id"] == "exp-001"

    def test_promote_experience_returns_404_when_not_found(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus", new=AsyncMock(return_value=self._mock_bus(False))):
            response = client.post(
                "/api/promotion/nonexistent/promote",
                json={"target_scope": "business", "target_scope_id": "biz-001"},
            )
        assert response.status_code == 404
