import json
import uuid
from datetime import datetime
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


def make_legacy_knowledge_json(tmp_path):
    exp_id = str(uuid.uuid4())
    data = {
        exp_id: {
            "id": exp_id,
            "type": "bugfix",
            "level": "L2",
            "title": "旧经验标题",
            "tags": ["python"],
            "problem": "旧问题描述",
            "solution": "旧解决方案描述",
            "key_decisions": "旧关键决策：注意事项",
            "confidence": 0.8,
            "status": "active",
            "source": "agent",
            "created_at": datetime.utcnow().isoformat(),
            "metadata": {"tech_stack": ["python"], "problem_type": "bugfix", "scene": []},
        }
    }
    knowledge_file = tmp_path / "knowledge.json"
    knowledge_file.write_text(json.dumps(data))
    return tmp_path, exp_id


class TestMigration:
    def test_migrate_preserves_all_experiences(self, tmp_path, monkeypatch):
        import src.storage as storage_mod
        legacy_path, exp_id = make_legacy_knowledge_json(tmp_path)

        target_path = tmp_path / "target"
        target_path.mkdir()
        monkeypatch.setattr(storage_mod, "XP_HOME", target_path)
        monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", target_path / "knowledge.json")
        monkeypatch.setattr(storage_mod, "METRICS_DB", target_path / "metrics.db")

        from scripts.migrate_knowledge_to_server import migrate
        migrated_count = migrate(source_path=legacy_path, dry_run=False)

        assert migrated_count == 1
        from src.storage import ExperienceStore
        store = ExperienceStore()
        exp = store.get(exp_id)
        assert exp is not None
        assert exp.title == "旧经验标题"

    def test_migrate_dry_run_does_not_write(self, tmp_path, monkeypatch):
        import src.storage as storage_mod
        legacy_path, exp_id = make_legacy_knowledge_json(tmp_path)

        target_path = tmp_path / "target"
        target_path.mkdir()
        monkeypatch.setattr(storage_mod, "XP_HOME", target_path)
        monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", target_path / "knowledge.json")
        monkeypatch.setattr(storage_mod, "METRICS_DB", target_path / "metrics.db")

        from scripts.migrate_knowledge_to_server import migrate
        migrated_count = migrate(source_path=legacy_path, dry_run=True)

        assert migrated_count == 1
        from src.storage import ExperienceStore
        store = ExperienceStore()
        assert store.get(exp_id) is None
