#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合检索模块单元测试
"""

import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# 添加项目路径
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.hybrid_retriever import (
    _EmbeddingIndex,
    HybridRetriever,
    build_or_load_hybrid,
    invalidate_vector_cache,
)


# ═══════════════════════════════════════════════
#  测试数据
# ═══════════════════════════════════════════════

SAMPLE_ENTRIES = [
    {
        "id": "test1_chunk000",
        "article_id": "test1",
        "text": "广发银行信用卡评分推荐，值得办理的卡种分析",
        "title": "广发银行信用卡评分",
        "date": "2024-01-15",
        "banks": ["广发银行"],
        "categories": ["持卡评判"],
    },
    {
        "id": "test2_chunk000",
        "article_id": "test2",
        "text": "招商银行权益变更公告，积分兑换规则调整",
        "title": "招商银行权益变更",
        "date": "2024-02-20",
        "banks": ["招商银行"],
        "categories": ["公告点评"],
    },
    {
        "id": "test3_chunk000",
        "article_id": "test3",
        "text": "中信银行活动返现优惠，刷卡满减可参与",
        "title": "中信银行活动",
        "date": "2024-03-10",
        "banks": ["中信银行"],
        "categories": ["活动"],
    },
    {
        "id": "test4_chunk000",
        "article_id": "test4",
        "text": "小众神卡推荐，免年费信用卡亮点挖掘",
        "title": "小众神卡推荐",
        "date": "2024-04-05",
        "banks": [],
        "categories": ["亮点挖掘"],
    },
    {
        "id": "test5_chunk000",
        "article_id": "test5",
        "text": "信用卡积分兑换里程路径操作指南",
        "title": "积分兑换里程指南",
        "date": "2024-05-01",
        "banks": [],
        "categories": ["知识科普"],
    },
]


# ═══════════════════════════════════════════════
#  _EmbeddingIndex 测试
# ═══════════════════════════════════════════════

class TestEmbeddingIndex:
    """测试向量索引类。"""

    def test_search_returns_sorted_results(self):
        """测试搜索结果按分数降序排列。"""
        # 创建简单的测试向量
        embeddings = np.array([
            [1.0, 0.0, 0.0],  # doc 0
            [0.0, 1.0, 0.0],  # doc 1
            [1.0, 1.0, 0.0],  # doc 2
        ], dtype=np.float32)
        index = _EmbeddingIndex(embeddings, model_name="test")

        # 查询向量
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        results = index.search(query, top_k=3)

        # 验证结果格式
        assert isinstance(results, list)
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

        # 验证排序
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)

        # 验证最相似的是 doc 0 和 doc 2
        top_indices = [r[0] for r in results[:2]]
        assert 0 in top_indices
        assert 2 in top_indices

    def test_search_empty_index(self):
        """测试空索引搜索。"""
        embeddings = np.array([], dtype=np.float32).reshape(0, 3)
        index = _EmbeddingIndex(embeddings, model_name="test")

        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        results = index.search(query, top_k=5)
        assert results == []

    def test_save_load_roundtrip(self):
        """测试保存和加载索引。"""
        embeddings = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ], dtype=np.float32)
        index = _EmbeddingIndex(embeddings, model_name="test-model")

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            temp_path = f.name

        try:
            # 保存
            index.save(temp_path)
            assert os.path.exists(temp_path)

            # 加载
            loaded = _EmbeddingIndex.load(temp_path)
            assert loaded.doc_count == 2
            assert loaded.model_name == "test-model"
            np.testing.assert_array_equal(loaded.embeddings, embeddings)
        finally:
            os.unlink(temp_path)


# ═══════════════════════════════════════════════
#  HybridRetriever 测试
# ═══════════════════════════════════════════════

class TestHybridRetriever:
    """测试混合检索器。"""

    def test_bm25_only_mode(self):
        """测试纯 BM25 模式。"""
        retriever = HybridRetriever(
            entries=SAMPLE_ENTRIES,
            enable_vector=False,
        )

        results = retriever.search("广发银行信用卡", top_k=3)

        # 验证返回格式
        assert isinstance(results, list)
        assert len(results) <= 3
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

        # 验证排序
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_fusion_ordering(self):
        """测试 RRF 融合排序。"""
        retriever = HybridRetriever(
            entries=SAMPLE_ENTRIES,
            enable_vector=False,  # 禁用向量，只用 BM25
        )

        # 模拟 BM25 和向量结果
        bm25_results = [(0, 0.9), (1, 0.7), (2, 0.5)]
        vector_results = [(2, 0.95), (0, 0.8), (3, 0.6)]

        fused = retriever._reciprocal_rank_fusion(bm25_results, vector_results)

        # 验证融合结果
        assert isinstance(fused, list)
        assert len(fused) == 4  # 4 个唯一文档

        # 验证排序
        scores = [r[1] for r in fused]
        assert scores == sorted(scores, reverse=True)

        # doc 0 和 doc 2 应该在顶部（两个列表都有）
        top_indices = [r[0] for r in fused[:2]]
        assert 0 in top_indices
        assert 2 in top_indices

    def test_rrf_all_bm25_top(self):
        """测试当两个列表一致时，顶部结果应该相同。"""
        retriever = HybridRetriever(
            entries=SAMPLE_ENTRIES,
            enable_vector=False,
        )

        # 两个列表完全一致
        bm25_results = [(0, 0.9), (1, 0.7), (2, 0.5)]
        vector_results = [(0, 0.9), (1, 0.7), (2, 0.5)]

        fused = retriever._reciprocal_rank_fusion(bm25_results, vector_results)

        # 顶部应该是 doc 0
        assert fused[0][0] == 0

    def test_search_returns_format(self):
        """测试搜索返回格式。"""
        retriever = HybridRetriever(
            entries=SAMPLE_ENTRIES,
            enable_vector=False,
        )

        results = retriever.search("信用卡", top_k=5)

        # 验证格式
        assert isinstance(results, list)
        for idx, score in results:
            assert isinstance(idx, int)
            assert isinstance(score, float)
            assert 0 <= idx < len(SAMPLE_ENTRIES)

    def test_vector_disabled_fallback(self):
        """测试向量禁用时降级到 BM25。"""
        retriever = HybridRetriever(
            entries=SAMPLE_ENTRIES,
            enable_vector=False,
        )

        assert not retriever.is_vector_available
        results = retriever.search("信用卡", top_k=3)
        assert len(results) > 0


# ═══════════════════════════════════════════════
#  缓存管理测试
# ═══════════════════════════════════════════════

class TestCacheManagement:
    """测试缓存管理函数。"""

    def test_invalidate_vector_cache(self):
        """测试删除向量缓存。"""
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            temp_path = f.name

        try:
            # 创建临时缓存文件
            with open(temp_path, 'wb') as f:
                pickle.dump({"test": "data"}, f)

            # 模拟 VECTOR_CACHE 路径
            with patch('common.hybrid_retriever.VECTOR_CACHE', Path(temp_path)):
                assert os.path.exists(temp_path)
                invalidate_vector_cache()
                assert not os.path.exists(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


# ═══════════════════════════════════════════════
#  Fallback 测试
# ═══════════════════════════════════════════════

class TestFallback:
    """测试降级机制。"""

    def test_missing_sentence_transformers(self):
        """测试 sentence-transformers 不可用时的降级。"""
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            retriever = HybridRetriever(
                entries=SAMPLE_ENTRIES,
                enable_vector=True,
            )
            # 应该降级到 BM25-only
            assert not retriever.is_vector_available
            results = retriever.search("信用卡", top_k=3)
            assert len(results) > 0


# ═══════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════

def _sentence_transformers_available() -> bool:
    """检查 sentence-transformers 是否可用（避免 torch 导入问题）。"""
    try:
        # 只检查包是否存在，不实际导入 torch
        import importlib.util
        spec = importlib.util.find_spec("sentence_transformers")
        return spec is not None
    except Exception:
        return False


# ═══════════════════════════════════════════════
#  集成测试
# ═══════════════════════════════════════════════

# 注意：由于 torch 在 Windows 上可能有访问冲突问题，
# 集成测试需要在有正常 torch 环境的机器上运行。
# 这里跳过集成测试，核心逻辑已在单元测试中验证。

class TestIntegration:
    """集成测试（跳过 torch 问题）。"""

    @pytest.mark.skip(reason="Requires working torch environment (Windows access violation)")
    def test_build_or_load_hybrid_fallback(self):
        """测试 build_or_load_hybrid 降级到 BM25-only。"""
        # 由于 sentence-transformers 可能未安装，测试降级
        retriever = build_or_load_hybrid(
            entries=SAMPLE_ENTRIES,
        )

        # 应该成功创建（可能降级到 BM25-only）
        assert retriever is not None
        results = retriever.search("信用卡", top_k=3)
        assert len(results) > 0
