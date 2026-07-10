"""common.display_fields 单元测试

覆盖：
  - _ACTION_KEYWORDS 扩展
  - _generate_title 标题生成
  - _build_highlight_summary 摘要模板
  - _extract_first_sentence 辅助函数
  - generate_display_fields 完整流程
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from common.display_fields import (
    _ACTION_KEYWORDS,
    _generate_title,
    _build_highlight_summary,
    _extract_first_sentence,
    generate_display_fields,
)


# ── 关键词扩展 ────────────────────────────────────────────

class TestActionKeywords:
    def test_activity_keywords_expanded(self):
        """活动分类关键词包含新增词"""
        kw = _ACTION_KEYWORDS["活动"]
        assert "免年费" in kw
        assert "达标" in kw
        assert "新户" in kw
        assert "里程" in kw
        assert "开卡礼" in kw
        assert "刷卡金" in kw
        assert "兑换" in kw
        assert "抽奖" in kw

    def test_original_keywords_preserved(self):
        """原有关键词保留"""
        kw = _ACTION_KEYWORDS["活动"]
        assert "活动" in kw
        assert "优惠" in kw
        assert "满减" in kw


# ── _generate_title ────────────────────────────────────────

class TestGenerateTitle:
    def test_new_card_with_name(self):
        """新卡有卡种名 → 生成"银行发布卡种名" """
        result = _generate_title("招商银行", "新卡", {"卡种": "白金信用卡"})
        assert result == "招商银行发布白金信用卡"

    def test_new_card_no_name(self):
        """新卡无卡种名 → 兜底"""
        result = _generate_title("招商银行", "新卡", {})
        assert result == "招商银行发布新卡"

    def test_activity_with_content(self):
        """活动有内容 → 截断到 30 字"""
        long_content = "满200减50优惠活动，还有更多惊喜等你来" * 2
        result = _generate_title("招商银行", "活动", {"活动内容": long_content})
        assert result.startswith("招商银行活动：")
        assert len(result) <= len("招商银行活动：") + 31  # safe_truncate may add '…'

    def test_activity_no_content(self):
        """活动无内容 → 兜底"""
        result = _generate_title("招商银行", "活动", {})
        assert result == "招商银行推出优惠活动"

    def test_benefit_change_with_action_keyword(self):
        """权益变更标题含动作词 → 保留"""
        result = _generate_title(
            "招商银行", "权益变更",
            {"变更内容": "调整内容"},
            fallback_title="招行权益缩水通知",
        )
        assert "权益缩水" in result

    def test_benefit_change_no_keyword(self):
        """权益变更标题无动作词 → 用变更内容"""
        result = _generate_title(
            "招商银行", "权益变更",
            {"变更内容": "白金卡权益调整"},
            fallback_title="招行通知",
        )
        assert "权益调整" in result

    def test_fallback_category(self):
        """未知分类 → 兜底"""
        result = _generate_title("招商银行", "其他", {})
        assert result == "招商银行其他"


# ── _extract_first_sentence ────────────────────────────────

class TestExtractFirstSentence:
    def test_simple_sentence(self):
        """简单句子 → 原样返回"""
        assert _extract_first_sentence("白金卡权益丰富。") == "白金卡权益丰富"

    def test_skip_activity_marker(self):
        """跳过「活动时间」类标记"""
        text = "活动时间：2025.01.01-2025.12.31白金卡权益丰富"
        result = _extract_first_sentence(text)
        assert "活动时间" not in result
        assert "白金卡" in result

    def test_semicolon_split(self):
        """分号分隔 → 取第一段"""
        result = _extract_first_sentence("权益调整；影响范围广泛")
        assert result == "权益调整"

    def test_empty_input(self):
        assert _extract_first_sentence("") == ""
        assert _extract_first_sentence(None) == ""


# ── _build_highlight_summary ──────────────────────────────

class TestBuildHighlightSummary:
    def test_new_card_with_highlight(self):
        """新卡有卡亮点 → "卡种名：亮点" """
        result = _build_highlight_summary(
            "新卡",
            {"卡种": "白金信用卡", "卡亮点": "免年费+里程双倍"},
            bank="招商银行",
        )
        assert "白金信用卡" in result
        assert "免年费" in result

    def test_new_card_no_highlight(self):
        """新卡无卡亮点 → "银行发布卡种" """
        result = _build_highlight_summary(
            "新卡",
            {"卡种": "白金信用卡"},
            bank="招商银行",
        )
        assert "招商银行" in result
        assert "白金信用卡" in result

    def test_new_card_prefers_clean(self):
        """新卡优先用 structured_clean"""
        result = _build_highlight_summary(
            "新卡",
            {"卡种": "旧卡"},
            structured_clean={"卡种": "新卡", "卡亮点": "亮点"},
        )
        assert "新卡" in result

    def test_activity_uses_content(self):
        """活动优先用活动内容（非 raw_title）"""
        result = _build_highlight_summary(
            "活动",
            {"活动内容": "满200减50"},
            raw_title="招行活动通知",
        )
        assert result == "满200减50"

    def test_activity_includes_scope_time_and_core(self):
        """活动类摘要应带适用卡种/时间/核心内容。"""
        result = _build_highlight_summary(
            "活动",
            {
                "活动内容": "2026年7月7日至2026年9月30日，农行含银联标识信用卡持卡人在京东支付有机会享受满50元随机减至高18元优惠",
                "活动时间": "2026.07.07-2026.09.30",
                "适用人群": "农行含银联标识信用卡持卡人",
            },
            raw_title="农行活动通知",
        )
        assert "持卡人" in result
        assert "2026.07.07-2026.09.30" in result
        assert "满50元随机减至高18元" in result

    def test_activity_fallback_to_title(self):
        """活动内容 = raw_title → 回退到 raw_title"""
        result = _build_highlight_summary(
            "活动",
            {"活动内容": "招行活动通知"},
            raw_title="招行活动通知",
        )
        assert result == "招行活动通知"

    def test_benefit_change_uses_content(self):
        """权益变更优先用变更内容第一句"""
        result = _build_highlight_summary(
            "权益变更",
            {"变更内容": "白金卡机场贵宾厅权益取消。影响高端持卡人"},
        )
        assert "白金卡" in result
        assert "影响高端" not in result  # 只取第一句

    def test_benefit_change_includes_time_scope_and_delta(self):
        """权益变更摘要应带时间、范围和前后变化。"""
        result = _build_highlight_summary(
            "权益变更",
            {
                "消息时间": "2026.07.07",
                "影响范围": "兴业银行部分白金卡持卡人",
                "变更内容": "自2026年9月1日起，部分白金卡次年年费减免规则由积分抵扣调整为刷卡或取现满12笔，或累计分期金额达到5000元。",
            },
            raw_title="兴业权益调整公告",
        )
        assert "2026.07.07" in result
        assert "白金卡持卡人" in result
        assert "由积分抵扣调整为刷卡或取现满12笔" in result

    def test_new_card_includes_fee_info(self):
        """新卡摘要应带核心权益和年费。"""
        result = _build_highlight_summary(
            "新卡",
            {
                "卡种": "经典白金卡",
                "卡亮点": "机场贵宾厅、接送机、里程兑换",
                "详情": "首年免年费，消费达标免次年年费。",
            },
            bank="招商银行",
        )
        assert "经典白金卡" in result
        assert "机场贵宾厅" in result
        assert "首年免年费" in result

    def test_benefit_change_fallback_to_title(self):
        """无变更内容 → 用 raw_title"""
        result = _build_highlight_summary(
            "权益变更",
            {},
            raw_title="招行权益调整通知",
        )
        assert result == "招行权益调整通知"

    def test_benefit_change_navigation_noise_falls_back(self):
        """变更内容像导航文本时回退标题。"""
        result = _build_highlight_summary(
            "权益变更",
            {"变更内容": "银行卡 贵宾 加入收藏 兴业银行信用卡 在线申请信用卡 产品介绍 白金卡系列 标准卡系列 主题卡系列"},
            raw_title="关于兴业银行信用卡积分规则调整的公告",
        )
        assert result == "关于兴业银行信用卡积分规则调整的公告"

    def test_announcement(self):
        """公告 → 消息内容"""
        result = _build_highlight_summary(
            "公告",
            {"消息内容": "系统维护通知"},
        )
        assert result == "系统维护通知"

    def test_other_category(self):
        """其他 → raw_text 或 raw_title"""
        result = _build_highlight_summary(
            "其他",
            {},
            raw_text="这是一篇其他内容",
        )
        assert "其他内容" in result

    def test_marketing_tail_stripped(self):
        """摘要末尾去营销尾巴"""
        result = _build_highlight_summary(
            "新卡",
            {"卡种": "白金卡", "卡亮点": "权益丰富珍藏周边礼等你领"},
        )
        assert "珍藏周边礼等你领" not in result


# ── generate_display_fields ───────────────────────────────

class TestGenerateDisplayFields:
    def test_new_card_title_generation(self):
        """新卡标题含动作词 → 保留原标题"""
        result = generate_display_fields(
            bank="招商银行",
            category="新卡",
            structured={"卡种": "白金卡"},
            raw_title="招行发布全新白金信用卡",
        )
        assert result["title"] == "招行发布全新白金信用卡"
        assert result["title_source"] == "raw"

    def test_new_card_no_action_keyword(self):
        """新卡标题无动作词 → 重新生成"""
        result = generate_display_fields(
            bank="招商银行",
            category="新卡",
            structured={"卡种": "白金卡"},
            raw_title="白金卡推荐",
        )
        assert "发布" in result["title"]
        assert result["title_source"] == "generated"

    def test_no_title_fully_generated(self):
        """无标题 → 完全生成"""
        result = generate_display_fields(
            bank="招商银行",
            category="新卡",
            structured={"卡种": "白金卡"},
            raw_title="",
        )
        assert result["title_source"] == "generated"
        assert "白金卡" in result["title"]

    def test_announcement_preserves_title(self):
        """公告 → 保留原标题"""
        result = generate_display_fields(
            bank="招商银行",
            category="公告",
            structured={"消息内容": "系统维护"},
            raw_title="系统维护通知",
        )
        assert result["title"] == "系统维护通知"

    def test_highlight_summary_populated(self):
        """摘要字段生成"""
        result = generate_display_fields(
            bank="招商银行",
            category="新卡",
            structured={"卡种": "白金卡", "卡亮点": "免年费"},
            raw_title="招行发布白金卡",
        )
        assert result["highlight_summary"]
        assert "白金卡" in result["highlight_summary"]
