"""
展示字段生成模块 — Generate display-oriented fields (title, summary, etc.).

Logic mirrors _refine_article_title + _generate_title in _agent.py.

Usage:
    from common.display_fields import generate_display_fields
    result = generate_display_fields(bank="招商银行", category="新卡", ...)
"""

import re
from common.utils import safe_truncate


def _strip_marketing_tail(text: str) -> str:
    """去掉营销 CTA 尾巴和尾部标签（内联版，避免循环导入）。"""
    if not text:
        return ""
    text = re.sub(r'珍藏周边礼等你领.*$', '', text).strip()
    text = re.sub(r'【[^】]+】$', '', text).strip()
    return text


# ── Category action keywords (title is "good enough" if it contains these) ─

_ACTION_KEYWORDS: dict[str, list[str]] = {
    "新卡":     ["发布", "发行", "推出", "首发", "上市", "全新", "新卡"],
    "权益变更": ["调整", "变更", "升级", "取消", "优化", "缩水", "新规", "权益", "修改",
                 "下架", "停用", "上线", "启用"],
    "活动":     ["活动", "优惠", "返现", "满减", "立减", "福利", "折扣", "积分", "送",
                 "消费奖励", "免年费", "达标", "新户", "里程", "开卡礼", "刷卡金",
                 "兑换", "抽奖"],
    "公告":     [],  # 公告类标题保持原样
}


# ── 活动标题样板话开头列表（应跳过，抽取真正活动名） ──
_ACTIVITY_BOILERPLATE = [
    "一、活动时间", "二、活动对象", "三、活动内容", "四、活动细则",
    "一、活动对象", "二、活动内容", "三、活动时间",
    "活动时间", "活动对象", "活动内容", "活动细则", "活动规则",
    "活动详情", "活动简介", "活动主题", "报名时间", "消费达标时间",
    "二、活动", "三、", "四、", "五、",
]


def _extract_activity_name(text: str) -> str:
    """从活动正文中抽取真正活动名称，跳过样板话及纯日期/数字开头。"""
    if not text:
        return ""

    # 1. 跳过样板话前缀
    remaining = text
    for boiler in _ACTIVITY_BOILERPLATE:
        if remaining.startswith(boiler):
            remaining = remaining[len(boiler):].lstrip("：: \n")
            break

    # 2. 逐句扫描，跳过纯日期/数字片段和编号样板话，找到第一句有意义文本
    import re as _re
    for sep in ["。", "！", "？", "\n"]:
        parts = remaining.split(sep)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if _is_date_or_number_fragment(part):
                continue
            # 跳过编号样板话（如"二、活动对象 农行..."），整句都不是活动名
            # 但"三、活动内容 Visa世界杯"→ 样板话后面的内容是活动名
            matched_boiler = None
            for boiler in _ACTIVITY_BOILERPLATE:
                if part.startswith(boiler):
                    matched_boiler = boiler
                    break
            if matched_boiler:
                # 如果样板话本身含"内容"两个字 → 后面的内容就是活动名
                if "活动内容" in matched_boiler:
                    rest = part[len(matched_boiler):].lstrip("：: \n").strip()
                    if rest and not _is_date_or_number_fragment(rest):
                        return rest
                # 否则跳过整句，继续往下找
                continue
            # 没有匹配到任何样板话 → 这是真正的活动名
            return part
        break  # 只用第一个分隔符逐句拆分

    # 3. 全都没意义 → 返回最长的片段
    best = max(remaining.split("。"), key=lambda x: len(x.strip()))
    return best.strip()


def _generate_title(
    bank: str,
    category: str,
    structured: dict,
    fallback_title: str = "",
) -> str:
    """按分类生成主谓宾结构标题。"""
    bank = bank or fallback_title or "银行"

    # 修复1：银行无法识别时，宁可保留原标题也不生成"未知推出优惠活动"
    if bank in ("未知", "银行"):
        return fallback_title or f"{bank}推出优惠活动"

    if category == "新卡":
        card_name = (structured.get("卡种") or "").strip()
        if card_name:
            return f"{bank}发布{card_name}"
        return f"{bank}发布新卡"

    if category == "活动":
        activity = (structured.get("活动内容") or "").strip()
        if activity:
            # 修复3：优先提取真正活动名，而不是取正文前30字
            activity_name = _extract_activity_name(activity)
            if activity_name:
                display = safe_truncate(activity_name, 30)
                return f"{bank}活动：{display}"
            return f"{bank}活动：{safe_truncate(activity, 30)}"
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


def _is_date_or_number_fragment(text: str) -> bool:
    """判断文本是否只是日期/数字片段（不适合作为摘要）。"""
    if not text:
        return True
    # 纯日期："7月31日"、"2026年6月"、"6月1日至6月30日"
    if re.match(r'^[\d\-/.~至到年月日号月日]+$', text.strip()):
        return True
    # 纯数字+单位："10点"、"100元"
    if re.match(r'^[\d.]+\s*[元点%]$', text.strip()):
        return True
    return False


def _build_highlight_summary(
    category: str,
    structured: dict,
    raw_text: str = "",
    raw_title: str = "",
    bank: str = "",
    structured_clean: dict | None = None,
) -> str:
    """从 structured 中提取主要的内容摘要。

    优先使用 structured_clean（已清洗版本），回退到 structured。
    所有类别摘要末尾统一调用 _strip_marketing_tail() 去营销噪音。
    """
    sc = structured_clean or structured or {}

    if category == "新卡":
        card_name = (sc.get("卡种") or structured.get("卡种") or "").strip()
        highlight = (sc.get("卡亮点") or structured.get("卡亮点") or "").strip()
        if highlight:
            summary = f"{card_name}：{highlight[:80]}" if card_name else highlight[:100]
        elif card_name:
            summary = f"{bank}发布{card_name}" if bank else card_name
        else:
            summary = (raw_title or sc.get("详情", ""))[:100]
    elif category == "活动":
        activity = (sc.get("活动内容") or structured.get("活动内容") or "").strip()
        if activity and activity != raw_title:
            extracted = _extract_first_sentence(activity)
            # 提取结果只是日期/数字片段 → 用 raw_title 兜底
            if _is_date_or_number_fragment(extracted) and raw_title:
                summary = raw_title[:100]
            else:
                summary = extracted[:100]
        else:
            summary = raw_title[:100] if raw_title else ""
    elif category == "权益变更":
        change = (sc.get("变更内容") or structured.get("变更内容") or "").strip()
        if change:
            extracted = _extract_first_sentence(change)
            # 提取结果只是日期/数字片段 → 用 raw_title 兜底
            if _is_date_or_number_fragment(extracted) and raw_title:
                summary = raw_title[:100]
            else:
                summary = extracted[:100]
        else:
            summary = raw_title[:100] if raw_title else ""
    elif category == "公告":
        summary = (sc.get("消息内容") or structured.get("消息内容") or "")[:200]
    else:
        summary = (raw_text or raw_title or "")[:200]

    # 统一去营销尾巴
    summary = _strip_marketing_tail(summary)
    return summary


def _extract_first_sentence(text: str) -> str:
    """从文本中提取第一句有意义的话，跳过时间/活动类标记。

    截断点：句号/分号/中文编号段落（一、二、...）/（一）（二）...
    """
    if not text:
        return ""
    # 在句号/分号之前，先按中文编号段落截断（"一、""二、" 等）
    # 这些标记在正式文档中表示新段落，应作为摘要边界
    first_sentence = re.split(r'[。；]', text)[0]
    m = re.search(r'(?:^|[：:\s])[一二三四五六七八九十]+、', first_sentence)
    if m:
        first_sentence = first_sentence[:m.start()].strip()
    # 跳过「活动时间」类前缀（marker + 其值部分），循环去除连续标记
    _markers = ['活动时间', '活动内容', '活动对象', '报名时间', '领奖用奖时间',
                '消费达标时间', '活动规则', '活动详情', '活动细则', '活动期限',
                '优惠内容', '权益内容', '调整内容', '原规则', '新规则']
    for _ in range(5):  # 最多去 5 轮
        matched = False
        for marker in _markers:
            if first_sentence.startswith(marker):
                rest = first_sentence[len(marker):]
                rest = re.sub(r'^[：:\s]+', '', rest)
                rest = re.sub(r'^[\d\-/.~至到年月日号]*[年月日号]', '', rest)
                rest = re.sub(r'^\s*\d+[：:点时分]\d*\s*', '', rest)
                rest = re.sub(r'^起至\s*', '', rest)
                if rest.strip():
                    first_sentence = rest.strip()
                    matched = True
                    break
        if not matched:
            break
    # 去掉开头的"尊敬的客户："等称呼
    first_sentence = re.sub(r'^(尊敬的客户[：:]?|您好[！!]?|感谢您[^，,]*[，,]?)\s*', '', first_sentence)
    return first_sentence.strip()


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
    highlight_summary = _build_highlight_summary(
        category, structured or {}, raw_text, raw_title, bank=bank,
        structured_clean=structured_clean,
    )

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
