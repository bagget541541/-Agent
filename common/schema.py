"""
信用卡资讯统一数据契约（Standard Schema）

本模块定义整个信用卡周报流水线的统一中间数据格式。
所有上游 skill（news-analyzer、wechat-article-extractor）的输出，
以及所有下游 skill（word-merger、card-holding-suggestion）的输入，
都应以本标准格式为契约。

Schema Version: 1.1 — 新增审核/质量字段（confidence, evidence, flags 等）

使用方式：
    from common.schema import CreditCardItem, CreditCardBatch

    item = CreditCardItem(
        source="wechat",
        category="活动",
        bank="中信银行",
        title="中信消费返现",
        ...
    )
    batch = CreditCardBatch(items=[item, ...])
    batch.save_json("output.json")          # 写出标准格式
    batch2 = CreditCardBatch.load_json(...)  # 读入标准格式
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional

# ── 标准化分类枚举 ─────────────────────────────────────
# 所有 skill 必须使用以下 5 个分类名称，不再使用变体
STANDARD_CATEGORIES = {"新卡", "权益变更", "活动", "公告", "其他"}

# 非标准分类 → 标准分类的映射表（用于上游数据清洗）
CATEGORY_MAP = {
    "新卡发布": "新卡",
    "新发行信用卡": "新卡",
    "新卡发行": "新卡",
    "首发": "新卡",
    "信用卡活动": "活动",
    "活动": "活动",
    "优惠活动": "活动",
    "权益变更": "权益变更",
    "权益调整": "权益变更",
    "权益更新": "权益变更",
    "公告": "公告",
    "公告或其他": "公告",

}


def normalize_category(raw: str) -> str:
    """将非标准分类名映射为标准分类名，未知统一归为“其他”。"""
    if raw in STANDARD_CATEGORIES:
        return raw
    return CATEGORY_MAP.get(raw, "其他")


# ── 标准化数据源枚举 ────────────────────────────────────
STANDARD_SOURCES = {"website", "wechat"}


# ── 核心数据模型 ────────────────────────────────────────

def _auto_source_type(source: str) -> str:
    """根据 source 自动推导 source_type。"""
    if source == "website":
        return "官网公告"
    elif source == "wechat":
        return "公众号文章"
    return source

class CreditCardItem:
    """单条信用卡资讯的标准化表示。

    字段说明：
        source       — 数据来源: "website" | "wechat"
        source_type  — 来源详细类型: "官网公告" | "公众号文章"
        category     — 标准化分类: "新卡" | "权益变更" | "活动" | "公告" | "其他"
        bank         — 发卡银行名称（如"中信银行""建设银行"），未知留空
        issuer_bank  — 发卡机构全称（如"中信银行信用卡中心"）
        publisher_name — 发布者名称（公众号/官网发布机构）
        source_name  — 来源渠道名
        title        — 资讯标题（尽量简洁，10-15字）
        raw_title    — 原始标题（抓取时的原文标题）
        normalized_title — 规范化后的标题（去噪后）
        display_title    — 展示用标题（最终修正后）
        highlight_summary — 亮点摘要（一句话吸引点）
        title_source — 标题来源标记: "raw" | "normalized" | "generated"
        url          — 原文链接
        raw_text     — 提取的原始全文文本
        content_blocks — 内容块列表（按段落/图片/表格分隔的区块）
        images       — 本地图片路径列表（绝对路径）
        structured   — 按品类组织的结构化字段 dict（旧版模式）：
                        新卡 → {卡种, 卡亮点, 适用人群, 来源, 详情}
                        权益变更 → {消息时间, 影响范围, 变更内容, 变更分析}
                        活动 → {活动内容, 活动时间, 适用人群}
                        公告 → {消息内容, 点评}
        structured_clean — 清洗后的结构化字段（去噪音版本）
        author       — 作者/公众号名
        publish_time — 原文发布时间（如 "2026.05.08"）
        extracted_at — 提取时间（ISO格式）
        item_id      — 唯一标识（自动生成）
        confidence   — 可信度评分 dict: {"overall": 0.0-1.0, "category": ..., "bank": ..., "title": ..., "structured": ...}
        evidence     — 依据 dict: {"category": ["关键词1", "标题模式"], "bank": ["来源域名"], ...}
        noise_flags  — 噪音标记列表: ["navigation_text", "ocr_noise", "boilerplate"]
        review_flags — 审核标记列表: ["needs_category_review", "needs_title_review", ...]
        category_candidates — 候选类别及分数: [["活动", 0.71], ["公告", 0.58]]
    """

    def __init__(
        self,
        *,
        source: str = "",
        source_type: str = "",
        category: str = "",
        bank: str = "",
        issuer_bank: str = "",
        publisher_name: str = "",
        source_name: str = "",
        title: str = "",
        raw_title: str = "",
        normalized_title: str = "",
        display_title: str = "",
        highlight_summary: str = "",
        title_source: str = "",
        url: str = "",
        raw_text: str = "",
        content_blocks: Optional[list[dict]] = None,
        images: Optional[list[str]] = None,
        structured: Optional[dict] = None,
        structured_clean: Optional[dict] = None,
        author: str = "",
        publish_time: str = "",
        extracted_at: str = "",
        item_id: str = "",
        confidence: Optional[dict] = None,
        evidence: Optional[dict] = None,
        noise_flags: Optional[list[str]] = None,
        review_flags: Optional[list[str]] = None,
        category_candidates: Optional[list[list]] = None,
        # 多主题拆分追溯字段
        article_id: str = "",
        topic_id: str = "",
        source_article_title: str = "",
        is_multi_topic_split: bool = False,
        topic_split_confidence: float = 0.0,
        topic_split_signals: Optional[list[str]] = None,
    ):
        self.source = source
        self.source_type = source_type or _auto_source_type(source)
        self.category = normalize_category(category) if category else ""
        self.bank = bank
        self.issuer_bank = issuer_bank or bank
        self.publisher_name = publisher_name
        self.source_name = source_name
        self.title = title
        self.raw_title = raw_title or title
        self.normalized_title = normalized_title or title
        self.display_title = display_title or title
        self.highlight_summary = highlight_summary
        self.title_source = title_source or ("raw" if raw_title else "generated" if not title else "")
        self.url = url
        self.raw_text = raw_text
        self.content_blocks = content_blocks or []
        self.images = images or []
        self.structured = structured or {}
        self.structured_clean = structured_clean or {}
        self.author = author
        self.publish_time = publish_time
        self.extracted_at = extracted_at or datetime.now().isoformat(timespec="seconds")
        self.item_id = item_id or uuid.uuid4().hex[:12]
        self.confidence = confidence or {}
        self.evidence = evidence or {}
        self.noise_flags = noise_flags or []
        self.review_flags = review_flags or []
        self.category_candidates = category_candidates or []
        # 多主题拆分追溯字段
        self.article_id = article_id
        self.topic_id = topic_id
        self.source_article_title = source_article_title
        self.is_multi_topic_split = is_multi_topic_split
        self.topic_split_confidence = topic_split_confidence
        self.topic_split_signals = topic_split_signals or []

    # ── 序列化 ────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "source": self.source,
            "source_type": self.source_type,
            "category": self.category,
            "bank": self.bank,
            "issuer_bank": self.issuer_bank,
            "publisher_name": self.publisher_name,
            "source_name": self.source_name,
            "title": self.title,
            "raw_title": self.raw_title,
            "normalized_title": self.normalized_title,
            "display_title": self.display_title,
            "highlight_summary": self.highlight_summary,
            "title_source": self.title_source,
            "url": self.url,
            "raw_text": self.raw_text,
            "content_blocks": self.content_blocks,
            "images": self.images,
            "structured": self.structured,
            "structured_clean": self.structured_clean,
            "author": self.author,
            "publish_time": self.publish_time,
            "extracted_at": self.extracted_at,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "noise_flags": self.noise_flags,
            "review_flags": self.review_flags,
            "category_candidates": self.category_candidates,
            "article_id": self.article_id,
            "topic_id": self.topic_id,
            "source_article_title": self.source_article_title,
            "is_multi_topic_split": self.is_multi_topic_split,
            "topic_split_confidence": self.topic_split_confidence,
            "topic_split_signals": self.topic_split_signals,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CreditCardItem":
        return cls(
            source=d.get("source", ""),
            source_type=d.get("source_type", ""),
            category=d.get("category", ""),
            bank=d.get("bank", ""),
            issuer_bank=d.get("issuer_bank", ""),
            publisher_name=d.get("publisher_name", ""),
            source_name=d.get("source_name", ""),
            title=d.get("title", ""),
            raw_title=d.get("raw_title", ""),
            normalized_title=d.get("normalized_title", ""),
            display_title=d.get("display_title", ""),
            highlight_summary=d.get("highlight_summary", ""),
            title_source=d.get("title_source", ""),
            url=d.get("url", ""),
            raw_text=d.get("raw_text", ""),
            content_blocks=d.get("content_blocks"),
            images=d.get("images"),
            structured=d.get("structured"),
            structured_clean=d.get("structured_clean"),
            author=d.get("author", ""),
            publish_time=d.get("publish_time", ""),
            extracted_at=d.get("extracted_at", ""),
            item_id=d.get("item_id", ""),
            confidence=d.get("confidence"),
            evidence=d.get("evidence"),
            noise_flags=d.get("noise_flags"),
            review_flags=d.get("review_flags"),
            category_candidates=d.get("category_candidates"),
            article_id=d.get("article_id", ""),
            topic_id=d.get("topic_id", ""),
            source_article_title=d.get("source_article_title", ""),
            is_multi_topic_split=d.get("is_multi_topic_split", False),
            topic_split_confidence=d.get("topic_split_confidence", 0.0),
            topic_split_signals=d.get("topic_split_signals"),
        )

    def __repr__(self) -> str:
        return (
            f"<CreditCardItem [{self.category}] {self.bank} {self.title[:20]}>"
        )


# ── 批次容器 ────────────────────────────────────────────

class CreditCardBatch:
    """一批信用卡资讯的集合，用于文件级读写。"""

    SCHEMA_VERSION = "1.1"

    def __init__(self, items: Optional[list[CreditCardItem]] = None, batch_label: str = ""):
        self.items = items or []
        self.batch_label = batch_label or f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.generated_at = datetime.now().isoformat(timespec="seconds")

    def add(self, item: CreditCardItem) -> None:
        self.items.append(item)

    def size(self) -> int:
        return len(self.items)

    def by_category(self, category: str) -> list[CreditCardItem]:
        """按标准化分类筛选。"""
        cat = normalize_category(category)
        return [it for it in self.items if it.category == cat]

    # ── JSON 文件读写 ──────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "batch_label": self.batch_label,
            "total": len(self.items),
            "items": [it.to_dict() for it in self.items],
        }

    def save_json(self, filepath: str, *, ensure_ascii: bool = False, indent: int = 2) -> str:
        """写出标准格式 JSON 文件。返回写入的绝对路径。"""
        abs_path = os.path.abspath(filepath)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=ensure_ascii, indent=indent)
        return abs_path

    @classmethod
    def load_json(cls, filepath: str) -> "CreditCardBatch":
        """从标准格式 JSON 文件读取。"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = [CreditCardItem.from_dict(it) for it in data.get("items", [])]
        return cls(
            items=items,
            batch_label=data.get("batch_label", ""),
        )

    def __repr__(self) -> str:
        return f"<CreditCardBatch {len(self.items)} items, label={self.batch_label}>"
