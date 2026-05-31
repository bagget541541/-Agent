"""common.llm_review 单元测试

覆盖：
  - _parse_json_response（JSON 解析）
  - llm_review_items（审核流程，mock LLM）
  - apply_suggestions（建议回写）
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from unittest.mock import patch, MagicMock
from common.llm_review import (
    _parse_json_response,
    llm_review_items,
    apply_suggestions,
    VALID_CATEGORIES,
)
from common.schema import CreditCardItem


# ── _parse_json_response ─────────────────────────────────

class TestParseJsonResponse:
    def test_direct_json(self):
        """直接 JSON 字符串"""
        result = _parse_json_response('{"category": "新卡", "bank": "招商银行"}')
        assert result["category"] == "新卡"

    def test_markdown_code_block(self):
        """markdown code block 包裹"""
        text = '```json\n{"category": "活动", "title": "测试"}\n```'
        result = _parse_json_response(text)
        assert result["category"] == "活动"

    def test_markdown_block_no_lang(self):
        """无语言标记的 code block"""
        text = '```\n{"category": "公告"}\n```'
        result = _parse_json_response(text)
        assert result["category"] == "公告"

    def test_invalid_json(self):
        """无效 JSON → 返回空 dict"""
        result = _parse_json_response("这不是 JSON")
        assert result == {}

    def test_empty_string(self):
        result = _parse_json_response("")
        assert result == {}


# ── llm_review_items（mock LLM） ─────────────────────────

class TestLlmReviewItems:
    def _make_flagged_item(self, **overrides):
        return {
            "item_id": "test_001",
            "title": "农业银行活动活动：一、活动时间",
            "bank": "农业银行活动",
            "category": "活动",
            "severity": "high",
            "confidence": {"overall": 0.55},
            "review_flags": ["needs_title_review"],
            **overrides,
        }

    @patch("common.llm_review._call_llm")
    def test_returns_corrections(self, mock_llm):
        """LLM 返回修正 → 正确解析"""
        mock_llm.return_value = json.dumps({
            "category": "活动",
            "bank": "农业银行",
            "title": "农业银行6月消费达标活动",
            "reason": "银行名含噪音，标题需精简",
        }, ensure_ascii=False)

        items = [self._make_flagged_item()]
        results = llm_review_items(items)
        assert len(results) == 1
        s = results[0]["suggestion"]
        assert s["bank"]["correction"] == "农业银行"
        assert s["title"]["correction"] == "农业银行6月消费达标活动"
        assert "category" not in s  # 分类正确，不修正

    @patch("common.llm_review._call_llm")
    def test_no_correction_when_same(self, mock_llm):
        """LLM 返回与当前值相同 → 不记录修正"""
        mock_llm.return_value = json.dumps({
            "category": "活动",
            "bank": "农业银行活动",
            "title": "农业银行活动活动：一、活动时间",
        }, ensure_ascii=False)

        items = [self._make_flagged_item()]
        results = llm_review_items(items)
        assert len(results) == 1
        assert results[0]["suggestion"] == {}

    @patch("common.llm_review._call_llm")
    def test_invalid_category_rejected(self, mock_llm):
        """LLM 返回非法分类 → 忽略"""
        mock_llm.return_value = json.dumps({
            "category": "促销",
            "bank": "农业银行",
        }, ensure_ascii=False)

        items = [self._make_flagged_item()]
        results = llm_review_items(items)
        assert "category" not in results[0]["suggestion"]

    @patch("common.llm_review._call_llm")
    def test_llm_failure_graceful(self, mock_llm):
        """LLM 调用失败 → 跳过"""
        mock_llm.return_value = ""
        items = [self._make_flagged_item()]
        results = llm_review_items(items)
        assert results == []

    @patch("common.llm_review._call_llm")
    def test_max_items_limit(self, mock_llm):
        """max_items 限制审核数量"""
        mock_llm.return_value = '{"bank": "招商银行"}'
        items = [self._make_flagged_item(item_id=f"item_{i}") for i in range(20)]
        results = llm_review_items(items, max_items=3)
        assert mock_llm.call_count == 3

    @patch("common.llm_review._call_llm")
    def test_skips_low_severity(self, mock_llm):
        """low severity 条目跳过"""
        items = [self._make_flagged_item(severity="low")]
        results = llm_review_items(items)
        assert results == []
        mock_llm.assert_not_called()


# ── apply_suggestions ─────────────────────────────────────

class TestApplySuggestions:
    def _make_item(self):
        return CreditCardItem(
            source="wechat", category="其他", bank="未知",
            title="短", structured={},
            confidence={"overall": 0.3, "category": 0.0, "bank": 0.0, "title": 0.4, "structured": 0.0},
            category_candidates=[["其他", 0.2]],
        )

    def test_apply_category_correction(self):
        """修正分类"""
        item = self._make_item()
        item.item_id = "test_001"
        suggestions = [{
            "item_id": "test_001",
            "suggestion": {"category": {"current": "其他", "correction": "公告"}},
        }]
        modified = apply_suggestions([item], suggestions)
        assert modified == 1
        assert item.category == "公告"

    def test_apply_bank_correction(self):
        """修正银行"""
        item = self._make_item()
        item.item_id = "test_001"
        suggestions = [{
            "item_id": "test_001",
            "suggestion": {"bank": {"current": "未知", "correction": "招商银行"}},
        }]
        modified = apply_suggestions([item], suggestions)
        assert modified == 1
        assert item.bank == "招商银行"

    def test_apply_title_correction(self):
        """修正标题"""
        item = self._make_item()
        item.item_id = "test_001"
        suggestions = [{
            "item_id": "test_001",
            "suggestion": {"title": {"current": "短", "correction": "招商银行信用卡公告"}},
        }]
        modified = apply_suggestions([item], suggestions)
        assert modified == 1
        assert item.title == "招商银行信用卡公告"
        assert item.display_title == "招商银行信用卡公告"

    def test_no_match_skipped(self):
        """item_id 不匹配 → 跳过"""
        item = self._make_item()
        item.item_id = "test_001"
        suggestions = [{
            "item_id": "other_id",
            "suggestion": {"bank": {"current": "未知", "correction": "招商银行"}},
        }]
        modified = apply_suggestions([item], suggestions)
        assert modified == 0
        assert item.bank == "未知"

    def test_empty_suggestion_skipped(self):
        """空修正 → 不修改"""
        item = self._make_item()
        item.item_id = "test_001"
        suggestions = [{"item_id": "test_001", "suggestion": {}}]
        modified = apply_suggestions([item], suggestions)
        assert modified == 0


# 导入用于 mock 测试
import json
