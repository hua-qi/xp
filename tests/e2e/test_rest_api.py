import pytest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
import numpy as np
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)


def _make_exp(exp_id=None):
    return Experience(
        id=exp_id or str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="防抖 Hook",
        tags=["react"],
        problem="防抖问题",
        solution="useDebounce 解决",
        key_decisions="用 useRef",
        confidence=0.7,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(tech_stack=["react"]),
    )


class TestRESTAPI:
    def test_list_pending_experiences(self, client, mock_bus):
        exp = _make_exp()
        mock_bus.dispatch = AsyncMock(return_value=[exp])
        response = client.get("/api/experiences?status=pending")
        assert response.status_code == 200

    def test_review_activate(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=True)
        exp_id = str(uuid.uuid4())
        response = client.patch(f"/api/experiences/{exp_id}", json={"action": "activate"})
        assert response.status_code == 200

    def test_review_archive(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=True)
        exp_id = str(uuid.uuid4())
        response = client.patch(
            f"/api/experiences/{exp_id}",
            json={"action": "archive", "reason": "测试归档"}
        )
        assert response.status_code == 200

    def test_post_feedback(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=True)
        exp_id = str(uuid.uuid4())
        response = client.post("/api/feedback", json={
            "experience_id": exp_id,
            "adopted": True,
        })
        assert response.status_code == 200

    def test_post_session(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=True)
        response = client.post("/api/sessions", json={
            "session_id": "test-session-001",
            "task_description": "实现功能",
            "experience_ids_injected": [],
            "iteration_count": 3,
            "had_error_correction": False,
            "user_accepted": True,
        })
        assert response.status_code == 200

    def test_get_stats(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value={
            "session_total": 0, "active_count": 0, "pending_count": 0, "archived_count": 0,
            "search_total": 0, "search_hit_rate": 0.0, "review_confirmed": 0,
            "review_rejected": 0, "review_pass_rate": 0.0,
            "result_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
            "result_not_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
            "avg_result_count": 0.0, "query_adoption_rate": 0.0, "top_adopted_experiences": [],
            "zombie_count": 0, "type_distribution": {}, "avg_confidence": 0.0,
            "top_miss_queries": [], "trend_30d": {"new_experiences": 0, "new_sessions": 0},
        })
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "active_count" in data

    def test_post_infer_adoption(self, client, mock_bus):
        mock_bus.dispatch = AsyncMock(return_value=[])
        exp_id = str(uuid.uuid4())
        response = client.post("/api/infer-adoption", json={
            "session_id": "s-001",
            "final_response": "用 useRef 解决了防抖问题",
            "experience_ids_injected": [exp_id],
        })
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
