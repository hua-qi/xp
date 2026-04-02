import pytest
import numpy as np
from src.embeddings import EmbeddingProvider, set_provider


class FakeProvider(EmbeddingProvider):
    def embed_texts(self, texts):
        vecs = []
        for _ in texts:
            v = np.random.rand(64).astype(np.float32)
            vecs.append((v / np.linalg.norm(v)).tolist())
        return vecs


@pytest.fixture
def extraction_deps(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    set_provider(FakeProvider())

    from src.storage import ExperienceStore, VectorStore
    return ExperienceStore(), VectorStore()


class TestExtractionService:
    async def test_valid_input_returns_experience(self, extraction_deps):
        from src.domain.extraction import ExtractionService
        store, v_store = extraction_deps
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

    async def test_short_key_decisions_raises(self, extraction_deps):
        from src.domain.extraction import ExtractionService
        store, v_store = extraction_deps
        svc = ExtractionService(store, v_store)

        with pytest.raises(ValueError, match="key_decisions"):
            await svc.extract(
                task_description="任务",
                solution_summary="解决方案超过二十个字符",
                key_decisions="短",
            )
