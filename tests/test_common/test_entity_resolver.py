"""common.entity_resolver 单元测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from common.entity_resolver import (
    resolve_bank, resolve_source_name,
    _find_bank_in_text, _BANK_ALIASES, _CANONICAL_BANKS, _SOURCE_TO_BANK,
)


# ── _find_bank_in_text ─────────────────────────────────

class TestFindBankInText:
    def test_canonical_name(self):
        """正文中含标准银行名 → 返回标准名"""
        assert _find_bank_in_text("招商银行信用卡") == "招商银行"

    def test_longest_match_wins(self):
        """多个银行名时取最长匹配（canonical 名长度相同时取第一个命中）"""
        # 同长度 canonical 名：迭代顺序不确定，只验证返回的是合法银行名
        result = _find_bank_in_text("中国银行和招商银行都发了公告")
        assert result in ("中国银行", "招商银行")

    def test_alias_resolution(self):
        """简称 → 标准名"""
        assert _find_bank_in_text("招行发布新卡") == "招商银行"
        assert _find_bank_in_text("工行系统升级") == "工商银行"
        assert _find_bank_in_text("中信权益调整") == "中信银行"

    def test_no_match(self):
        """无银行名 → None"""
        assert _find_bank_in_text("今天天气不错") is None
        assert _find_bank_in_text("") is None
        assert _find_bank_in_text(None) is None


# ── resolve_bank ────────────────────────────────────────

class TestResolveBank:
    def test_explicit_bank_highest_priority(self):
        """explicit_bank 优先级最高"""
        result = resolve_bank(
            title="新卡发布",
            author="某公众号",
            explicit_bank="招商银行",
        )
        assert result["bank"] == "招商银行"

    def test_explicit_alias_resolved(self):
        """explicit_bank 为简称时自动解析"""
        result = resolve_bank(explicit_bank="招行")
        assert result["bank"] == "招商银行"

    def test_author_source_mapping(self):
        """author 通过 SOURCE_TO_BANK 映射"""
        result = resolve_bank(author="招商银行信用卡中心")
        assert result["bank"] == "招商银行"
        assert result["publisher_name"] == "招商银行信用卡中心"

    def test_author_contains_bank_name(self):
        """author 中含银行标准名"""
        result = resolve_bank(author="中信银行信用卡")
        assert result["bank"] == "中信银行"

    def test_title_fallback(self):
        """author 无银行信息时从 title 提取"""
        result = resolve_bank(title="招行经典白金卡发布", author="某自媒体")
        assert result["bank"] == "招商银行"

    def test_text_fallback(self):
        """title 也无银行信息时从 text 提取"""
        result = resolve_bank(
            title="新卡发布",
            author="某自媒体",
            text="浦发银行今日发布全新信用卡",
        )
        assert result["bank"] == "浦发银行"

    def test_no_signal_defaults_unknown(self):
        """所有信号为空 → 未知"""
        result = resolve_bank()
        assert result["bank"] == "未知"
        assert result["source_name"] == "未知"

    def test_unknown_author_filtered(self):
        """'未知公众号' 等占位符不作为 publisher_name"""
        result = resolve_bank(author="未知公众号")
        assert result["publisher_name"] == ""

    def test_evidence_populated(self):
        """evidence 记录识别依据"""
        result = resolve_bank(explicit_bank="招行")
        assert len(result["evidence"]) > 0
        assert "指定参数" in result["evidence"][0]

    def test_source_name_fallback(self):
        """bank=未知 时 source_name 用 author"""
        result = resolve_bank(author="信用卡小助手")
        assert result["source_name"] == "信用卡小助手"


# ── resolve_source_name ────────────────────────────────

class TestResolveSourceName:
    def test_bank_priority(self):
        """bank 优先"""
        assert resolve_source_name("某来源", bank="招商银行") == "招商银行"

    def test_unknown_bank_fallback_to_author(self):
        """bank=未知时用 author"""
        assert resolve_source_name("", bank="未知", author="信用卡助手") == "信用卡助手"

    def test_no_bank_no_author_fallback_to_source(self):
        """都无 → 原始 source"""
        assert resolve_source_name("某网站") == "某网站"

    def test_all_empty(self):
        """全空 → 未知"""
        assert resolve_source_name("") == "未知"


# ── bank_confidence ─────────────────────────────────────

class TestBankConfidence:
    def test_explicit_canonical(self):
        """显式标准银行名 → confidence 1.0"""
        result = resolve_bank(explicit_bank="招商银行")
        assert result["bank_confidence"] == 1.0

    def test_explicit_alias(self):
        """显式简称（解析后为标准名）→ confidence 1.0"""
        result = resolve_bank(explicit_bank="招行")
        assert result["bank_confidence"] == 1.0

    def test_author_source_mapping(self):
        """作者通过 SOURCE_TO_BANK 映射 → confidence 0.9"""
        result = resolve_bank(author="招商银行信用卡中心")
        assert result["bank_confidence"] == 0.9

    def test_author_contains_bank(self):
        """作者名包含银行标准名 → confidence 0.75"""
        result = resolve_bank(author="某包含华夏银行的公众号")
        assert result["bank_confidence"] == 0.75

    def test_title_match(self):
        """仅标题匹配 → confidence 0.7"""
        result = resolve_bank(title="招行经典白金卡发布", author="某自媒体")
        assert result["bank_confidence"] == 0.7

    def test_text_match(self):
        """仅正文匹配 → confidence 0.5"""
        result = resolve_bank(title="新卡发布", author="某自媒体", text="浦发银行今日发布")
        assert result["bank_confidence"] == 0.5

    def test_unknown(self):
        """无信号 → confidence 0.0"""
        result = resolve_bank()
        assert result["bank_confidence"] == 0.0
