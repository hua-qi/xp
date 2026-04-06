import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from src.embeddings import EmbeddingProvider, set_provider
import numpy as np


class _FakeProvider(EmbeddingProvider):
    def embed_text(self, text):
        v = np.random.rand(384).astype(np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def embed_texts(self, texts):
        return [self.embed_text(t) for t in texts]


@pytest.fixture(autouse=True)
def mock_embedding():
    set_provider(_FakeProvider())


@pytest.fixture
def mock_bus():
    bus = MagicMock()
    bus.dispatch = AsyncMock(return_value=None)
    return bus


@pytest.fixture
def app(mock_bus, monkeypatch):
    monkeypatch.setattr("src.interfaces.rest_api.build_command_bus", AsyncMock(return_value=mock_bus))
    from src.interfaces.rest_api import create_app
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)
