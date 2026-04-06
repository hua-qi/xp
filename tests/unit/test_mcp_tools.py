import pytest


class TestMCPToolDefinitions:
    def _get_tool_definitions(self):
        import ast
        import re

        with open("src/server.py", "r") as f:
            content = f.read()

        tool_names = re.findall(r'name="([^"]+)"', content)
        return content, tool_names

    def test_search_tool_exists(self):
        content, _ = self._get_tool_definitions()
        assert 'name="search"' in content

    def test_save_tool_exists(self):
        content, _ = self._get_tool_definitions()
        assert 'name="save"' in content

    def test_feedback_tool_exists(self):
        content, _ = self._get_tool_definitions()
        assert 'name="feedback"' in content

    def test_search_tool_has_task_description_param(self):
        content, _ = self._get_tool_definitions()
        search_section = content[content.index('name="search"'):]
        save_section_start = search_section.index('name="save"')
        search_only = search_section[:save_section_start]
        assert '"task_description"' in search_only

    def test_search_tool_has_project_id_param(self):
        content, _ = self._get_tool_definitions()
        search_section = content[content.index('name="search"'):]
        save_section_start = search_section.index('name="save"')
        search_only = search_section[:save_section_start]
        assert '"project_id"' in search_only

    def test_search_tool_has_project_manifest_param(self):
        content, _ = self._get_tool_definitions()
        search_section = content[content.index('name="search"'):]
        save_section_start = search_section.index('name="save"')
        search_only = search_section[:save_section_start]
        assert '"project_manifest"' in search_only

    def test_save_tool_has_outcome_param(self):
        content, _ = self._get_tool_definitions()
        save_section = content[content.index('name="save"'):]
        feedback_start = save_section.index('name="feedback"')
        save_only = save_section[:feedback_start]
        assert '"outcome"' in save_only

    def test_save_tool_has_search_event_id_param(self):
        content, _ = self._get_tool_definitions()
        save_section = content[content.index('name="save"'):]
        feedback_start = save_section.index('name="feedback"')
        save_only = save_section[:feedback_start]
        assert '"search_event_id"' in save_only

    def test_feedback_tool_has_search_event_id_param(self):
        content, _ = self._get_tool_definitions()
        feedback_section = content[content.index('name="feedback"'):]
        assert '"search_event_id"' in feedback_section[:2000]

    def test_feedback_tool_has_helpful_ids_param(self):
        content, _ = self._get_tool_definitions()
        feedback_section = content[content.index('name="feedback"'):]
        assert '"helpful_ids"' in feedback_section[:2000]
