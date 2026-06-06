#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/rag_query.py 单元测试
覆盖: tokenize, BM25, build_prompt
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag_query import tokenize, BM25, build_prompt


# ═══════════════════════════════════════════════
#  tokenize 测试
# ═══════════════════════════════════════════════

class TestTokenize:
    """测试 tokenize 分词函数。"""

    def test_cjk_bigrams(self):
        """中文应生成字符二元组。"""
        tokens = tokenize("信用卡")
        # "信用卡" → bigrams: ["信用", "用卡"] + chars: ["信", "用", "卡"]
        assert "信用" in tokens
        assert "用卡" in tokens
        assert "信" in tokens

    def test_english_words(self):
        """英文单词应被正确提取。"""
        tokens = tokenize("hello world test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_mixed_cjk_english(self):
        """中英混合应同时生成二元组和英文单词。"""
        tokens = tokenize("广发银行信用卡ABC")
        assert "广发" in tokens
        assert "abc" in tokens

    def test_empty_string(self):
        """空字符串应返回空列表。"""
        assert tokenize("") == []

    def test_single_char(self):
        """单个字符只有 char，无 bigram。"""
        tokens = tokenize("信")
        assert "信" in tokens
        # 单字符不应产生 bigram
        assert len([t for t in tokens if len(t) == 2 and ord(t[0]) > 127]) == 0

    def test_lowercase_normalization(self):
        """应统一转为小写。"""
        tokens = tokenize("Hello WORLD")
        assert "hello" in tokens
        assert "world" in tokens

    def test_short_english_filtered(self):
        """单字符英文单词应被过滤。"""
        tokens = tokenize("a b cc")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cc" in tokens

    def test_hyphenated_word(self):
        """连字符连接的单词应整体提取。"""
        tokens = tokenize("anti-virus")
        assert "anti-virus" in tokens


# ═══════════════════════════════════════════════
#  BM25 测试
# ═══════════════════════════════════════════════

SAMPLE_DOCS = [
    "广发银行信用卡评分推荐，值得办理的卡种分析",
    "招商银行权益变更公告，积分兑换规则调整",
    "中信银行活动返现优惠，刷卡满减可参与",
    "小众神卡推荐，免年费信用卡亮点挖掘",
    "信用卡积分兑换里程路径操作指南",
]


class TestBM25:
    """测试 BM25 检索。"""

    def test_fit_and_search(self):
        """fit + search 基本流程。"""
        bm25 = BM25().fit(SAMPLE_DOCS)
        results = bm25.search("广发银行信用卡", top_k=3)

        assert isinstance(results, list)
        assert len(results) <= 3
        # 第一条应该包含"广发银行"
        assert results[0][0] == 0

    def test_search_returns_sorted(self):
        """搜索结果应按分数降序排列。"""
        bm25 = BM25().fit(SAMPLE_DOCS)
        results = bm25.search("信用卡", top_k=5)

        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_no_match(self):
        """查询无匹配时应返回空列表或低分。"""
        bm25 = BM25().fit(SAMPLE_DOCS)
        results = bm25.search("量子物理", top_k=5)
        # 可能返回空或低分
        for _, score in results:
            assert score >= 0

    def test_empty_query(self):
        """空查询应返回空列表。"""
        bm25 = BM25().fit(SAMPLE_DOCS)
        results = bm25.search("", top_k=5)
        assert results == []

    def test_top_k_limit(self):
        """结果数量不应超过 top_k。"""
        bm25 = BM25().fit(SAMPLE_DOCS)
        results = bm25.search("信用卡", top_k=2)
        assert len(results) <= 2

    def test_score_positive(self):
        """匹配文档的分数应为正数。"""
        bm25 = BM25().fit(SAMPLE_DOCS)
        qt = tokenize("信用卡")
        score = bm25.score(qt, 0)  # 第一条包含"信用卡"
        assert score > 0

    def test_score_lower_for_unrelated(self):
        """无关查询的分数应明显低于相关查询。"""
        bm25 = BM25().fit(SAMPLE_DOCS)
        unrelated_score = bm25.score(tokenize("量子物理"), 0)
        related_score = bm25.score(tokenize("广发银行信用卡"), 0)
        assert unrelated_score < related_score

    def test_single_doc(self):
        """单文档也能正常工作。"""
        bm25 = BM25().fit(["只有一个文档"])
        results = bm25.search("文档", top_k=1)
        assert len(results) == 1


# ═══════════════════════════════════════════════
#  build_prompt 测试
# ═══════════════════════════════════════════════

SAMPLE_ENTRIES = [
    {
        "title": "广发银行信用卡评分",
        "date": "2024-01-15",
        "banks": ["广发银行"],
        "categories": ["持卡评判"],
        "text": "广发银行信用卡评分推荐内容" * 50,
    },
    {
        "title": "招商银行权益变更",
        "date": "2024-02-20",
        "banks": ["招商银行"],
        "categories": ["公告点评"],
        "text": "招商银行权益变更公告内容" * 50,
    },
]


class TestBuildPrompt:
    """测试 LLM prompt 构建。"""

    def test_returns_three_elements(self):
        """应返回 (system_msg, user_msg, sources)。"""
        scores = [(0, 0.85), (1, 0.72)]
        system_msg, user_msg, sources = build_prompt("信用卡推荐", SAMPLE_ENTRIES, scores)

        assert isinstance(system_msg, str)
        assert isinstance(user_msg, str)
        assert isinstance(sources, list)

    def test_sources_format(self):
        """sources 应包含 rank, score, title 等字段。"""
        scores = [(0, 0.85)]
        _, _, sources = build_prompt("信用卡推荐", SAMPLE_ENTRIES, scores)

        assert len(sources) == 1
        s = sources[0]
        assert s["rank"] == 1
        assert s["score"] == 0.85
        assert s["title"] == "广发银行信用卡评分"
        assert "广发银行" in s["bank"]

    def test_user_msg_contains_query(self):
        """user_msg 应包含用户查询。"""
        scores = [(0, 0.85)]
        _, user_msg, _ = build_prompt("招行白金卡", SAMPLE_ENTRIES, scores)
        assert "招行白金卡" in user_msg

    def test_context_truncation(self):
        """超长文本应被截断到 MAX_CONTEXT_CHARS。"""
        scores = [(0, 0.85)]
        _, user_msg, _ = build_prompt("测试", SAMPLE_ENTRIES, scores)
        # MAX_CONTEXT_CHARS = 3000，验证不会无限长
        assert len(user_msg) < 10000

    def test_system_msg_contains_rules(self):
        """system_msg 应包含回答规则。"""
        scores = [(0, 0.85)]
        system_msg, _, _ = build_prompt("测试", SAMPLE_ENTRIES, scores)
        assert "信用卡知识助手" in system_msg
        assert "参考资料" in system_msg
