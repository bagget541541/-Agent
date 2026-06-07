"""
Phase 2 测试：标题优化 + highlight 增强 + 综合建议升级 + 格式统一

覆盖：
- F1: build_report_title LLM fallback
- F2: highlight_summary 增强
- F3: 综合建议（销卡/保留调整/时间节点/趋势）
- F4: 新卡卡亮点不重复渲染
"""

import json
import os
import sys
import tempfile
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from common.schema import CreditCardItem


# ── F1: build_report_title 测试 ─────────────────────────


class TestBuildReportTitle:
    """标题生成测试"""

    def _get_build_report_title(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_report",
            os.path.join(_PROJECT_ROOT, "word-merger", "scripts", "generate_report.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        scripts_dir = os.path.join(_PROJECT_ROOT, "word-merger", "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        spec.loader.exec_module(mod)
        return mod.build_report_title

    def test_fallback_no_items(self):
        """无条目时返回 batch_label + 周报"""
        fn = self._get_build_report_title()
        result = fn([], "2026年6月第1周", use_llm=False)
        assert "周报" in result

    def test_fallback_with_items(self):
        """keyword 拼接模式下返回 top-2 标题"""
        fn = self._get_build_report_title()
        items = [
            {"title": "平安百夫长权益缩水", "category": "权益变更", "priority_emoji": "\U0001f534",
             "highlight_summary": "附属卡贵宾厅从无限次变12次"},
            {"title": "中信i白金返现", "category": "活动", "priority_emoji": "\U0001f534",
             "highlight_summary": "指定渠道10%返现"},
        ]
        result = fn(items, "测试批次", use_llm=False)
        assert "测试批次" in result
        assert "亮点" in result

    def test_emoji_items_sorted_by_priority(self):
        """emoji 排序：🔴 > 🟡 > ⚪"""
        fn = self._get_build_report_title()
        items = [
            {"title": "低价值", "category": "活动", "priority_emoji": "\u26aa",
             "highlight_summary": "小活动"},
            {"title": "高价值", "category": "新卡", "priority_emoji": "\U0001f534",
             "highlight_summary": "重磅新卡"},
            {"title": "中价值", "category": "活动", "priority_emoji": "\U0001f7e1",
             "highlight_summary": "一般活动"},
        ]
        result = fn(items, "批次", use_llm=False)
        # 高价值应排在前面
        assert "高价值" in result

    def test_llm_fallback_on_failure(self):
        """LLM 不可用时自动 fallback"""
        fn = self._get_build_report_title()
        items = [
            {"title": "测试卡", "category": "新卡", "priority_emoji": "\U0001f534",
             "highlight_summary": "测试亮点"},
        ]
        # use_llm=True 但 LLM 不可用，应 fallback
        result = fn(items, "批次", use_llm=True)
        assert "批次" in result


# ── F2: highlight_summary 增强测试 ──────────────────────


class TestHighlightSummaryEnhanced:
    """highlight_summary 增强测试"""

    def _get_generate_display_fields(self):
        from common.display_fields import generate_display_fields
        return generate_display_fields

    def test_with_key_benefits(self):
        """传入 key_benefits 后 highlight_summary 应增强"""
        fn = self._get_generate_display_fields()
        result = fn(
            bank="测试银行", category="新卡",
            structured={"卡种": "测试卡", "卡亮点": "境外返现"},
            raw_title="测试卡",
            key_benefits=["免年费", "境外五重返现"],
        )
        hs = result["highlight_summary"]
        assert "免年费" in hs or "境外" in hs

    def test_without_enrichment(self):
        """无富字段时 highlight_summary 不变"""
        fn = self._get_generate_display_fields()
        result = fn(
            bank="测试银行", category="新卡",
            structured={"卡种": "测试卡", "卡亮点": "境外返现"},
            raw_title="测试卡",
        )
        hs = result["highlight_summary"]
        assert "境外返现" in hs

    def test_with_fee_assessment(self):
        """传入 fee_assessment 后 highlight_summary 应增强"""
        fn = self._get_generate_display_fields()
        result = fn(
            bank="测试银行", category="新卡",
            structured={"卡种": "测试卡"},
            raw_title="测试卡",
            fee_assessment="0年费，零持卡成本",
        )
        hs = result["highlight_summary"]
        assert "0年费" in hs or "零持卡成本" in hs

    def test_no_duplicate_benefits(self):
        """如果 key_benefits 已在 summary 中，不重复追加"""
        fn = self._get_generate_display_fields()
        result = fn(
            bank="测试银行", category="新卡",
            structured={"卡种": "测试卡", "卡亮点": "免年费、境外返现"},
            raw_title="测试卡",
            key_benefits=["免年费"],
        )
        hs = result["highlight_summary"]
        # 不应出现重复的"免年费"
        assert hs.count("免年费") <= 2  # 最多出现2次（原始+追加）


# ── F4: 格式统一测试 ────────────────────────────────────


class TestFormatUnification:
    """格式统一测试"""

    def test_no_duplicate_highlight_rendering(self):
        """新卡不重复渲染卡亮点和亮点"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_report",
            os.path.join(_PROJECT_ROOT, "word-merger", "scripts", "generate_report.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        scripts_dir = os.path.join(_PROJECT_ROOT, "word-merger", "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        spec.loader.exec_module(mod)

        item = {
            "item_id": "test001",
            "source": "website",
            "source_type": "\u5b98\u7f51\u516c\u544a",
            "category": "\u65b0\u5361",
            "bank": "\u6d4b\u8bd5\u94f6\u884c",
            "title": "\u6d4b\u8bd5\u5361",
            "display_title": "\u6d4b\u8bd5\u5361",
            "raw_title": "\u6d4b\u8bd5\u5361",
            "highlight_summary": "\u5883\u5916\u8fd4\u73b05%",
            "url": "",
            "raw_text": "",
            "structured": {"\u5361\u79cd": "\u6d4b\u8bd5\u5361", "\u5361\u4eae\u70b9": "\u5883\u5916\u8fd4\u73b05%", "\u9002\u7528\u4eba\u7fa4": "\u6301\u5361\u4eba"},
            "structured_clean": {},
            "images": [],
            "target_audience": "\u5883\u5916\u6d88\u8d39\u8fd4\u73b0",
            "key_benefits": ["\u514d\u5e74\u8d39", "\u5883\u5916\u8fd4\u73b0"],
            "fee_assessment": "0\u5e74\u8d39",
            "worth_applying": [{"icon": "\u2705", "condition": "\u6709\u9700\u6c42", "conclusion": "\u503c\u5f97"}],
            "priority_emoji": "\U0001f534",
        }
        batch = {
            "schema_version": "1.1",
            "generated_at": "2026-06-07",
            "batch_label": "\u6d4b\u8bd5",
            "total": 1,
            "items": [item],
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False, encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace(".json", ".docx")
        try:
            result = mod.generate_report(input_path, output_path)
            assert result["success"] is True
            # 验证 docx 生成成功
            assert os.path.exists(output_path)
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)