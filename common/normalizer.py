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
from typing import Optional

from common.schema import CreditCardItem, CreditCardBatch
from common.classifier import classify_item
from common.entity_resolver import resolve_bank
from common.display_fields import generate_display_fields
from common.review import generate_review_flags
from common.utils import safe_truncate


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


def _normalize_highlight_text(text: str) -> str:
    """清洗高亮/详情文本：去称呼、章节标题、噪音标记、多余空白。

    从 generate_report.py 迁移，作为 structured_clean 的通用清洗步骤。
    """
    if not text:
        return ""
    text = re.sub(r"\[图片核心内容\s*-\s*[^\]]+\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 去称呼前缀
    for prefix in [
        "尊敬的客户：", "尊敬的持卡人：", "附件：", "点击可查阅：",
        "一、活动时间", "二、活动对象", "三、活动内容", "四、活动细则",
    ]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    # 去"关于"前缀
    text = re.sub(r"^(关于)?启用新版", "启用新版", text)
    text = re.sub(r"^(关于)?新增", "新增", text)
    text = text.replace("特此公告。", "").strip()
    text = re.sub(r"\s+", " ", text).strip(" ：:;；，,。")
    return text


def _normalize_detail_text(text: str) -> str:
    """深度清洗「详情」字段：识别 OCR 结构化格式、过滤噪音行、提取有用信息。

    从 generate_report.py 迁移，仅处理 key='详情' 的值。
    """
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful_lines = []
    inside_core_section = False
    for line in lines:
        # 噪音行直接跳过
        if line.startswith('[图片核心内容 - '):
            continue
        if '未包含任何信用卡相关信息' in line:
            continue
        if '仅显示一个用于申卡的微信二维码' in line:
            continue
        # 识别"核心信用卡资讯"结构化段落
        if '核心信用卡资讯' in line:
            inside_core_section = True
            continue
        if '补充说明' in line or 'image_description' in line.lower():
            inside_core_section = False
            continue
        if inside_core_section:
            useful_lines.append(line)
            continue
        # 识别 "- 银行：/卡种：..." 前缀格式
        if any(line.startswith(p) for p in
               ['- 银行：', '- 卡种：', '- 卡面级别：', '- 卡面主题：',
                '- 活动：', '- 合作：']):
            useful_lines.append(line.lstrip('- ').strip())
            continue
        # 识别编号前缀格式 "1. 发卡银行：..."
        if re.match(r'^\d+\.\s*(发卡银行|卡种名称|卡片级别|卡面特色|上线状态|年费信息|权益亮点)', line):
            cleaned = re.sub(r'^\d+\.\s*', '', line)
            useful_lines.append(cleaned)
            continue
        # 首条长文本作为兜底
        if not useful_lines and len(line) >= 8 and '二维码' not in line:
            useful_lines.append(line)
    if useful_lines:
        return '；'.join(useful_lines[:6])
    return _normalize_highlight_text(text)


def _strip_marketing_tail(text: str) -> str:
    """去掉营销 CTA 尾巴和尾部标签。

    从 generate_report.py 迁移。
    """
    if not text:
        return ""
    text = re.sub(r'珍藏周边礼等你领.*$', '', text).strip()
    text = re.sub(r'【[^】]+】$', '', text).strip()
    return text


# 营销后缀/修饰词（用于清洗卡种名）
_CARD_NAME_NOISE_SUFFIXES = re.compile(
    r'(重磅上市|正式发行|燃情首发|震撼来袭|火热上线|盛大发布|即将上线|全新上线|新卡上线|！|!)+$'
)
# 中间噪音短语（如 "交行新卡上线 泡泡玛特" → 去掉 "新卡上线 "）
_CARD_NAME_NOISE_MIDDLE = re.compile(r'\s*(新卡上线|重磅上市|正式发行|燃情首发)\s*')
_CARD_NAME_NOISE_TAIL_TAGS = re.compile(r'【[^】]+】\s*$|\|\s*[^|]+$')
_CARD_NAME_NOISE_PREFIXES = re.compile(r'^(狂欢|重磅|全新|盛大|火热|震撼)\s*')
_CARD_NAME_STRIP_CHARS = " ，,。.、；;！!"


def _clean_card_name(title: str) -> str:
    """从原标题中清洗出核心卡种名，去掉营销噪音。

    Examples:
        "招商银行发布全新白金信用卡，正式发行！" → "白金信用卡"
        "农行Visa全球支付白金卡（世界杯版）【限时】" → "农行Visa全球支付白金卡（世界杯版）"
        "重磅！华夏南航联名信用卡发布" → "华夏南航联名信用卡"
    """
    if not title:
        return "" if title is not None else None
    name = title.strip()
    # 去营销后缀
    name = _CARD_NAME_NOISE_SUFFIXES.sub('', name)
    # 去中间噪音短语
    name = _CARD_NAME_NOISE_MIDDLE.sub(' ', name).strip()
    # 去尾部标签 【xxx】| xxx
    name = _CARD_NAME_NOISE_TAIL_TAGS.sub('', name)
    # 去开头修饰
    name = _CARD_NAME_NOISE_PREFIXES.sub('', name)
    # 去尾部标点
    name = name.strip(_CARD_NAME_STRIP_CHARS)
    return name or title


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
        structured["卡种"] = _clean_card_name(title)
        structured["卡亮点"] = ""
        structured["适用人群"] = "信用卡持卡人"
        structured["来源"] = author or url
        structured["详情"] = safe_truncate(source_text, 500) if source_text else title

    elif category == "活动":
        structured["活动内容"] = safe_truncate(source_text, 300) if source_text else title
        structured["活动时间"] = ""
        structured["适用人群"] = "信用卡持卡人"

    elif category == "权益变更":
        structured["消息时间"] = ""
        structured["影响范围"] = ""
        structured["变更内容"] = safe_truncate(source_text, 500) if source_text else title
        structured["变更分析"] = ""

    elif category == "公告":
        structured["消息内容"] = safe_truncate(source_text, 500) if source_text else title
        structured["点评"] = ""

    else:
        structured["详细内容"] = safe_truncate(source_text, 500) if source_text else title

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


# ── Confidence scoring ────────────────────────────────────────────────────

# 各分类的期望 structured 字段（与 _build_structured_for_category 保持一致）
_EXPECTED_FIELDS = {
    "新卡": ["卡种", "卡亮点", "适用人群", "来源", "详情"],
    "活动": ["活动内容", "活动时间", "适用人群"],
    "权益变更": ["消息时间", "影响范围", "变更内容", "变更分析"],
    "公告": ["消息内容", "点评"],
    "其他": ["详细内容"],
}


def _compute_confidence(
    category_candidates: list,
    bank_confidence: float,
    title_source: str,
    raw_title: str,
    structured: dict,
    category: str,
) -> dict:
    """Compute continuous confidence scores from available signals.

    Returns dict with keys: overall, category, bank, title, structured.
    All values are in [0.0, 1.0].
    """
    # --- category: 使用 classifier 真实顶分，模糊分类时扣减 ---
    if category_candidates and len(category_candidates) >= 1:
        top_score = category_candidates[0][1]
        if len(category_candidates) >= 2:
            gap = top_score - category_candidates[1][1]
            discount = max(0.0, (0.15 - gap)) * 0.5
            category_score = max(0.0, min(1.0, top_score - discount))
        else:
            category_score = top_score
    else:
        category_score = 0.0

    # --- bank: 直接使用 entity_resolver 的 bank_confidence ---
    bank_score = bank_confidence

    # --- title: 原始标题基础分 + 长度奖励 ---
    if title_source == "generated":
        title_score = 0.4
    else:
        title_score = 0.7
    if raw_title and len(raw_title) >= 10:
        title_score = min(1.0, title_score + 0.1)
    if raw_title and len(raw_title) >= 20:
        title_score = min(1.0, title_score + 0.1)

    # --- structured: 已填充字段数 / 该分类期望字段数 ---
    expected = _EXPECTED_FIELDS.get(category, _EXPECTED_FIELDS["其他"])
    if structured and expected:
        filled = sum(1 for f in expected if structured.get(f))
        structured_score = filled / len(expected)
    elif structured:
        total = len(structured)
        filled = sum(1 for v in structured.values() if v)
        structured_score = filled / total if total > 0 else 0.0
    else:
        structured_score = 0.0

    # --- overall: 加权平均 ---
    overall = (
        0.35 * category_score
        + 0.25 * bank_score
        + 0.20 * structured_score
        + 0.20 * title_score
    )
    overall = round(max(0.0, min(1.0, overall)), 3)

    return {
        "overall": round(overall, 3),
        "category": round(category_score, 3),
        "bank": round(bank_score, 3),
        "title": round(title_score, 3),
        "structured": round(structured_score, 3),
    }


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

    # ── 2.5 纯广告/空内容检测 ──
    _raw_text_stripped = (raw_text or "").strip()
    if _raw_text_stripped in ("（以上内容为广告）", "以上内容为广告", ""):
        if category not in ("其他",):
            noise_flags.append("pure_ad_or_empty")

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
        if not v:
            continue
        cleaned = _trim_marketing_intro(v)
        # 去掉 "[图片核心内容 - xxx]" 等纯噪音标记
        cleaned = re.sub(r'\[图片核心内容\s*-\s*[^\]]*\]', '', cleaned).strip()
        # 去掉 "（以上内容为广告）" 尾巴
        cleaned = re.sub(r'（以上内容为广告）', '', cleaned).strip()
        # 按字段类型做深度清洗
        if k == '详情':
            cleaned = _normalize_detail_text(cleaned)
        elif k in ('变更内容', '活动内容', '消息内容', '详细内容'):
            cleaned = _normalize_highlight_text(cleaned)
        if cleaned:
            structured_clean[k] = cleaned
    # 写入已解析的来源（替代 Word 层的 未知公众号 fallback）
    if entity_result["source_name"] and entity_result["source_name"] != "未知":
        structured_clean['来源'] = entity_result["source_name"]

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
    confidence = _compute_confidence(
        category_candidates=category_candidates,
        bank_confidence=entity_result.get("bank_confidence", 0.0),
        title_source=display_result["title_source"],
        raw_title=title,
        structured=structured,
        category=category,
    )

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
        from common.images import centralize_images
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
