import tomllib
from pathlib import Path


def test_package_name_is_xp_agent():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["name"] == "xp-agent"


def test_xp_server_entrypoint_exists():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    scripts = data["project"]["scripts"]
    assert "xp-server" in scripts
    assert scripts["xp-server"] == "src.server:run"


def test_xp_entrypoint_exists():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    scripts = data["project"]["scripts"]
    assert "xp" in scripts
    assert scripts["xp"] == "src.cli:run"


def test_httpx_in_dependencies():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    deps = data["project"]["dependencies"]
    assert any("httpx" in d for d in deps)
