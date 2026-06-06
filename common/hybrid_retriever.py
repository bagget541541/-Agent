#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合检索模块 — BM25 + 向量检索 + RRF 融合

使用 Reciprocal Rank Fusion (RRF) 将 BM25 关键词检索与向量语义检索结合，
提升检索质量，特别是对于语义相似但关键词不匹配的查询。
"""

import hashlib
import os
import pickle
import time
from datetime import datetime
from pathlib import Path

import numpy as np

# 使用统一配置
from common.config import DATA_DIR, EMBEDDING_MODEL, VECTOR_CACHE

# BM25 cache 路径（复用现有）
BM25_CACHE = str(DATA_DIR / "bm25_cache.pkl")


# ═══════════════════════════════════════════════
#  向量索引
# ═══════════════════════════════════════════════

class _EmbeddingIndex:
    """轻量级向量索引，使用 numpy 数组 + pickle 序列化。"""

    __slots__ = ('embeddings', 'norms', 'doc_count', 'model_name', 'built_at')

    def __init__(self, embeddings: np.ndarray, model_name: str, built_at: str = ""):
        """
        Args:
            embeddings: 形状 (n_docs, dim) 的 numpy 数组
            model_name: embedding 模型名称
            built_at: 构建时间戳
        """
        self.embeddings = embeddings.astype(np.float32)
        self.norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        self.doc_count = embeddings.shape[0]
        self.model_name = model_name
        self.built_at = built_at or datetime.now().isoformat(timespec="seconds")

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list[tuple[int, float]]:
        """
        使用余弦相似度搜索最相似的文档。

        Args:
            query_embedding: 查询向量，形状 (dim,)
            top_k: 返回前 K 个结果

        Returns:
            [(doc_index, cosine_score), ...] 按分数降序排列
        """
        if self.doc_count == 0:
            return []

        # 计算余弦相似度: cos(a, b) = (a·b) / (||a|| * ||b||)
        q = query_embedding.astype(np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm < 1e-8:
            return []

        # 向量化计算所有文档的相似度
        scores = np.dot(self.embeddings, q) / (self.norms.flatten() * q_norm)

        # 取 top_k（使用 argpartition 优化，避免全排序）
        if top_k >= self.doc_count:
            top_indices = np.argsort(-scores)
        else:
            top_indices = np.argpartition(-scores, top_k)[:top_k]
            top_indices = top_indices[np.argsort(-scores[top_indices])]

        return [(int(idx), float(scores[idx])) for idx in top_indices if scores[idx] > 0]

    def save(self, path: str) -> None:
        """保存索引到 pickle 文件。"""
        data = {
            'embeddings': self.embeddings,
            'model_name': self.model_name,
            'built_at': self.built_at,
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str) -> '_EmbeddingIndex':
        """从 pickle 文件加载索引。"""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        return cls(
            embeddings=data['embeddings'],
            model_name=data['model_name'],
            built_at=data.get('built_at', ''),
        )


# ═══════════════════════════════════════════════
#  混合检索器
# ═══════════════════════════════════════════════

class HybridRetriever:
    """BM25 + 向量检索 + RRF 融合的混合检索器。"""

    def __init__(
        self,
        entries: list[dict],
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
        rrf_k: int = 60,
        embedding_model: str = EMBEDDING_MODEL,
        enable_vector: bool = True,
    ):
        """
        Args:
            entries: KB entries 列表
            bm25_weight: BM25 结果在 RRF 融合中的权重
            vector_weight: 向量结果在 RRF 融合中的权重
            rrf_k: RRF 常数（越大，排名靠后的位置权重越低）
            embedding_model: sentence-transformers 模型名称
            enable_vector: 是否启用向量检索（禁用则纯 BM25）
        """
        self.entries = entries
        self.rrf_k = rrf_k
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight

        # 加载 BM25（从 src/rag_query.py 导入）
        from src.rag_query import BM25, tokenize
        self._tokenize = tokenize
        texts = [e["text"] for e in entries]
        self._bm25 = BM25(k1=1.5, b=0.75).fit(texts)

        # 向量检索
        self._embedding_index = None
        self._embedding_model = None
        self._vector_enabled = False

        if enable_vector:
            self._init_vector(embedding_model)

    def _init_vector(self, model_name: str) -> None:
        """初始化向量检索组件。失败时优雅降级。"""
        try:
            from sentence_transformers import SentenceTransformer
            print(f"  [HybridRetriever] Loading embedding model: {model_name}...")
            self._embedding_model = SentenceTransformer(model_name)
            self._vector_enabled = True
            print(f"  [HybridRetriever] Vector search enabled")
        except ImportError:
            print("  [HybridRetriever] sentence-transformers not installed, vector search disabled")
        except Exception as e:
            print(f"  [HybridRetriever] Failed to load embedding model: {e}")
            print("  [HybridRetriever] Falling back to BM25 only")

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """
        混合检索，返回融合后的 top-k 结果。

        Args:
            query: 用户查询文本
            top_k: 返回前 K 个结果

        Returns:
            [(entry_index, fused_score), ...] 按融合分数降序排列
        """
        # BM25 检索（始终启用）
        bm25_results = self._bm25_search(query, top_k=top_k * 2)  # 多取一些用于融合

        # 向量检索（如果可用）
        vector_results = []
        if self._vector_enabled and self._embedding_index is not None:
            vector_results = self._vector_search(query, top_k=top_k * 2)

        # RRF 融合
        if not vector_results:
            # 纯 BM25 模式
            return bm25_results[:top_k]

        fused = self._reciprocal_rank_fusion(bm25_results, vector_results)
        return fused[:top_k]

    def _bm25_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """BM25 检索。"""
        return self._bm25.search(query, top_k=top_k)

    def _vector_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """向量语义检索。"""
        if self._embedding_model is None or self._embedding_index is None:
            return []
        query_emb = self._embedding_model.encode(query)
        return self._embedding_index.search(query_emb, top_k=top_k)

    def _reciprocal_rank_fusion(
        self,
        bm25_results: list[tuple[int, float]],
        vector_results: list[tuple[int, float]],
    ) -> list[tuple[int, float]]:
        """
        Reciprocal Rank Fusion (RRF) 融合。

        公式: score(d) = bm25_w * Σ(1/(k + rank_bm25(d))) + vector_w * Σ(1/(k + rank_vector(d)))

        Args:
            bm25_results: BM25 检索结果 [(idx, score), ...]
            vector_results: 向量检索结果 [(idx, score), ...]

        Returns:
            融合后的结果 [(idx, fused_score), ...] 按分数降序排列
        """
        scores = {}

        # BM25 贡献
        for rank, (idx, _) in enumerate(bm25_results):
            scores[idx] = scores.get(idx, 0) + self.bm25_weight / (self.rrf_k + rank + 1)

        # 向量贡献
        for rank, (idx, _) in enumerate(vector_results):
            scores[idx] = scores.get(idx, 0) + self.vector_weight / (self.rrf_k + rank + 1)

        # 按融合分数降序排列
        sorted_items = sorted(scores.items(), key=lambda x: -x[1])
        return [(idx, score) for idx, score in sorted_items]

    @property
    def is_vector_available(self) -> bool:
        """向量检索是否可用。"""
        return self._vector_enabled and self._embedding_index is not None


# ═══════════════════════════════════════════════
#  缓存管理
# ═══════════════════════════════════════════════

def _compute_cache_key(entries: list[dict], model_name: str) -> str:
    """计算缓存 key。"""
    key_str = f"{len(entries)}_{model_name}"
    return hashlib.md5(key_str.encode()).hexdigest()[:12]


def build_or_load_hybrid(
    entries: list[dict],
    embedding_model: str = EMBEDDING_MODEL,
    force_rebuild: bool = False,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> HybridRetriever:
    """
    构建或从缓存加载混合检索器。

    缓存文件:
      - data/bm25_cache.pkl       (现有，不变)
      - data/vector_cache.pkl     (新建，embedding 索引)

    如果任一缓存过期，两者都会重建。
    """
    cache_key = _compute_cache_key(entries, embedding_model)
    bm25_cache_path = BM25_CACHE
    vector_cache_path = str(VECTOR_CACHE)

    # 尝试加载缓存
    if not force_rebuild:
        try:
            if os.path.isfile(vector_cache_path):
                with open(vector_cache_path, 'rb') as f:
                    cached = pickle.load(f)
                if cached.get('cache_key') == cache_key:
                    print("  [HybridRetriever] Loading from cache...")
                    retriever = HybridRetriever(
                        entries=entries,
                        bm25_weight=bm25_weight,
                        vector_weight=vector_weight,
                        enable_vector=True,  # 先允许初始化
                    )
                    # 直接加载索引，跳过模型下载
                    retriever._embedding_index = _EmbeddingIndex.load(vector_cache_path)
                    retriever._vector_enabled = True
                    print(f"  [HybridRetriever] Cache loaded: {retriever._embedding_index.doc_count} docs")
                    return retriever
        except Exception as e:
            print(f"  [HybridRetriever] Cache load failed: {e}, rebuilding...")

    # 构建新的检索器
    print("  [HybridRetriever] Building hybrid retriever...")
    t0 = time.time()

    retriever = HybridRetriever(
        entries=entries,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        embedding_model=embedding_model,
        enable_vector=True,
    )

    # 如果向量检索可用，构建并保存索引
    if retriever._vector_enabled:
        print("  [HybridRetriever] Building embedding index...")
        texts = [e["text"] for e in entries]
        embeddings = retriever._embedding_model.encode(texts, show_progress_bar=True)
        retriever._embedding_index = _EmbeddingIndex(
            embeddings=embeddings,
            model_name=embedding_model,
        )
        # 保存缓存（包含 cache_key）
        cached_data = {
            'cache_key': cache_key,
            'embeddings': retriever._embedding_index.embeddings,
            'model_name': embedding_model,
            'built_at': retriever._embedding_index.built_at,
        }
        with open(vector_cache_path, 'wb') as f:
            pickle.dump(cached_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"  [HybridRetriever] Index saved: {len(entries)} docs, {embeddings.shape[1]}d")

    elapsed = time.time() - t0
    print(f"  [HybridRetriever] Ready ({elapsed:.1f}s)")
    return retriever


def invalidate_vector_cache() -> None:
    """删除向量缓存。KB 更新后调用。"""
    vector_cache_path = str(VECTOR_CACHE)
    if os.path.isfile(vector_cache_path):
        os.remove(vector_cache_path)
        print("  [HybridRetriever] Vector cache invalidated")
