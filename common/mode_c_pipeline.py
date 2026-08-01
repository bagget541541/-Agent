"""
Mode C 提取流水线 — 公众号文章 L1 抓取 → L2 OCR → content_blocks → envelope

编排层：把 wechat_fetch / ocr / extraction 三个模块串成一条可复用的链路，
供 step3_merge 生产链路调用。

流程：
    1. L1 抓取：已有 HTML 直接用；否则 fetch_and_parse（含幂等缓存）；
    2. 正文图片化检测：is_image_body=True 时进入 L2 OCR；
    3. L2 OCR：下载图片 → OCRModule.ocr_images → ocr_results_to_blocks；
    4. 字段级证据：从 OCR/文本扫描关键事实，生成 field_evidence；
    5. 构建 ArticleEnvelope：含 extraction_status / evidence_coverage 等
       状态与溯源字段，供下游 normalize 与门禁消费。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from common.article_envelope import build_article_envelope
from common.extraction import build_field_evidence
from common.extraction_gate import scan_key_facts, compute_evidence_coverage
from common.ocr import OCRModule, ocr_results_to_blocks, aggregate_confidence
from common.wechat_fetch import (
    fetch_and_parse,
    parse_wechat_metadata,
    detect_image_body,
)


def extract_article(
    url: str,
    *,
    html: str = "",
    content_text: str = "",
    images: Optional[list[str]] = None,
    publisher_name: str = "",
    publish_time: str = "",
    raw_title: str = "",
    use_cache: bool = True,
    save_cache: bool = True,
    force_refresh: bool = False,
    ocr_config: Optional[dict] = None,
    ocr_workdir: str | Path = "",
    download_images_dir: str | Path = "",
) -> dict:
    """跑完整条 Mode C 提取流水线，返回 ArticleEnvelope（dict）。

    Args:
        url: 文章 URL（必填）
        html: 已有原始 HTML（有则跳过 L1 抓取）
        content_text: 已有正文文本（有则跳过 OCR 图片化判定）
        images: 已有图片 URL/本地路径列表
        publisher_name / publish_time / raw_title: 已知元信息（未提供则从 HTML 解析）
        use_cache / save_cache / force_refresh: L1 抓取缓存策略
        ocr_config: OCR 配置（覆盖默认）
        ocr_workdir: OCR 进度/图片工作目录
        download_images_dir: 图片下载目录（默认 ocr_workdir）

    Returns:
        ArticleEnvelope dict（失败时含 extraction_status=FETCH_FAILED/OCR_FAILED）
    """
    meta: dict = {}
    if html:
        meta = parse_wechat_metadata(html)
    elif content_text:
        meta = {"content_text": content_text, "images": images or [],
                "parse_notes": [], "raw_title": raw_title,
                "publisher_name": publisher_name, "publish_time": publish_time}
    else:
        # L1 抓取
        fetched = fetch_and_parse(
            url,
            use_cache=use_cache,
            save_cache=save_cache,
            force_refresh=force_refresh,
        )
        if not fetched.get("ok"):
            return {
                "article_id": fetched.get("article_id", ""),
                "url": url,
                "source_url": url,
                "canonical_url": fetched.get("canonical_url", ""),
                "url_hash": fetched.get("url_hash", ""),
                "publisher_name": "",
                "publish_time": "",
                "raw_title": "",
                "raw_html": "",
                "content_blocks": [],
                "images": [],
                "fetch_status": "failed",
                "ocr_status": "skipped",
                "extraction_status": fetched.get("extraction_status", "FETCH_FAILED"),
                "content_text_ratio": 0.0,
                "image_count": 0,
                "evidence_coverage": 0.0,
                "review_reasons": fetched.get("review_reasons", ["fetch_failed"]),
                "field_evidence": [],
                "error": fetched.get("error", ""),
            }
        meta = {
            "raw_title": fetched.get("raw_title", raw_title),
            "publisher_name": fetched.get("publisher_name", publisher_name),
            "publish_time": fetched.get("publish_time", publish_time),
            "content_text": fetched.get("content_text", content_text),
            "images": fetched.get("images") or images or [],
            "parse_notes": fetched.get("parse_notes", []),
        }
        html = fetched.get("raw_html", "")

    # 正文图片化检测
    body_detect = detect_image_body(
        meta.get("content_text", ""),
        meta.get("images", []),
        meta.get("parse_notes", []),
    )
    ocr_status = "skipped"
    content_blocks: list[dict] = []
    field_evidence: list[dict] = []
    ocr_confidence = 0.0

    if body_detect["is_image_body"] and meta.get("images"):
        # L2 OCR
        ocr = OCRModule(workdir=ocr_workdir or download_images_dir or "ocr_work",
                        config=ocr_config)
        items = [
            {"image_id": f"OCR-图{i:02d}", "url": u, "local_path": (
                u if not u.startswith(("http://", "https://")) else ""
            )}
            for i, u in enumerate(meta["images"])
        ]
        results = ocr.ocr_images(items)
        blocks, _noise = ocr_results_to_blocks(results)
        content_blocks = blocks
        ocr_confidence = aggregate_confidence(blocks)
        ocr_status = "done" if any(r.get("status") == "done" for r in results) else "failed"
        # 字段级证据：按扫描出的关键事实归类（与覆盖率检查同字段）
        for b in blocks:
            if b.get("type") != "ocr_fact" or not b.get("text"):
                continue
            btext = b["text"]
            for fact in scan_key_facts(btext):
                try:
                    field_evidence.append(build_field_evidence(
                        value=fact["match"], field=fact["field"],
                        source_type="ocr",
                        image_id=b.get("image_id", ""),
                        quote=btext[:60],
                        confidence=b.get("confidence", 0.9),
                    ))
                except ValueError:
                    pass
            if not scan_key_facts(btext):
                try:
                    field_evidence.append(build_field_evidence(
                        value=btext[:30], field="ocr_fact", source_type="ocr",
                        image_id=b.get("image_id", ""),
                        quote=btext[:60], confidence=b.get("confidence", 0.9),
                    ))
                except ValueError:
                    pass
    elif meta.get("content_text", "").strip():
        # 纯文本文章：生成 article_text 块 + 文本证据
        content_blocks = [{"type": "article_text", "text": meta["content_text"],
                           "confidence": 0.95}]
        for fact in scan_key_facts(meta["content_text"]):
            try:
                field_evidence.append(build_field_evidence(
                    value=fact["match"], field=fact["field"],
                    source_type="page_text", quote=fact["match"],
                    confidence=0.95,
                ))
            except ValueError:
                pass

    # 证据覆盖率
    body_text = " ".join(b.get("text", "") for b in content_blocks)
    cov = compute_evidence_coverage(body_text, field_evidence, "SUCCESS")

    # 状态推导
    review_reasons = list(meta.get("parse_notes", []))
    if ocr_status == "failed":
        extraction_status = "OCR_FAILED"
        review_reasons.append("ocr_failed")
    elif body_detect["is_image_body"] and not content_blocks:
        extraction_status = "OCR_FAILED"
        review_reasons.append("image_body_no_ocr_output")
    else:
        extraction_status = "SUCCESS" if cov["coverage"] >= 1.0 else "PARTIAL"

    envelope = build_article_envelope(
        url=url,
        source_url=url,
        publisher_name=meta.get("publisher_name", ""),
        publish_time=meta.get("publish_time", ""),
        raw_title=meta.get("raw_title", ""),
        raw_html=html,
        content_blocks=content_blocks,
        author=meta.get("publisher_name", ""),
        images=meta.get("images", []),
        fetch_status="ok",
        ocr_status=ocr_status,
        extraction_status=extraction_status,
        content_text_ratio=body_detect["content_text_ratio"],
        image_count=body_detect["image_count"],
        evidence_coverage=cov["coverage"],
        review_reasons=review_reasons,
        field_evidence=field_evidence,
    )
    envelope["body_text"] = body_text
    envelope["ocr_confidence"] = ocr_confidence
    envelope["uncovered_facts"] = cov["uncovered"]
    return envelope


def envelope_to_raw_item(env: dict) -> dict:
    """把 ArticleEnvelope 转为 normalize_item 可消费的 raw_item（保留 mode_c 字段）。"""
    return {
        "title": env.get("raw_title", ""),
        "raw_title": env.get("raw_title", ""),
        "url": env.get("url", ""),
        "content_text": env.get("body_text", ""),
        "full_text": env.get("body_text", ""),
        "content_blocks": env.get("content_blocks", []),
        "author": env.get("publisher_name", ""),
        "account_name": env.get("publisher_name", ""),
        "publish_time": env.get("publish_time", ""),
        "images": env.get("images", []),
        "source": "wechat",
        # ── Mode C 溯源字段（透传到 CreditCardItem） ──
        "source_url": env.get("source_url", env.get("url", "")),
        "canonical_url": env.get("canonical_url", ""),
        "url_hash": env.get("url_hash", ""),
        "fetch_status": env.get("fetch_status", ""),
        "ocr_status": env.get("ocr_status", ""),
        "extraction_status": env.get("extraction_status", ""),
        "content_text_ratio": env.get("content_text_ratio", 0.0),
        "image_count": env.get("image_count", 0),
        "evidence_coverage": env.get("evidence_coverage", 0.0),
        "review_reasons": env.get("review_reasons", []),
        "field_evidence": env.get("field_evidence", []),
    }
