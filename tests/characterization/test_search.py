import pytest
from unittest.mock import MagicMock
import numpy as np


def unit_vec(seed=42):
    rng = np.random.default_rng(seed)
    v = rng.random(384).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def svc_with_exp(svc, monkeypatch):
    import src.embeddings as emb_mod
    vec = unit_vec(1)
    mock_provider = MagicMock()
    mock_provider.embed_text.return_value = vec
    mock_provider.embed_texts.return_value = [vec]
    monkeypatch.setattr(emb_mod, "get_provider", lambda: mock_provider)
    return svc


class TestSearch:
    async def test_returns_tuple(self, svc_with_exp):
        results, meta = await svc_with_exp.search("防抖搜索框")
        assert isinstance(results, list)
        assert "ab_test_group" in meta
        assert "show_results" in meta
        assert "strategy" in meta

    async def test_empty_store_returns_empty_list(self, svc_with_exp):
        results, meta = await svc_with_exp.search("任意查询")
        assert results == []

    async def test_treatment_group_returns_results(self, svc_with_exp, monkeypatch):
        import hashlib
        session_id = "my-session"
        hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
        assert hash_val % 10 != 0, "该 session_id 应该是 treatment 组，请换一个"

        results, meta = await svc_with_exp.search("查询", session_id=session_id)
        assert meta["ab_test_group"] == "treatment"
        assert meta["show_results"] is True

    async def test_control_group_returns_empty(self, svc_with_exp):
        import hashlib
        for candidate in [f"s{i}" for i in range(100)]:
            h = int(hashlib.md5(candidate.encode()).hexdigest(), 16)
            if h % 10 == 0:
                control_session_id = candidate
                break

        results, meta = await svc_with_exp.search(
            "查询", session_id=control_session_id, enable_ab_test=True
        )
        assert meta["ab_test_group"] == "control"
        assert results == []

    async def test_strategy_is_embedding_only(self, svc_with_exp):
        _, meta = await svc_with_exp.search("test")
        assert meta["strategy"] == "embedding_only"
