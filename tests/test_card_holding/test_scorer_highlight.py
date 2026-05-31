"""P0: scorer.py — 高亮判定 + 关键词评分逻辑测试"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'card-holding-suggestion'))

import pytest
from scripts.scorer import (
    _calc_highlight, _generate_notes, ROI_Score, ROI_Dimension, DIMENSION_TEMPLATES,
    score_with_keywords, _parse_llm_response,
)


class TestCalcHighlight:
    """重点条目判定逻辑"""

    def test_new_card_high_score(self):
        """新卡高分 → 强烈推荐"""
        hl, reason = _calc_highlight("新卡", 9.0, "高")
        assert hl is True
        assert "强烈推荐" in reason

    def test_new_card_low_score(self):
        """新卡低分 → 建议避坑"""
        hl, reason = _calc_highlight("新卡", 2.5, "低")
        assert hl is True
        assert "避坑" in reason

    def test_new_card_mid_score(self):
        """新卡中等分 → 不重点"""
        hl, reason = _calc_highlight("新卡", 6.0, "中")
        assert hl is False
        assert reason == ""

    def test_change_low_score(self):
        """权益变更低分 → 严重缩水"""
        hl, reason = _calc_highlight("权益变更", 3.0, "低")
        assert hl is True
        assert "缩水" in reason

    def test_change_high_score(self):
        """权益变更高分 → 重大利好"""
        hl, reason = _calc_highlight("权益变更", 8.5, "高")
        assert hl is True
        assert "利好" in reason

    def test_change_mid_score(self):
        """权益变更中等分 → 不重点"""
        hl, reason = _calc_highlight("权益变更", 6.0, "中")
        assert hl is False

    def test_activity_high_score(self):
        """活动高分 → 高价值"""
        hl, reason = _calc_highlight("活动", 9.0, "高")
        assert hl is True
        assert "参加" in reason

    def test_activity_low_score(self):
        """活动低分 → 建议放弃"""
        hl, reason = _calc_highlight("活动", 2.0, "低")
        assert hl is True
        assert "放弃" in reason

    def test_activity_mid_score(self):
        """活动中等分 → 不重点"""
        hl, reason = _calc_highlight("活动", 5.0, "中")
        assert hl is False

    def test_announcement_extreme_high(self):
        """公告高分 → 重要公告"""
        hl, reason = _calc_highlight("公告", 9.5, "高")
        assert hl is True
        assert "重要公告" in reason

    def test_announcement_mid(self):
        """公告中等分 → 不重点"""
        hl, reason = _calc_highlight("公告", 5.0, "中")
        assert hl is False

    def test_unknown_category(self):
        """未知分类 → 不重点"""
        hl, reason = _calc_highlight("未知分类", 5.0, "中")
        assert hl is False


class TestGenerateNotes:
    """注意事项生成逻辑"""

    def test_new_card_high_score(self):
        """新卡高分 → 年费减免提示"""
        notes = _generate_notes("新卡", 8.0, "免年费消费返现")
        assert "年费减免" in notes

    def test_new_card_high_score_no_fee(self):
        """新卡高分但有刚性年费 → 年费警示"""
        notes = _generate_notes("新卡", 8.0, "刚性年费白金卡")
        assert "刚性年费" in notes

    def test_new_card_low_score(self):
        """新卡低分 → 建议谨慎"""
        notes = _generate_notes("新卡", 2.0, "权益鸡肋限制多")
        assert "谨慎" in notes or "鸡肋" in notes

    def test_new_card_mid_score(self):
        """新卡中等分 → 视需求评估"""
        notes = _generate_notes("新卡", 5.0, "普通卡基本权益")
        assert "需求" in notes

    def test_change_high_score(self):
        """权益变更高分 → 利好"""
        notes = _generate_notes("权益变更", 8.0, "比例提升额度增加")
        assert "利好" in notes

    def test_change_low_score(self):
        """权益变更低分 → 缩水"""
        notes = _generate_notes("权益变更", 2.0, "缩水严重比例下调")
        assert "缩水" in notes

    def test_change_mid_score(self):
        """权益变更中等分 → 影响有限"""
        notes = _generate_notes("权益变更", 5.0, "微小调整")
        assert "影响有限" in notes

    def test_activity_high_score(self):
        """活动高分 → 注意规则"""
        notes = _generate_notes("活动", 8.0, "满减返现多倍积分")
        assert "注意" in notes

    def test_activity_limited_quota(self):
        """活动有名额限制 → 尽早参与"""
        notes = _generate_notes("活动", 8.0, "名额有限先到先得")
        assert "名额限制" in notes

    def test_activity_low_score(self):
        """活动低分 → 放弃"""
        notes = _generate_notes("活动", 2.0, "小毛套路多")
        assert "放弃" in notes or "套路" in notes

    def test_activity_mid_score(self):
        """活动中等分 → 视习惯"""
        notes = _generate_notes("活动", 5.0, "普通消费活动")
        assert "消费习惯" in notes

    def test_announcement_high(self):
        """公告高分 → 重大公告"""
        notes = _generate_notes("公告", 9.0, "费率调整重大变更")
        assert "重大" in notes

    def test_announcement_mid(self):
        """公告中等分 → 例行"""
        notes = _generate_notes("公告", 5.0, "系统升级通知")
        assert "例行" in notes or "可选择性" in notes

    def test_unknown_category(self):
        """未知分类 → 空字符串"""
        notes = _generate_notes("未知分类", 5.0, "test")
        assert notes == ""


class TestROIScore:
    """ROI_Score 数据结构与序列化"""

    def test_default_values(self):
        """默认值"""
        s = ROI_Score()
        assert s.overall_score == 5.0
        assert s.overall_roi == ""
        assert s.recommendation == ""
        assert s.is_highlight is False
        assert s.highlight_reason == ""

    def test_to_dict_contains_new_fields(self):
        """to_dict 包含 is_highlight 和 highlight_reason"""
        s = ROI_Score(overall_score=8.0, overall_roi="高",
                      is_highlight=True, highlight_reason="强烈推荐")
        d = s.to_dict()
        assert d["is_highlight"] is True
        assert d["highlight_reason"] == "强烈推荐"

    def test_to_dict_new_fields_notes_activity(self):
        """to_dict 包含 notes 和 activity_value 新字段"""
        s = ROI_Score(overall_score=7.0, overall_roi="高",
                      is_highlight=True, highlight_reason="强烈推荐",
                      notes="关注年费减免条件", activity_value="高")
        d = s.to_dict()
        assert d["notes"] == "关注年费减免条件"
        assert d["activity_value"] == "高"

    def test_to_dict_roundtrip(self):
        """asdict 往返"""
        s = ROI_Score(overall_score=7.5, overall_roi="高",
                      recommendation="值得申请",
                      dimensions=[{"name": "年费", "weight": 0.5, "score": 8, "reason": "免年费"}],
                      is_highlight=True, highlight_reason="推荐")
        d = s.to_dict()
        assert d["overall_score"] == 7.5
        assert d["overall_roi"] == "高"
        assert len(d["dimensions"]) == 1
        assert d["is_highlight"] is True


class TestKeyWordScoring:
    """关键词评分引擎"""

    def test_new_card_scorer_highlights_high_score(self):
        """新卡高分触发高亮"""
        item = {
            "category": "新卡",
            "bank": "招商银行",
            "title": "招行经典白金卡",
            "raw_text": "免年费消费返现积分贵宾厅",
            "structured": {"卡种": "经典白金卡", "卡亮点": "返现贵宾厅"},
        }
        dims = DIMENSION_TEMPLATES["新卡"]()
        result = score_with_keywords(item, dims)
        assert result.is_highlight is True  # score >= 7 或关键词匹配
        assert result.highlight_reason in ("强烈推荐", "建议避坑")

    def test_new_card_scorer_low_score_highlight(self):
        """新卡低分触发高亮"""
        item = {
            "category": "新卡",
            "bank": "某银行",
            "title": "刚性年费伪白金",
            "raw_text": "刚性年费缩水限制停发",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["新卡"]()
        result = score_with_keywords(item, dims)
        assert result.is_highlight is True
        assert result.highlight_reason == "建议避坑"

    def test_activity_high_value(self):
        """高价值活动 → 高亮"""
        item = {
            "category": "活动",
            "bank": "农业银行",
            "title": "618满200减50",
            "raw_text": "返现满减立减多倍积分名额充足",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["活动"]()
        result = score_with_keywords(item, dims)
        assert result.is_highlight is True

    def test_activity_medium_not_highlighted(self):
        """中等价值活动 → 不高亮"""
        item = {
            "category": "活动",
            "bank": "某银行",
            "title": "日常消费活动",
            "raw_text": "普通消费积分活动",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["活动"]()
        result = score_with_keywords(item, dims)
        # 没有返现/满减等强关键词，分数应在中等区间
        assert result.is_highlight is False

    def test_change_benefit_downgrade(self):
        """权益变更缩水 → 高亮（建议避坑）"""
        item = {
            "category": "权益变更",
            "bank": "中信银行",
            "title": "里程兑换比例下调",
            "raw_text": "缩水严重比例下调限制停发",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["权益变更"]()
        result = score_with_keywords(item, dims)
        assert result.is_highlight is True
        assert "严重缩水" in result.highlight_reason

    def test_change_benefit_upgrade(self):
        """权益变更利好 → 高亮"""
        item = {
            "category": "权益变更",
            "bank": "招商银行",
            "title": "经典白权益升级",
            "raw_text": "升级增加贵宾厅次数里程比例提升",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["权益变更"]()
        result = score_with_keywords(item, dims)
        assert result.is_highlight is True
        assert "利好" in result.highlight_reason

    def test_change_neutral_not_highlighted(self):
        """权益变更中性 → 不高亮"""
        item = {
            "category": "权益变更",
            "bank": "某银行",
            "title": "微小调整",
            "raw_text": "赠送积分活动微调影响不大",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["权益变更"]()
        result = score_with_keywords(item, dims)
        assert result.is_highlight is False

    def test_announcement_keyword_engine_limitation(self):
        """公告关键词评分无法达到高亮阈值（需要 LLM）- 确认不高亮是预期行为"""
        item = {
            "category": "公告",
            "bank": "建设银行",
            "title": "费率调整通知",
            "raw_text": "重大调整费率变更影响所有持卡人",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["公告"]()
        result = score_with_keywords(item, dims)
        # 关键词引擎没有足够信号拉升分数到 >= 9，因此不高亮
        # 这是预期行为 —— 重要公告需 LLM 评分才能识别
        assert result.is_highlight is False
        assert result.scorer_used == "keyword"

    def test_announcement_routine_not_highlighted(self):
        """例行公告 → 不高亮"""
        item = {
            "category": "公告",
            "bank": "建设银行",
            "title": "系统升级通知",
            "raw_text": "系统升级暂停服务通知",
            "structured": {},
        }
        dims = DIMENSION_TEMPLATES["公告"]()
        result = score_with_keywords(item, dims)
        assert result.is_highlight is False


class TestLLMParse:
    """LLM 响应解析"""

    def test_parse_json_block(self):
        """解析 ```json ``` 块"""
        text = '```json\n{"overall_score": 8.5, "overall_roi": "高", "recommendation": "建议申请", "summary": "值得办", "dimensions": []}\n```'
        result = _parse_llm_response(text)
        assert result.overall_score == 8.5
        assert result.overall_roi == "高"
        assert result.recommendation == "建议申请"

    def test_parse_plain_json(self):
        """解析纯 JSON 文本"""
        text = '{"overall_score": 3.0, "overall_roi": "低", "recommendation": "不建议", "summary": "避开"}'
        result = _parse_llm_response(text)
        assert result.overall_score == 3.0
        assert result.overall_roi == "低"

    def test_parse_malformed_fallback(self):
        """解析失败 → 返回默认值"""
        text = "这根本不是 JSON"
        result = _parse_llm_response(text)
        assert result.overall_score == 5.0
        assert "解析失败" in result.summary or "解析" in result.recommendation
