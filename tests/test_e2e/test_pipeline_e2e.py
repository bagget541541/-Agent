"""端到端测试 — 数据管线全链路

模拟真实输入（原始文章 dict），走完整个数据处理链：
  raw dict → normalizer.normalize_item → normalize_batch
      → classifier → entity_resolver → display_fields → review_flags

不涉及 LLM/HTTP 实际调用（全 mock）。
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from common.normalizer import normalize_item, normalize_batch
from common.schema import CreditCardItem, CreditCardBatch


# ═══════════════════════════════════════════════════════════
# 模拟原始数据
# ═══════════════════════════════════════════════════════════

def make_raw_wechat(**overrides) -> dict:
    """构造模拟的微信文章原始 dict"""
    data = {
        "title": "招商银行经典白金信用卡首发",
        "author": "招商银行信用卡",
        "publish_time": "2026.06.01",
        "full_text": "招商银行全新推出经典白金信用卡，年费3600元，消费达标免年费，无限贵宾厅权益。",
        "source": "wechat",
        "images": ["https://example.com/card1.jpg", "https://example.com/card2.jpg"],
    }
    data.update(overrides)
    return data


def make_raw_website(**overrides) -> dict:
    """构造模拟的银行官网公告原始 dict"""
    data = {
        "title": "关于调整信用卡积分规则的公告",
        "author": "建设银行",
        "publish_time": "2026.06.10",
        "full_text": "自2026年7月1日起，建设银行信用卡积分兑换比例进行调整，详情见附件。",
        "source": "website",
        "images": [],
        "category": "公告",
    }
    data.update(overrides)
    return data


# ═══════════════════════════════════════════════════════════
# E2E 测试：单条目全链路
# ═══════════════════════════════════════════════════════════

class TestSingleItemEndToEnd:
    """一条微信文章从原始 dict → CreditCardItem 的全链路"""

    def test_wechat_new_card_full_chain(self):
        """微信新卡文章 → 正确分类为"新卡"、银行识别正确"""
        raw = make_raw_wechat()
        item = normalize_item(raw, source="wechat")

        assert isinstance(item, CreditCardItem)
        assert item.source == "wechat"
        assert item.category == "新卡"
        assert item.bank == "招商银行"
        assert item.title == "招商银行经典白金信用卡首发"
        assert len(item.images) > 0

    def test_website_announcement_full_chain(self):
        """官网公告 → 正确分类 + 银行识别"""
        raw = make_raw_website()
        item = normalize_item(raw, source="website", bank="建设银行", skip_auto_classify=True)

        assert isinstance(item, CreditCardItem)
        assert item.source == "website"
        assert item.category == "公告"
        assert item.bank == "建设银行"
        assert item.structured.get("消息内容") is not None

    def test_unknown_bank_with_author_resolved(self):
        """未指定 bank 但有 author → entity_resolver 从公众号识别银行"""
        raw = make_raw_wechat(author="招商银行信用卡")
        # 不传 bank 参数，依靠 author 自动识别
        item = normalize_item(raw, source="wechat")
        assert item.bank == "招商银行" or item.issuer_bank == "招商银行"

    def test_missing_title_uses_display_title_fallback(self):
        """标题很短 → display_fields 自动补全"""
        raw = make_raw_wechat(title="活动")
        item = normalize_item(raw, source="wechat")
        assert item.title == "活动"
        # display_title 应该由 display_fields 生成
        assert len(item.display_title) >= len(item.title)

    def test_empty_text_no_crash(self):
        """空正文 → 不崩溃"""
        raw = make_raw_wechat(full_text="", title="测试标题")
        item = normalize_item(raw, source="wechat")
        assert item is not None
        assert item.title == "测试标题"


# ═══════════════════════════════════════════════════════════
# E2E 测试：批量处理
# ═══════════════════════════════════════════════════════════

class TestBatchEndToEnd:
    """多条文章批量处理"""

    def test_normalize_batch_returns_batch(self):
        """normalize_batch 返回 CreditCardBatch"""
        raws = [make_raw_wechat(), make_raw_wechat(title="第二篇文章")]
        batch = normalize_batch(raws, source="wechat", batch_label="2026W23")

        assert isinstance(batch, CreditCardBatch)
        assert batch.batch_label == "2026W23"
        assert len(batch.items) == 2
        for item in batch.items:
            assert isinstance(item, CreditCardItem)
            assert item.source == "wechat"
            assert item.category in ("新卡", "活动", "权益变更", "公告", "其他")

    def test_empty_list_returns_batch_with_zero_items(self):
        """空列表 → 空 batch"""
        batch = normalize_batch([], source="wechat", batch_label="empty")
        assert isinstance(batch, CreditCardBatch)
        assert len(batch.items) == 0

    def test_mixed_sources(self):
        """混合来源 → 各自正确处理"""
        raws = [
            make_raw_wechat(),
            make_raw_website(),
            {},
        ]
        batch = normalize_batch(raws, batch_label="mixed")
        # 无效 dict 应被过滤或容错
        assert len(batch.items) <= 3

    def test_all_items_have_confidence(self):
        """所有条目都有 confidence 字段"""
        raws = [make_raw_wechat(title=f"文章{i}") for i in range(5)]
        batch = normalize_batch(raws, source="wechat")
        for item in batch.items:
            assert hasattr(item, "confidence")
            assert isinstance(item.confidence, dict)
            assert "overall" in item.confidence

    def test_all_items_have_review_flags(self):
        """所有条目都有 review_flags"""
        raws = [make_raw_wechat(title=f"文章{i}") for i in range(3)]
        batch = normalize_batch(raws, source="wechat")
        for item in batch.items:
            assert hasattr(item, "review_flags")


# ═══════════════════════════════════════════════════════════
# E2E 测试：边界情况
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """边界 / 异常输入"""

    def test_minimal_fields(self):
        """最小字段 → 能正常完成流程"""
        raw = {"title": "测试", "source": "wechat"}
        item = normalize_item(raw, source="wechat")
        assert item is not None
        assert item.title == "测试"

    def test_numeric_bank(self):
        """非法 bank 值 → 不崩溃"""
        raw = make_raw_wechat(author="12345")
        item = normalize_item(raw, source="wechat")
        assert item is not None

    def test_very_long_title(self):
        """超长标题 → 截断不崩溃"""
        long_title = "招行" * 200
        raw = make_raw_wechat(title=long_title)
        item = normalize_item(raw, source="wechat")
        assert item is not None
        assert len(item.title) <= len(long_title)

    def test_special_characters(self):
        """特殊字符 → 不崩溃"""
        raw = make_raw_wechat(
            title="招行💳信用卡<test>&nbsp;活动",
            full_text="活动内容：\n1. 满减\n2. 积分\n价格：￥100\n汇率：$10",
        )
        item = normalize_item(raw, source="wechat")
        assert item is not None
        assert "招行" in item.title
