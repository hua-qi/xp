"""Embedding 模型封装 - 使用 BGE-small-zh 实现语义检索

BGE (BAAI General Embedding) 是智源研究院开源的中文 Embedding 模型
- 模型: BAAI/bge-small-zh-v1.5
- 大小: ~100MB
- 维度: 512
- 许可: MIT

与 Agent 大模型完全解耦，所有计算在 XP Server 内部完成
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import numpy as np

# 延迟加载 sentence-transformers，避免启动时立即加载模型
_model = None
_model_name = "BAAI/bge-small-zh-v1.5"


def _get_model():
    """懒加载 Embedding 模型"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        # 使用环境变量指定缓存目录
        cache_dir = os.getenv("XP_EMBEDDING_CACHE", Path.home() / ".cache" / "xp" / "embeddings")
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        _model = SentenceTransformer(_model_name, cache_folder=str(cache_dir))
    return _model


def encode(text: str, normalize: bool = True) -> np.ndarray:
    """将文本编码为向量

    Args:
        text: 输入文本
        normalize: 是否归一化向量（用于余弦相似度计算）

    Returns:
        向量数组 (512维)
    """
    model = _get_model()
    embedding = model.encode(text, normalize_embeddings=normalize, convert_to_numpy=True)
    return embedding


def encode_batch(texts: list[str], normalize: bool = True) -> np.ndarray:
    """批量编码文本

    Args:
        texts: 文本列表
        normalize: 是否归一化

    Returns:
        向量矩阵 (N, 512)
    """
    if not texts:
        return np.array([])

    model = _get_model()
    embeddings = model.encode(texts, normalize_embeddings=normalize, convert_to_numpy=True)
    return embeddings


def cosine_similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
    """计算余弦相似度

    Args:
        query_vec: 查询向量 (512,)
        doc_vecs: 文档向量矩阵 (N, 512)

    Returns:
        相似度分数数组 (N,)
    """
    # 向量已归一化，点积即余弦相似度
    return np.dot(doc_vecs, query_vec)


def get_text_hash(text: str) -> str:
    """计算文本的哈希值，用于缓存键"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """Embedding 向量缓存

    避免重复计算相同文本的向量，提升检索速度
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache_dir = cache_dir or Path.home() / ".xp" / "embedding_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, np.ndarray] = {}

    def _get_cache_path(self, text_hash: str) -> Path:
        """获取缓存文件路径"""
        return self._cache_dir / f"{text_hash}.npy"

    def get(self, text: str) -> Optional[np.ndarray]:
        """获取缓存的向量"""
        text_hash = get_text_hash(text)

        # 先查内存缓存
        if text_hash in self._memory_cache:
            return self._memory_cache[text_hash]

        # 再查磁盘缓存
        cache_path = self._get_cache_path(text_hash)
        if cache_path.exists():
            vec = np.load(cache_path)
            self._memory_cache[text_hash] = vec
            return vec

        return None

    def set(self, text: str, vec: np.ndarray):
        """设置缓存"""
        text_hash = get_text_hash(text)

        # 内存缓存
        self._memory_cache[text_hash] = vec

        # 磁盘缓存
        cache_path = self._get_cache_path(text_hash)
        np.save(cache_path, vec)

    def get_or_compute(self, text: str) -> np.ndarray:
        """获取缓存向量，不存在则计算"""
        vec = self.get(text)
        if vec is None:
            vec = encode(text)
            self.set(text, vec)
        return vec

    def get_or_compute_batch(self, texts: list[str]) -> np.ndarray:
        """批量获取缓存向量，不存在则计算"""
        results = []
        to_compute = []
        to_compute_idx = []

        for i, text in enumerate(texts):
            vec = self.get(text)
            if vec is not None:
                results.append((i, vec))
            else:
                to_compute.append(text)
                to_compute_idx.append(i)

        # 批量计算未缓存的
        if to_compute:
            computed = encode_batch(to_compute)
            for idx, text, vec in zip(to_compute_idx, to_compute, computed):
                self.set(text, vec)
                results.append((idx, vec))

        # 按原始顺序组装结果
        results.sort(key=lambda x: x[0])
        return np.array([r[1] for r in results])


# 全局缓存实例
_cache = None


def get_cache() -> EmbeddingCache:
    """获取全局缓存实例"""
    global _cache
    if _cache is None:
        _cache = EmbeddingCache()
    return _cache
