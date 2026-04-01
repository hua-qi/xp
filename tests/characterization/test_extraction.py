import pytest
from unittest.mock import patch, MagicMock
import numpy as np


def make_fake_embedding():
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()


@pytest.fixture
def mock_embedding(monkeypatch):
    fake_vec = make_fake_embedding()
    mock_provider = MagicMock()
    mock_provider.embed_text.return_value = fake_vec
    mock_provider.embed_texts.return_value = [fake_vec]
    import src.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "get_provider", lambda: mock_provider)
    return mock_provider


class TestExtractExperience:
    async def test_valid_extraction_creates_pending(self, svc, mock_embedding):
        exp = await svc.extract_experience(
            task_description="实现防抖搜索框",
            solution_summary="使用 lodash debounce 包装 onChange，延迟 300ms 触发搜索",
            key_decisions="不能直接对 setState 防抖，需要对函数本身防抖，否则每次渲染会重建函数引用",
            tags=["react"],
            related_files=["src/SearchBox.tsx"],
        )
        assert exp.id is not None
        assert exp.status.value in ("pending", "active")
        assert exp.problem == "实现防抖搜索框"

    async def test_short_key_decisions_raises(self, svc, mock_embedding):
        with pytest.raises(ValueError, match="key_decisions"):
            await svc.extract_experience(
                task_description="任务",
                solution_summary="解决方案超过二十个字符的详细描述",
                key_decisions="太短",
            )

    async def test_short_solution_raises(self, svc, mock_embedding):
        with pytest.raises(ValueError, match="solution_summary"):
            await svc.extract_experience(
                task_description="任务",
                solution_summary="短",
                key_decisions="关键决策超过十个字符的描述",
            )

    async def test_high_quality_auto_activates(self, svc, mock_embedding):
        exp = await svc.extract_experience(
            task_description="实现 React 防抖 Hook",
            solution_summary="封装 useDebounce 自定义 hook，内部用 useRef 保持函数引用稳定，避免依赖数组问题",
            key_decisions="核心是用 useRef 保存最新的回调，避免 useEffect 频繁触发，这是 React hooks 闭包陷阱的标准解法",
            tags=["react", "typescript"],
            related_files=["src/hooks/useDebounce.ts", "src/SearchBox.tsx"],
        )
        assert exp.status.value == "active"
        assert exp.confidence == 0.65

    async def test_low_quality_raises(self, svc, mock_embedding):
        with pytest.raises(ValueError, match="质量评分过低"):
            await svc.extract_experience(
                task_description="任务",
                solution_summary="b" * 20,
                key_decisions="a" * 10,
            )
