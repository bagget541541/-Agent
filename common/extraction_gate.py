"""
提取质量门禁 — 失败状态隔离与证据覆盖率检查

依据 doc/mode_c_公众号文章解析改进规范.md 第 7.3 / 7.4 / 7.9 节实现：

- 失败状态隔离：
    FETCH_FAILED  — 页面未成功获取，不得生成活动事实；
    OCR_FAILED    — 页面获取成功但图片文字无法识别，不得猜测关键字段；
    PARTIAL       — 仅部分内容可核实，所有缺失字段必须单独标记；
    NEEDS_REVIEW  — 自动门禁发现疑似串稿/主题不一致/证据不足；
    只有 SUCCESS 或经人工确认的 PARTIAL 才允许进入下游点评流程。
- 证据覆盖率检查：
    关键字段（金额/日期/门槛/名额/比例/次数/适用条件）证据覆盖率 100%；
    无来源金额、日期、名额和门槛数量为 0；
    抓取或 OCR 失败文章不得生成无依据的结构化活动事实；
    URL 串稿数量为 0。
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from common.extraction import (
    EXTRACTION_STATUS_VALUES,
    validate_field_evidence,
)

# ── 关键事实字段（规范 7.9：关键字段证据覆盖率 100%） ────
KEY_FACT_FIELDS = (
    "amount",       # 金额（如 20元 / 减50）
    "threshold",    # 门槛（如 满18元 / 满5000元）
    "quota",        # 名额（如 8000份 / 限17000个）
    "ratio",        # 比例（如 返6% / 2倍积分）
    "count",        # 次数（如 每月限1次 / 每日限1次）
    "valid_until",  # 日期/有效期（如 截至9月30日 / 2026年8月31日前）
    "condition",    # 适用条件（如 仅限主卡 / 需先报名）
)

# 数字+单位模式（用于从文本中扫描无来源关键事实）
_FACT_PATTERNS = [
    (r"\d+(?:\.\d+)?\s*(?:元|块钱|人民币|美元)", "amount"),
    (r"满\s*\d+(?:\.\d+)?\s*元", "threshold"),
    (r"减\s*\d+(?:\.\d+)?\s*元|立减\s*\d+\s*元|返\s*\d+%", "amount"),
    (r"(?:限|仅限|共限|含)\s*\d+\s*(?:份|个|名|张|笔|次)", "quota"),
    (r"返\s*\d+(?:\.\d+)?%|享\s*\d+\s*倍积分|返现\s*\d+%", "ratio"),
    (r"(?:每|限)\s*(?:月|日|周|年|季|人|户|卡|笔|单)\s*(?:限|可)?\s*\d+\s*次", "count"),
    (r"(?:截至|截止|至|到)\s*\d{4}年\d{1,2}月\d{1,2}日", "valid_until"),
    (r"\d{4}年\d{1,2}月\d{1,2}日[\u4e00-\u9fff]{0,6}\d{1,2}月\d{1,2}日", "valid_until"),
    (r"\d{4}年\d{1,2}月\d{1,2}日前", "valid_until"),
]


def scan_key_facts(text: str) -> list[dict]:
    """扫描文本中的关键事实候选（金额/门槛/名额/比例/次数/日期）。

    Returns:
        [{"field": "amount", "match": "减20元", "pos": int}, ...]
        已去重（同 field 同 match 只保留首个）。
    """
    if not text:
        return []
    seen = set()
    facts: list[dict] = []
    for pattern, field in _FACT_PATTERNS:
        for m in re.finditer(pattern, text):
            key = (field, m.group(0))
            if key in seen:
                continue
            seen.add(key)
            facts.append({"field": field, "match": m.group(0), "pos": m.start()})
    return facts


def _norm_evidence_text(s: str) -> str:
    """证据匹配用归一化：全角→半角、去空白、数字占位。"""
    out = []
    for ch in str(s or ""):
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return re.sub(r"\s+", "", "".join(out))


def _digit_tokens(s: str) -> set[str]:
    """提取文本中的数字 token（金额/比例/日期等），用于证据对应性校验。"""
    norm = _norm_evidence_text(s)
    return set(
        re.findall(r"\d+(?:\.\d+)?\s*(?:元|块|美元|%|积分|笔|张|份|次|期|倍|折|日)", norm)
    )


def _fact_covered_by_evidence(fact: dict, ev: dict) -> bool:
    """判断单个 fact 是否被同字段的一条 evidence 覆盖（归一化精确/数字 token 匹配）。

    修复 P0-1：不再按字段名放行。只有 evidence 的 value/quote 归一化后
    与 fact 匹配（或数字 token 对应）才算覆盖。
    """
    match = fact["match"]
    norm_match = _norm_evidence_text(match)
    value = _norm_evidence_text(ev.get("value", ""))
    quote = _norm_evidence_text(ev.get("quote", ""))
    # 精确包含匹配（双向）
    if norm_match and (norm_match in value or norm_match in quote or value in norm_match or quote in norm_match):
        return True
    # 数字 token 匹配：fact 与 evidence 的数字 token 有交集且金额一致
    match_digits = _digit_tokens(match)
    ev_digits = _digit_tokens(value) | _digit_tokens(quote)
    if match_digits and ev_digits and match_digits & ev_digits:
        return True
    return False


def compute_evidence_coverage(
    text: str,
    field_evidence: Optional[list[dict]] = None,
    extraction_status: str = "",
) -> dict:
    """计算关键字段证据覆盖率（规范 7.9）。

    Args:
        text: 供扫描关键事实的正文/结构化文本
        field_evidence: 字段级证据列表
        extraction_status: 提取状态

    Returns:
        {
          "coverage": float,          # 0-1
          "facts_total": int,         # 扫描到的关键事实数
          "facts_covered": int,       # 有证据覆盖的事实数
          "uncovered": [ {field, match} ... ],  # 无来源事实
        }
    """
    if extraction_status in ("FETCH_FAILED", "OCR_FAILED"):
        # 失败状态：不得生成任何结构化活动事实
        return {
            "coverage": 0.0,
            "facts_total": 0,
            "facts_covered": 0,
            "uncovered": [],
            "blocked": True,
        }

    facts = scan_key_facts(text)
    if not facts:
        return {
            "coverage": 1.0,
            "facts_total": 0,
            "facts_covered": 0,
            "uncovered": [],
            "blocked": False,
        }

    # 修复 P0-1：非法 evidence 不得参与覆盖计算
    valid_evidence = [
        ev for ev in (field_evidence or [])
        if not validate_field_evidence(ev)
    ]
    # 按字段分组，逐 fact 与同字段 evidence 做对应性匹配
    evidence_by_field: dict[str, list[dict]] = {}
    for ev in valid_evidence:
        evidence_by_field.setdefault(ev.get("field", ""), []).append(ev)

    covered = 0
    uncovered: list[dict] = []
    for fact in facts:
        field = fact["field"]
        evs = evidence_by_field.get(field, [])
        if any(_fact_covered_by_evidence(fact, ev) for ev in evs):
            covered += 1
        else:
            uncovered.append({"field": field, "match": fact["match"]})

    return {
        "coverage": round(covered / len(facts), 3),
        "facts_total": len(facts),
        "facts_covered": covered,
        "uncovered": uncovered,
        "blocked": False,
    }


# ── 失败状态隔离（规范 7.4） ─────────────────────────────

def is_downstream_safe(
    extraction_status: str,
    manual_confirmed: bool = False,
) -> bool:
    """是否允许进入下游点评流程。

    只有 SUCCESS，或经人工确认的 PARTIAL 才允许。
    """
    if extraction_status == "SUCCESS":
        return True
    if extraction_status == "PARTIAL" and manual_confirmed:
        return True
    return False


def build_downstream_view(article: dict, manual_confirmed: bool = False) -> dict:
    """构建下游安全视图：未放行状态剥离结构化活动事实。

    修复 P0-2：以 `safe` 为唯一放行条件。只有 SUCCESS 或经人工确认的
    PARTIAL 才返回 activity_facts / structured；其余状态（FETCH_FAILED、
    OCR_FAILED、未确认 PARTIAL、NEEDS_REVIEW）统一清空活动事实，
    并保留仅供人工复核的原始内容字段，杜绝调用方拿到未放行字段。
    """
    status = article.get("extraction_status", "")
    reasons = list(article.get("review_reasons") or [])
    safe = is_downstream_safe(status, manual_confirmed=manual_confirmed)

    view = {
        "article_id": article.get("article_id", ""),
        "url": article.get("url", ""),
        "raw_title": article.get("raw_title", ""),
        "publisher_name": article.get("publisher_name", ""),
        "extraction_status": status,
        "downstream_safe": safe,
        "blocked_reasons": [] if safe else reasons,
    }

    if not safe:
        # 未放行状态：禁止向下游暴露结构化活动事实（P0-2）
        view["activity_facts"] = []
        view["structured"] = {}
        view["evidence_coverage"] = 0.0
        view["blocked_reasons"] = reasons or [f"{status}: 未获准进入下游"]
        # 仅供人工复核的原始内容，字段名明确标记 review 用途
        view["review_raw"] = {
            "content_blocks": article.get("content_blocks") or [],
            "structured": article.get("structured") or {},
            "field_evidence": article.get("field_evidence") or [],
        }
        if status in ("FETCH_FAILED", "OCR_FAILED"):
            view["note"] = "抓取或OCR失败，不得解释为'没有优惠'，禁止用银行常识补全"
        else:
            view["note"] = "待复核或证据不足，不得作为活动事实进入下游"
        return view

    # 放行状态（SUCCESS 或已确认 PARTIAL）：保留内容，附证据覆盖率
    facts = compute_evidence_coverage(
        article.get("content_text", "") or article.get("raw_text", ""),
        article.get("field_evidence"),
        status,
    )
    view["activity_facts"] = article.get("content_blocks") or []
    view["structured"] = article.get("structured") or {}
    view["evidence_coverage"] = facts["coverage"]
    view["uncovered_facts"] = facts["uncovered"]
    if facts["uncovered"] and status == "SUCCESS":
        view["blocked_reasons"].append(
            f"uncovered_facts: {[u['match'] for u in facts['uncovered'][:5]]}"
        )
    return view


# ── 批量门禁检查（规范 7.9 验收标准） ─────────────────────

def check_batch_gate(
    articles: Iterable[dict],
    *,
    manual_confirmed_ids: Optional[set] = None,
) -> dict:
    """批量门禁检查，输出验收报告。

    Returns:
        {
          "total": int,
          "violations": [ {article_id, severity, message} ... ],
          "stats": {
            "downstream_safe": int,
            "failed_state": int,
            "uncovered_facts_total": int,
            "url_duplicates": int,
          },
        }
    """
    confirmed = set(manual_confirmed_ids or [])
    violations: list[dict] = []
    url_seen: dict[str, str] = {}
    url_dups = 0
    stats = {
        "downstream_safe": 0,
        "failed_state": 0,
        "uncovered_facts_total": 0,
    }

    # 修复 P1-3：入口先物化为 list，避免生成器二次迭代耗尽
    article_list = list(articles)

    for article in article_list:
        aid = article.get("article_id", "")
        url = article.get("url", "")
        status = article.get("extraction_status", "")

        # URL 串稿检查（规范 7.9：URL 串稿数量为 0）
        if url:
            c = url.rstrip("/")
            if c in url_seen:
                url_dups += 1
                violations.append({
                    "article_id": aid,
                    "severity": "high",
                    "message": f"URL 重复/串稿: {c} (首个: {url_seen[c]})",
                })
            else:
                url_seen[c] = aid

        if status in ("FETCH_FAILED", "OCR_FAILED"):
            stats["failed_state"] += 1
            # 失败状态仍生成了结构化事实 → 违规
            if article.get("structured") or article.get("activity_facts"):
                violations.append({
                    "article_id": aid,
                    "severity": "high",
                    "message": f"{status} 状态下生成了结构化活动事实（禁止）",
                })
            if article.get("content_blocks"):
                violations.append({
                    "article_id": aid,
                    "severity": "medium",
                    "message": f"{status} 状态下 content_blocks 非空（禁止）",
                })
            continue

        safe = is_downstream_safe(status, manual_confirmed=(aid in confirmed))
        if safe:
            stats["downstream_safe"] += 1

        # 证据覆盖检查
        facts = compute_evidence_coverage(
            article.get("content_text", "") or article.get("raw_text", ""),
            article.get("field_evidence"),
            status,
        )
        stats["uncovered_facts_total"] += len(facts["uncovered"])
        for u in facts["uncovered"]:
            violations.append({
                "article_id": aid,
                "severity": "medium",
                "message": f"无来源关键事实: [{u['field']}] {u['match']}",
            })
        if status == "SUCCESS" and facts["uncovered"]:
            violations.append({
                "article_id": aid,
                "severity": "high",
                "message": f"SUCCESS 状态仍有 {len(facts['uncovered'])} 个无来源事实",
            })
        if status == "PARTIAL" and not (aid in confirmed):
            violations.append({
                "article_id": aid,
                "severity": "low",
                "message": "PARTIAL 状态未人工确认，不应进入下游",
            })

        # 证据记录本身合法性
        for ev in article.get("field_evidence") or []:
            for problem in validate_field_evidence(ev):
                violations.append({
                    "article_id": aid,
                    "severity": "medium",
                    "message": f"evidence 非法: {problem}",
                })

    stats["url_duplicates"] = url_dups
    return {
        "total": len(article_list),
        "violations": violations,
        "stats": stats,
    }
