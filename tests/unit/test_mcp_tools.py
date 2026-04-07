import pytest


class TestMCPToolDefinitions:
    def _get_source(self):
        with open("src/server.py", "r") as f:
            return f.read()

    def test_search_tool_exists(self):
        content = self._get_source()
        assert "async def search" in content

    def test_save_tool_exists(self):
        content = self._get_source()
        assert "async def save" in content

    def test_feedback_tool_exists(self):
        content = self._get_source()
        assert "async def feedback" in content

    def test_search_tool_has_task_description_param(self):
        content = self._get_source()
        assert "task_description" in content

    def test_search_tool_has_project_id_param(self):
        content = self._get_source()
        assert "project_id" in content

    def test_save_tool_has_outcome_param(self):
        content = self._get_source()
        assert "outcome" in content

    def test_save_tool_has_outcome_description_param(self):
        content = self._get_source()
        assert "outcome_description" in content

    def test_feedback_tool_has_adopted_ids_param(self):
        content = self._get_source()
        assert "adopted_ids" in content

    def test_feedback_tool_has_rejected_ids_param(self):
        content = self._get_source()
        assert "rejected_ids" in content

    def test_server_uses_fastmcp(self):
        content = self._get_source()
        assert "FastMCP" in content
