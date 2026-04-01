import json
import pytest


async def test_preflight_check_empty():
    from scripts.migrate_to_postgres import preflight_check
    from pathlib import Path
    result = await preflight_check(Path("/nonexistent/knowledge.json"))
    assert result["total"] == 0
    assert result["ok"] is True


async def test_preflight_check_with_data(tmp_path):
    from scripts.migrate_to_postgres import preflight_check
    import uuid
    data = {
        str(uuid.uuid4()): {"solution": "some solution"},
        str(uuid.uuid4()): {},
    }
    json_path = tmp_path / "knowledge.json"
    json_path.write_text(json.dumps(data))
    result = await preflight_check(json_path)
    assert result["total"] == 2
    assert len(result["missing_vectors"]) == 1
