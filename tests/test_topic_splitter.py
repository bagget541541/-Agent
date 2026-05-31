"""
多主题公众号文章拆分模块 — 单元测试

覆盖：
1. detect_multi_topic — 单主题/多主题判定
2. split_article_into_topics — 主题切分算法
3. merge_small_topics — 过拆修正
4. 单主题回退闭环
5. 低置信度回退
"""

import json
import sys
import os

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.topic_splitter import (
    detect_multi_topic,
    split_article_into_topics,
    merge_small_topics,
    _has_numbered_prefix,
    _detect_template_group,
    _extract_named_entities,
    _find_bank_hints,
    _is_topic_start,
)
from common.article_envelope import build_article_envelope, build_topic_candidate
from common.normalizer import normalize_topic
from common.schema import CreditCardItem


# ═══════════════════════════════════════════════════════════
# 辅助：构建测试用的 content_blocks
# ═══════════════════════════════════════════════════════════


def _make_block(text: str, btype: str = "article_text", **kwargs) -> dict:
    block = {"type": btype, "text": text}
    block.update(kwargs)
    return block


def _make_heading_block(text: str, **kwargs) -> dict:
    """构建标题型 block（强制 is_heading_like=True）。"""
    block = {"type": "article_text", "text": text, "is_heading_like": True}
    block.update(kwargs)
    return block


# ═══════════════════════════════════════════════════════════
# 1. _has_numbered_prefix
# ═══════════════════════════════════════════════════════════

class TestNumberedPrefix:
    def test_chinese_numbered(self):
        assert _has_numbered_prefix("一、618积分五倍赠")
        assert _has_numbered_prefix("二. 新客返现")
        assert _has_numbered_prefix("三、")
        assert not _has_numbered_prefix("积分活动介绍")

    def test_digit_numbered(self):
        assert _has_numbered_prefix("1. 活动内容")
        assert _has_numbered_prefix("2、活动对象")
        assert _has_numbered_prefix("3. 活动时间")
        assert not _has_numbered_prefix("10倍积分")

    def test_activity_numbered(self):
        assert _has_numbered_prefix("活动一：618积分")
        assert _has_numbered_prefix("活动二、新客返现")
        assert _has_numbered_prefix("卡种一：Visa世界杯版")
        assert not _has_numbered_prefix("活动介绍")


# ═══════════════════════════════════════════════════════════
# 2. _detect_template_group
# ═══════════════════════════════════════════════════════════

class TestTemplateGroup:
    def test_activity_template(self):
        text = "活动时间：2025年1月1日\n活动对象：持卡人\n活动内容：消费返现"
        result = _detect_template_group(text)
        assert result is not None
        assert "活动时间" in result
        assert "活动对象" in result

    def test_card_template(self):
        text = "卡种：Visa世界杯版\n权益：双倍积分\n年费：免年费"
        result = _detect_template_group(text)
        assert result is not None

    def test_no_template(self):
        text = "这是一段普通正文"
        assert _detect_template_group(text) is None


# ═══════════════════════════════════════════════════════════
# 3. detect_multi_topic — 单主题文章
# ═══════════════════════════════════════════════════════════

SINGLE_TOPIC_BLOCKS = [
    _make_block("欢迎关注农业银行信用卡"),
    _make_block("农业银行推出全新 Visa 世界杯主题信用卡"),
    _make_block("卡种：Visa世界杯版"),
    _make_block("权益：消费双倍积分，海外消费免货币转换费"),
    _make_block("年费：首年免年费，消费5笔免次年年费"),
    _make_block("适用人群：足球爱好者、境外消费用户"),
    _make_block("立即扫码申卡"),
]

SINGLE_ENVELOPE = build_article_envelope(
    url="https://mp.weixin.qq.com/s/test",
    publisher_name="农行信用卡",
    publish_time="2026-01-15",
    raw_title="农行Visa世界杯信用卡首发",
    content_blocks=SINGLE_TOPIC_BLOCKS,
)


class TestDetectSingleTopic:
    def test_single_topic_no_strong_signal(self):
        result = detect_multi_topic(SINGLE_ENVELOPE)
        assert result["is_multi_topic_candidate"] is False
        assert result["split_confidence"] == 0.0

    def test_single_topic_split_fallback(self):
        topics = split_article_into_topics(SINGLE_ENVELOPE)
        assert len(topics) == 1
        assert topics[0]["split_signals"][0].startswith("single_topic_fallback")
        assert topics[0]["split_confidence"] == 1.0
        assert topics[0]["headline"] == "农行Visa世界杯信用卡首发"


# ═══════════════════════════════════════════════════════════
# 4. detect_multi_topic — 多主题文章（编号标题）
# ═══════════════════════════════════════════════════════════

MULTI_TOPIC_BLOCKS = [
    _make_heading_block("一、618积分五倍赠"),
    _make_block("活动时间：2026年6月1日-6月30日"),
    _make_block("活动对象：农行信用卡持卡人"),
    _make_block("活动内容：使用农行信用卡消费享5倍积分"),
    _make_block("立即扫码参与"),
    _make_heading_block("二、新客返现100元"),
    _make_block("活动时间：即日起至2026年12月31日"),
    _make_block("活动对象：首次申请农行信用卡的新客户"),
    _make_block("活动内容：核卡后30天内消费满3笔可获100元返现"),
    _make_block("立即扫码申卡"),
    _make_heading_block("三、境外消费返现8%"),
    _make_block("活动时间：2026年全年"),
    _make_block("活动对象：农行Visa信用卡持卡人"),
    _make_block("活动内容：境外消费享8%返现，每月上限200元"),
]

MULTI_ENVELOPE = build_article_envelope(
    url="https://mp.weixin.qq.com/s/test2",
    publisher_name="农行信用卡",
    publish_time="2026-05-31",
    raw_title="618福利合集",
    content_blocks=MULTI_TOPIC_BLOCKS,
)

TEMPLATE_MULTI_BLOCKS = [
    _make_block("活动一：积分五倍赠"),
    _make_block("活动时间：6月1日-6月30日"),
    _make_block("活动对象：全体持卡人"),
    _make_block("活动内容：积分5倍"),
    _make_block("活动二：新客返现"),
    _make_block("活动时间：即日起"),
    _make_block("活动对象：新客户"),
    _make_block("活动内容：消费满3笔返100元"),
]

TEMPLATE_MULTI_ENVELOPE = build_article_envelope(
    url="https://mp.weixin.qq.com/s/test3",
    publisher_name="农行信用卡",
    raw_title="618活动合集",
    content_blocks=TEMPLATE_MULTI_BLOCKS,
)


class TestDetectMultiTopic:
    def test_numbered_headings_detected(self):
        result = detect_multi_topic(MULTI_ENVELOPE)
        assert result["is_multi_topic_candidate"] is True
        assert "multiple_numbered_headings" in result["signals"]
        assert result["split_confidence"] >= 0.7

    def test_split_produces_three_topics(self):
        topics = split_article_into_topics(MULTI_ENVELOPE)
        assert len(topics) >= 2  # 至少拆出2个
        headlines = [t["headline"] for t in topics]
        assert any("618积分" in h or "积分五倍" in h for h in headlines)
        assert any("新客返现" in h or "返现100" in h for h in headlines)
        assert any("境外消费" in h or "返现8%" in h for h in headlines)

    def test_each_topic_has_blocks(self):
        topics = split_article_into_topics(MULTI_ENVELOPE)
        for t in topics:
            assert len(t["blocks"]) > 0
            assert t["start_block"] <= t["end_block"]

    def test_template_groups_detected(self):
        result = detect_multi_topic(TEMPLATE_MULTI_ENVELOPE)
        assert result["is_multi_topic_candidate"] is True
        assert "repeated_activity_templates" in result["signals"]

    def test_template_split(self):
        topics = split_article_into_topics(TEMPLATE_MULTI_ENVELOPE)
        assert len(topics) >= 2


# ═══════════════════════════════════════════════════════════
# 5. merge_small_topics
# ═══════════════════════════════════════════════════════════

class TestMergeSmallTopics:
    def test_merge_adjacent_short_topics(self):
        topics = [
            {"topic_id": "t1", "headline": "活动一", "blocks": [
                _make_block("heading"), _make_block("content"),
                _make_block("more content")
            ], "topic_type_hint": "活动", "source_article_title": "合集"},
            {"topic_id": "t2", "headline": "合集", "blocks": [
                _make_block("short")
            ], "topic_type_hint": "活动", "source_article_title": "合集"},
        ]
        merged = merge_small_topics(topics)
        assert len(merged) == 1

    def test_no_merge_when_both_large(self):
        topics = [
            {"topic_id": "t1", "headline": "活动一", "blocks": [
                _make_block("a") for _ in range(5)
            ], "topic_type_hint": "活动", "source_article_title": "合集"},
            {"topic_id": "t2", "headline": "活动二", "blocks": [
                _make_block("b") for _ in range(5)
            ], "topic_type_hint": "活动", "source_article_title": "合集"},
        ]
        merged = merge_small_topics(topics)
        assert len(merged) == 2

    def test_empty_input(self):
        assert merge_small_topics([]) == []
        assert len(merge_small_topics([{"topic_id": "t1"}])) == 1


# ═══════════════════════════════════════════════════════════
# 6. normalize_topic — 桥接函数
# ═══════════════════════════════════════════════════════════

class TestNormalizeTopic:
    def test_topic_to_item(self):
        topic = {
            "topic_id": "wx_abc_t1",
            "article_id": "wx_abc",
            "source_article_title": "618福利合集",
            "url": "https://mp.weixin.qq.com/s/test",
            "publisher_name": "农行信用卡",
            "publish_time": "2026-05-31",
            "start_block": 0,
            "end_block": 3,
            "headline": "618积分五倍赠",
            "blocks": [
                _make_block("618积分五倍赠活动"),
                _make_block("活动时间：6月1日-6月30日"),
                _make_block("活动内容：消费享5倍积分"),
            ],
            "topic_type_hint": "活动",
            "split_confidence": 0.85,
            "split_signals": ["heading_marker"],
            "images": [],
        }
        item = normalize_topic(topic)
        assert isinstance(item, CreditCardItem)
        assert item.is_multi_topic_split is True
        assert item.article_id == "wx_abc"
        assert item.topic_id == "wx_abc_t1"
        assert item.source_article_title == "618福利合集"
        assert item.topic_split_confidence == 0.85
        assert "heading_marker" in (item.topic_split_signals or [])

    def test_low_confidence_triggers_review(self):
        topic = {
            "topic_id": "wx_low_t1",
            "article_id": "wx_low",
            "source_article_title": "测试文章",
            "headline": "测试主题",
            "blocks": [_make_block("测试内容")],
            "split_confidence": 0.3,
            "split_signals": ["weak_signal"],
            "images": [],
        }
        item = normalize_topic(topic)
        assert item.is_multi_topic_split is True
        assert "needs_topic_split_review" in (item.review_flags or [])

    def test_empty_topic_safe(self):
        item = normalize_topic({})
        assert isinstance(item, CreditCardItem)
        assert not item.title == ""


# ═══════════════════════════════════════════════════════════
# 7. Edge cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_blocks_list(self):
        envelope = build_article_envelope(
            url="https://mp.weixin.qq.com/s/empty",
            raw_title="无内容文章",
            content_blocks=[],
        )
        result = detect_multi_topic(envelope)
        assert result["is_multi_topic_candidate"] is False
        topics = split_article_into_topics(envelope)
        assert len(topics) == 1

    def test_single_heading_not_multi(self):
        blocks = [
            _make_heading_block("一、活动介绍"),
            _make_block("这是一个活动介绍段落"),
            _make_block("更多内容"),
        ]
        envelope = build_article_envelope(
            url="https://mp.weixin.qq.com/s/single",
            raw_title="活动介绍",
            content_blocks=blocks,
        )
        result = detect_multi_topic(envelope)
        # 只有一个编号小标题，不足2个 → 不算多主题
        assert result["is_multi_topic_candidate"] is False

    def test_all_noise_blocks(self):
        blocks = [
            _make_block("扫码申卡", "image_cta"),
            _make_block("了解更多", "image_cta"),
        ]
        envelope = build_article_envelope(
            url="https://mp.weixin.qq.com/s/noise",
            raw_title="无实质内容",
            content_blocks=blocks,
        )
        result = detect_multi_topic(envelope)
        assert result["is_multi_topic_candidate"] is False

    def test_bank_hint_detection(self):
        blocks = [
            _make_block("农业银行信用卡优惠"),
            _make_block("招商银行活动"),
            _make_block("中信银行返现"),
        ]
        hints = _find_bank_hints(blocks)
        assert "农业银行" in hints
        assert "招商银行" in hints
        assert "中信银行" in hints

    def test_is_topic_start(self):
        assert _is_topic_start(_make_heading_block("测试标题", is_heading_like=True))
        assert _is_topic_start(_make_block("一、编号标题"))
        assert _is_topic_start(_make_block("农业银行新卡首发"))
        assert not _is_topic_start(_make_block("普通段落内容"))

    def test_named_entities_extraction(self):
        entities = _extract_named_entities("Visa世界杯版 积分活动 新客返现优惠 农业银行")
        assert len(entities) >= 2  # 至少找到卡名/活动名


# ═══════════════════════════════════════════════════════════
# 8. article_envelope builder
# ═══════════════════════════════════════════════════════════

class TestArticleEnvelope:
    def test_build_envelope(self):
        envelope = build_article_envelope(
            url="https://mp.weixin.qq.com/s/test",
            publisher_name="农行信用卡",
            publish_time="2026-01-01",
            raw_title="测试文章",
            content_blocks=[_make_block("hello")],
        )
        assert envelope["url"] == "https://mp.weixin.qq.com/s/test"
        assert envelope["publisher_name"] == "农行信用卡"
        assert envelope["raw_title"] == "测试文章"
        assert len(envelope["content_blocks"]) == 1
        assert envelope["topic_split_meta"]["is_multi_topic_candidate"] is False

    def test_article_id_auto_generation(self):
        envelope = build_article_envelope(
            url="https://mp.weixin.qq.com/s/unique123",
            raw_title="标题",
        )
        assert envelope["article_id"] != ""
        assert envelope["article_id"].startswith("wx_")


# ═══════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
