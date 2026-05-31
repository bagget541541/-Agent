"""
统一标准化入口模块

设计目标：
- 消除 _agent.py、news-analyzer/convert_to_standard.py、wechat-article-extractor/convert_to_standard.py
  各自维护标准化规则的问题
- 提供单一入口 normalize_item() / normalize_batch()
- 集成分类器、来源识别、展示字段生成、结构化生成

使用方式：
    from common.normalizer import normalize_item, normalize_batch

    item = normalize_item(raw_dict, source="wechat")
    batch = normalize_batch(raw_items, source="website", bank="招商银行")
"""

import re

from common.schema import CreditCardItem, CreditCardBatch
from common.classifier import classify_item
from common.entity_resolver import resolve_bank
from common.display_fields import generate_display_fields
from common.review import generate_review_flags


# ── Internal: structured field generation ─────────────────────────────────

# 公众号文章常见营销引言前缀，结构化构建时应跳过
_MARKETING_INTRO_REGEX = re.compile(
    r'^(说在前头.*?[\。\！\n]'
    r'|自从公众号推送机制.*?[\。\！\n]'
    r'|大行白金卡权益一缩再缩.*?[\。\！\n]'
    r'|经典小神卡迎来反转.*?[\。\！\n]'
    r'|好在还有这些可以选择.*?[\。\！\n]'
    r')',
    re.DOTALL,
)


def _trim_marketing_intro(text: str) -> str:
    """去掉公众号文章开头的广告/营销引导段落。"""
    if not text:
        return text
    # 移除匹配的引言前缀
    while True:
        m = _MARKETING_INTRO_REGEX.match(text)
        if not m:
            break
        text = text[m.end():].lstrip()
    return text


def _safe_truncate(text: str, max_chars: int = 500) -> str:
    """按句子边界截断文本，避免在词中间截断。"""
    if not text or len(text) <= max_chars:
        return text
    # 优先在句号/感叹号/问号处截断
    candidates = []
    for sep in ['。', '！', '？', '\n']:
        idx = text.rfind(sep, 0, max_chars)
        if idx > max_chars * 0.5:
            candidates.append((idx + 1, sep))
    if not candidates:
        # 退到空格截断
        idx = text.rfind(' ', 0, max_chars)
        return text[:idx] + '…' if idx > 10 else text[:max_chars] + '…'
    # 选最接近 max_chars 的切分点
    best = max(candidates, key=lambda x: x[0])
    return text[:best[0]]


def _build_structured_for_category(
    category: str,
    title: str,
    text: str,
    raw_text: str = "",
    author: str = "",
    url: str = "",
) -> dict:
    """从正文提取结构化字段，按分类模板填充。

    纯图片文章（无 content_text）：用 raw_text（OCR 分析）构建。
    """
    # 取源文本：优先用 clean_text，否则取 raw_text（去掉营销引言）
    source_text = text if text.strip() else _trim_marketing_intro(raw_text or title)

    structured: dict[str, str] = {}

    if category == "新卡":
        structured["卡种"] = title
        structured["卡亮点"] = ""
        structured["适用人群"] = "信用卡持卡人"
        structured["来源"] = author or url
        structured["详情"] = _safe_truncate(source_text, 500) if source_text else title

    elif category == "活动":
        structured["活动内容"] = _safe_truncate(source_text, 300) if source_text else title
        structured["活动时间"] = ""
        structured["适用人群"] = "信用卡持卡人"

    elif category == "权益变更":
        structured["消息时间"] = ""
        structured["影响范围"] = ""
        structured["变更内容"] = _safe_truncate(source_text, 500) if source_text else title
        structured["变更分析"] = ""

    elif category == "公告":
        structured["消息内容"] = _safe_truncate(source_text, 500) if source_text else title
        structured["点评"] = ""

    else:
        structured["详细内容"] = _safe_truncate(source_text, 500) if source_text else title

    return structured


def _extract_ocr_field(ocr_text: str, pattern: str) -> str:
    """从 OCR 文本中提取某个键对应的值，去重合并。"""
    import re
    values = []
    for m in re.finditer(pattern, ocr_text):
        for g in range(1, m.lastindex + 1 if m.lastindex else 1):
            try:
                v = m.group(g)
                if v and v.strip() not in ("未提及", "未说明", "未明确显示", "无", ""):
                    v = v.strip().rstrip("。，")
                    if v not in values:
                        values.append(v)
                    break
            except IndexError:
                continue
    return "；".join(values)


def _build_image_structured(title: str, ocr_text: str, category: str) -> dict:
    """从纯图片文章的 OCR 分析文本中提取结构化信息。"""
    import re

    def _extract_all_lines(pattern: str) -> str:
        lines = []
        for m in re.finditer(pattern, ocr_text, re.MULTILINE):
            lines.append(m.group(0).strip())
        return "\n".join(lines)

    card_name = _extract_ocr_field(ocr_text, r"卡种[名称]*[：:]\s*(.*)")
    bank_name = _extract_ocr_field(ocr_text, r"银行[名称]*[：:]\s*(.*)")
    benefit = _extract_ocr_field(
        ocr_text,
        r"(?:核心)?权益[：:]\s*(.*)|"
        r"核心[：:]\s*(.*)|"
        r"活动内容[：:]\s*(.*)|"
        r"优惠内容[：:]\s*(.*)"
    )
    price = _extract_ocr_field(
        ocr_text,
        r"(?:适用)?价格[：:]\s*(.*)|优惠价格[：:]\s*(.*)|(?:.*?)(\d+元[^。\n]*)"
    )
    time_info = _extract_ocr_field(
        ocr_text,
        r"活动时间[：:]\s*(.*)|有效期[：:]\s*(.*)|时间[：:]\s*(.*)"
    )
    conditions = _extract_ocr_field(
        ocr_text,
        r"适用条件[：:]\s*(.*)|适用人群[：:]\s*(.*)"
    )

    benefit_parts = [b for b in [benefit, price] if b]
    benefit_text = (
        "；".join(benefit_parts)
        if benefit_parts
        else _extract_all_lines(r"(?:核心权益|优惠内容|活动简介)[：:]\s*.*")
    )

    structured: dict[str, str] = {}

    if category == "新卡":
        structured["卡种"] = card_name or title
        structured["卡亮点"] = benefit_text[:200]
        structured["适用人群"] = conditions or "信用卡持卡人"
        structured["来源"] = bank_name or title
        structured["详情"] = ocr_text[:500] if ocr_text else title
    elif category == "活动":
        structured["活动内容"] = benefit_text[:300] or title
        structured["活动时间"] = time_info or "详见活动说明"
        structured["适用人群"] = conditions or "信用卡持卡人"
    elif category == "权益变更":
        structured["消息时间"] = time_info or ""
        structured["影响范围"] = conditions or "信用卡持卡人"
        structured["变更内容"] = benefit_text[:500] or title
        structured["变更分析"] = ""
    elif category == "公告":
        structured["消息内容"] = benefit_text[:300] or title
        structured["点评"] = ""
    else:
        structured["详细内容"] = ocr_text[:500] if ocr_text else title

    # 干净兜底
    has_any_value = any(v for v in structured.values())
    if not has_any_value and ocr_text:
        summary = ocr_text[:500]
        if category in ("活动", "权益变更"):
            structured["活动内容" if category == "活动" else "变更内容"] = summary
        elif category == "新卡":
            structured["详情"] = summary

    return structured


# ── Main normalize functions ──────────────────────────────────────────────

def normalize_item(
    raw_item: dict,
    source: str = "",
    bank: str = "",
    skip_auto_classify: bool = False,
) -> CreditCardItem:
    """将任意来源的原始数据标准化为 CreditCardItem。

    执行的操作（按顺序）：
    1. 提取 raw_text、title、url、author、images、structured
    2. 调用 classifier 自动分类（除非 skip_auto_classify=True）
    3. 调用 entity_resolver 解析银行和来源
    4. 生成 structured（如原始 structured 为空）
    5. 调用 display_fields 生成展示字段
    6. 初始化 confidence / evidence / review_flags
    7. 自动标记审核项

    Args:
        raw_item: 上游原始数据 dict
        source: 数据来源 "website" | "wechat"
        bank: 银行名称（已知时传入）
        skip_auto_classify: 为 True 时跳过自动分类（保留 raw_item 中的 category）

    Returns:
        CreditCardItem 实例
    """
    if not isinstance(raw_item, dict):
        raw_item = {}

    # ── 0. 提取 content_blocks（如有）→ 用于获取清洁文本和噪音标记 ──
    content_blocks = raw_item.get("content_blocks") or []
    noise_flags: list[str] = []
    if content_blocks:
        # 从 blocks 获取清洁文本（只取文章正文 + OCR 事实）
        clean_text_parts = [
            b["text"] for b in content_blocks
            if b.get("type") in ("article_text", "ocr_fact") and b.get("text")
        ]
        clean_text = "\n\n".join(clean_text_parts)
        # 从 blocks 提取噪音标记
        for b in content_blocks:
            btype = b.get("type", "")
            if btype == "ocr_noise":
                noise_flags.append("ocr_noise")
            elif btype == "image_cta":
                noise_flags.append("image_cta")
        # 如果有 ocr_noise 块，打 review 标
        if any(b.get("type") == "ocr_noise" for b in content_blocks):
            noise_flags.append("has_ocr_noise")
    else:
        clean_text = ""

    # ── 1. 提取原始字段 ──
    raw_text = (
        raw_item.get("content_text")
        or raw_item.get("raw_text")
        or raw_item.get("full_text")
        or raw_item.get("text")
        or clean_text
        or ""
    )
    images = raw_item.get("images") or raw_item.get("image_urls") or []
    title = raw_item.get("title", "")
    # text 优先用 content_blocks 清洁文本（如果有），否则 fallback
    text = clean_text or raw_item.get("content_text") or raw_item.get("full_text") or ""
    author = raw_item.get("author") or raw_item.get("account_name") or ""
    url = raw_item.get("url", "")
    publish_time = raw_item.get("publish_time") or raw_item.get("pub_date") or raw_item.get("publish_date") or ""

    # ── 2. 分类 ──
    existing_category = raw_item.get("category", "")
    if existing_category and skip_auto_classify:
        category = existing_category
        category_candidates = []
        classify_evidence = [f"保留原始分类: {existing_category}"]
    else:
        classify_result = classify_item(title, text or raw_text)
        category = classify_result["category"]
        category_candidates = classify_result["category_candidates"]
        classify_evidence = classify_result["evidence"]

    # ── 3. 来源识别 ──
    # bank 参数优先，其次 raw_item 内 bank 字段
    actual_bank = bank or raw_item.get("bank", "")
    entity_result = resolve_bank(
        title=title,
        author=author,
        text=text or raw_text,
        explicit_bank=actual_bank,
    )

    # ── 4. 生成 structured ──
    existing_structured = raw_item.get("structured") or {}
    if existing_structured:
        structured = existing_structured
        structured_evidence = ["保留原始 structured"]
    else:
        # 纯图片文章
        is_image_article = not text.strip() and images
        if is_image_article:
            structured = _build_image_structured(title, raw_text, category)
            structured_evidence = ["从 OCR 分析构建 structured"]
        else:
            structured = _build_structured_for_category(
                category, title, text,
                raw_text=raw_text, author=author, url=url,
            )
            structured_evidence = [f"从正文构建 structured ({category})"]

    # ── 4.5 生成 structured_clean（去营销引言/噪音版本） ──
    structured_clean: dict[str, str] = {}
    for k, v in structured.items():
        if v:
            cleaned = _trim_marketing_intro(v)
            # 去掉 "[图片核心内容 - xxx]" 等纯噪音标记
            cleaned = re.sub(r'\[图片核心内容\s*-\s*[^\]]*\]', '', cleaned).strip()
            # 去掉 "（以上内容为广告）" 尾巴
            cleaned = re.sub(r'（以上内容为广告）', '', cleaned).strip()
            if cleaned:
                structured_clean[k] = cleaned

    # ── 5. 展示字段 ──
    display_result = generate_display_fields(
        bank=entity_result["bank"],
        category=category,
        structured=structured,
        structured_clean=structured_clean,
        raw_title=title,
        raw_text=text or raw_text,
    )

    # ── 6. 可信度 ──
    confidence = {
        "overall": 0.7,
        "category": 0.7 if category_candidates else 0.5,
        "bank": 0.9 if entity_result["bank"] != "未知" else 0.0,
        "title": 0.6 if display_result["title_source"] == "generated" else 0.9,
        "structured": 0.7 if structured else 0.3,
    }

    evidence = {}
    if entity_result.get("evidence"):
        evidence["bank"] = entity_result["evidence"]
    if classify_evidence:
        evidence["category"] = classify_evidence
    if display_result.get("evidence"):
        evidence["title"] = display_result["evidence"]

    item = CreditCardItem(
        source=source or raw_item.get("source", ""),
        source_type="公众号文章" if source == "wechat" else "官网公告",
        category=category,
        bank=entity_result["bank"],
        issuer_bank=entity_result["issuer_bank"],
        publisher_name=entity_result["publisher_name"],
        source_name=entity_result["source_name"],
        title=display_result["title"],
        raw_title=title,
        normalized_title=display_result["normalized_title"],
        display_title=display_result["display_title"],
        highlight_summary=display_result["highlight_summary"],
        title_source=display_result["title_source"],
        url=url,
        raw_text=raw_text,
        content_blocks=content_blocks or raw_item.get("content_blocks") or [],
        images=images if isinstance(images, list) else [],
        structured=structured,
        structured_clean=structured_clean,
        author=author,
        publish_time=publish_time,
        confidence=confidence,
        evidence=evidence,
        noise_flags=noise_flags,
        category_candidates=category_candidates,
    )

    # 自动标记审核项
    item.review_flags = generate_review_flags(item)

    # P0-4: 强制图片按 item_id 隔离 → data/images/{item_id}/
    if item.images:
        from common.utils import centralize_images
        centralized = centralize_images(item.images, item.item_id)
        if centralized:
            item.images = centralized

    return item


def normalize_batch(
    raw_items: list[dict],
    source: str = "",
    bank: str = "",
    batch_label: str = "",
    skip_auto_classify: bool = False,
) -> CreditCardBatch:
    """批量标准化，返回 CreditCardBatch。

    Args:
        raw_items: 原始数据 dict 列表
        source: 数据来源（所有条目共享）
        bank: 银行名称（所有条目共享，可被条目级覆盖）
        batch_label: 批次标签
        skip_auto_classify: 跳过自动分类

    Returns:
        CreditCardBatch 实例
    """
    items = []
    for raw in raw_items:
        item_bank = raw.get("bank", bank) if isinstance(raw, dict) else bank
        item = normalize_item(
            raw, source=source, bank=item_bank,
            skip_auto_classify=skip_auto_classify,
        )
        items.append(item)

    return CreditCardBatch(items=items, batch_label=batch_label)


# ── TopicCandidate 标准化 ───────────────────────────────


def normalize_topic(
    topic_candidate: dict,
    article_meta: Optional[dict] = None,
    source: str = "wechat",
    bank: str = "",
    skip_auto_classify: bool = False,
) -> CreditCardItem:
    """将 TopicCandidate 标准化为 CreditCardItem。

    这是"多主题拆分"链路的核心桥接函数：
    1. 从 topic_candidate 提取 headline / blocks → 构造 raw_item dict
    2. 调用 normalize_item（复用现有标准化逻辑）
    3. 回填多主题拆分追溯字段

    Args:
        topic_candidate: TopicCandidate 字典
        article_meta: 原始文章元信息（用于追溯字段回填）
        source: 数据来源
        bank: 银行名称（已知时传入）
        skip_auto_classify: 是否跳过自动分类

    Returns:
        CreditCardItem 实例
    """
    if not isinstance(topic_candidate, dict):
        topic_candidate = {}

    blocks = topic_candidate.get("blocks") or []
    headline = topic_candidate.get("headline", "")
    source_title = topic_candidate.get("source_article_title", "")
    url = topic_candidate.get("url", "")
    publisher_name = topic_candidate.get("publisher_name", "")
    publish_time = topic_candidate.get("publish_time", "")
    images = topic_candidate.get("images") or []

    # 从 topic 范围内的 blocks 构建清洁文本
    clean_text_parts = [
        b["text"] for b in blocks
        if b.get("type") in ("article_text", "ocr_fact") and b.get("text")
    ]
    clean_text = "\n\n".join(clean_text_parts)

    # 构造 raw_item dict 供 normalize_item 消费
    raw_item = {
        "title": headline or source_title,
        "raw_title": headline or source_title,
        "url": url,
        "content_text": clean_text,
        "full_text": clean_text,
        "content_blocks": blocks,
        "author": publisher_name,
        "account_name": publisher_name,
        "publish_time": publish_time,
        "images": images,
        "source": source,
    }

    # 运行标准 normalize_item
    item = normalize_item(
        raw_item,
        source=source,
        bank=bank or topic_candidate.get("topic_type_hint", ""),
        skip_auto_classify=skip_auto_classify,
    )

    # 回填多主题拆分追溯字段
    item.article_id = topic_candidate.get("article_id", "")
    item.topic_id = topic_candidate.get("topic_id", "")
    item.source_article_title = source_title
    item.is_multi_topic_split = True
    item.topic_split_confidence = topic_candidate.get("split_confidence", 0.0)
    item.topic_split_signals = topic_candidate.get("split_signals") or []

    # 如果拆分置信度低，在 review_flags 中标记
    if item.topic_split_confidence < 0.6 and item.topic_split_confidence > 0:
        if "needs_topic_split_review" not in item.review_flags:
            item.review_flags = (item.review_flags or []) + ["needs_topic_split_review"]

    return item
