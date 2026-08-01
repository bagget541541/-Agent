"""
标题-正文一致性门禁 + 提取质量评分

依据 doc/mode_c_公众号文章解析改进规范.md 第 7.2 / 7.9 节实现：

- 标题-正文相似度只用于风险筛查，低分结果统一进入人工复核队列，
  绝不直接丢弃文章；复核时保留原始抓取内容与 OCR 结果；
- 分词与关键词归一化（轻量实现，不依赖 jieba）：
    停用词过滤、全角→半角、数字/金额归一化、银行名称容错；
- 多主题文章：标题与任一分块文本匹配即可；
- 缺标题/正文/OCR 时明确降级处理，不武断判低分；
- 质量评分综合 extraction_status / evidence_coverage / 标题一致性
  / OCR 置信度，输出 0-1 分与复核建议。
"""

from __future__ import annotations

import re
from typing import Optional

# ── 轻量分词（无 jieba 依赖） ───────────────────────────

# 通用停用词（标题与正文匹配时忽略）
_STOPWORDS = {
    "的", "了", "在", "是", "有", "和", "与", "及", "或", "等", "之", "于",
    "至", "到", "起", "及", "其", "此", "该", "也", "都", "将", "已", "可",
    "我们", "您", "你", "我", "请", "点击", "查看", "更多", "详情", "立即",
    "即将", "重磅", "惊喜", "福利", "来袭", "上线", "火热", "招募", "开启",
    "活动", "期间", "通知", "公告", "发布", "推出", "新增", "升级", "焕新",
    "超", "最", "高", "低", "起", "仅", "仅限", "享", "可享", "有机会",
    "第", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
}

# 银行名称别名表（标题/正文识别容错）
_BANK_ALIASES = {
    "农行": "农业银行", "中行": "中国银行", "工行": "工商银行",
    "建行": "建设银行", "交行": "交通银行", "招行": "招商银行",
    "中信": "中信银行", "广发": "广发银行", "兴业": "兴业银行",
    "民生": "民生银行", "浦发": "浦发银行", "光大": "光大银行",
    "邮储": "邮政储蓄银行", "华夏": "华夏银行", "平安": "平安银行",
    "浙商": "浙商银行", "上海银行": "上海银行", "长安银行": "长安银行",
    "北京农商": "北京农商银行", "北京农商银行": "北京农商银行",
}

# 标题营销词（出现时降低自动拦截强度，规范 7.2：标题营销化降级）
_MARKETING_WORDS = {
    "重磅", "惊喜", "福利", "来袭", "超省钱", "全攻略", "速戳", "提醒",
    "待领取", "开抢", "火热", "狂欢", "专属", "尊享", "礼遇", "加码",
}


def normalize_text(text: str) -> str:
    """文本归一化：全角→半角、大小写、空白压缩。"""
    if not text:
        return ""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    s = "".join(out).lower()
    return re.sub(r"\s+", " ", s).strip()


def extract_keywords(text: str) -> list[str]:
    """提取文本关键词：按 2-4 字窗口切分 + 停用词过滤 + 银行别名归一。

    轻量实现：对中文文本做字窗口切词（2 字/3 字），过滤停用词后保留
    有信息量的词元。银行名做别名归一。返回**去重**后的词元列表。
    """
    if not text:
        return []
    norm = normalize_text(text)
    tokens: list[str] = []

    # 先做银行名替换（长名优先）
    for alias, full in sorted(_BANK_ALIASES.items(), key=lambda x: -len(x[0])):
        norm = norm.replace(alias, full)

    # 中文字窗口切词：2-4 字（去重）
    seen = set()
    for n in (4, 3, 2):
        for i in range(len(norm) - n + 1):
            w = norm[i:i + n]
            if re.fullmatch(r"[\u4e00-\u9fff]+", w) and w not in _STOPWORDS and w not in seen:
                seen.add(w)
                tokens.append(w)
    # 英文/数字 token
    for w in re.findall(r"[a-z]{2,}|\d+(?:\.\d+)?", norm):
        if w not in seen:
            seen.add(w)
            tokens.append(w)
    return tokens


def _digit_normalize(text: str) -> str:
    """数字归一化：金额、满减、日期中的数字统一为 X，便于跨文本匹配。"""
    if not text:
        return ""
    norm = re.sub(r"\d+(?:\.\d+)?", "X", normalize_text(text))
    norm = re.sub(r"(X\s*[元块%])", "X", norm)
    norm = re.sub(r"[满减返至高]+\s*X", "X", norm)
    return norm


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── 标题-正文一致性门禁（规范 7.2） ─────────────────────

def _split_title_blocks(title: str) -> list[str]:
    """按分隔符将标题切分为语义块。

    例："景区秒杀/20元折扣券每周三开抢" → ["景区秒杀", "20元折扣券", "每周三", "开抢"]。
    块级匹配比字窗口词覆盖更抗碎片词干扰。
    """
    norm = normalize_text(title)
    blocks = re.split(r"[/，。！？、；：\s\-—·|（）()]", norm)
    return [b.strip() for b in blocks if b.strip()]


def _block_hit(block: str, body_norm: str, body_digits: str) -> bool:
    """判断一个标题块是否在正文中命中。

    命中规则（任一条成立即命中）：
      1. 整块作为子串出现在正文；
      2. 块内任一词元（2-4 字）出现在正文；
      3. 块数字归一化后出现在正文数字归一化文本中。
    """
    if not block:
        return False
    if block in body_norm:
        return True
    block_d = _digit_normalize(block)
    if block_d and len(block_d) >= 3 and block_d in body_digits:
        return True
    words = extract_keywords(block)
    return any(w in body_norm for w in words)


def title_body_consistency(
    title: str,
    body_text: str,
    *,
    title_required: bool = True,
) -> dict:
    """计算标题与正文的一致性分数（只用于风险筛查，不直接丢弃）。

    算法：
        1. 标题按分隔符切分为语义块（_split_title_blocks）；
        2. 每块在正文中做块级命中（整块子串 / 块内词元 / 数字归一化）；
        3. 命中率 = 命中块数 / 总块数；
        4. 标题含营销词且命中率达标时降低拦截强度（+0.1）；
        5. 缺标题/正文：标记缺失交由人工，不武断判低分。

    Returns:
        {
          "score": float,           # 0-1
          "level": "high|medium|low|unknown",
          "flagged": bool,          # 是否需要人工复核（低分/缺失）
          "blocks": [...],          # 标题语义块
          "hit_blocks": [...],
          "missed_blocks": [...],
          "missing": {"title": bool, "body": bool},
        }
    """
    missing = {
        "title": not title or not title.strip(),
        "body": not body_text or not body_text.strip(),
    }
    # 缺标题/正文：不武断判低分，标记缺失交由人工（规范 7.2 缺失处理）
    if missing["title"] or missing["body"]:
        return {
            "score": 0.0,
            "level": "unknown",
            "flagged": True,
            "blocks": [],
            "hit_blocks": [],
            "missed_blocks": [],
            "missing": missing,
        }

    blocks = _split_title_blocks(title)
    if not blocks:
        return {
            "score": 0.0, "level": "unknown", "flagged": True,
            "blocks": [], "hit_blocks": [], "missed_blocks": [],
            "missing": missing,
        }

    body_norm = normalize_text(body_text)
    body_digits = _digit_normalize(body_text)

    hits = [b for b in blocks if _block_hit(b, body_norm, body_digits)]
    score = len(hits) / len(blocks)

    # 营销标题降级：标题含营销词时降低自动拦截强度（规范 7.2）
    title_has_marketing = any(w in title for w in _MARKETING_WORDS)
    if title_has_marketing and score >= 0.5:
        score = min(1.0, score + 0.1)

    score = round(score, 3)
    if score >= 0.6:
        level = "high"
    elif score >= 0.4:
        level = "medium"
    else:
        level = "low"

    return {
        "score": score,
        "level": level,
        "flagged": level in ("low", "medium", "unknown"),
        "blocks": blocks,
        "hit_blocks": hits,
        "missed_blocks": [b for b in blocks if b not in hits],
        "missing": missing,
        "marketing_title": title_has_marketing,
    }


def multi_topic_consistency(
    title: str,
    topic_texts: list[str],
) -> list[dict]:
    """多主题文章：标题与每个主题分块分别计算，返回逐块结果。"""
    return [title_body_consistency(title, t) for t in topic_texts]


# ── 提取质量评分（规范 7.9） ─────────────────────────────

def quality_score(
    *,
    extraction_status: str,
    evidence_coverage: float = 0.0,
    title_consistency: Optional[dict] = None,
    ocr_confidence: float = 0.0,
    review_reasons: Optional[list[str]] = None,
) -> dict:
    """综合提取质量评分。

    评分组成：
        status_score: SUCCESS=1.0 / PARTIAL=0.7 / NEEDS_REVIEW=0.5
                      / OCR_FAILED=0.2 / FETCH_FAILED=0.0
        evidence_score: evidence_coverage（0-1）
        title_score: 标题一致性 score（缺失时为 0.5 中性值）
        ocr_score: OCR 置信度（无 OCR 时为 0.8 中性偏正）

    总分 = 加权平均（status 40% + evidence 30% + title 20% + ocr 10%）

    Returns:
        {"total": float, "level": "A|B|C|D", "components": {...}, "suggest": str}
    """
    status_scores = {
        "SUCCESS": 1.0, "PARTIAL": 0.7, "NEEDS_REVIEW": 0.5,
        "OCR_FAILED": 0.2, "FETCH_FAILED": 0.0,
    }
    status_score = status_scores.get(extraction_status, 0.3)
    evidence_score = float(evidence_coverage or 0.0)
    if title_consistency is None:
        title_score = 0.5
    else:
        title_score = title_consistency.get("score", 0.5)
        # 缺失标题/正文 → 中性 0.5，不叠加惩罚
        if title_consistency.get("missing", {}).get("title"):
            title_score = 0.5
    ocr_score = float(ocr_confidence or 0.0) or 0.8

    total = round(
        0.40 * status_score + 0.30 * evidence_score
        + 0.20 * title_score + 0.10 * ocr_score,
        3,
    )
    if total >= 0.85:
        level, suggest = "A", "可直接进入下游点评"
    elif total >= 0.7:
        level, suggest = "B", "可进入下游，建议抽查关键事实"
    elif total >= 0.5:
        level, suggest = "C", "需人工复核后决定是否进入下游"
    else:
        level, suggest = "D", "不建议进入下游，需人工重取或补 OCR"

    reasons = review_reasons or []
    return {
        "total": total,
        "level": level,
        "suggest": suggest,
        "components": {
            "status_score": status_score,
            "evidence_score": evidence_score,
            "title_score": title_score,
            "ocr_score": ocr_score,
        },
        "review_reasons": reasons,
    }
