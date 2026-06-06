#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_docs.py 单元测试
覆盖: _title_similarity, categorize_h1, extract_bank_from_content,
      extract_structured_fields, contents_to_items, _find_original_item,
      _fallback_merge, convert_batch_to_merged, _keyword_holistic_suggestion
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merge_docs import (
    _title_similarity,
    categorize_h1,
    extract_bank_from_content,
    extract_structured_fields,
    contents_to_items,
    _find_original_item,
    _fallback_merge,
    _H1_CATEGORY_MAP,
    convert_batch_to_merged,
    _keyword_holistic_suggestion,
)


# ═══════════════════════════════════════════════
#  _title_similarity 测试
# ═══════════════════════════════════════════════

class TestTitleSimilarity:
    """测试标题相似度计算。"""

    def test_identical_titles(self):
        """相同标题应返回 1.0。"""
        assert _title_similarity("测试标题", "测试标题") == 1.0

    def test_similar_titles(self):
        """高度相似标题应返回高分。"""
        score = _title_similarity("招商银行权益变更公告", "招商银行权益调整公告")
        # Jaccard 二元组相似度，部分重叠即可
        assert score > 0.4

    def test_different_titles(self):
        """不同标题应返回低分。"""
        score = _title_similarity("招商银行权益变更", "广发银行信用卡推荐")
        assert score < 0.3

    def test_empty_titles(self):
        """空标题应返回 0.0。"""
        assert _title_similarity("", "测试") == 0.0
        assert _title_similarity("测试", "") == 0.0
        assert _title_similarity("", "") == 0.0

    def test_single_char_titles(self):
        """单字符标题。"""
        score = _title_similarity("A", "B")
        assert score == 0.0

    def test_partial_overlap(self):
        """部分重叠的标题。"""
        score = _title_similarity("信用卡积分兑换", "信用卡权益调整")
        # 共享"信用卡"二元组
        assert 0.0 < score < 1.0


# ═══════════════════════════════════════════════
#  categorize_h1 测试
# ═══════════════════════════════════════════════

class TestCategorizeH1:
    """测试 H1 分类映射。"""

    def test_known_categories(self):
        """已知分类应正确映射。"""
        assert categorize_h1("新卡资讯") == "新卡"
        assert categorize_h1("权益变更") == "权益变更"
        assert categorize_h1("优惠活动") == "活动"
        assert categorize_h1("银行公告") == "公告"
        assert categorize_h1("其他内容") == "其他"

    def test_partial_match(self):
        """包含关键词应匹配。"""
        assert categorize_h1("本周新卡发布汇总") == "新卡"
        assert categorize_h1("重要权益调整通知") == "权益变更"

    def test_unknown_category(self):
        """未知分类应返回其他。"""
        assert categorize_h1("完全无关的标题") == "其他"

    def test_all_map_keys(self):
        """验证 _H1_CATEGORY_MAP 中每个 key 都能映射。"""
        for key, expected_cat in _H1_CATEGORY_MAP.items():
            result = categorize_h1(key)
            assert result == expected_cat, f"'{key}' should map to '{expected_cat}', got '{result}'"


# ═══════════════════════════════════════════════
#  extract_bank_from_content 测试
# ═══════════════════════════════════════════════

class TestExtractBankFromContent:
    """测试银行名提取。"""

    def test_from_h1_title(self):
        """优先从 H1 标题提取。"""
        bank = extract_bank_from_content("招商银行权益变更", ["一些内容"])
        assert "招商" in bank or "招商银行" in bank

    def test_from_content(self):
        """从内容中提取。"""
        bank = extract_bank_from_content("银行公告", ["广发银行信用卡评分"])
        assert "广发" in bank or "广发银行" in bank

    def test_no_bank(self):
        """无银行名时返回空字符串。"""
        bank = extract_bank_from_content("通用标题", ["通用内容"])
        assert bank == ""

    def test_h1_priority(self):
        """H1 优先于 content。"""
        bank = extract_bank_from_content("中信银行公告", ["广发银行活动"])
        assert "中信" in bank


# ═══════════════════════════════════════════════
#  extract_structured_fields 测试
# ═══════════════════════════════════════════════

class TestExtractStructuredFields:
    """测试结构化字段提取。"""

    def test_basic_fields(self):
        """基本字段提取。"""
        lines = ["卡种：白金卡", "亮点：无限贵宾厅", "详情：年费3600元"]
        result = extract_structured_fields(lines)
        assert result.get("卡种") == "白金卡"
        assert result.get("卡亮点") == "无限贵宾厅"  # 别名映射
        assert result.get("详情") == "年费3600元"

    def test_alias_normalization(self):
        """别名标准化。"""
        lines = ["亮点：测试", "生效日期：2024-01-01", "消息内容：通知内容"]
        result = extract_structured_fields(lines)
        assert "卡亮点" in result
        assert "时间" in result
        assert "消息" in result

    def test_empty_lines(self):
        """空行应被跳过。"""
        lines = ["", "  ", "卡种：白金卡", ""]
        result = extract_structured_fields(lines)
        assert len(result) == 1

    def test_no_fields(self):
        """无字段格式的行应被忽略。"""
        lines = ["这是一段普通文本", "没有字段格式"]
        result = extract_structured_fields(lines)
        assert result == {}

    def test_long_value_truncated(self):
        """超过 2000 字符的值应被跳过。"""
        long_value = "x" * 2001
        lines = [f"详情：{long_value}"]
        result = extract_structured_fields(lines)
        assert "详情" not in result

    def test_duplicate_field_first_wins(self):
        """重复字段应保留第一个。"""
        lines = ["卡种：白金卡", "卡种：金卡"]
        result = extract_structured_fields(lines)
        assert result["卡种"] == "白金卡"


# ═══════════════════════════════════════════════
#  contents_to_items 测试
# ═══════════════════════════════════════════════

class TestContentsToItems:
    """测试 H1/H2 结构转标准 items。"""

    def test_basic_conversion(self):
        """基本转换。"""
        contents = [
            {
                "file": "test.docx",
                "h1_sections": [
                    {
                        "title": "新卡资讯",
                        "h2_items": [
                            {
                                "title": "招行新卡发布",
                                "content": ["招商银行推出新卡", "亮点：无限贵宾厅"],
                                "images": [],
                            }
                        ],
                        "content": [],
                    }
                ],
            }
        ]
        items = contents_to_items(contents)
        assert len(items) == 1
        item = items[0]
        assert item["category"] == "新卡"
        assert item["title"] == "招行新卡发布"
        assert "招商" in item["bank"] or "招商银行" in item["bank"]

    def test_skip_short_content(self):
        """过短内容应被跳过。"""
        contents = [
            {
                "file": "test.docx",
                "h1_sections": [
                    {
                        "title": "其他",
                        "h2_items": [
                            {
                                "title": "短条目",
                                "content": ["短"],
                                "images": [],
                            }
                        ],
                        "content": [],
                    }
                ],
            }
        ]
        items = contents_to_items(contents)
        assert len(items) == 0

    def test_skip_ad_content(self):
        """广告内容应被跳过。"""
        contents = [
            {
                "file": "test.docx",
                "h1_sections": [
                    {
                        "title": "其他",
                        "h2_items": [
                            {
                                "title": "广告条目",
                                "content": ["以上内容为广告，与本号无关"],
                                "images": [],
                            }
                        ],
                        "content": [],
                    }
                ],
            }
        ]
        items = contents_to_items(contents)
        assert len(items) == 0

    def test_empty_sections(self):
        """空 H1 sections 应返回空列表。"""
        items = contents_to_items([{"file": "test.docx", "h1_sections": []}])
        assert items == []


# ═══════════════════════════════════════════════
#  _find_original_item 测试
# ═══════════════════════════════════════════════

class TestFindOriginalItem:
    """测试原始条目查找。"""

    def test_exact_title_bank_match(self):
        """精确 title+bank 匹配。"""
        originals = [
            {"title": "招行新卡", "bank": "招商银行", "raw_text": "内容A"},
        ]
        llm_item = {"title": "招行新卡", "bank": "招商银行"}
        result = _find_original_item(llm_item, originals)
        assert result is not None
        assert result["title"] == "招行新卡"

    def test_title_only_match(self):
        """仅 title 匹配。"""
        originals = [
            {"title": "招行新卡", "bank": "招商银行", "raw_text": "内容A"},
        ]
        llm_item = {"title": "招行新卡", "bank": ""}
        result = _find_original_item(llm_item, originals)
        assert result is not None

    def test_similarity_match(self):
        """标题相似度匹配（bank+substring 兜底）。"""
        originals = [
            {"title": "招商银行权益变更公告详情", "bank": "招商银行", "raw_text": "内容A"},
        ]
        # LLM 可能缩短标题 → 用 bank + substring 匹配兜底
        llm_item = {"title": "招商银行权益变更", "bank": "招商银行"}
        result = _find_original_item(llm_item, originals)
        assert result is not None

    def test_no_match(self):
        """无匹配返回 None。"""
        originals = [
            {"title": "招行新卡", "bank": "招商银行", "raw_text": "内容A"},
        ]
        llm_item = {"title": "完全不同的标题", "bank": "其他银行"}
        result = _find_original_item(llm_item, originals)
        assert result is None


# ═══════════════════════════════════════════════
#  _fallback_merge 测试
# ═══════════════════════════════════════════════

class TestFallbackMerge:
    """测试降级合并。"""

    def test_dedup_same_bank_same_title(self):
        """同银行同标题应去重。"""
        items = [
            {"title": "招行公告", "bank": "招商银行", "raw_text": "短内容"},
            {"title": "招行公告", "bank": "招商银行", "raw_text": "更完整的长内容" * 20},
        ]
        result = _fallback_merge(items, ["file1.docx", "file2.docx"])
        assert result["stats"]["total_out"] == 1
        # 应保留更完整的内容
        assert len(result["items"][0]["raw_text"]) > len("短内容")

    def test_keep_different_banks(self):
        """不同银行应保留。"""
        items = [
            {"title": "公告", "bank": "招商银行", "raw_text": "内容A"},
            {"title": "公告", "bank": "广发银行", "raw_text": "内容B"},
        ]
        result = _fallback_merge(items, ["file1.docx"])
        assert result["stats"]["total_out"] == 2

    def test_empty_items(self):
        """空列表应返回空结果。"""
        result = _fallback_merge([], ["file1.docx"])
        assert result["stats"]["total_in"] == 0
        assert result["stats"]["total_out"] == 0

    def test_batch_label(self):
        """应生成正确的 batch_label。"""
        result = _fallback_merge([], ["a.docx", "b.docx"])
        assert "2份合并" in result["batch_label"]


# ═══════════════════════════════════════════════
#  convert_batch_to_merged 测试
# ═══════════════════════════════════════════════

class TestConvertBatchToMerged:
    """测试 batch → merged dict 转换。"""

    def test_basic_conversion(self):
        """基本转换。"""
        batch = {
            "batch_label": "测试批次",
            "items": [
                {"category": "新卡", "title": "招行新卡", "raw_text": "内容", "url": ""},
                {"category": "活动", "title": "农行活动", "raw_text": "内容", "url": ""},
            ],
            "stats": {"sources": ["file1.docx"]},
        }
        merged = convert_batch_to_merged(batch)
        assert merged["title"] == "测试批次"
        assert len(merged["h1_sections"]) == 2  # 新卡、活动

    def test_empty_batch(self):
        """空批次。"""
        merged = convert_batch_to_merged({"items": []})
        assert merged["h1_sections"] == []


# ═══════════════════════════════════════════════
#  _keyword_holistic_suggestion 测试
# ═══════════════════════════════════════════════

class TestKeywordHolisticSuggestion:
    """测试关键词降级建议。"""

    def test_with_keywords(self):
        """包含关键词时应生成建议。"""
        text = "免年费卡推荐，返现活动进行中，部分权益缩水升级"
        result = _keyword_holistic_suggestion(text)
        assert result["overall"] is not None
        assert len(result["overall"]["action_items"]) > 0

    def test_without_keywords(self):
        """无关键词时应返回空建议框架。"""
        text = "这是一段无关的内容，没有信用卡相关关键词"
        result = _keyword_holistic_suggestion(text)
        assert result["overall"] is not None
        assert result["scorer"] == "keyword"

    def test_structure(self):
        """验证返回结构。"""
        result = _keyword_holistic_suggestion("免年费 返现")
        assert "overall" in result
        assert "highlights" in result["overall"]
        assert "action_items" in result["overall"]
        assert "risk_warnings" in result["overall"]
        assert "overall_strategy" in result["overall"]
