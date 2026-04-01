import pytest
from unittest.mock import MagicMock
import numpy as np


@pytest.fixture
def mock_extraction_deps(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    from src.storage import ExperienceStore, VectorStore
    store = ExperienceStore()
    v_store = VectorStore()

    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]

    import src.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "get_provider", lambda: mock_provider)

    return store, v_store


class TestExtractionService:
    async def test_valid_input_returns_experience(self, mock_extraction_deps):
        from src.domain.extraction import ExtractionService
        store, v_store = mock_extraction_deps
        svc = ExtractionService(store, v_store)

        exp = await svc.extract(
            task_description="实现 React 防抖 Hook",
            solution_summary="封装 useDebounce 自定义 hook，用 useRef 保持函数引用稳定",
            key_decisions="核心是用 useRef 保存最新回调，避免 useEffect 频繁触发，这是 React hooks 闭包陷阱的标准解法",
            related_files=["src/hooks/useDebounce.ts"],
            tags=["react"],
        )
        assert exp.id is not None
        assert exp.problem == "实现 React 防抖 Hook"

    async def test_short_key_decisions_raises(self, mock_extraction_deps):
        from src.domain.extraction import ExtractionService
        store, v_store = mock_extraction_deps
        svc = ExtractionService(store, v_store)

        with pytest.raises(ValueError, match="key_decisions"):
            await svc.extract(
                task_description="任务",
                solution_summary="解决方案超过二十个字符",
                key_decisions="短",
            )
