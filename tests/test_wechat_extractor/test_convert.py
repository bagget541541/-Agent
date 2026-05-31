"""wechat-article-extractor / convert_to_standard.py 单元测试"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── 路径设置 ──────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "wechat-article-extractor", "scripts"))

import convert_to_standard as cts


# ═══════════════════════════════════════════════════════════════
# _build_structured — 按分类构建结构化字段
# ═══════════════════════════════════════════════════════════════

class TestBuildStructured:

    def test_activity_category(self):
        result = cts._build_structured("活动", "618大促", "6月1日到6月20日活动")
        assert "活动内容" in result
        assert "活动时间" in result
        assert "适用人群" in result
        assert result["活动内容"] == "6月1日到6月20日活动"

    def test_activity_extracts_date(self):
        text = "活动时间2024-05-01到2024-06-30，名额有限"
        result = cts._build_structured("活动", "测试", text)
        assert result["活动时间"] == "2024-05-01"

    def test_activity_date_with_dots(self):
        text = "活动期间2024.01.15至2024.03.01"
        result = cts._build_structured("活动", "测试", text)
        assert result["活动时间"] == "2024.01.15"

    def test_new_card_category(self):
        result = cts._build_structured("新卡", "招行白金卡", "全新白金卡发行")
        assert result["卡种"] == "招行白金卡"
        assert "详情" in result
        assert result["详情"] == "全新白金卡发行"

    def test_benefit_change_category(self):
        result = cts._build_structured("权益变更", "里程缩水", "里程兑换比例下调50%")
        assert "消息时间" in result
        assert "变更内容" in result
        assert result["变更内容"] == "里程兑换比例下调50%"
        assert "变更分析" in result

    def test_notice_category(self):
        result = cts._build_structured("公告", "系统维护", "6月1日系统升级")
        assert "消息内容" in result
        assert result["消息内容"] == "6月1日系统升级"
        assert "点评" in result

    def test_unknown_category_defaults_to_notice(self):
        result = cts._build_structured("其他分类", "标题", "正文内容")
        assert "详细内容" in result
        assert result["详细内容"] == "正文内容"

    def test_empty_text(self):
        result = cts._build_structured("活动", "标题", "")
        assert result["活动内容"] == ""

    def test_text_truncated_to_300_chars(self):
        long_text = "A" * 500
        result = cts._build_structured("公告", "标题", long_text)
        assert len(result["消息内容"]) == 300


# ═══════════════════════════════════════════════════════════════
# convert — 端到端转换（mock 文件 I/O + 图片集中存储）
# ═══════════════════════════════════════════════════════════════

class TestConvert:

    SAMPLE_BATCH_RESULT = {
        "https://mp.weixin.qq.com/s/AAA": {
            "title": "招行经典白金卡发布",
            "text": "招商银行推出全新经典白金卡，免年费，赠送贵宾厅权益。",
            "category": "新卡发布",       # 非标准分类，需 normalize
            "bank": "招商银行",
            "images": [],
            "author": "招行信用卡中心",
            "publish_time": "2026.05.20",
        },
        "https://mp.weixin.qq.com/s/BBB": {
            "title": "618大促满200减50",
            "text": "农业银行618活动，2024.06.01-2024.06.20，满200减50。",
            "category": "活动",
            "bank": "",
            "images": [],
            "author": "农业银行",
        },
    }

    def _write_batch_result(self, tmp):
        path = os.path.join(tmp, "batch_result.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.SAMPLE_BATCH_RESULT, f, ensure_ascii=False)
        return path

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_convert_returns_batch(self, mock_centralize, mock_ensure):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_batch_result(tmp)
            batch = cts.convert(path, batch_label="test_batch")
            assert batch.size() == 2
            assert batch.batch_label == "test_batch"

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_category_normalized(self, mock_centralize, mock_ensure):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_batch_result(tmp)
            batch = cts.convert(path)
            # "新卡发布" → "新卡"
            new_cards = batch.by_category("新卡")
            assert len(new_cards) == 1
            assert new_cards[0].title == "招行经典白金卡发布"

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_bank_from_text_when_missing(self, mock_centralize, mock_ensure):
        """bank 字段为空时从文本中提取银行名。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_batch_result(tmp)
            batch = cts.convert(path)
            activity = [it for it in batch.items if it.category == "活动"][0]
            # 文本含"农业银行"，应自动提取
            assert "农业" in activity.bank

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_structured_built_when_missing(self, mock_centralize, mock_ensure):
        """无 structured 字段时自动构建。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_batch_result(tmp)
            batch = cts.convert(path)
            new_card = batch.by_category("新卡")[0]
            assert "卡种" in new_card.structured
            assert new_card.structured["卡种"] == "招行经典白金卡发布"

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_raw_text_cleaned_of_brackets(self, mock_centralize, mock_ensure):
        """raw_text 中的 [...] 标记应被清除。"""
        data = {
            "https://test.com": {
                "title": "测试",
                "text": "正文[图片文字]还有内容",
                "category": "公告",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "batch_result.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            batch = cts.convert(path)
            item = batch.items[0]
            assert "[图片文字]" not in item.raw_text

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_empty_batch_result(self, mock_centralize, mock_ensure):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "batch_result.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({}, f)
            batch = cts.convert(path)
            assert batch.size() == 0

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_batch_label_default(self, mock_centralize, mock_ensure):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_batch_result(tmp)
            batch = cts.convert(path)
            # 默认 batch_label 非空（自动生成时间戳）
            assert batch.batch_label != ""

    @patch.object(cts, "ensure_dirs")
    @patch.object(cts, "centralize_images", side_effect=lambda imgs, _: imgs)
    def test_images_centralized(self, mock_centralize, mock_ensure):
        """有图片时应调用 centralize_images。"""
        data = {
            "https://test.com": {
                "title": "测试",
                "text": "有图片的文章",
                "category": "活动",
                "images": ["http://img.test.com/a.jpg", "http://img.test.com/b.jpg"],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "batch_result.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            batch = cts.convert(path)
            # centralize_images 被调用，且 images 被赋值为 mock 返回值
            mock_centralize.assert_called_once()
            item = batch.items[0]
            assert item.images == ["http://img.test.com/a.jpg", "http://img.test.com/b.jpg"]
