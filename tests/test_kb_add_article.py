#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/rag/kb_add_article.py 单元测试
覆盖: parse_fm, strip_md, extract_banks, classify, is_card_related, smart_chunk
"""

import sys
import tempfile
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.rag.kb_add_article import (
    parse_fm,
    strip_md,
    extract_banks,
    classify,
    is_card_related,
    smart_chunk,
    process_article,
    BANK_MAP,
    CATEGORY_KWS,
)


# ═══════════════════════════════════════════════
#  parse_fm 测试
# ═══════════════════════════════════════════════

class TestParseFm:
    """测试 YAML front matter 解析。"""

    def test_basic_front_matter(self):
        """基本 front matter 解析。"""
        text = '---\ntitle: 测试文章\ndate: 2024-01-15\ntags: ["信用卡", "测评"]\n---\n正文内容'
        meta = parse_fm(text)
        assert meta["title"] == "测试文章"
        assert meta["date"] == "2024-01-15"
        assert "信用卡" in meta["tags"]

    def test_draft_flag(self):
        """草稿标记解析。"""
        text = '---\ntitle: 草稿\ndraft: true\n---\n内容'
        meta = parse_fm(text)
        assert meta["draft"] is True

    def test_no_front_matter(self):
        """无 front matter 应返回默认值。"""
        text = "这是一篇没有front matter的文章"
        meta = parse_fm(text)
        assert meta["title"] == ""
        assert meta["date"] == ""
        assert meta["tags"] == []
        assert meta["draft"] is False

    def test_single_quoted_title(self):
        """单引号标题。"""
        text = "---\ntitle: '单引号标题'\n---\n内容"
        meta = parse_fm(text)
        assert meta["title"] == "单引号标题"

    def test_empty_tags(self):
        """空 tags。"""
        text = '---\ntitle: 无标签\ntags: []\n---\n内容'
        meta = parse_fm(text)
        assert meta["tags"] == []


# ═══════════════════════════════════════════════
#  strip_md 测试
# ═══════════════════════════════════════════════

class TestStripMd:
    """测试 Markdown 清理。"""

    def test_remove_front_matter(self):
        """应移除 front matter。"""
        text = "---\ntitle: 测试\n---\n正文内容"
        result = strip_md(text)
        assert "title:" not in result
        assert "正文内容" in result

    def test_remove_images(self):
        """应移除图片标记。"""
        text = "![图片描述](image.png) 正文"
        result = strip_md(text)
        assert "!" not in result
        assert "正文" in result

    def test_extract_link_text(self):
        """应保留链接文字。"""
        text = "[链接文字](https://example.com) 正文"
        result = strip_md(text)
        assert "链接文字" in result
        assert "https://" not in result

    def test_remove_formatting(self):
        """应移除格式符号。"""
        text = "**粗体** *斜体* `代码` # 标题"
        result = strip_md(text)
        assert "**" not in result
        assert "#" not in result

    def test_collapse_blank_lines(self):
        """应合并多余空行。"""
        text = "段落1\n\n\n\n段落2"
        result = strip_md(text)
        assert "\n\n\n" not in result


# ═══════════════════════════════════════════════
#  extract_banks 测试
# ═══════════════════════════════════════════════

class TestExtractBanks:
    """测试银行名提取。"""

    def test_extract_single_bank(self):
        """提取单个银行。"""
        result = extract_banks("广发银行信用卡评分")
        assert "广发银行" in result

    def test_extract_multiple_banks(self):
        """提取多个银行。"""
        result = extract_banks("广发银行和招商银行的对比分析")
        assert "广发银行" in result
        assert "招商银行" in result

    def test_extract_by_alias(self):
        """通过别名提取银行。"""
        result = extract_banks("工行信用卡活动")
        assert "工商银行" in result

    def test_no_bank(self):
        """无银行名时返回空列表。"""
        result = extract_banks("这是一篇通用文章")
        assert result == []

    def test_all_bank_aliases(self):
        """验证所有别名都能正确映射。"""
        for bname, kws in BANK_MAP:
            for kw in kws:
                result = extract_banks(f"{kw}测试")
                assert bname in result, f"别名 '{kw}' 未映射到 '{bname}'"


# ═══════════════════════════════════════════════
#  classify 测试
# ═══════════════════════════════════════════════

class TestClassify:
    """测试分类函数。"""

    def test_classify_review(self):
        """评分类文章。"""
        cats = classify("信用卡评分", "ROI分析 值不值得办")
        assert "持卡评判" in cats

    def test_classify_announcement(self):
        """公告类文章。"""
        cats = classify("银行公告", "权益变更通知 缩水调整")
        assert "公告点评" in cats

    def test_classify_highlights(self):
        """亮点类文章。"""
        cats = classify("小众神卡", "免年费 返现 亮点")
        assert "亮点挖掘" in cats

    def test_classify_weekly(self):
        """周报类文章。"""
        cats = classify("CW周报", "本周资讯汇总")
        assert "周报资讯" in cats

    def test_classify_guide(self):
        """知识科普类文章。"""
        cats = classify("使用指南", "兑换路径 操作路径")
        assert "知识科普" in cats

    def test_classify_unknown(self):
        """无法分类时返回其他。"""
        cats = classify("随便什么标题", "无关内容")
        assert "其他" in cats


# ═══════════════════════════════════════════════
#  is_card_related 测试
# ═══════════════════════════════════════════════

class TestIsCardRelated:
    """测试信用卡相关性判断。"""

    def test_tag_match(self):
        """标签包含信用卡。"""
        assert is_card_related("标题", "内容", ["信用卡"]) is True

    def test_title_keywords(self):
        """标题包含关键词。"""
        assert is_card_related("信用卡推荐", "内容", []) is True
        assert is_card_related("刷卡优惠", "内容", []) is True
        assert is_card_related("积分权益", "内容", []) is True

    def test_multi_bank_match(self):
        """文中出现多个银行名。"""
        text = "广发银行和招商银行的对比"
        assert is_card_related("标题", text, []) is True

    def test_not_card_related(self):
        """非信用卡相关内容。"""
        assert is_card_related("美食推荐", "好吃的餐厅", []) is False


# ═══════════════════════════════════════════════
#  smart_chunk 测试
# ═══════════════════════════════════════════════

class TestSmartChunk:
    """测试智能分块。"""

    def test_short_text_single_chunk(self):
        """短文本应返回单个块。"""
        text = "## 小标题\n这是一段简短的内容，不超过分块大小。"
        chunks = smart_chunk(text, sz=500, ov=100)
        assert len(chunks) >= 1
        assert chunks[0]["section"] == "小标题"

    def test_long_text_multiple_chunks(self):
        """长文本应分成多个块。"""
        # 创建超过 sz 的文本
        paragraphs = [f"段落{i}：" + "内容" * 50 for i in range(10)]
        text = "## 标题\n" + "\n\n".join(paragraphs)
        chunks = smart_chunk(text, sz=200, ov=50)
        assert len(chunks) > 1

    def test_empty_text(self):
        """空文本应返回空列表。"""
        chunks = smart_chunk("", sz=500, ov=100)
        assert chunks == []

    def test_very_short_text(self):
        """极短文本（<20字符）应返回空列表。"""
        chunks = smart_chunk("短", sz=500, ov=100)
        assert chunks == []

    def test_chunk_has_section(self):
        """每个块应包含 section 字段。"""
        text = "## 标题一\n内容一\n\n## 标题二\n内容二"
        chunks = smart_chunk(text, sz=500, ov=100)
        for ch in chunks:
            assert "section" in ch
            assert "text" in ch

    def test_no_heading_fallback(self):
        """无标题的长文本应使用空 section。"""
        text = "这是一段很长的内容" * 100
        chunks = smart_chunk(text, sz=200, ov=50)
        assert len(chunks) >= 1
        # 没有 heading 时 section 应为空
        assert any(ch["section"] == "" for ch in chunks)


# ═══════════════════════════════════════════════
#  process_article 测试（集成）
# ═══════════════════════════════════════════════

class TestProcessArticle:
    """测试文章处理（需要临时文件）。"""

    def _write_md(self, content):
        """写入临时 .md 文件。"""
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return f.name

    def test_draft_skipped(self):
        """草稿文章应被跳过。"""
        path = self._write_md('---\ntitle: 草稿\ndraft: true\n---\n' + '内容' * 200)
        try:
            aid, entries = process_article(path)
            assert aid is None
            assert entries is None
        finally:
            os.unlink(path)

    def test_short_article_skipped(self):
        """过短文章应被跳过。"""
        path = self._write_md('---\ntitle: 短文\n---\n短')
        try:
            aid, entries = process_article(path)
            assert aid is None
        finally:
            os.unlink(path)

    def test_normal_article(self):
        """正常文章应被正确处理。"""
        content = '---\ntitle: 测试文章\ndate: 2024-01-15\ntags: ["信用卡"]\n---\n' + '广发银行信用卡评分分析 ' * 30
        path = self._write_md(content)
        try:
            aid, entries = process_article(path)
            assert aid is not None
            assert isinstance(entries, list)
            assert len(entries) > 0
            # 验证 entry 结构
            e = entries[0]
            assert "id" in e
            assert "text" in e
            assert "title" in e
            assert "banks" in e
            assert "categories" in e
        finally:
            os.unlink(path)
