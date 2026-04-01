import pytest
from pathlib import Path


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    from src.storage import ExperienceStore, MetricsStore
    return ExperienceStore(), MetricsStore()


@pytest.fixture
def svc(tmp_store):
    from src.knowledge import KnowledgeService
    store, metrics = tmp_store
    return KnowledgeService(store, metrics)
