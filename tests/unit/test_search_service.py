import pytest
import hashlib
import numpy as np
from src.domain.search_domain import ab_assign


class TestSearchServiceABTest:
    def test_empty_store_via_ab_assign_treatment(self):
        treat_id = next(
            f"t{i}" for i in range(100)
            if int(hashlib.md5(f"t{i}".encode()).hexdigest(), 16) % 10 != 0
        )
        assert ab_assign(treat_id) == "treatment"

    def test_control_group_via_ab_assign(self):
        control_id = next(
            f"s{i}" for i in range(100)
            if int(hashlib.md5(f"s{i}".encode()).hexdigest(), 16) % 10 == 0
        )
        assert ab_assign(control_id) == "control"

    def test_treatment_group_via_ab_assign(self):
        treat_id = next(
            f"t{i}" for i in range(100)
            if int(hashlib.md5(f"t{i}".encode()).hexdigest(), 16) % 10 != 0
        )
        assert ab_assign(treat_id) == "treatment"


class TestSearchServiceEmptyStore:
    def test_empty_store_returns_empty(self, tmp_path, monkeypatch):
        import src.storage as storage_mod
        monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
        monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
        monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

        from src.embeddings import EmbeddingProvider, set_provider
        from src.storage import ExperienceStore, VectorStore, MetricsStore
        from src.domain.search import SearchService
        import asyncio

        class FakeProvider(EmbeddingProvider):
            def embed_text(self, text):
                v = np.random.rand(64).astype(np.float32)
                return (v / np.linalg.norm(v)).tolist()

            def embed_texts(self, texts):
                return [self.embed_text(t) for t in texts]

        set_provider(FakeProvider())
        store = ExperienceStore()
        v_store = VectorStore()
        metrics = MetricsStore()

        svc = SearchService(store, v_store, metrics, FakeProvider(), project="default")

        loop = asyncio.new_event_loop()
        results, meta = loop.run_until_complete(svc.search("query"))
        loop.close()

        assert results == []
        assert meta["strategy"] == "embedding_only"
