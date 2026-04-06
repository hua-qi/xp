import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid
from datetime import datetime
import numpy as np
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)


def _make_exp():
    return Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="防抖 Hook",
        tags=["react"],
        problem="实现 React 防抖 Hook",
        solution="封装 useDebounce 自定义 hook",
        key_decisions="用 useRef 保存最新回调",
        confidence=0.65,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(tech_stack=["react"]),
    )


class TestExtractAPI:
    def test_valid_extraction_returns_201(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=_make_exp())
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

    def test_low_quality_returns_400(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(side_effect=ValueError("质量评分过低，提取已拒绝"))
        response = client.post("/api/experiences", json={
            "task_description": "任务",
            "solution_summary": "b" * 20,
            "key_decisions": "a" * 10,
        })
        assert response.status_code == 400
        assert "质量评分过低" in response.json()["detail"]
