import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock
import numpy as np
from src.models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceStatus, ExperienceSource, ExperienceMetadata,
)


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch):
    import src.embeddings as emb_mod
    mock_provider = MagicMock()
    vec = np.random.rand(384).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    mock_provider.embed_text.return_value = vec.tolist()
    mock_provider.embed_texts.return_value = [vec.tolist()]
    monkeypatch.setattr(emb_mod, "get_provider", lambda: mock_provider)


@pytest.fixture
def seeded_client(client, tmp_path, monkeypatch):
    import src.storage as storage_mod
    from src.storage import ExperienceStore
    store = ExperienceStore()
    exp = Experience(
        id=str(uuid.uuid4()),
        type=ExperienceType.FEATURE,
        level=ExperienceLevel.L2,
        title="防抖 Hook",
        tags=["react"],
        problem="防抖问题",
        solution="useDebounce 解决",
        key_decisions="用 useRef",
        confidence=0.7,
        status=ExperienceStatus.PENDING,
        source=ExperienceSource.AGENT,
        created_at=datetime.utcnow().isoformat(),
        metadata=ExperienceMetadata(tech_stack=["react"]),
    )
    store.add(exp)
    return client, exp.id


class TestRESTAPI:
    def test_list_pending_experiences(self, seeded_client):
        client, exp_id = seeded_client
        response = client.get("/api/experiences?status=pending")
        assert response.status_code == 200
        data = response.json()
        assert len(data["experiences"]) >= 1

    def test_review_activate(self, seeded_client):
        client, exp_id = seeded_client
        response = client.patch(f"/api/experiences/{exp_id}", json={"action": "activate"})
        assert response.status_code == 200

    def test_review_archive(self, seeded_client):
        client, exp_id = seeded_client
        response = client.patch(
            f"/api/experiences/{exp_id}",
            json={"action": "archive", "reason": "测试归档"}
        )
        assert response.status_code == 200

    def test_post_feedback(self, seeded_client):
        client, exp_id = seeded_client
        response = client.post("/api/feedback", json={
            "experience_id": exp_id,
            "adopted": True,
        })
        assert response.status_code == 200

    def test_post_session(self, client):
        response = client.post("/api/sessions", json={
            "session_id": "test-session-001",
            "task_description": "实现功能",
            "experience_ids_injected": [],
            "iteration_count": 3,
            "had_error_correction": False,
            "user_accepted": True,
        })
        assert response.status_code == 200

    def test_get_stats(self, client):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "active_count" in data
