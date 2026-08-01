"""
ArticleEnvelope — 公众号文章抓取后的中间容器

用于在抓取层与主题拆分层之间传递结构化数据。
不直接进入标准化链路，而是经过 topic_splitter 处理后
生成 TopicCandidate 列表再送入 normalizer。
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from common.extraction import (
    ARTICLE_META_FIELDS,
    compute_extraction_status,
    extract_url_meta,
    validate_field_evidence,
)


def build_article_envelope(
    article_id: str = "",
    url: str = "",
    publisher_name: str = "",
    publish_time: str = "",
    raw_title: str = "",
    raw_html: str = "",
    content_blocks: Optional[list[dict]] = None,
    author: str = "",
    images: Optional[list[str]] = None,
    source_url: str = "",
    canonical_url: str = "",
    url_hash: str = "",
    fetch_status: str = "",
    ocr_status: str = "",
    extraction_status: str = "",
    content_text_ratio: float = 0.0,
    image_count: int = 0,
    evidence_coverage: float = 0.0,
    review_reasons: Optional[list[str]] = None,
    field_evidence: Optional[list[dict]] = None,
    **extra: Any,
) -> dict:
    """构建标准化 ArticleEnvelope 字典。

    Args:
        article_id: 文章唯一 ID（自动生成若为空）
        url: 原文链接
        publisher_name: 公众号名称
        publish_time: 发布时间
        raw_title: 原始标题
        raw_html: 原始 HTML（可选保留）
        content_blocks: 内容块列表 [{"type":..., "text":..., ...}]
        author: 作者
        images: 图片 URL 或本地路径列表
        source_url: 用户输入的原始 URL（规范 7.7）
        canonical_url: 规范化后的 URL
        url_hash: 基于 canonical_url 的稳定 hash
        fetch_status: 抓取状态（如 "ok" / "failed"）
        ocr_status: OCR 状态（如 "done" / "failed" / "skipped"）
        extraction_status: SUCCESS | PARTIAL | FETCH_FAILED | OCR_FAILED | NEEDS_REVIEW
        content_text_ratio: 正文有效文本占正文总内容比例（0-1）
        image_count: 正文图片数量
        evidence_coverage: 关键字段证据覆盖率（0-1）
        review_reasons: 进入人工复核的原因列表
        field_evidence: 字段级证据列表（规范 7.3）
        **extra: 其他保留字段

    Returns:
        标准化的 ArticleEnvelope 字典
    """
    # URL 元数据：未显式传入时自动派生（幂等）
    url_meta = extract_url_meta(url or source_url)
    if not article_id:
        article_id = url_meta["article_id"] or f"wx_{hashlib.md5(url.encode()).hexdigest()[:12]}"
    if not canonical_url:
        canonical_url = url_meta["canonical_url"]
    if not url_hash:
        url_hash = url_meta["url_hash"]

    # 校验字段级证据（不合法则记入 review_reasons）
    reasons = list(review_reasons or [])
    evidence_list = list(field_evidence or [])
    for ev in evidence_list:
        for problem in validate_field_evidence(ev):
            reasons.append(f"evidence_invalid: {problem}")

    # 自动推导 extraction_status（未显式指定时）
    if not extraction_status:
        extraction_status = compute_extraction_status(
            fetch_ok=None if not fetch_status else (fetch_status == "ok"),
            ocr_ok=None if not ocr_status else (ocr_status == "done"),
            evidence_coverage=evidence_coverage,
            review_reasons=reasons,
        )

    return {
        "article_id": article_id,
        "url": url,
        "source_url": source_url or url,
        "canonical_url": canonical_url,
        "url_hash": url_hash,
        "publisher_name": publisher_name,
        "publish_time": publish_time,
        "raw_title": raw_title,
        "raw_html": raw_html,
        "content_blocks": content_blocks or [],
        "author": author,
        "images": images or [],
        # ── Mode C 提取状态与溯源字段 ──
        "fetch_status": fetch_status,
        "ocr_status": ocr_status,
        "extraction_status": extraction_status,
        "content_text_ratio": round(float(content_text_ratio or 0.0), 3),
        "image_count": int(image_count or len(images or [])),
        "evidence_coverage": round(float(evidence_coverage or 0.0), 3),
        "review_reasons": reasons,
        "field_evidence": evidence_list,
        "topic_split_meta": {
            "is_multi_topic_candidate": False,
            "split_confidence": 0.0,
            "signals": [],
        },
        **extra,
    }


def build_topic_candidate(
    article_id: str,
    source_article_title: str,
    start_block: int,
    end_block: int,
    headline: str,
    blocks: list[dict],
    topic_type_hint: str = "",
    split_confidence: float = 0.0,
    split_signals: Optional[list[str]] = None,
    url: str = "",
    publisher_name: str = "",
    publish_time: str = "",
    images: Optional[list[str]] = None,
) -> dict:
    """构建 TopicCandidate 字典。

    Args:
        article_id: 所属文章 ID
        source_article_title: 原始文章标题
        start_block: 起始 block 索引（含）
        end_block: 结束 block 索引（含）
        headline: 主题标题（优于整篇标题）
        blocks: 该主题范围内的 content_blocks
        topic_type_hint: 主题类型提示（非最终分类）
        split_confidence: 拆分置信度
        split_signals: 拆分信号列表
        url: 原文链接（追溯用）
        publisher_name: 公众号名称
        publish_time: 发布时间
        images: 该主题关联的图片

    Returns:
        TopicCandidate 字典
    """
    topic_seq = 1  # 由调用方覆盖
    return {
        "topic_id": f"{article_id}_t{topic_seq}",
        "article_id": article_id,
        "source_article_title": source_article_title,
        "url": url,
        "publisher_name": publisher_name,
        "publish_time": publish_time,
        "start_block": start_block,
        "end_block": end_block,
        "headline": headline,
        "blocks": blocks,
        "topic_type_hint": topic_type_hint,
        "split_confidence": split_confidence,
        "split_signals": split_signals or [],
        "images": images or [],
    }
