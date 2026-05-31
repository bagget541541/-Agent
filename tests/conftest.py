"""pytest 共享 fixtures — 样本 CreditCardItem / CreditCardBatch 数据"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from common.schema import CreditCardItem, CreditCardBatch


@pytest.fixture
def sample_item_new_card() -> CreditCardItem:
    """样本：新卡"""
    return CreditCardItem(
        source="wechat",
        category="新卡",
        bank="招商银行",
        title="招行经典白金信用卡",
        url="https://example.com/card",
        raw_text="招商银行经典白金卡，免年费，无限贵宾厅权益，里程兑换比例优秀。",
        images=[],
        structured={
            "卡种": "经典白金卡",
            "卡亮点": "无限贵宾厅、里程兑换",
            "适用人群": "商旅人群",
            "来源": "招商银行",
            "详情": "年费3600元，消费20万免年费，赠送无限次贵宾厅。"
        },
        author="招行信用卡中心",
        publish_time="2026.05.20",
    )


@pytest.fixture
def sample_item_change() -> CreditCardItem:
    """样本：权益变更（负面）"""
    return CreditCardItem(
        source="wechat",
        category="权益变更",
        bank="中信银行",
        title="中信里程兑换比例下调",
        raw_text="中信银行公告：里程兑换比例从10:1调整为15:1，年上限从10万里程降至5万。缩水严重。",
        structured={
            "消息时间": "2026.05.15",
            "影响范围": "所有中信里程卡持卡人",
            "变更内容": "里程兑换比例下调50%，年上限减半",
            "变更分析": "严重缩水，建议评估是否继续持有"
        },
        author="中信银行",
        publish_time="2026.05.15",
    )


@pytest.fixture
def sample_item_activity() -> CreditCardItem:
    """样本：活动（高价值）"""
    return CreditCardItem(
        source="wechat",
        category="活动",
        bank="农业银行",
        title="农行618满200减50",
        raw_text="农业银行618活动：指定电商满200减50，名额充足，叠加多倍积分。",
        structured={
            "活动内容": "618消费满200减50",
            "活动时间": "2026.06.01-06.20",
            "适用人群": "所有农行信用卡持卡人"
        },
        author="农业银行",
        publish_time="2026.05.25",
    )


@pytest.fixture
def sample_item_announcement() -> CreditCardItem:
    """样本：公告"""
    return CreditCardItem(
        source="website",
        category="公告",
        bank="建设银行",
        title="建行系统升级通知",
        raw_text="建设银行将于6月1日凌晨进行系统升级，届时部分服务暂停。",
        structured={
            "消息内容": "系统升级，暂停服务",
            "点评": "常规维护，影响有限"
        },
        publish_time="2026.05.28",
    )


@pytest.fixture
def sample_batch_with_highlights(sample_item_new_card, sample_item_change, sample_item_activity) -> CreditCardBatch:
    """包含多种分类的批次，新卡和权益变更为高亮条目"""
    # 模拟评分：给 item 附加 evaluation
    import copy
    items = [sample_item_new_card, sample_item_change, sample_item_activity]
    return CreditCardBatch(items=items, batch_label="test_batch_2026W22")


@pytest.fixture
def empty_batch() -> CreditCardBatch:
    return CreditCardBatch(batch_label="empty_test")
