"""P0: schema.py — CreditCardItem / CreditCardBatch 序列化契约测试"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from common.schema import CreditCardItem, CreditCardBatch, normalize_category, STANDARD_CATEGORIES


class TestNormalizeCategory:
    """分类标准化测试"""

    def test_standard_passthrough(self):
        """标准分类直接通过"""
        for cat in STANDARD_CATEGORIES:
            assert normalize_category(cat) == cat

    def test_map_variants(self):
        """变体映射到标准分类"""
        cases = [
            ("新卡发布", "新卡"),
            ("新发行信用卡", "新卡"),
            ("信用卡活动", "活动"),
            ("优惠活动", "活动"),
            ("权益调整", "权益变更"),
            ("公告或其他", "公告"),
        ]
        for raw, expected in cases:
            assert normalize_category(raw) == expected, f"{raw} → {expected}"

    def test_unknown_maps_to_other(self):
        """未知分类映射为“其他”"""
        assert normalize_category("未知分类") == "其他"
        assert normalize_category("") == "其他"


class TestCreditCardItem:
    """单条资讯序列化测试"""

    def test_create_minimal(self):
        """最小字段创建"""
        item = CreditCardItem()
        assert item.item_id  # 自动生成
        assert item.extracted_at  # 自动生成
        assert item.images == []
        assert item.structured == {}

    def test_create_full(self, sample_item_new_card):
        """完整字段创建"""
        item = sample_item_new_card
        assert item.source == "wechat"
        assert item.category == "新卡"
        assert item.bank == "招商银行"
        assert item.title == "招行经典白金信用卡"
        assert len(item.images) == 0

    def test_category_auto_normalized(self):
        """category 自动标准化"""
        item = CreditCardItem(category="新卡发布")
        assert item.category == "新卡"

    def test_to_dict_roundtrip(self, sample_item_new_card):
        """to_dict → from_dict 往返不变"""
        item = sample_item_new_card
        d = item.to_dict()
        restored = CreditCardItem.from_dict(d)
        assert restored.item_id == item.item_id
        assert restored.source == item.source
        assert restored.category == item.category
        assert restored.bank == item.bank
        assert restored.title == item.title
        assert restored.raw_text == item.raw_text
        assert restored.structured == item.structured

    def test_to_dict_contains_all_keys(self, sample_item_new_card):
        """to_dict 包含所有必要字段"""
        d = sample_item_new_card.to_dict()
        required = {
            "item_id", "source", "source_type", "category", "bank",
            "issuer_bank", "publisher_name", "source_name",
            "title", "raw_title", "normalized_title", "display_title",
            "highlight_summary", "title_source",
            "url", "raw_text", "content_blocks", "images",
            "structured", "structured_clean",
            "author", "publish_time", "extracted_at",
            "confidence", "evidence", "noise_flags", "review_flags",
            "category_candidates",
        }
        assert required.issubset(d.keys()), f"Missing: {required - d.keys()}"

    def test_images_default_empty(self):
        """images 默认为空列表"""
        item = CreditCardItem()
        assert item.images == []

    def test_images_accept_list(self):
        """images 接受列表"""
        item = CreditCardItem(images=["a.jpg", "b.png"])
        assert len(item.images) == 2


class TestCreditCardBatch:
    """批次容器测试"""

    def test_create_empty(self, empty_batch):
        """空批次"""
        assert empty_batch.size() == 0
        assert empty_batch.batch_label.startswith("empty_test")

    def test_add_item(self, sample_item_new_card):
        """添加条目"""
        batch = CreditCardBatch()
        batch.add(sample_item_new_card)
        assert batch.size() == 1

    def test_by_category(self, sample_item_new_card, sample_item_change):
        """按分类筛选"""
        batch = CreditCardBatch(items=[sample_item_new_card, sample_item_change])
        new_cards = batch.by_category("新卡")
        assert len(new_cards) == 1
        assert new_cards[0].title == "招行经典白金信用卡"
        changes = batch.by_category("权益变更")
        assert len(changes) == 1

    def test_by_category_normalized(self, sample_item_new_card):
        """by_category 自动标准化分类名"""
        batch = CreditCardBatch(items=[sample_item_new_card])
        assert len(batch.by_category("新卡发布")) == 1

    def test_to_dict_structure(self, sample_item_new_card):
        """to_dict 包含版本号和时间戳"""
        batch = CreditCardBatch(items=[sample_item_new_card])
        d = batch.to_dict()
        assert d["schema_version"] == "1.1"
        assert "generated_at" in d
        assert d["total"] == 1
        assert len(d["items"]) == 1

    def test_json_file_roundtrip(self, sample_item_new_card, tmp_path):
        """save_json → load_json 往返不变"""
        batch = CreditCardBatch(items=[sample_item_new_card], batch_label="roundtrip_test")
        fp = tmp_path / "test_batch.json"
        saved_path = batch.save_json(str(fp))
        assert os.path.exists(saved_path)

        loaded = CreditCardBatch.load_json(str(fp))
        assert loaded.size() == 1
        assert loaded.batch_label == "roundtrip_test"
        assert loaded.items[0].title == sample_item_new_card.title

    def test_repr(self, sample_item_new_card):
        """__repr__ 格式"""
        batch = CreditCardBatch(items=[sample_item_new_card])
        r = repr(batch)
        assert "1 items" in r
        assert sample_item_new_card.batch_label if hasattr(sample_item_new_card, 'batch_label') else True
