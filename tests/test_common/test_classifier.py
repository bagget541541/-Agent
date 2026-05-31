"""common.classifier 单元测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from common.classifier import classify_item, _tier1_strong_rules, _tier2_scoring, _tier3_decide


# ── Tier 1: 强规则 ──────────────────────────────────────

class TestTier1StrongRules:
    def test_new_card_keywords(self):
        """标题含新卡关键词 → 新卡"""
        for kw in ["新卡", "首发", "上市", "发行", "推出", "全新发布"]:
            result = _tier1_strong_rules(f"某银行{kw}一款白金卡")
            assert result is not None, f"关键词 '{kw}' 未命中"
            assert result["category"] == "新卡"

    def test_benefit_change_keywords(self):
        """标题含权益变更关键词 → 权益变更"""
        for kw in ["调整", "变更", "升级", "缩水", "取消", "停用", "下架"]:
            result = _tier1_strong_rules(f"某银行权益{kw}")
            assert result is not None, f"关键词 '{kw}' 未命中"
            assert result["category"] == "权益变更"

    def test_no_match_returns_none(self):
        """标题不含强规则关键词 → None"""
        assert _tier1_strong_rules("今天天气不错") is None
        assert _tier1_strong_rules("") is None
        assert _tier1_strong_rules(None) is None

    def test_high_confidence(self):
        """强规则返回高置信度"""
        result = _tier1_strong_rules("招行发布新卡")
        assert result["category_candidates"][0][1] >= 0.88


# ── Tier 2: 弱规则评分 ──────────────────────────────────

class TestTier2Scoring:
    def test_title_keyword_scoring(self):
        """标题关键词评分"""
        scoring = _tier2_scoring("招行推出优惠活动", "")
        scores = scoring["scores"]
        assert scores["活动"] > 0, "活动类应有正分"
        assert scores["新卡"] > 0, "新卡类'推出'也应得分"

    def test_body_keyword_scoring(self):
        """正文关键词补充评分"""
        title = "招行公告"
        text = "招行信用卡推出全新优惠活动，满减返现福利多多"
        scoring = _tier2_scoring(title, text)
        # 正文中'优惠'、'满减'、'返现'、'福利'等应为活动加更多分
        assert scoring["scores"]["活动"] > scoring["scores"]["公告"]

    def test_empty_input(self):
        """空输入 → 所有类别为 0"""
        scoring = _tier2_scoring("", "")
        assert all(v == 0.0 for v in scoring["scores"].values())

    def test_candidates_sorted_desc(self):
        """候选按分数降序排列"""
        scoring = _tier2_scoring("信用卡活动优惠", "")
        candidates = scoring["candidates"]
        for i in range(len(candidates) - 1):
            assert candidates[i][1] >= candidates[i + 1][1]


# ── Tier 3: 决策 ────────────────────────────────────────

class TestTier3Decide:
    def test_high_score_decisive(self):
        """高分且领先 → 直接采纳"""
        scoring = {
            "candidates": [("活动", 0.9), ("公告", 0.2)],
            "evidence_raw": {"活动": ["标题匹配: 活动"]},
        }
        result = _tier3_decide(scoring)
        assert result["category"] == "活动"

    def test_low_score_defaults_other(self):
        """低分 → 降级为其他"""
        scoring = {
            "candidates": [("活动", 0.2), ("公告", 0.1)],
            "evidence_raw": {},
        }
        result = _tier3_decide(scoring)
        assert result["category"] == "其他"

    def test_close_scores_marked(self):
        """前两名接近 → 标记候选但取最高分"""
        scoring = {
            "candidates": [("活动", 0.6), ("公告", 0.5)],
            "evidence_raw": {"活动": ["test"]},
        }
        result = _tier3_decide(scoring)
        assert result["category"] == "活动"
        assert len(result["category_candidates"]) >= 2

    def test_empty_candidates(self):
        """空候选 → 其他"""
        scoring = {"candidates": [], "evidence_raw": {}}
        result = _tier3_decide(scoring)
        assert result["category"] == "其他"


# ── classify_item 集成 ──────────────────────────────────

class TestClassifyItem:
    def test_strong_rule_overrides(self):
        """强规则优先于弱规则评分"""
        result = classify_item("招行发布全新信用卡", "这是一个活动优惠")
        assert result["category"] == "新卡"

    def test_weak_rule_activity(self):
        """弱规则正确分类活动"""
        result = classify_item("招行618满减活动", "满200减50，名额充足")
        assert result["category"] == "活动"

    def test_weak_rule_announcement(self):
        """弱规则正确分类公告（标题含公告关键词）"""
        result = classify_item("银行公告通知", "公告内容")
        assert result["category"] == "公告"

    def test_empty_input_returns_other(self):
        """空输入 → 其他"""
        result = classify_item("", "")
        assert result["category"] == "其他"

    def test_return_structure(self):
        """返回格式完整"""
        result = classify_item("测试标题", "测试正文")
        assert "category" in result
        assert "category_candidates" in result
        assert "evidence" in result
        assert isinstance(result["category_candidates"], list)
        assert isinstance(result["evidence"], list)

    def test_credit_card_domain_keywords(self):
        """信用卡领域典型标题分类"""
        cases = [
            ("建行权益规则调整通知", "权益变更"),     # 强规则: 调整
            ("银行公告通知", "公告"),                  # 弱规则: 公告
            ("农行信用卡618大促满减优惠", "活动"),     # 弱规则: 优惠
        ]
        for title, expected in cases:
            result = classify_item(title)
            assert result["category"] == expected, \
                f"'{title}' 期望 {expected}，实际 {result['category']}"
