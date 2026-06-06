#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
word-merger/scripts/generate_report.py 单元测试
覆盖: clean_xml_text, sanitize_structure, build_report_title
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "word-merger" / "scripts"))

from generate_report import clean_xml_text, sanitize_structure, build_report_title


# ═══════════════════════════════════════════════
#  clean_xml_text 测试
# ═══════════════════════════════════════════════

class TestCleanXmlText:
    """测试 XML 文本清理。"""

    def test_normal_text(self):
        """正常文本不变。"""
        assert clean_xml_text("Hello World") == "Hello World"

    def test_chinese_text(self):
        """中文文本不变。"""
        assert clean_xml_text("信用卡资讯") == "信用卡资讯"

    def test_none_returns_empty(self):
        """None 返回空字符串。"""
        assert clean_xml_text(None) == ""

    def test_bytes_input(self):
        """bytes 输入应转为字符串。"""
        result = clean_xml_text(b"hello")
        assert result == "hello"

    def test_invalid_xml_chars(self):
        """应移除无效 XML 字符。"""
        text = "正常\x00文本\x1f测试"
        result = clean_xml_text(text)
        assert "\x00" not in result
        assert "\x1f" not in result
        assert "正常" in result
        assert "文本" in result

    def test_non_string_input(self):
        """非字符串输入应转为字符串。"""
        assert clean_xml_text(123) == "123"
        assert clean_xml_text(3.14) == "3.14"

    def test_preserves_newlines_tabs(self):
        """应保留换行和制表符。"""
        text = "行1\n行2\t缩进"
        assert clean_xml_text(text) == text


# ═══════════════════════════════════════════════
#  sanitize_structure 测试
# ═══════════════════════════════════════════════

class TestSanitizeStructure:
    """测试结构化数据清理。"""

    def test_dict_cleaning(self):
        """字典值应被清理。"""
        data = {"key": "正常\x00值"}
        result = sanitize_structure(data)
        assert "\x00" not in result["key"]
        assert "正常" in result["key"]

    def test_list_cleaning(self):
        """列表元素应被清理。"""
        data = ["正常\x00文本", "正常文本2"]
        result = sanitize_structure(data)
        assert "\x00" not in result[0]

    def test_nested_structure(self):
        """嵌套结构应递归清理。"""
        data = {
            "level1": {
                "level2": ["值\x001", "值\x002"]
            }
        }
        result = sanitize_structure(data)
        assert "\x00" not in result["level1"]["level2"][0]

    def test_tuple_to_list(self):
        """tuple 应转为 list。"""
        data = (1, 2, 3)
        result = sanitize_structure(data)
        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_non_string_passthrough(self):
        """非字符串值应原样传递。"""
        assert sanitize_structure(42) == 42
        assert sanitize_structure(3.14) == 3.14
        assert sanitize_structure(True) is True


# ═══════════════════════════════════════════════
#  build_report_title 测试
# ═══════════════════════════════════════════════

class TestBuildReportTitle:
    """测试报告标题生成。"""

    def test_with_items(self):
        """有条目时应生成包含亮点的标题。"""
        items = [
            {"category": "新卡", "title": "招行新白金卡发布"},
            {"category": "权益变更", "title": "中信里程权益调整"},
            {"category": "活动", "title": "农行618满减"},
        ]
        title = build_report_title(items)
        assert "亮点" in title
        assert "招行新白金卡发布" in title

    def test_with_batch_label(self):
        """有 batch_label 时应使用它。"""
        items = [{"category": "新卡", "title": "测试卡片"}]
        title = build_report_title(items, batch_label="测试批次")
        assert "测试批次" in title

    def test_empty_items(self):
        """空条目应返回默认标题。"""
        title = build_report_title([])
        assert "周报" in title

    def test_priority_order(self):
        """新卡应优先于活动。"""
        items = [
            {"category": "活动", "title": "活动标题"},
            {"category": "新卡", "title": "新卡标题"},
        ]
        title = build_report_title(items)
        assert "新卡标题" in title

    def test_strips_suffix(self):
        """应去除标题末尾的"公告"后缀。"""
        items = [
            {"category": "公告", "title": "系统升级公告"},
        ]
        title = build_report_title(items)
        assert "系统升级" in title

    def test_dedup_titles(self):
        """重复标题应去重。"""
        items = [
            {"category": "新卡", "title": "同一标题"},
            {"category": "新卡", "title": "同一标题"},
        ]
        title = build_report_title(items)
        # 不应出现两次"同一标题"
        assert title.count("同一标题") == 1


# ═══════════════════════════════════════════════
#  is_ad_image 测试（需要 mock PIL）
# ═══════════════════════════════════════════════

class TestIsAdImage:
    """测试广告图过滤。"""

    def test_file_not_found(self):
        """文件不存在时应返回 False（保守处理）。"""
        from generate_report import is_ad_image
        result = is_ad_image("/nonexistent/image.png")
        assert result is False

    def test_normal_image(self):
        """正常图片应返回 False。"""
        from unittest.mock import MagicMock, patch
        from generate_report import is_ad_image

        # PIL.Image is imported locally inside is_ad_image, mock via sys.modules
        mock_image = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_cm.size = (800, 600)
        mock_image.open.return_value = mock_cm

        with patch("os.path.getsize", return_value=100 * 1024):  # 100KB
            with patch.dict("sys.modules", {"PIL": MagicMock(Image=mock_image), "PIL.Image": mock_image}):
                result = is_ad_image("test.png")
                assert result is False

    def test_wide_banner(self):
        """超宽横幅应被过滤。"""
        from unittest.mock import MagicMock, patch
        from generate_report import is_ad_image

        mock_image = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_cm.size = (1000, 100)  # ratio = 10.0
        mock_image.open.return_value = mock_cm

        with patch("os.path.getsize", return_value=50 * 1024):
            with patch.dict("sys.modules", {"PIL": MagicMock(Image=mock_image), "PIL.Image": mock_image}):
                result = is_ad_image("banner.png")
                assert result is True
