import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestEdgeFunctionClient:
    def _make_client(self, base_url="https://xxx.supabase.co/functions/v1", token="xp_test"):
        from src.edge_client import EdgeFunctionClient
        return EdgeFunctionClient(base_url=base_url, token=token)

    def _mock_http_response(self, status_code=200, json_data=None):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or {}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    @pytest.mark.asyncio
    async def test_search_sends_token_in_header(self):
        client = self._make_client(token="xp_abc")
        mock_resp = self._mock_http_response(200, {"results": [], "search_event_id": "evt-001"})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.search(
                task_description="修复 bug",
                project_id="github.com/org/repo",
                project_manifest="{}",
            )
            _ = result

        call_kwargs = mock_http.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer xp_abc"

    @pytest.mark.asyncio
    async def test_search_returns_results_and_event_id(self):
        client = self._make_client()
        expected = {
            "results": [{"id": "exp-001", "title": "测试", "score": 0.9}],
            "search_event_id": "evt-001",
        }
        mock_resp = self._mock_http_response(200, expected)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.search(
                task_description="任务",
                project_id="proj-001",
                project_manifest="",
            )

        assert result["search_event_id"] == "evt-001"
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_save_sends_correct_payload(self):
        client = self._make_client()
        mock_resp = self._mock_http_response(200, {"experience_id": "exp-new", "status": "active", "quality_score": 85})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.save(
                task_description="修复 NPE",
                solution="增加 null 检查，超过五十字的解决方案描述",
                key_decisions="在 Service 层检查，超过三十字的关键决策描述",
                tags=["java", "null-safety"],
                project_id="github.com/org/repo",
                outcome="success",
            )

        assert result["experience_id"] == "exp-new"
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_feedback_sends_helpful_and_unhelpful_ids(self):
        client = self._make_client()
        mock_resp = self._mock_http_response(200, {"status": "ok", "search_event_id": "evt-001"})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.feedback(
                search_event_id="evt-001",
                helpful_ids=["exp-001"],
                unhelpful_ids=["exp-002"],
            )

        call_kwargs = mock_http.post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body["helpful_ids"] == ["exp-001"]
        assert body["unhelpful_ids"] == ["exp-002"]
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_raises_on_non_200(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("401 Unauthorized"))

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            with pytest.raises(Exception):
                await client.search(
                    task_description="test",
                    project_id="proj",
                    project_manifest="",
                )
