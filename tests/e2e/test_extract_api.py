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


class TestExtractAPI:
    def test_valid_extraction_returns_201(self, client):
        response = client.post("/api/experiences", json={
            "task_description": "实现 React 防抖 Hook",
            "solution_summary": "封装 useDebounce 自定义 hook，用 useRef 保持函数引用稳定，避免依赖数组问题",
            "key_decisions": "核心是用 useRef 保存最新的回调，避免 useEffect 频繁触发，这是 React hooks 闭包陷阱的标准解法",
            "tags": ["react"],
            "related_files": ["src/hooks/useDebounce.ts"],
        })
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["status"] in ("pending", "active")

    def test_missing_key_decisions_returns_422(self, client):
        response = client.post("/api/experiences", json={
            "task_description": "任务",
            "solution_summary": "解决方案超过二十个字符的描述",
        })
        assert response.status_code == 422

    def test_low_quality_returns_400(self, client):
        response = client.post("/api/experiences", json={
            "task_description": "任务",
            "solution_summary": "b" * 20,
            "key_decisions": "a" * 10,
        })
        assert response.status_code == 400
        assert "质量评分过低" in response.json()["detail"]
