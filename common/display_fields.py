"""
展示字段生成模块 — Generate display-oriented fields (title, summary, etc.).

Logic mirrors _refine_article_title + _generate_title in _agent.py.

Usage:
    from common.display_fields import generate_display_fields
    result = generate_display_fields(bank="招商银行", category="新卡", ...)
"""

# ── Category action keywords (title is "good enough" if it contains these) ─

_ACTION_KEYWORDS: dict[str, list[str]] = {
    "新卡":     ["发布", "发行", "推出", "首发", "上市", "全新", "新卡"],
    "权益变更": ["调整", "变更", "升级", "取消", "优化", "缩水", "新规", "权益", "修改",
                 "下架", "停用", "上线", "启用"],
    "活动":     ["活动", "优惠", "返现", "满减", "立减", "福利", "折扣", "积分", "送", "消费奖励"],
    "公告":     [],  # 公告类标题保持原样
}


def _generate_title(
    bank: str,
    category: str,
    structured: dict,
    fallback_title: str = "",
) -> str:
    """按分类生成主谓宾结构标题。"""
    bank = bank or fallback_title or "银行"

    if category == "新卡":
        card_name = (structured.get("卡种") or "").strip()
        if card_name:
            return f"{bank}发布{card_name}"
        return f"{bank}发布新卡"

    if category == "活动":
        activity = (structured.get("活动内容") or "").strip()
        if activity:
            return f"{bank}活动：{activity[:30]}"
        return f"{bank}推出优惠活动"

    if category == "权益变更":
        # P1: raw_title 含动作词时优先保留原始标题
        if fallback_title and any(kw in fallback_title for kw in _ACTION_KEYWORDS["权益变更"]):
            return f"{bank}权益调整：{fallback_title[:30]}"
        change = (structured.get("变更内容") or "").strip()
        if change:
            return f"{bank}权益调整：{change[:30]}"
        return f"{bank}调整信用卡权益"

    # 兜底
    return fallback_title or f"{bank}{category}"


def _build_highlight_summary(
    category: str,
    structured: dict,
    raw_text: str = "",
    raw_title: str = "",
    bank: str = "",
) -> str:
    """从 structured 中提取主要的内容摘要。"""
    structured = structured or {}

    if category == "新卡":
        card_name = (structured.get("卡种") or "").strip()
        if card_name:
            return f"{bank}发布{card_name}" if bank else card_name
        return (structured.get("卡亮点") or raw_title or structured.get("详情", "")[:100])[:100]
    elif category == "活动":
        activity = (structured.get("活动内容") or raw_title or "")[:100]
        return activity
    elif category == "权益变更":
        # 优先 raw_title，其次从 变更内容 提取第一句（跳过日期/时间）
        if raw_title:
            return raw_title[:100]
        change = (structured.get("变更内容") or "")
        if change:
            # 取第一句（句号前）
            first_sentence = change.split('。')[0] if '。' in change else change
            # 跳过「活动时间」类描述
            for marker in ['活动时间', '活动内容', '活动对象']:
                pos = first_sentence.find(marker)
                if pos > 0:
                    first_sentence = first_sentence[:pos].strip()
            return first_sentence[:100]
        return ""
    elif category == "公告":
        return (structured.get("消息内容") or "")[:200]
    else:
        return (raw_text or raw_title or "")[:200]


def generate_display_fields(
    bank: str,
    category: str,
    structured: dict,
    raw_title: str,
    raw_text: str = "",
    structured_clean: dict | None = None,
) -> dict:
    """生成展示字段：标题、摘要、来源等。

    Args:
        bank: 银行名称（已解析的规范名）
        category: 分类
        structured: 结构化字段 dict
        raw_title: 原始标题
        raw_text: 原始正文

    Returns:
        dict with keys:
            title, normalized_title, display_title (all same refined value)
            highlight_summary
            title_source ("raw" | "generated")
            evidence: list[str]
    """
    raw_title = (raw_title or "").strip()
    title_source = "raw"
    evidence: list[str] = []

    # 公告类直接保留原标题
    if category == "公告":
        title = raw_title or f"{bank}公告"
        evidence.append("title: 公告类保留原标题")
    elif raw_title in ("无标题", "图片", ""):
        # 无标题 → 完全生成
        title = _generate_title(bank, category, structured or {})
        title_source = "generated"
        evidence.append(f"title: 无原标题，完全生成")
    else:
        # 检查原标题是否已包含分类动作关键词
        keywords = _ACTION_KEYWORDS.get(category, [])
        if not keywords:
            # 该类别无必须动作词（如公告已提前处理）
            title = raw_title
        else:
            has_action = any(kw in raw_title for kw in keywords)
            if has_action:
                title = raw_title
                evidence.append(f"title: 原标题含{category}关键词，保留")
            else:
                # 原标题缺少动作关键词 → 重新生成
                generated = _generate_title(bank, category, structured or {}, raw_title)
                if generated != raw_title:
                    title = generated
                    title_source = "generated"
                    evidence.append(f"title: 原标题缺{category}动作词，重新生成")
                else:
                    title = raw_title

    # 摘要
    highlight_summary = _build_highlight_summary(category, structured or {}, raw_text, raw_title, bank=bank)

    # 默认 evidence
    if not evidence:
        evidence.append(f"title: 保留原标题: {raw_title[:30]}")

    return {
        "title": title,
        "normalized_title": title,
        "display_title": title,
        "highlight_summary": highlight_summary,
        "title_source": title_source,
        "evidence": evidence,
    }
