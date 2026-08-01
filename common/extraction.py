"""
Mode C 提取契约 — 字段级证据、提取状态、URL 规范化、ContentBlock 规范

依据 doc/mode_c_公众号文章解析改进规范.md 第 7.2–7.7 节落地。
本模块只定义契约与纯函数，不包含抓取/OCR 等 IO 逻辑（分别在
extractor / ocr 模块中实现）。

设计原则（对应规范 7.3 / 7.4 / 7.7）：
- 字段级 Evidence：每个金额/日期/门槛/名额/比例/次数/适用条件
  必须关联至少一个 evidence 记录；
- source_type 至少支持 page_text / ocr / manual；
- extraction_status 为机器可读状态，禁止用展示文本代替；
- URL 规范化：同时保留 source_url / canonical_url / article_id / url_hash。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ── 提取状态枚举（规范 7.4） ─────────────────────────────
EXTRACTION_STATUS_VALUES = (
    "SUCCESS",      # 全部关键字段可核实
    "PARTIAL",      # 仅部分内容可核实，缺失字段已单独标记
    "FETCH_FAILED", # 页面未成功获取，不得生成活动事实
    "OCR_FAILED",   # 页面获取成功但图片文字无法识别
    "NEEDS_REVIEW", # 自动门禁发现疑似串稿/主题不一致/证据不足
)

# source_type 合法取值（规范 7.3）
EVIDENCE_SOURCE_TYPES = ("page_text", "ocr", "manual")

# ── ContentBlock 类型规范（对应 normalizer 的 block type） ──
CONTENT_BLOCK_TYPES = (
    "article_text",  # 页面正文文本
    "ocr_fact",      # 图片 OCR 识别出的事实性内容
    "ocr_noise",     # OCR 噪声（导航/广告/版权等）
    "image_cta",     # 图片中的引导文案（如"点击办卡""查看详情"）
    "heading",       # 章节标题
    "image_meta",    # 图片元信息（仅记录，不入正文）
)

# ── 文章级元数据字段名（规范 7.3 建议字段） ───────────────
ARTICLE_META_FIELDS = (
    "extraction_status",
    "fetch_status",
    "ocr_status",
    "content_text_ratio",
    "image_count",
    "evidence_coverage",
    "review_reasons",
    "source_url",
    "canonical_url",
    "url_hash",
    "field_evidence",
)


# ── 字段级 Evidence ───────────────────────────────────────

def build_field_evidence(
    value: str,
    field: str,
    source_type: str,
    image_id: str = "",
    quote: str = "",
    confidence: float = 0.0,
    reason: str = "",
) -> dict:
    """构建字段级证据记录（规范 7.3 示例格式）。

    Args:
        value: 提取出的事实值，如 "满18元"
        field: 字段名，如 "threshold" / "amount" / "quota" / "valid_until"
        source_type: "page_text" | "ocr" | "manual"
        image_id: OCR 来源图片标识，如 "OCR-图03"（page_text 时可为空）
        quote: 原文/OCR 引文，用于人工复核
        confidence: 0.0–1.0 置信度
        reason: source_type="manual" 时必须填写人工修正原因
    """
    if source_type not in EVIDENCE_SOURCE_TYPES:
        raise ValueError(
            f"source_type 必须是 {EVIDENCE_SOURCE_TYPES} 之一，收到: {source_type!r}"
        )
    if source_type == "manual" and not reason:
        raise ValueError("manual 类型证据必须提供修正原因 (reason)")
    return {
        "value": value,
        "field": field,
        "source_type": source_type,
        "image_id": image_id,
        "quote": quote,
        "confidence": round(float(confidence), 3),
        "reason": reason,
    }


def validate_field_evidence(ev: dict) -> list[str]:
    """校验一条证据记录，返回问题列表（空列表 = 合法）。"""
    problems: list[str] = []
    if not isinstance(ev, dict):
        return ["evidence 必须是 dict"]
    if not ev.get("value"):
        problems.append("evidence.value 缺失")
    if not ev.get("field"):
        problems.append("evidence.field 缺失")
    if ev.get("source_type") not in EVIDENCE_SOURCE_TYPES:
        problems.append(f"evidence.source_type 非法: {ev.get('source_type')!r}")
    if ev.get("source_type") == "ocr" and not ev.get("image_id"):
        problems.append("ocr 证据缺少 image_id")
    if ev.get("source_type") == "manual" and not ev.get("reason"):
        problems.append("manual 证据缺少 reason")
    try:
        conf = float(ev.get("confidence", 0.0))
        if not (0.0 <= conf <= 1.0):
            problems.append(f"confidence 越界: {conf}")
    except (TypeError, ValueError):
        problems.append("confidence 非数字")
    return problems


# ── URL 规范化与幂等（规范 7.7） ─────────────────────────

# 微信文章 URL 上可丢弃的无意义追踪参数
_WECHAT_TRACKING_PARAMS = {"scene", "from", "isappinstalled", "subscene", "sessionid"}


def canonicalize_url(url: str) -> str:
    """规范化 URL：去除无关查询参数，得到稳定 canonical_url。

    规则：
    - 仅处理 http/https；
    - 统一去除 fragment 与已知追踪参数；
    - 其余参数按键名排序后保留，保证确定性；
    - 微信 /s/{id} 文章仅保留 path 本身。
    """
    if not url:
        return ""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return url
    query = parts.query
    if "mp.weixin.qq.com" in parts.netloc and re.search(r"/s/[A-Za-z0-9_-]+", parts.path):
        # 微信文章：仅保留 /s/<id>，丢弃全部查询参数
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
            if k not in _WECHAT_TRACKING_PARAMS]
    kept.sort(key=lambda kv: (kv[0], kv[1]))
    new_query = urlencode(kept)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, ""))


def url_hash(url: str) -> str:
    """基于 canonical_url 生成稳定 hash（用于缓存/去重/断点续跑）。"""
    c = canonicalize_url(url)
    return hashlib.sha256(c.encode("utf-8")).hexdigest()[:16] if c else ""


def article_id_from_url(url: str) -> str:
    """基于 canonical_url 生成稳定文章 ID（幂等、可跨批一致）。"""
    c = canonicalize_url(url)
    return f"wx_{hashlib.md5(c.encode('utf-8')).hexdigest()[:12]}" if c else ""


# ── ContentBlock 构建辅助 ─────────────────────────────────

def build_content_block(
    btype: str,
    text: str = "",
    image_id: str = "",
    confidence: float = 0.0,
    **extra: Any,
) -> dict:
    """构建规范化 ContentBlock。

    Args:
        btype: CONTENT_BLOCK_TYPES 之一
        text: 块文本（ocr_fact 为识别文本，article_text 为页面文本）
        image_id: 关联图片标识（ocr 类块必填）
        confidence: OCR 识别置信度（可选）
    """
    if btype not in CONTENT_BLOCK_TYPES:
        raise ValueError(f"block type 必须是 {CONTENT_BLOCK_TYPES} 之一，收到: {btype!r}")
    block: dict[str, Any] = {"type": btype, "text": text}
    if image_id:
        block["image_id"] = image_id
    if btype in ("ocr_fact", "ocr_noise") and confidence:
        block["confidence"] = round(float(confidence), 3)
    block.update(extra)
    return block


def extract_url_meta(url: str) -> dict:
    """生成 URL 元数据：source_url / canonical_url / article_id / url_hash。"""
    return {
        "source_url": url,
        "canonical_url": canonicalize_url(url),
        "article_id": article_id_from_url(url),
        "url_hash": url_hash(url),
    }


# ── 提取状态工具 ──────────────────────────────────────────

def compute_extraction_status(
    fetch_ok: Optional[bool] = None,
    ocr_ok: Optional[bool] = None,
    evidence_coverage: float = 0.0,
    review_reasons: Optional[list[str]] = None,
) -> str:
    """按规范 7.4 计算 extraction_status。

    优先级：
        FETCH_FAILED > OCR_FAILED > NEEDS_REVIEW > PARTIAL > SUCCESS
    """
    reasons = review_reasons or []
    if fetch_ok is False:
        return "FETCH_FAILED"
    if ocr_ok is False:
        return "OCR_FAILED"
    if reasons:
        return "NEEDS_REVIEW"
    if evidence_coverage < 1.0:
        return "PARTIAL"
    return "SUCCESS"
