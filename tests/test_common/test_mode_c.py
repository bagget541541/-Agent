"""
Mode C 链路单元测试

覆盖：
1. extraction 契约：URL 规范化 / 字段级 Evidence / 状态推导
2. extraction_gate：证据覆盖率（P0-1 修复）/ 下游视图（P0-2 修复）/
   批量门禁（P1-3 修复）/ 失败隔离
3. title_gate：标题一致性（块级匹配）/ 质量评分
4. wechat_fetch：URL 安全校验 / 正文图片化检测
5. mode_c_pipeline：envelope_to_raw_item 溯源字段透传 / 纯文本提取
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from common.extraction import (
    build_field_evidence,
    validate_field_evidence,
    canonicalize_url,
    url_hash,
    article_id_from_url,
    extract_url_meta,
    build_content_block,
    compute_extraction_status,
)
from common.extraction_gate import (
    compute_evidence_coverage,
    scan_key_facts,
    build_downstream_view,
    check_batch_gate,
    is_downstream_safe,
)
from common.title_gate import title_body_consistency, quality_score
from common.wechat_fetch import validate_url, detect_image_body
from common.mode_c_pipeline import envelope_to_raw_item


# ── extraction 契约 ──────────────────────────────────────

class TestUrlCanonicalization:
    def test_wechat_tracking_params_stripped(self):
        url = "https://mp.weixin.qq.com/s/W8TDbtGoDfJ_O-HON1Vkkg?scene=1&from=timeline"
        assert canonicalize_url(url) == "https://mp.weixin.qq.com/s/W8TDbtGoDfJ_O-HON1Vkkg"

    def test_stable_hash_and_id(self):
        url = "https://mp.weixin.qq.com/s/W8TDbtGoDfJ_O-HON1Vkkg"
        assert url_hash(url) == url_hash(url + "?scene=1")
        assert article_id_from_url(url) == article_id_from_url(url + "?from=timeline")

    def test_url_meta(self):
        m = extract_url_meta("https://mp.weixin.qq.com/s/abc")
        assert m["article_id"].startswith("wx_")
        assert m["url_hash"]
        assert m["canonical_url"].endswith("/s/abc")


class TestFieldEvidence:
    def test_ocr_requires_image_id(self):
        ev = build_field_evidence("满18元", "threshold", "ocr",
                                  image_id="OCR-图03", quote="满18元", confidence=0.9)
        assert validate_field_evidence(ev) == []

    def test_manual_requires_reason(self):
        with pytest.raises(ValueError):
            build_field_evidence("18元", "amount", "manual")
        ev = build_field_evidence("18元", "amount", "manual", reason="人工核对")
        assert validate_field_evidence(ev) == []

    def test_invalid_source_type(self):
        with pytest.raises(ValueError):
            build_field_evidence("x", "y", "bogus")

    def test_content_block_types(self):
        with pytest.raises(ValueError):
            build_content_block("bogus", "x")
        b = build_content_block("ocr_fact", "满18元", image_id="OCR-图01", confidence=0.9)
        assert b["type"] == "ocr_fact"
        assert b["image_id"] == "OCR-图01"


class TestExtractionStatus:
    def test_status_priority(self):
        assert compute_extraction_status(fetch_ok=False) == "FETCH_FAILED"
        assert compute_extraction_status(fetch_ok=True, ocr_ok=False) == "OCR_FAILED"
        assert compute_extraction_status(fetch_ok=True, ocr_ok=True,
                                         review_reasons=["x"]) == "NEEDS_REVIEW"
        assert compute_extraction_status(fetch_ok=True, ocr_ok=True,
                                         evidence_coverage=0.5) == "PARTIAL"
        assert compute_extraction_status(fetch_ok=True, ocr_ok=True,
                                         evidence_coverage=1.0) == "SUCCESS"


# ── extraction_gate ──────────────────────────────────────

class TestEvidenceCoverage:
    def test_same_field_two_amounts_only_covered_one(self):
        """P0-1 回归：同字段两个金额，只有对应 evidence 的通过。"""
        text = "单笔满18元有机会立减，满5000元返现"
        ev = [build_field_evidence("满18元", "threshold", "page_text", quote="单笔满18元")]
        cov = compute_evidence_coverage(text, ev, "SUCCESS")
        assert any(u["match"] == "满5000元" for u in cov["uncovered"])
        assert not any(u["match"] == "满18元" for u in cov["uncovered"])
        assert cov["facts_covered"] == 1

    def test_invalid_evidence_excluded(self):
        """非法 evidence 不得参与覆盖计算。"""
        text = "满18元立减"
        bad = {"value": "", "field": "threshold", "source_type": "ocr"}  # 缺 image_id/value
        cov = compute_evidence_coverage(text, [bad], "SUCCESS")
        assert any(u["match"] == "满18元" for u in cov["uncovered"])

    def test_failed_status_blocked(self):
        cov = compute_evidence_coverage("满18元", [], "FETCH_FAILED")
        assert cov["blocked"] and cov["coverage"] == 0.0

    def test_scan_key_facts(self):
        facts = scan_key_facts("满18元，返6%，截至2026年9月30日，限8000份")
        fields = {f["field"] for f in facts}
        assert "threshold" in fields and "ratio" in fields
        assert "valid_until" in fields and "quota" in fields


class TestDownstreamView:
    @pytest.mark.parametrize("status", ["PARTIAL", "NEEDS_REVIEW"])
    def test_unconfirmed_view_empty(self, status):
        """P0-2 回归：未确认 PARTIAL / NEEDS_REVIEW 视图不含活动事实。"""
        v = build_downstream_view({
            "article_id": "a1", "url": "u", "extraction_status": status,
            "content_blocks": [{"type": "article_text", "text": "x"}],
            "structured": {"活动内容": "y"},
        })
        assert v["activity_facts"] == []
        assert v["structured"] == {}
        assert v["review_raw"]["content_blocks"]  # 复核材料保留

    def test_manual_confirmed_partial_released(self):
        v = build_downstream_view({
            "article_id": "a1", "url": "u", "extraction_status": "PARTIAL",
            "content_blocks": [{"type": "article_text", "text": "x"}],
        }, manual_confirmed=True)
        assert v["downstream_safe"] and v["activity_facts"]

    def test_fetch_failed_view(self):
        v = build_downstream_view({"article_id": "a", "url": "u",
                                   "extraction_status": "FETCH_FAILED",
                                   "structured": {"活动内容": "编造"}})
        assert v["activity_facts"] == [] and v["structured"] == {}
        assert "不得" in v.get("note", "")


class TestBatchGate:
    def test_generator_total(self):
        """P1-3 回归：generator 传入 total 正确。"""
        gen = (a for a in [
            {"article_id": "a1", "url": "u1", "extraction_status": "SUCCESS",
             "content_text": "满18元",
             "field_evidence": [build_field_evidence("满18元", "threshold", "page_text")]},
            {"article_id": "a2", "url": "u2", "extraction_status": "SUCCESS",
             "content_text": "满50元",
             "field_evidence": [build_field_evidence("满50元", "threshold", "page_text")]},
        ])
        rep = check_batch_gate(gen)
        assert rep["total"] == 2

    def test_url_duplicate_detected(self):
        articles = [
            {"article_id": "a1", "url": "https://x.com/1", "extraction_status": "SUCCESS",
             "content_text": "满18元", "field_evidence": []},
            {"article_id": "a2", "url": "https://x.com/1", "extraction_status": "SUCCESS",
             "content_text": "满18元", "field_evidence": []},
        ]
        rep = check_batch_gate(articles)
        assert rep["stats"]["url_duplicates"] == 1

    def test_failed_state_with_facts_violation(self):
        articles = [{
            "article_id": "a1", "url": "u", "extraction_status": "FETCH_FAILED",
            "structured": {"活动内容": "编造"}, "content_blocks": [{"type": "article_text"}],
        }]
        rep = check_batch_gate(articles)
        assert any(v["severity"] == "high" for v in rep["violations"])


# ── title_gate ───────────────────────────────────────────

class TestTitleConsistency:
    def test_matched(self):
        r = title_body_consistency(
            "景区秒杀/20元折扣券每周三开抢",
            "长安银行信用卡客户每周三早上10点可参与景区门票秒杀活动，20元优惠券每周限领2张")
        assert r["level"] == "high" and not r["flagged"]

    def test_mismatched(self):
        r = title_body_consistency(
            "景区秒杀/20元折扣券每周三开抢",
            "长安银行作为陕西省区域性城商行，无界卡获评全国优秀案例")
        assert r["level"] == "low" and r["flagged"]

    def test_missing_body(self):
        r = title_body_consistency("兴运月月抽", "")
        assert r["level"] == "unknown" and r["flagged"] and r["missing"]["body"]

    def test_digit_normalization(self):
        r = title_body_consistency(
            "至高赢88元刷卡金券包",
            "至高88元刷卡金券包，面额随机发放，每月可抽一次")
        assert r["score"] >= 0.6


class TestQualityScore:
    def test_success_high(self):
        q = quality_score(extraction_status="SUCCESS", evidence_coverage=1.0,
                          title_consistency={"score": 0.9})
        assert q["level"] == "A"

    def test_fetch_failed_low(self):
        q = quality_score(extraction_status="FETCH_FAILED", evidence_coverage=0.0)
        assert q["level"] == "D" and q["total"] < 0.5


# ── wechat_fetch ─────────────────────────────────────────

class TestWechatFetch:
    def test_validate_url(self):
        assert validate_url("https://mp.weixin.qq.com/s/abc") is None
        assert validate_url("file:///etc/passwd")
        assert validate_url("javascript:alert(1)")
        assert validate_url("")

    def test_detect_image_body(self):
        d = detect_image_body("", ["http://x/1.jpg", "http://x/2.jpg"], [])
        assert d["is_image_body"] and d["image_count"] == 2
        d2 = detect_image_body("这是一段超过五十个字的正常正文内容，用于说明非图片化文章。", [], [])
        assert not d2["is_image_body"]


# ── mode_c_pipeline ──────────────────────────────────────

class TestModeCPipeline:
    def test_envelope_to_raw_item_passthrough(self):
        env = {
            "url": "https://mp.weixin.qq.com/s/abc",
            "raw_title": "测试",
            "publisher_name": "测试银行",
            "publish_time": "2026-08-01",
            "body_text": "满18元立减",
            "content_blocks": [{"type": "article_text", "text": "满18元立减"}],
            "images": [],
            "source_url": "https://mp.weixin.qq.com/s/abc?scene=1",
            "canonical_url": "https://mp.weixin.qq.com/s/abc",
            "url_hash": "abc123",
            "fetch_status": "ok",
            "ocr_status": "skipped",
            "extraction_status": "SUCCESS",
            "content_text_ratio": 1.0,
            "image_count": 0,
            "evidence_coverage": 1.0,
            "review_reasons": [],
            "field_evidence": [{"value": "满18元", "field": "threshold",
                                "source_type": "page_text", "quote": "满18元",
                                "confidence": 0.95, "reason": ""}],
        }
        raw = envelope_to_raw_item(env)
        assert raw["extraction_status"] == "SUCCESS"
        assert raw["canonical_url"] == "https://mp.weixin.qq.com/s/abc"
        assert raw["url_hash"] == "abc123"
        assert raw["evidence_coverage"] == 1.0
        assert raw["field_evidence"]  # 溯源字段保留

    def test_envelope_to_raw_item_required_keys(self):
        """转换结果必须包含 normalize_item 消费所需字段。"""
        env = {"url": "u", "raw_title": "t", "body_text": "b",
               "content_blocks": [], "images": []}
        raw = envelope_to_raw_item(env)
        for key in ["title", "url", "content_text", "content_blocks", "author",
                    "account_name", "publish_time", "images", "source"]:
            assert key in raw, f"缺少 {key}"
