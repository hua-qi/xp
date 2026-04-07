"""Embedding 模型抽象与提供者实现
支持本地模型 (BGE-small-zh) 与云端模型 (OpenAI 等)
"""

import abc
import os
from pathlib import Path
from typing import Optional

import numpy as np

EMBEDDING_DIM = 1024

def cosine_similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
    """计算余弦相似度
    Args:
        query_vec: 查询向量 (D,)
        doc_vecs: 文档向量矩阵 (N, D)
    Returns:
        相似度分数数组 (N,)
    """
    if len(doc_vecs) == 0:
        return np.array([])
    # 假设向量已归一化，点积即余弦相似度
    return np.dot(doc_vecs, query_vec)

class EmbeddingProvider(abc.ABC):
    @abc.abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        pass

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class LocalBGEProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self._model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            cache_dir = os.getenv("XP_EMBEDDING_CACHE", Path.home() / ".cache" / "xp" / "embeddings")
            cache_dir = Path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(self._model_name, cache_folder=str(cache_dir))
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        embeddings = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return embeddings.tolist()


class CloudAPIProvider(EmbeddingProvider):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", api_base: Optional[str] = None):
        self._api_key = api_key
        self._model = model
        self._api_base = api_base
        import openai
        self._client = openai.OpenAI(api_key=api_key, base_url=api_base)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(
            input=texts,
            model=self._model
        )
        return [data.embedding for data in response.data]


_provider_instance: Optional[EmbeddingProvider] = None

def get_provider() -> EmbeddingProvider:
    global _provider_instance
    if _provider_instance is None:
        # Default to LocalBGEProvider
        _provider_instance = LocalBGEProvider()
    return _provider_instance

def set_provider(provider: EmbeddingProvider):
    global _provider_instance
    _provider_instance = provider
