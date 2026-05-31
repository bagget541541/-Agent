"""common.normalizer 单元测试

覆盖：
  - 内部清洗函数（_normalize_highlight_text / _normalize_detail_text / _strip_marketing_tail 等）
  - _build_structured_for_category（按分类构建 structured）
  - normalize_item（完整标准化流程）
  - normalize_batch（批量标准化）
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from common.normalizer import (
    _normalize_highlight_text,
    _normalize_detail_text,
    _strip_marketing_tail,
    _trim_marketing_intro,
    _safe_truncate,
    _clean_card_name,
    _build_structured_for_category,
    _build_image_structured,
    normalize_item,
    normalize_batch,
    normalize_topic,
)


# ── 清洗函数 ────────────────────────────────────────────

class TestNormalizeHighlightText:
    def test_remove_image_markers(self):
        """去除 [图片核心内容 - xxx] 噪音标记"""
        text = "权益内容 [图片核心内容 - 银行公告截图] 详情如下"
        result = _normalize_highlight_text(text)
        assert "[图片核心内容" not in result
        assert "权益内容" in result

    def test_remove_greeting_prefix(self):
        """去除称呼前缀"""
        for prefix in ["尊敬的客户：", "尊敬的持卡人：", "附件：", "点击可查阅："]:
            result = _normalize_highlight_text(f"{prefix}活动内容如下")
            assert not result.startswith(prefix)

    def test_remove_section_headers(self):
        """去除章节标题"""
        text = "一、活动时间\n二、活动对象\n活动内容是满200减50"
        result = _normalize_highlight_text(text)
        assert "一、活动时间" not in result
        assert "满200减50" in result

    def test_collapse_whitespace(self):
        """折叠多余空白"""
        result = _normalize_highlight_text("内容   多\n\n   行")
        assert "  " not in result
        assert "\n\n" not in result

    def test_empty_input(self):
        """空输入 → 空字符串"""
        assert _normalize_highlight_text("") == ""
        assert _normalize_highlight_text(None) == ""


class TestNormalizeDetailText:
    def test_ocr_structured_format(self):
        """识别 '- 银行：xxx' 前缀格式"""
        text = "- 银行：招商银行\n- 卡种：经典白金卡\n- 卡面级别：白金"
        result = _normalize_detail_text(text)
        assert "招商银行" in result
        assert "经典白金卡" in result

    def test_numbered_format(self):
        """识别 '1. 发卡银行：xxx' 编号格式"""
        text = "1. 发卡银行：中信银行\n2. 卡种名称：i白金卡\n3. 权益亮点：免年费"
        result = _normalize_detail_text(text)
        assert "中信银行" in result
        assert "i白金卡" in result

    def test_noise_lines_filtered(self):
        """过滤噪音行，保留有用内容"""
        text = "[图片核心内容 - 银行公告]\n未包含任何信用卡相关信息\n招商银行白金卡权益丰富可享用\n仅显示一个用于申卡的微信二维码"
        result = _normalize_detail_text(text)
        assert "未包含" not in result
        assert "二维码" not in result
        assert "招商银行" in result

    def test_core_section_detection(self):
        """识别 '核心信用卡资讯' 结构化段落"""
        text = "前言内容\n核心信用卡资讯\n银行：招行\n卡种：白金卡\n补充说明\n无关内容"
        result = _normalize_detail_text(text)
        assert "招行" in result
        assert "白金卡" in result

    def test_max_six_lines(self):
        """最多保留 6 条有用行"""
        lines = "\n".join([f"- 银行：银行{i}" for i in range(10)])
        result = _normalize_detail_text(lines)
        parts = result.split("；")
        assert len(parts) <= 6

    def test_fallback_to_highlight(self):
        """全部噪音行 → useful_lines 为空 → 兜底调用 _normalize_highlight_text"""
        # 全部是噪音行（短文本或噪音标记），走兜底路径
        result = _normalize_detail_text("[图片核心内容 - 截图]\n二维码")
        # highlight_text 会去掉 [图片核心内容 - xxx] 标记
        assert "[图片核心内容" not in result
        assert "二维码" in result  # highlight_text 不过滤二维码文本


class TestStripMarketingTail:
    def test_remove_cta_tail(self):
        """去除营销 CTA 尾巴"""
        text = "活动内容珍藏周边礼等你领，快来参与"
        result = _strip_marketing_tail(text)
        assert "珍藏周边礼等你领" not in result

    def test_remove_tag_tail(self):
        """去除尾部【xxx】标签"""
        text = "活动内容【限时优惠】"
        result = _strip_marketing_tail(text)
        assert result.endswith("活动内容") or "【" not in result

    def test_empty_input(self):
        assert _strip_marketing_tail("") == ""
        assert _strip_marketing_tail(None) == ""


class TestTrimMarketingIntro:
    def test_remove_intro_pattern(self):
        """去除公众号营销引言"""
        text = "说在前头，这是一篇广告。以下是正文内容。"
        result = _trim_marketing_intro(text)
        assert "说在前头" not in result
        assert "正文内容" in result

    def test_no_intro_unchanged(self):
        """无引言 → 原文不变"""
        text = "直接是正文内容，没有引言。"
        result = _trim_marketing_intro(text)
        assert result == text


class TestSafeTruncate:
    def test_short_text_unchanged(self):
        """短文本不截断"""
        assert _safe_truncate("短文本", 100) == "短文本"

    def test_sentence_boundary(self):
        """按句子边界截断"""
        text = "第一句话。第二句话。第三句话。"
        result = _safe_truncate(text, 20)
        assert result.endswith("。") or len(result) <= 21

    def test_empty_input(self):
        assert _safe_truncate("", 100) == ""
        assert _safe_truncate(None, 100) is None


# ── structured 构建 ─────────────────────────────────────

class TestBuildStructuredForCategory:
    def test_new_card(self):
        """新卡分类 → 正确字段"""
        result = _build_structured_for_category("新卡", "招行白金卡", "权益内容")
        assert "卡种" in result
        assert "详情" in result

    def test_activity(self):
        """活动分类 → 正确字段"""
        result = _build_structured_for_category("活动", "618满减", "满200减50")
        assert "活动内容" in result
        assert "活动时间" in result

    def test_benefit_change(self):
        """权益变更 → 正确字段"""
        result = _build_structured_for_category("权益变更", "权益调整", "缩水内容")
        assert "变更内容" in result
        assert "影响范围" in result

    def test_announcement(self):
        """公告 → 正确字段"""
        result = _build_structured_for_category("公告", "系统通知", "维护内容")
        assert "消息内容" in result

    def test_other_category(self):
        """其他分类 → 详细内容"""
        result = _build_structured_for_category("其他", "其他标题", "其他内容")
        assert "详细内容" in result

    def test_empty_text_fallback_to_title(self):
        """空正文时用标题兜底"""
        result = _build_structured_for_category("新卡", "招行白金卡", "")
        assert result["卡种"] == "招行白金卡"


# ── normalize_item ──────────────────────────────────────

class TestNormalizeItem:
    def test_basic_wechat_article(self):
        """标准公众号文章 → 完整 CreditCardItem"""
        raw = {
            "title": "招行发布新卡",
            "url": "https://mp.weixin.qq.com/test",
            "content_text": "招商银行今日发布全新白金信用卡，权益丰富。",
            "author": "招商银行信用卡",
            "source": "wechat",
        }
        item = normalize_item(raw, source="wechat")
        assert item.category in ("新卡", "活动", "公告", "权益变更", "其他")
        assert item.bank == "招商银行"
        assert item.url == "https://mp.weixin.qq.com/test"
        assert item.title  # 有标题
        assert item.structured  # 有 structured
        assert isinstance(item.confidence, dict)
        assert isinstance(item.evidence, dict)

    def test_explicit_bank_override(self):
        """显式 bank 参数覆盖自动识别"""
        raw = {"title": "某卡发布", "author": "某公众号"}
        item = normalize_item(raw, source="wechat", bank="中信银行")
        assert item.bank == "中信银行"

    def test_skip_auto_classify(self):
        """skip_auto_classify=True 保留原始分类"""
        raw = {"title": "测试", "category": "活动"}
        item = normalize_item(raw, skip_auto_classify=True)
        assert item.category == "活动"

    def test_empty_input(self):
        """空 dict → 不报错，返回合理默认值"""
        item = normalize_item({}, source="website")
        assert item.source == "website"
        assert item.category in STANDARD_CATEGORIES

    def test_structured_passthrough(self):
        """已有 structured → 保留原值"""
        raw = {
            "title": "测试",
            "structured": {"卡种": "白金卡", "详情": "test"},
        }
        item = normalize_item(raw, source="wechat")
        assert item.structured.get("卡种") == "白金卡"

    def test_structured_clean_generated(self):
        """structured_clean 生成且去噪"""
        raw = {
            "title": "测试",
            "content_text": "说在前头，这是一篇广告。尊敬的客户：权益内容如下。",
        }
        item = normalize_item(raw, source="wechat")
        # structured_clean 应该存在
        assert isinstance(item.structured_clean, dict)
        # 应该去掉了称呼前缀
        for v in item.structured_clean.values():
            assert "尊敬的客户" not in v

    def test_review_flags_populated(self):
        """review_flags 自动生成"""
        raw = {"title": "测试"}  # 缺少很多字段
        item = normalize_item(raw, source="wechat")
        assert isinstance(item.review_flags, list)

    def test_content_blocks_clean_text(self):
        """content_blocks 中的清洁文本被提取"""
        raw = {
            "title": "测试",
            "content_blocks": [
                {"type": "article_text", "text": "文章正文内容"},
                {"type": "ocr_fact", "text": "OCR识别内容"},
                {"type": "navigation", "text": "导航噪音"},
            ],
        }
        item = normalize_item(raw, source="wechat")
        assert "文章正文内容" in (item.raw_text or "")
        assert "导航噪音" not in (item.raw_text or "")

    def test_noise_flags_from_blocks(self):
        """content_blocks 中的噪音标记 → noise_flags"""
        raw = {
            "title": "测试",
            "content_blocks": [
                {"type": "ocr_noise", "text": "噪音"},
                {"type": "image_cta", "text": "引导"},
            ],
        }
        item = normalize_item(raw, source="wechat")
        assert "ocr_noise" in item.noise_flags
        assert "image_cta" in item.noise_flags


# ── normalize_batch ─────────────────────────────────────

class TestNormalizeBatch:
    def test_basic_batch(self):
        """批量标准化返回 CreditCardBatch"""
        raw_items = [
            {"title": "招行新卡", "content_text": "招商银行发布新卡"},
            {"title": "活动优惠", "content_text": "满200减50活动"},
        ]
        batch = normalize_batch(raw_items, source="wechat")
        assert len(batch.items) == 2
        assert all(item.category in STANDARD_CATEGORIES for item in batch.items)

    def test_empty_batch(self):
        """空列表 → 空 batch"""
        batch = normalize_batch([], source="wechat")
        assert len(batch.items) == 0

    def test_batch_label(self):
        """batch_label 传递"""
        batch = normalize_batch([{"title": "测试"}], batch_label="W22")
        assert batch.batch_label == "W22"


# ── normalize_topic ─────────────────────────────────────

class TestNormalizeTopic:
    def test_topic_candidate_conversion(self):
        """TopicCandidate → CreditCardItem"""
        topic = {
            "headline": "招行新卡发布",
            "blocks": [
                {"type": "article_text", "text": "招商银行发布全新白金卡"},
            ],
            "url": "https://mp.weixin.qq.com/test",
            "publisher_name": "招商银行信用卡",
            "images": [],
        }
        item = normalize_topic(topic, source="wechat")
        assert item.title
        assert item.is_multi_topic_split is True
        assert item.source_article_title == ""

    def test_topic_with_meta(self):
        """article_meta 回填"""
        topic = {
            "headline": "测试标题",
            "blocks": [{"type": "article_text", "text": "内容"}],
            "source_article_title": "原始文章标题",
        }
        item = normalize_topic(topic, article_meta={"url": "https://test.com"})
        assert item.source_article_title == "原始文章标题"

    def test_low_confidence_flags(self):
        """低拆分置信度 → review_flag"""
        topic = {
            "headline": "测试",
            "blocks": [{"type": "article_text", "text": "内容"}],
            "split_confidence": 0.3,
        }
        item = normalize_topic(topic, source="wechat")
        assert "needs_topic_split_review" in item.review_flags


# ── Review flags + 队列排序（连续分数版本） ──────────────

from common.schema import CreditCardItem, STANDARD_CATEGORIES
from common.review import generate_review_flags, build_review_queue, _severity


class TestReviewFlagsContinuous:
    def test_high_confidence_no_flags(self):
        """高质量条目 → 无审核标记"""
        item = CreditCardItem(
            source="wechat", category="新卡", bank="招商银行",
            title="招行发布全新白金信用卡权益丰富",
            structured={"卡种": "白金卡", "卡亮点": "权益丰富", "适用人群": "持卡人", "来源": "招行", "详情": "详情"},
            publish_time="2026.05.20",
            confidence={"overall": 0.85, "category": 0.92, "bank": 1.0, "title": 0.9, "structured": 1.0},
            category_candidates=[["新卡", 0.92]],
        )
        flags = generate_review_flags(item)
        assert "needs_category_review" not in flags
        assert "needs_source_review" not in flags
        assert "needs_title_review" not in flags

    def test_low_bank_flags_source_review(self):
        """bank 分数 0.0 → needs_source_review"""
        item = CreditCardItem(
            source="wechat", category="活动", bank="未知",
            title="某银行优惠活动内容丰富",
            confidence={"overall": 0.3, "category": 0.6, "bank": 0.0, "title": 0.7, "structured": 0.67},
            category_candidates=[["活动", 0.6]],
            publish_time="2026.05.20",
        )
        flags = generate_review_flags(item)
        assert "needs_source_review" in flags

    def test_low_category_flags_review(self):
        """category 分数 < 0.7 → needs_category_review"""
        item = CreditCardItem(
            source="wechat", category="活动", bank="招商银行",
            title="招行活动优惠内容丰富",
            confidence={"overall": 0.55, "category": 0.55, "bank": 0.9, "title": 0.8, "structured": 0.67},
            category_candidates=[["活动", 0.55], ["公告", 0.45]],
            publish_time="2026.05.20",
        )
        flags = generate_review_flags(item)
        assert "needs_category_review" in flags

    def test_generated_title_flags_title_review(self):
        """生成标题 (title < 0.6) → needs_title_review"""
        item = CreditCardItem(
            source="wechat", category="新卡", bank="招商银行",
            title="招商银行发布新卡",
            confidence={"overall": 0.6, "category": 0.9, "bank": 1.0, "title": 0.4, "structured": 0.6},
            category_candidates=[["新卡", 0.9]],
            publish_time="2026.05.20",
        )
        flags = generate_review_flags(item)
        assert "needs_title_review" in flags

    def test_low_structured_flags_detail_review(self):
        """structured 分数 < 0.5 → needs_detail_review"""
        item = CreditCardItem(
            source="wechat", category="新卡", bank="招商银行",
            title="招行新卡发布内容丰富",
            structured={"卡种": "白金卡"},
            confidence={"overall": 0.5, "category": 0.9, "bank": 1.0, "title": 0.7, "structured": 0.2},
            category_candidates=[["新卡", 0.9]],
            publish_time="2026.05.20",
        )
        flags = generate_review_flags(item)
        assert "needs_detail_review" in flags

    def test_overall_low_flags_overall_review(self):
        """overall < 0.5 → needs_overall_review"""
        item = CreditCardItem(
            source="wechat", category="其他", bank="未知", title="短",
            confidence={"overall": 0.3, "category": 0.2, "bank": 0.0, "title": 0.4, "structured": 0.0},
            category_candidates=[["其他", 0.2]],
            publish_time="2026.05.20",
        )
        flags = generate_review_flags(item)
        assert "needs_overall_review" in flags


class TestReviewQueueSorting:
    def test_sorted_by_confidence_asc(self):
        """队列按 overall confidence 升序排列"""
        high = CreditCardItem(
            source="wechat", category="新卡", bank="招商银行", title="招行新卡发布",
            confidence={"overall": 0.85, "category": 0.9, "bank": 1.0, "title": 0.9, "structured": 1.0},
            category_candidates=[["新卡", 0.9]],
            publish_time="2026.05.20",
        )
        low = CreditCardItem(
            source="wechat", category="其他", bank="未知", title="短",
            confidence={"overall": 0.3, "category": 0.2, "bank": 0.0, "title": 0.4, "structured": 0.0},
            category_candidates=[["其他", 0.2]],
        )
        high.review_flags = ["needs_time_review"]
        low.review_flags = ["needs_source_review", "needs_category_review"]
        queue = build_review_queue([high, low])
        items = queue["flagged_items"]
        assert items[0]["item_id"] == low.item_id
        assert items[-1]["item_id"] == high.item_id

    def test_severity_in_flagged_items(self):
        """flagged_item 包含 severity 字段"""
        item = CreditCardItem(
            source="wechat", category="新卡", bank="未知", title="短",
            confidence={"overall": 0.3, "category": 0.2, "bank": 0.0, "title": 0.4, "structured": 0.0},
            category_candidates=[["其他", 0.2]],
        )
        item.review_flags = ["needs_source_review"]
        queue = build_review_queue([item])
        assert queue["flagged_items"][0]["severity"] == "high"

    def test_meta_high_severity_count(self):
        """meta 中 high_severity 计数正确"""
        item = CreditCardItem(
            source="wechat", category="新卡", bank="未知", title="短",
            confidence={"overall": 0.3, "category": 0.2, "bank": 0.0, "title": 0.4, "structured": 0.0},
            category_candidates=[["其他", 0.2]],
        )
        item.review_flags = ["needs_source_review"]
        queue = build_review_queue([item])
        assert queue["meta"]["high_severity"] == 1


class TestSeverity:
    def test_high(self):
        """含关键标记 → high"""
        assert _severity(["needs_category_review"]) == "high"
        assert _severity(["needs_source_review", "needs_time_review"]) == "high"
        assert _severity(["needs_overall_review"]) == "high"

    def test_medium(self):
        """≥3 个非关键标记 → medium"""
        assert _severity(["needs_title_review", "needs_detail_review", "needs_time_review"]) == "medium"

    def test_low(self):
        """1-2 个非关键标记 → low"""
        assert _severity(["needs_time_review"]) == "low"
        assert _severity(["needs_title_review", "needs_detail_review"]) == "low"


# ── _clean_card_name ──────────────────────────────────────

class TestCleanCardName:
    def test_remove_suffix_exclamation(self):
        """去掉末尾感叹号"""
        result = _clean_card_name("招商银行白金信用卡！")
        assert result == "招商银行白金信用卡"

    def test_remove_suffix_marketing(self):
        """去掉营销后缀"""
        result = _clean_card_name("华夏南航联名信用卡正式发行！")
        assert "正式发行" not in result
        assert "华夏南航联名信用卡" in result

    def test_remove_tail_tag(self):
        """去掉尾部【xxx】标签"""
        result = _clean_card_name("农行Visa白金卡（世界杯版）【限时】")
        assert "【限时】" not in result
        assert "农行Visa白金卡" in result

    def test_remove_prefix_decorations(self):
        """去掉开头修饰词"""
        result = _clean_card_name("重磅！招商银行白金卡发布")
        assert "重磅" not in result
        assert "招商银行白金卡" in result

    def test_preserve_core_name(self):
        """保留核心卡名"""
        result = _clean_card_name("农行Visa全球支付白金卡（世界杯版）")
        assert "农行Visa全球支付白金卡" in result

    def test_empty_input(self):
        """空输入 → 原样返回"""
        assert _clean_card_name("") == ""
        assert _clean_card_name(None) is None

    def test_no_noise_unchanged(self):
        """无噪音 → 原文不变"""
        result = _clean_card_name("招商银行经典白金卡")
        assert result == "招商银行经典白金卡"


# ── structured["卡种"] 清洗 ──────────────────────────────

class TestStructuredCardNameCleaned:
    def test_new_card_card_name_cleaned(self):
        """新卡分类 → structured["卡种"] 被清洗"""
        result = _build_structured_for_category("新卡", "招行发布白金卡！", "内容")
        assert "！" not in result["卡种"]
        assert "白金卡" in result["卡种"]

    def test_new_card_card_name_preserved(self):
        """新卡分类 → 清洗后仍保留核心卡名"""
        result = _build_structured_for_category("新卡", "全新农行Visa白金卡【限时】", "内容")
        assert "农行Visa白金卡" in result["卡种"]


# ── 内容质量门控 ──────────────────────────────────────────

class TestContentQualityGate:
    def test_pure_ad_flagged(self):
        """纯广告文章 → noise_flags 含 pure_ad_or_empty"""
        raw = {"title": "招行新卡发布", "content_text": "以上内容为广告"}
        item = normalize_item(raw, source="wechat")
        assert "pure_ad_or_empty" in item.noise_flags

    def test_empty_content_flagged(self):
        """空内容 → noise_flags 含 pure_ad_or_empty"""
        raw = {"title": "招行新卡发布", "content_text": ""}
        item = normalize_item(raw, source="wechat")
        assert "pure_ad_or_empty" in item.noise_flags

    def test_normal_content_not_flagged(self):
        """正常内容 → 不标记"""
        raw = {"title": "招行新卡发布", "content_text": "招商银行发布新卡"}
        item = normalize_item(raw, source="wechat")
        assert "pure_ad_or_empty" not in item.noise_flags

    def test_other_category_not_flagged(self):
        """其他分类 → 即使空内容也不标记"""
        raw = {"title": "测试", "content_text": "", "category": "其他"}
        item = normalize_item(raw, source="wechat", skip_auto_classify=True)
        assert "pure_ad_or_empty" not in item.noise_flags
