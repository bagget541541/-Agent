"""common.normalizer._compute_confidence 单元测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from common.normalizer import _compute_confidence


class TestComputeConfidence:
    """_compute_confidence 各维度打分测试"""

    def test_strong_category_high_score(self):
        """Tier-1 分类器结果（单一候选 0.92）→ 高分类分数"""
        result = _compute_confidence(
            [["新卡", 0.92]], 0.9, "raw", "招行发布新卡",
            {"卡种": "白金卡", "卡亮点": "权益", "适用人群": "持卡人", "来源": "招行", "详情": "详情"},
            "新卡",
        )
        assert result["category"] >= 0.9

    def test_ambiguous_category_reduced(self):
        """前两名接近 → 分类分数被扣减"""
        result = _compute_confidence(
            [["活动", 0.6], ["公告", 0.5]], 0.9, "raw", "银行通知", {}, "活动",
        )
        # gap=0.1 < 0.15, discount = (0.15-0.1)*0.5 = 0.025, score = 0.6-0.025 = 0.575
        assert result["category"] < 0.6

    def test_empty_candidates_zero(self):
        """无候选 → 分类分数 0.0"""
        result = _compute_confidence([], 0.9, "raw", "title", {}, "其他")
        assert result["category"] == 0.0

    def test_single_candidate_no_discount(self):
        """单一候选 → 无扣减"""
        result = _compute_confidence([["活动", 0.8]], 0.9, "raw", "title", {}, "活动")
        assert result["category"] == 0.8

    def test_bank_explicit_canonical(self):
        """显式标准银行名 → bank=1.0"""
        result = _compute_confidence([["新卡", 0.9]], 1.0, "raw", "title", {}, "新卡")
        assert result["bank"] == 1.0

    def test_bank_unknown(self):
        """未知银行 → bank=0.0"""
        result = _compute_confidence([["新卡", 0.9]], 0.0, "raw", "title", {}, "新卡")
        assert result["bank"] == 0.0

    def test_bank_text_match(self):
        """正文匹配 → bank=0.5"""
        result = _compute_confidence([["新卡", 0.9]], 0.5, "raw", "title", {}, "新卡")
        assert result["bank"] == 0.5

    def test_generated_title_low(self):
        """生成标题 → title=0.4"""
        result = _compute_confidence([["新卡", 0.9]], 0.9, "generated", "title", {}, "新卡")
        assert result["title"] == 0.4

    def test_raw_title_short(self):
        """原始标题 < 10 字符 → title=0.7"""
        result = _compute_confidence([["新卡", 0.9]], 0.9, "raw", "短", {}, "新卡")
        assert result["title"] == 0.7

    def test_raw_title_medium(self):
        """原始标题 10-19 字符 → title=0.8"""
        result = _compute_confidence(
            [["新卡", 0.9]], 0.9, "raw", "这是一个十个字符的标题", {}, "新卡",
        )
        assert result["title"] == 0.8

    def test_raw_title_long_bonus(self):
        """原始标题 ≥ 20 字符 → title=0.9"""
        result = _compute_confidence(
            [["新卡", 0.9]], 0.9, "raw",
            "这是一个超过二十个字符的标题文本用于测试", {}, "新卡",
        )
        assert result["title"] == 0.9

    def test_structured_completeness_full(self):
        """所有期望字段已填充 → structured=1.0"""
        structured = {"卡种": "白金卡", "卡亮点": "亮点", "适用人群": "人群", "来源": "来源", "详情": "详情"}
        result = _compute_confidence([["新卡", 0.9]], 0.9, "raw", "title", structured, "新卡")
        assert result["structured"] == 1.0

    def test_structured_completeness_partial(self):
        """部分字段填充 → structured=填充数/期望数"""
        structured = {"卡种": "白金卡", "卡亮点": "", "适用人群": "人群", "来源": "", "详情": "详情"}
        result = _compute_confidence([["新卡", 0.9]], 0.9, "raw", "title", structured, "新卡")
        # 3/5 = 0.6
        assert abs(result["structured"] - 0.6) < 0.01

    def test_structured_empty(self):
        """无 structured → structured=0.0"""
        result = _compute_confidence([["新卡", 0.9]], 0.9, "raw", "title", {}, "新卡")
        assert result["structured"] == 0.0

    def test_overall_is_weighted_average(self):
        """overall 应为各维度加权平均"""
        result = _compute_confidence(
            [["新卡", 0.9]], 0.9, "raw", "长标题文本超过二十字符的标题",
            {"卡种": "x", "详情": "y"}, "新卡",
        )
        expected = (
            0.35 * result["category"]
            + 0.25 * result["bank"]
            + 0.20 * result["structured"]
            + 0.20 * result["title"]
        )
        assert abs(result["overall"] - round(expected, 3)) < 0.01

    def test_all_scores_in_range(self):
        """所有分数必须在 [0.0, 1.0]"""
        result = _compute_confidence(
            [["活动", 0.6], ["公告", 0.5]], 0.7, "generated", "短", {}, "活动",
        )
        for key in ("overall", "category", "bank", "title", "structured"):
            assert 0.0 <= result[key] <= 1.0, f"{key}={result[key]} out of range"


class TestScoreDifferentiation:
    """验证不同输入产生有意义的分数差异"""

    def test_two_profiles_differ(self):
        """高质量 vs 低质量 → overall 差距 > 0.3"""
        good = _compute_confidence(
            [["新卡", 0.92]], 1.0, "raw",
            "招商银行发布全新白金信用卡权益丰富",
            {"卡种": "白金", "卡亮点": "权益", "适用人群": "持卡人", "来源": "招行", "详情": "详情"},
            "新卡",
        )
        bad = _compute_confidence(
            [["其他", 0.2]], 0.0, "generated", "短", {}, "其他",
        )
        assert good["overall"] - bad["overall"] > 0.3

    def test_ambiguity_reduces_score(self):
        """模糊分类 → category 分数低于清晰分类"""
        clear = _compute_confidence([["活动", 0.9]], 0.9, "raw", "活动优惠满减", {}, "活动")
        ambiguous = _compute_confidence(
            [["活动", 0.6], ["公告", 0.5]], 0.9, "raw", "通知公告", {}, "活动",
        )
        assert clear["category"] > ambiguous["category"]

    def test_bank_resolution_quality_matters(self):
        """显式银行 vs 正文匹配 → bank 分数差距 ≥ 0.5"""
        explicit = _compute_confidence([["新卡", 0.9]], 1.0, "raw", "title", {}, "新卡")
        text_match = _compute_confidence([["新卡", 0.9]], 0.5, "raw", "title", {}, "新卡")
        assert explicit["bank"] - text_match["bank"] >= 0.5
