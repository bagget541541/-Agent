"""
统一分类器模块 — Three-tier classifier for credit card news categories.

Design:
  Tier 1 (Strong Rules): Title patterns that are definitive for a category
  Tier 2 (Weak Rule Scoring): Weighted keyword scoring across categories
  Tier 3 (Low Confidence): Default to '其他' when scores are low or close

Usage:
    from common.classifier import classify_item
    result = classify_item(title, text)
    # result == {"category": "活动", "category_candidates": [...], "evidence": [...]}
"""

from common.schema import STANDARD_CATEGORIES


# ── Tier 1: Strong Rules ──────────────────────────────────────────────────

# (category, keywords, min_confidence)
_STRONG_RULES = [
    ("新卡", ["新卡", "首发", "上市", "发行", "推出", "全新发布",
              "首发上市", "全新推出", "正式发行"], 0.92),
    ("权益变更", ["调整", "变更", "升级", "缩水", "取消", "停用", "下架",
                  "优化更新", "规则调整", "权益更新"], 0.88),
]

# ── Tier 2: Weak Rule Keywords ───────────────────────────────────────────

_CATEGORY_KEYWORDS = {
    "新卡": {
        "title": ["发布", "推出", "新卡", "首发", "上市", "全新", "发行"],
        "body": ["全新推出", "首发上市", "正式发行", "全新上市", "首次推出"],
        "weight_title": 2.0,
        "weight_body": 1.0,
    },
    "权益变更": {
        "title": ["调整", "变更", "升级", "缩水", "取消", "停用", "下架",
                   "优化", "更新", "新规", "规则调整", "修改", "权益更新"],
        "body": ["调整", "变更", "升级", "缩水", "取消", "停用", "下架",
                 "优化", "更新", "新规", "规则调整", "修改", "权益更新"],
        "weight_title": 2.0,
        "weight_body": 1.0,
    },
    "公告": {
        "title": ["公告", "通知", "声明", "重要提示", "风险提示"],
        "body": ["公告", "通知", "声明", "重要提示", "系统维护", "风险提示"],
        "weight_title": 2.0,
        "weight_body": 1.0,
    },
    "活动": {
        "title": ["活动", "优惠", "返现", "满减", "立减", "福利",
                   "积分", "折扣", "送礼", "抽奖", "送", "免费"],
        "body": ["活动", "优惠", "返现", "满减", "立减", "福利",
                 "积分", "折扣", "送礼", "抽奖", "消费奖励",
                 "刷卡", "返利", "礼遇", "惠享", "体验价", "享", "免费"],
        "weight_title": 2.0,
        "weight_body": 1.0,
    },
}

_THRESHOLD_HIGH = 0.5   # above this → accept directly
_THRESHOLD_CLOSE = 0.15  # if top two within this → low confidence


def _tier1_strong_rules(title: str) -> dict | None:
    """Check strong rules. Returns None if no rule matches."""
    if not title:
        return None
    for cat, keywords, confidence in _STRONG_RULES:
        if any(kw in title for kw in keywords):
            return {
                "category": cat,
                "category_candidates": [[cat, confidence]],
                "evidence": [f"强规则: 标题含{cat}关键词"],
            }
    return None


def _tier2_scoring(title: str, text: str) -> dict:
    """Score each category independently, return candidates sorted by score."""
    text_for_analysis = text[:500] if text else ""
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}

    for cat, cfg in _CATEGORY_KEYWORDS.items():
        score = 0.0
        ev = []

        # Title keywords
        title_matches = [kw for kw in cfg["title"] if kw in title]
        if title_matches:
            score += len(title_matches) * cfg["weight_title"]
            ev.append(f"标题匹配: {', '.join(title_matches)}")

        # Body keywords
        if text_for_analysis:
            body_matches = [kw for kw in cfg["body"] if kw in text_for_analysis]
            if body_matches:
                # Deduplicate matches that already appeared in title
                unique_body = [kw for kw in body_matches if kw not in title]
                if unique_body:
                    score += len(unique_body) * cfg["weight_body"]
                    ev.append(f"正文匹配: {', '.join(unique_body)}")

        scores[cat] = score
        evidence[cat] = ev

    # Normalize to 0~1 range (cap at 5 raw points = 1.0)
    max_raw = max(scores.values()) if scores else 0.0
    if max_raw > 0:
        normalized = {k: min(v / 5.0, 1.0) for k, v in scores.items()}
    else:
        normalized = {k: 0.0 for k in scores}

    # Sort by score descending
    candidates = sorted(normalized.items(), key=lambda x: -x[1])

    return {
        "scores": normalized,
        "candidates": candidates,
        "evidence_raw": evidence,
    }


def _tier3_decide(scoring: dict) -> dict:
    """Decide final category based on scoring results."""
    candidates = scoring["candidates"]
    evidence_raw = scoring["evidence_raw"]

    if not candidates:
        return {
            "category": "其他",
            "category_candidates": [["其他", 0.5]],
            "evidence": ["无匹配关键词，默认其他"],
        }

    top_cat, top_score = candidates[0]

    # Tier 3a: Score too low → '其他'
    if top_score < _THRESHOLD_HIGH:
        # Build all candidates with review flag
        cat_candidates = [[c, s] for c, s in candidates if s > 0]
        if not cat_candidates:
            cat_candidates = [["其他", 0.5]]

        return {
            "category": "其他",
            "category_candidates": cat_candidates,
            "evidence": [f"最高分{top_cat}={top_score:.2f}<{_THRESHOLD_HIGH}，降级为其他"],
        }

    # Tier 3b: Top two close → mark for review
    if len(candidates) >= 2:
        second_cat, second_score = candidates[1]
        if top_score - second_score < _THRESHOLD_CLOSE:
            cat_candidates = [[c, s] for c, s in candidates[:3] if s > 0]
            return {
                "category": top_cat,
                "category_candidates": cat_candidates,
                "evidence": [f"前两名接近: {top_cat}={top_score:.2f} vs {second_cat}={second_score:.2f}"],
            }

    # Confident decision
    ev = evidence_raw.get(top_cat, [f"分类决策: {top_cat}"])
    return {
        "category": top_cat,
        "category_candidates": [[c, s] for c, s in candidates[:3] if s > 0],
        "evidence": ev,
    }


def classify_item(title: str, text: str = "") -> dict:
    """Three-tier classifier for credit card news categories.

    Args:
        title: Article title (primary signal)
        text: Article body text (secondary signal)

    Returns:
        dict with keys:
            category: str — 新卡, 权益变更, 活动, 公告, 其他
            category_candidates: list[list[str, float]] — sorted candidates
            evidence: list[str] — human-readable reasons
    """
    title = (title or "").strip()
    text = (text or "").strip()

    # Tier 1: Strong rules (title patterns that are definitive)
    result = _tier1_strong_rules(title)
    if result:
        return result

    # Tier 2: Weak rule scoring
    scoring = _tier2_scoring(title, text)

    # Tier 3: Decide + low-confidence defaults
    return _tier3_decide(scoring)
