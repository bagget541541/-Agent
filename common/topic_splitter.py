"""
多主题公众号文章拆分模块（topic_splitter）

核心职责：
1. 判定文章是单主题还是多主题候选
2. 对多主题候选执行主题切分 → 输出 TopicCandidate 列表
3. 过拆修正（合并相邻过短主题）
4. 低置信度时安全回退为单主题

设计文档：../../多主题公众号文章拆分设计.md
"""

from __future__ import annotations

import re
from typing import Any, Optional

# ── 信号类型常量 ────────────────────────────────────────

STRONG_SIGNALS = {
    "multiple_numbered_headings": "多个编号小标题",
    "repeated_activity_templates": "多组活动模板字段重复",
    "multiple_distinct_topics": "多个明显不同的主题标题",
    "multiple_independent_sections": "多个独立图文段落（标题+说明+图片）",
}

WEAK_SIGNALS = {
    "multiple_activity_names": "出现多个不同活动名称",
    "multiple_card_names": "出现多个不同卡种名称",
    "action_word_switching": "多个主题动作词切换（首发/新增/调整/返现/积分）",
    "topic_keyword_switch": "段落间主题关键词切换明显",
}

# 模板字段组：可用于判定多主题
TEMPLATE_GROUPS = [
    {"活动时间", "活动对象", "活动内容"},
    {"卡种", "权益", "亮点", "年费", "适用人群"},
    {"活动时间", "活动内容", "适用人群", "参与方式"},
    {"优惠内容", "适用门店", "有效期"},
]

# 动作词：段落间切换提示主题变化
ACTION_WORDS = {"首发", "新增", "调整", "返现", "积分", "优惠", "满减", "立减", "折扣", "免年费"}

# 信用卡银行名关键词（用于 bank_hint 检测）
BANK_KEYWORDS = [
    "农业银行", "农行", "招商银行", "招行", "中信银行", "中信",
    "建设银行", "建行", "工商银行", "工行", "中国银行", "中行",
    "交通银行", "交行", "邮储银行", "邮储", "民生银行", "民生",
    "光大银行", "光大", "浦发银行", "浦发", "平安银行", "平安",
    "兴业银行", "广发银行", "广发", "华夏银行", "北京银行",
]


# ── 辅助函数 ────────────────────────────────────────────


def _extract_block_text(block: dict) -> str:
    """安全提取 block 文本。"""
    return (block.get("text") or "").strip()


def _has_numbered_prefix(text: str) -> bool:
    """检测文本是否含编号前缀（编号小标题）。"""
    patterns = [
        r"^[一二三四五六七八九十]+[、.．]\s*",          # 一、 二.
        r"^\d+[、.．]\s*",                              # 1. 2、
        r"^[\(\（]\d+[\)\）]\s*",                       # (1) （2）
        r"^(?:活动|卡种|方案|权益|优惠)[一二三四五六七八九十]",
        r"^(?:活动|卡种|方案|权益|优惠)\d+",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return False


def _detect_template_group(text: str) -> Optional[set[str]]:
    """检测文本是否命中某个模板字段组，返回命中的组。"""
    for group in TEMPLATE_GROUPS:
        # 检查文本中是否包含该组中 2 个及以上字段
        matches = {kw for kw in group if kw in text}
        if len(matches) >= 2:
            return group
    return None


def _extract_named_entities(text: str) -> set[str]:
    """提取文本中真正的卡种名/活动名（排除噪音关键词）。"""
    found: set[str] = set()
    # 卡种名：特定格式的卡名
    card_patterns = re.findall(r"(?:Visa|MasterCard|银联|JCB|美国运通)[^\s，。]{0,6}(?:卡|版)", text)
    if not card_patterns:
        # 兜底：较长 + 以卡/版结尾且不含噪音词
        card_patterns = re.findall(r"[^\s，。]{4,10}(?:卡|版)", text)
    for cp in card_patterns:
        noise = {"扫码申卡", "主题信用卡", "信用卡", "银行卡", "借记卡"}
        if cp not in noise and not any(n in cp for n in {"扫码", "主题"}):
            found.add(cp)
    # 活动名：xx活动 / xx优惠 / xx返现 — 少于6字
    activity_patterns = re.findall(r"[^\s，。]{2,6}(?:活动|优惠|返现|赠)", text)
    for ap in activity_patterns:
        noise = {"活动", "优惠", "返现", "赠"}
        stripped = ap.rstrip("活动优惠返现赠")
        if stripped and stripped not in noise and len(stripped) >= 2:
            found.add(ap)
    return found


def _find_bank_hints(blocks: list[dict]) -> set[str]:
    """从 blocks 中提取银行名称提示。"""
    hints: set[str] = set()
    for block in blocks:
        text = _extract_block_text(block)
        for kw in BANK_KEYWORDS:
            if kw in text:
                hints.add(kw)
    return hints


# ── 多主题判定 ──────────────────────────────────────────


def detect_multi_topic(article_envelope: dict) -> dict:
    """判定一篇文章是否属于多主题候选。

    Args:
        article_envelope: ArticleEnvelope 字典（必须含 content_blocks）

    Returns:
        {
            "is_multi_topic_candidate": bool,
            "split_confidence": float,        # 0.0 ~ 1.0
            "signals": list[str],             # 命中的信号名称
        }
    """
    blocks = article_envelope.get("content_blocks") or []
    if not blocks:
        return {
            "is_multi_topic_candidate": False,
            "split_confidence": 0.0,
            "signals": [],
        }

    strong_signals: list[str] = []
    weak_signals: list[str] = []

    # ── 检查强信号 ──

    # 1. 多个编号小标题
    heading_blocks = [b for b in blocks if b.get("is_heading_like") or _has_numbered_prefix(_extract_block_text(b))]
    numbered_headings = [b for b in heading_blocks if _has_numbered_prefix(_extract_block_text(b))]
    if len(numbered_headings) >= 2:
        strong_signals.append("multiple_numbered_headings")

    # 2. 多组模板字段（以编号小标题为界，分区检测）
    # 先根据编号小标题/heading 把 blocks 分成若干大段
    sections: list[list[dict]] = []
    current_section: list[dict] = []
    for block in blocks:
        text = _extract_block_text(block)
        is_heading = block.get("is_heading_like") or _has_numbered_prefix(text)
        if is_heading and current_section:
            sections.append(current_section)
            current_section = [block]
        else:
            current_section.append(block)
    if current_section:
        sections.append(current_section)

    # 统计包含模板组的段落数
    template_matches = 0
    for sec in sections:
        sec_text = "\n".join(_extract_block_text(b) for b in sec if b.get("type") in ("article_text", "ocr_fact"))
        if sec_text and _detect_template_group(sec_text):
            template_matches += 1
    if template_matches >= 2:
        strong_signals.append("repeated_activity_templates")

    # 3. 多个明显不同的主题标题（heading blocks + 不同命名实体）
    if len(heading_blocks) >= 2:
        all_entities: set[str] = set()
        for b in heading_blocks:
            all_entities.update(_extract_named_entities(_extract_block_text(b)))
        if len(all_entities) >= 2:
            strong_signals.append("multiple_distinct_topics")

    # 4. 多个独立图文段落
    # 模式：heading → text → image 序列出现 2+ 次
    seq_count = 0
    in_section = False
    has_img = False
    has_text = False
    for block in blocks:
        btype = block.get("type", "")
        if btype == "image_caption" or (btype.startswith("image") and not btype == "image_cta"):
            has_img = True
        if btype == "article_text" and _extract_block_text(block):
            has_text = True
        if block.get("is_heading_like") or _has_numbered_prefix(_extract_block_text(block)):
            # 新标题开始 → 检查前一节是否完整
            if in_section and has_img and has_text:
                seq_count += 1
            in_section = True
            has_img = False
            has_text = False
    # 检查最后一节
    if in_section and has_img and has_text:
        seq_count += 1
    if seq_count >= 2:
        strong_signals.append("multiple_independent_sections")

    # ── 检查弱信号 ──

    # 1. 多个不同活动名 / 卡种名
    all_text = "\n".join(_extract_block_text(b) for b in blocks)
    named_entities = _extract_named_entities(all_text)
    if len(named_entities) >= 3:
        weak_signals.append("multiple_activity_names")

    # 2. 多个不同卡种名 — 同上，复用命名实体
    card_entities = {e for e in named_entities if "卡" in e or "版" in e}
    if len(card_entities) >= 2:
        weak_signals.append("multiple_card_names")

    # 3. 动作词切换
    action_matches = {w for w in ACTION_WORDS if w in all_text}
    if len(action_matches) >= 3:
        weak_signals.append("action_word_switching")

    # 4. 段落间关键词切换
    # 将 blocks 按段落分组，检查相邻段落的命名实体集变化
    para_entities: list[set[str]] = []
    for block in blocks:
        text = _extract_block_text(block)
        if text:
            para_entities.append(_extract_named_entities(text))
    switch_count = 0
    for i in range(1, len(para_entities)):
        if para_entities[i] and para_entities[i - 1]:
            # 如果当前段落实体与上一段落完全不同，视为切换
            if not para_entities[i].intersection(para_entities[i - 1]) and not para_entities[i] == para_entities[i - 1]:
                switch_count += 1
    if switch_count >= 2:
        weak_signals.append("topic_keyword_switch")

    # ── 综合判定 ──
    if strong_signals:
        # 任一强信号 → 多主题候选
        confidence = 0.7 + 0.1 * min(len(strong_signals), 3)
        return {
            "is_multi_topic_candidate": True,
            "split_confidence": min(confidence, 0.95),
            "signals": strong_signals + weak_signals,
        }
    elif len(weak_signals) >= 2:
        # 多个弱信号 → 升级
        confidence = 0.5 + 0.1 * min(len(weak_signals), 3)
        return {
            "is_multi_topic_candidate": True,
            "split_confidence": min(confidence, 0.75),
            "signals": weak_signals,
        }
    else:
        return {
            "is_multi_topic_candidate": False,
            "split_confidence": 0.0,
            "signals": [],
        }


# ── 主题切分 ────────────────────────────────────────────


def _is_topic_start(block: dict) -> bool:
    """判断一个 block 是否可视为主题起点。"""
    if block.get("is_heading_like"):
        return True
    text = _extract_block_text(block)
    if _has_numbered_prefix(text):
        return True
    if _detect_template_group(text):
        return True
    # 银行 + 特定动作词组合
    for kw in BANK_KEYWORDS:
        if kw in text and any(aw in text for aw in ACTION_WORDS):
            return True
    return False


def split_article_into_topics(article_envelope: dict) -> list[dict]:
    """将文章按主题切分为 TopicCandidate 列表。

    Args:
        article_envelope: ArticleEnvelope 字典

    Returns:
        至少含一个 TopicCandidate 的列表
    """
    blocks = article_envelope.get("content_blocks") or []
    if not blocks:
        return [_build_fallback_topic(article_envelope, blocks, reason="no_blocks")]

    article_id = article_envelope.get("article_id", "")
    source_title = article_envelope.get("raw_title", "无标题")
    url = article_envelope.get("url", "")
    publisher_name = article_envelope.get("publisher_name", "")
    publish_time = article_envelope.get("publish_time", "")
    all_images = article_envelope.get("images", [])

    # Step 1: 扫描主题起点
    topic_starts: list[int] = []
    for i, block in enumerate(blocks):
        if _is_topic_start(block):
            topic_starts.append(i)

    # 如果没有起点，或只有 1 个起点在开头 → 单主题
    if not topic_starts:
        return [_build_fallback_topic(article_envelope, blocks, reason="no_topic_starts")]

    # Step 2: 从起点划分主题边界
    topics: list[dict[str, Any]] = []
    for idx, start_idx in enumerate(topic_starts):
        # 终点 = 下一个起点 - 1，或者最后一个 block
        if idx + 1 < len(topic_starts):
            end_idx = topic_starts[idx + 1] - 1
        else:
            end_idx = len(blocks) - 1

        # 如果终点小于起点（相邻起点），该主题为空 → 跳过
        if end_idx < start_idx:
            continue

        topic_blocks = blocks[start_idx: end_idx + 1]
        headline = _extract_block_text(blocks[start_idx])
        topic_type_hint = _guess_topic_type(topic_blocks)
        bank_hints = _find_bank_hints(topic_blocks)

        topic = {
            "topic_id": f"{article_id}_t{idx + 1}",
            "article_id": article_id,
            "source_article_title": source_title,
            "url": url,
            "publisher_name": publisher_name,
            "publish_time": publish_time,
            "start_block": start_idx,
            "end_block": end_idx,
            "headline": headline or source_title,
            "blocks": topic_blocks,
            "topic_type_hint": topic_type_hint,
            "split_confidence": 0.8,
            "split_signals": ["heading_marker"],
            "images": all_images,  # 全量图片暂保留，后续可优化
        }
        topics.append(topic)

    # Step 3: 合并过小主题
    topics = merge_small_topics(topics)

    # Step 4: 如果合并后只有一个 → 视为单主题
    if len(topics) <= 1:
        return [_build_fallback_topic(article_envelope, blocks, reason="merged_to_single")]

    # 给 topic_id 重新编号
    for i, t in enumerate(topics):
        t["topic_id"] = f"{article_id}_t{i + 1}"

    return topics


def _guess_topic_type(blocks: list[dict]) -> str:
    """从 blocks 推测主题类型。

    Returns:
        "新卡" | "活动" | "权益变更" | "公告" | ""
    """
    text = "\n".join(_extract_block_text(b) for b in blocks)
    # 新卡信号
    if any(kw in text for kw in ["新卡", "首发", "发行", "上市", "卡种", "年费"]):
        card_signals = sum(1 for kw in ["新卡", "首发", "发行", "上市", "卡种", "年费"] if kw in text)
        if card_signals >= 2:
            return "新卡"
    # 活动信号
    if any(kw in text for kw in ["活动", "优惠", "返现", "积分", "满减"]):
        activity_signals = sum(1 for kw in ["活动", "优惠", "返现", "积分", "满减"] if kw in text)
        if activity_signals >= 2:
            return "活动"
    # 权益变更信号
    if any(kw in text for kw in ["调整", "变更", "更新", "权益"]):
        return "权益变更"
    # 公告
    if any(kw in text for kw in ["公告", "通知", "关于", "提示"]):
        return "公告"
    return ""


def _build_fallback_topic(article_envelope: dict, blocks: list[dict], reason: str = "") -> dict:
    """构建单主题回退的 TopicCandidate。"""
    article_id = article_envelope.get("article_id", "")
    source_title = article_envelope.get("raw_title", "无标题")
    return {
        "topic_id": f"{article_id}_t1",
        "article_id": article_id,
        "source_article_title": source_title,
        "url": article_envelope.get("url", ""),
        "publisher_name": article_envelope.get("publisher_name", ""),
        "publish_time": article_envelope.get("publish_time", ""),
        "start_block": 0,
        "end_block": len(blocks) - 1 if blocks else 0,
        "headline": source_title,
        "blocks": blocks,
        "topic_type_hint": "",
        "split_confidence": 1.0,
        "split_signals": [f"single_topic_fallback{':' + reason if reason else ''}"],
        "images": article_envelope.get("images", []),
    }


# ── 合并修正 ────────────────────────────────────────────


def merge_small_topics(topics: list[dict]) -> list[dict]:
    """合并过小的相邻主题。

    合并条件：
    - 类别 hint 一致
    - 后一个主题长度过短（<= 2 个 block）
    - 后一个主题没有独立 headline

    Args:
        topics: TopicCandidate 列表

    Returns:
        合并后的列表
    """
    if len(topics) <= 1:
        return topics

    merged: list[dict] = [topics[0]]
    for t in topics[1:]:
        prev = merged[-1]
        prev_blocks = prev.get("blocks") or []
        curr_blocks = t.get("blocks") or []
        curr_headline = t.get("headline", "")

        should_merge = (
            # 后一个主题过短
            len(curr_blocks) <= 2
            # 后一个主题没有独立标题（与来源标题相同）
            or (curr_headline and curr_headline == t.get("source_article_title"))
            # 前后主题类型 hint 一致且后一个很短
            or (
                prev.get("topic_type_hint")
                and prev["topic_type_hint"] == t.get("topic_type_hint")
                and len(curr_blocks) <= 3
            )
        )

        if should_merge:
            # 合并到 prev
            prev["blocks"] = prev_blocks + curr_blocks
            prev["end_block"] = t.get("end_block", prev.get("end_block", 0))
            # 如果 prev 没有 headline 或更短，用后一个的 headline
            if not prev.get("headline") and t.get("headline"):
                prev["headline"] = t["headline"]
            prev["split_signals"] = (prev.get("split_signals") or []) + ["merged"]
        else:
            merged.append(t)

    return merged


# ── raw_text 主题拆分（content_blocks 为空时的兜底） ──

# 主题标题检测正则：句末后出现「银行名 + 动作词」= 新主题边界
_BANK_ACTION_RE = re.compile(
    r'(?<=[。？！\n])\s*'
    r'(' + '|'.join(BANK_KEYWORDS) + r')'
    r'('
    r'下架|上架|新卡(?:上线)?|上线|发行|调整|变更|取消|'
    r'权益|活动|发布|新增|返现|积分|升级|首发|退市|下线|'
    r'公告|通知|缩水|优化|温暖|升级'
    r')'
)

# 纯文本主题关键词检测（无银行前缀也可作为主题边界）
_TOPIC_HEADING_KEYWORDS = [
    '新卡上线', '新卡发行', '活动上线', '权益调整',
    '积分调整', '积分活动', '返现活动', '优惠活动',
    '下架提醒', '卡片下线', '公告通知',
]


def _split_raw_text_into_topics(raw_text: str) -> list[dict[str, Any]]:
    """从 raw_text 检测并拆分为主题列表（content_blocks 为空时兜底）。

    检测策略：
    1. 扫描「银行名 + 动作词」组合作为主题边界
    2. 每个主题包含 headline + body_text

    Args:
        raw_text: 文章正文纯文本

    Returns:
        [{"headline": str, "body_text": str, "bank_hints": list[str]}, ...]
        若检测不到多主题，返回空列表
    """
    if not raw_text or len(raw_text) < 200:
        return []

    # Step 1: 找到所有 topic heading 边界位置
    boundaries: list[tuple[int, str]] = []  # (pos, heading_text)

    for m in _BANK_ACTION_RE.finditer(raw_text):
        bank = m.group(1)
        action = m.group(2)
        heading_text = f'{bank}{action}'
        start = m.start()
        # 提取完整的标题行（到首个结构化标记或句号或最大 30 字）
        snippet = raw_text[start:start + 60]
        end_mark = 60
        # 在结构化标记处截断
        for marker in ['活动时间', '活动内容', '活动对象', '适用人群',
                        '参与方式', '年费：', '权益：', '活动说明', '优惠内容']:
            pos = snippet.find(marker, len(heading_text))
            if 0 < pos < end_mark:
                end_mark = pos
        # 没有结构化标记时取第一个句号
        if end_mark == 60:
            dot_pos = snippet.find('。')
            if 0 < dot_pos < 60:
                end_mark = dot_pos
            else:
                end_mark = min(30, len(snippet))
        heading_text = snippet[:end_mark].strip().rstrip('。，')
        # 如果 heading 过长，在第一个空格或 20 字处截断
        if len(heading_text) > 20:
            # 尝试在最后一个词边界截断
            truncated = heading_text[:20]
            # 如果截断后以中文结尾（非字母），保留；否则回退到原型
            if any('\u4e00' <= c <= '\u9fff' for c in truncated[-1:]):
                heading_text = truncated
            else:
                heading_text = heading_text[:18]

        # 避免重复检测到相同 heading
        if not boundaries or (start - boundaries[-1][0]) > 50:
            boundaries.append((start, heading_text))

    # Step 2: 也检测纯标题关键词
    for kw in _TOPIC_HEADING_KEYWORDS:
        pos = 0
        while True:
            pos = raw_text.find(kw, pos + 100 if boundaries else 0)  # 跳过前 100 字符（广告区）
            if pos < 0:
                break
            if boundaries and abs(pos - boundaries[-1][0]) < 50:
                continue
            # 提取完整标题
            start = max(0, pos - 15)
            snippet = raw_text[start:start + 60]
            end_mark = min(
                snippet.find('。', 0) if snippet.find('。', 0) >= 0 else 60,
                snippet.find('\n', 0) if snippet.find('\n', 0) >= 0 else 60,
            )
            heading = snippet[:end_mark + 1].strip() if end_mark > 0 else kw
            boundaries.append((start, heading))
            boundaries.sort(key=lambda x: x[0])

    # Step 3: 去重（位置相近的合并）
    if not boundaries or len(boundaries) < 2:
        return []

    deduped: list[tuple[int, str]] = [boundaries[0]]
    for pos, heading in boundaries[1:]:
        if pos - deduped[-1][0] > 80:  # 间距大于 80 字才算独立主题
            deduped.append((pos, heading))

    if len(deduped) < 2:
        return []

    # Step 4: 按边界切分文本
    topics: list[dict[str, Any]] = []
    for i, (pos, heading) in enumerate(deduped):
        end_pos = deduped[i + 1][0] if i + 1 < len(deduped) else len(raw_text)
        body_text = raw_text[pos:end_pos].strip()
        # 从 body 提取 bank hints
        bank_hints = []
        for bk in BANK_KEYWORDS:
            if bk in body_text[:200]:
                bank_hints.append(bk)
        topics.append({
            "headline": heading.strip().rstrip('。，'),
            "body_text": body_text,
            "bank_hints": bank_hints or [],
        })

    # 如果切分后的主题过短（< 60 字），合并到上一个
    merged_topics: list[dict[str, Any]] = [topics[0]]
    for t in topics[1:]:
        if len(t["body_text"]) < 60 and merged_topics:
            prev = merged_topics[-1]
            prev["body_text"] += '\n' + t["body_text"]
            if prev.get("bank_hints") or t.get("bank_hints"):
                prev["bank_hints"] = list(set(prev.get("bank_hints", []) + t.get("bank_hints", [])))
        else:
            merged_topics.append(t)

    return merged_topics if len(merged_topics) >= 2 else []


def detect_multi_topic_from_raw_text(raw_text: str) -> dict:
    """判定 raw_text 是否包含多主题信号（content_blocks 为空时兜底）。

    Args:
        raw_text: 文章正文纯文本

    Returns:
        {
            "is_multi_topic": bool,
            "confidence": float,
            "signals": list[str],
        }
    """
    topics = _split_raw_text_into_topics(raw_text)
    if topics and len(topics) >= 2:
        return {
            "is_multi_topic": True,
            "confidence": 0.75,
            "signals": ["raw_text_bank_action_boundaries"],
            "topics": topics,
        }
    return {
        "is_multi_topic": False,
        "confidence": 0.0,
        "signals": [],
        "topics": [],
    }
