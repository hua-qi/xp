from src.domain.manifest_parser import parse_manifest


class TestParseManifestPackageJson:
    def test_detects_language_as_javascript(self):
        manifest = '{"dependencies": {"react": "^18.0.0"}, "devDependencies": {}}'
        result = parse_manifest(manifest)
        assert result["language"] == "javascript"

    def test_extracts_top_dependencies_from_package_json(self):
        manifest = '{"dependencies": {"react": "^18", "axios": "^1"}}'
        result = parse_manifest(manifest)
        assert "react" in result["top_dependencies"]
        assert "axios" in result["top_dependencies"]

    def test_detects_react_framework(self):
        manifest = '{"dependencies": {"react": "^18", "react-dom": "^18"}}'
        result = parse_manifest(manifest)
        assert "react" in result["frameworks"]

    def test_detects_nextjs_framework(self):
        manifest = '{"dependencies": {"next": "^14"}}'
        result = parse_manifest(manifest)
        assert "nextjs" in result["frameworks"]


class TestParseManifestPyprojectToml:
    def test_detects_language_as_python(self):
        manifest = '[project]\ndependencies = ["fastapi>=0.110", "sqlalchemy>=2.0"]'
        result = parse_manifest(manifest)
        assert result["language"] == "python"

    def test_extracts_dependencies_from_pyproject(self):
        manifest = '[project]\ndependencies = ["fastapi>=0.110", "sqlalchemy>=2.0"]'
        result = parse_manifest(manifest)
        assert "fastapi" in result["top_dependencies"]
        assert "sqlalchemy" in result["top_dependencies"]

    def test_detects_fastapi_framework(self):
        manifest = '[project]\ndependencies = ["fastapi>=0.110"]'
        result = parse_manifest(manifest)
        assert "fastapi" in result["frameworks"]


class TestParseManifestGoMod:
    def test_detects_language_as_go(self):
        manifest = 'module github.com/org/repo\ngo 1.21\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)'
        result = parse_manifest(manifest)
        assert result["language"] == "go"

    def test_extracts_dependencies_from_go_mod(self):
        manifest = 'module github.com/org/repo\ngo 1.21\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)'
        result = parse_manifest(manifest)
        assert "gin" in result["top_dependencies"]


class TestParseManifestEdgeCases:
    def test_empty_string_returns_defaults(self):
        result = parse_manifest("")
        assert result["language"] == "unknown"
        assert result["top_dependencies"] == []
        assert result["frameworks"] == []

    def test_none_returns_defaults(self):
        result = parse_manifest(None)
        assert result["language"] == "unknown"

    def test_invalid_json_does_not_raise(self):
        result = parse_manifest("{invalid json}")
        assert result["language"] == "unknown"

    def test_top_dependencies_capped_at_ten(self):
        deps = {f"dep{i}": "^1.0" for i in range(20)}
        import json
        manifest = json.dumps({"dependencies": deps})
        result = parse_manifest(manifest)
        assert len(result["top_dependencies"]) <= 10
