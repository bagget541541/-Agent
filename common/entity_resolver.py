"""
来源/银行识别模块 — Resolve bank, publisher, source from multiple signals.

Design:
  Priority chain: explicit param > author/account_name > title > text > '未知'
  Bank aliases mapped to canonical names.

Usage:
    from common.entity_resolver import resolve_bank, resolve_source_name
    result = resolve_bank(title="招行经典白金卡", author="招商银行信用卡")
    # result == {"bank": "招商银行", "issuer_bank": "招商银行", ...}
"""

import re

# ── Bank name aliases → canonical name ───────────────────────────────────

_BANK_ALIASES: dict[str, str] = {
    # 简称
    "招行": "招商银行",
    "招商": "招商银行",
    "平安": "平安银行",
    "工行": "工商银行",
    "农行": "农业银行",
    "中行": "中国银行",
    "建行": "建设银行",
    "交行": "交通银行",
    "中信": "中信银行",
    "光大": "光大银行",
    "民生": "民生银行",
    "广发": "广发银行",
    "浦发": "浦发银行",
    "华夏": "华夏银行",
    "兴业": "兴业银行",
    "邮储": "邮储银行",
    "北京银行": "北京银行",
    "上海银行": "上海银行",
    "杭州银行": "杭州银行",
}

# Full official names (canonical)
_CANONICAL_BANKS = {
    "招商银行", "平安银行", "工商银行", "农业银行", "中国银行",
    "建设银行", "交通银行", "中信银行", "光大银行", "民生银行",
    "广发银行", "浦发银行", "华夏银行", "兴业银行", "邮储银行",
    "北京银行", "上海银行", "杭州银行",
}

# ── Source name → bank mapping ────────────────────────────────────────────

_SOURCE_TO_BANK: dict[str, str] = {
    "招商银行信用卡": "招商银行",
    "招商银行信用卡中心": "招商银行",
    "平安银行信用卡": "平安银行",
    "工银信用卡": "工商银行",
    "农业银行信用卡": "农业银行",
    "中国银行信用卡": "中国银行",
    "建设银行信用卡": "建设银行",
    "交通银行信用卡": "交通银行",
    "中信银行信用卡": "中信银行",
    "光大银行信用卡": "光大银行",
    "民生信用卡": "民生银行",
    "广发信用卡": "广发银行",
    "浦发银行信用卡": "浦发银行",
    "华夏银行信用卡": "华夏银行",
    "兴业银行信用卡": "兴业银行",
}


def _find_bank_in_text(text: str) -> str | None:
    """Scan text for known bank names (canonical or alias)."""
    if not text:
        return None

    # Check canonical names first (longer match = more reliable)
    matches = []
    for bank in _CANONICAL_BANKS:
        if bank in text:
            matches.append((len(bank), bank))
    if matches:
        matches.sort(key=lambda x: -x[0])
        return matches[0][1]

    # Check aliases
    for alias, bank in _BANK_ALIASES.items():
        if alias in text:
            return bank

    return None


def resolve_bank(
    title: str = "",
    author: str = "",
    text: str = "",
    explicit_bank: str = "",
) -> dict:
    """Resolve bank, issuer_bank, publisher_name, source_name from signals.

    Priority: explicit_bank > author/account_name > title > text > '未知'

    Args:
        title: Article title
        author: Author or account name
        text: Article body text
        explicit_bank: Explicitly specified bank (highest priority)

    Returns:
        dict with keys:
            bank, issuer_bank, publisher_name, source_name, evidence
    """
    evidence: list[str] = []
    bank = ""
    publisher_name = author if author and author not in {"未知公众号", "未知", "公众号"} else ""

    # 1. Explicit bank (highest priority)
    if explicit_bank:
        canonical = _BANK_ALIASES.get(explicit_bank, explicit_bank)
        if canonical in _CANONICAL_BANKS or explicit_bank:
            bank = canonical or explicit_bank
            evidence.append(f"bank: 指定参数: {explicit_bank}")
        else:
            bank = explicit_bank
            evidence.append(f"bank: 指定参数(非标准): {explicit_bank}")

    # 2. Author / account name
    if not bank and author:
        # Check source→bank mapping
        mapped = _SOURCE_TO_BANK.get(author)
        if mapped:
            bank = mapped
            evidence.append(f"bank: 公众号映射: {author} → {mapped}")
        else:
            found = _find_bank_in_text(author)
            if found:
                bank = found
                evidence.append(f"bank: 作者名包含: {found}")

    # 3. Title
    if not bank and title:
        found = _find_bank_in_text(title)
        if found:
            bank = found
            evidence.append(f"bank: 标题包含: {found}")

    # 4. Body text
    if not bank and text:
        found = _find_bank_in_text(text[:500])
        if found:
            bank = found
            evidence.append(f"bank: 正文包含: {found}")

    # 5. Default
    if not bank:
        bank = "未知"
        evidence.append("bank: 未识别到银行信息")

    if not publisher_name:
        publisher_name = bank if bank != "未知" else ""

    source_name = bank if bank != "未知" else (author or "未知")

    if not evidence:
        evidence.append(f"bank: 默认: {bank}")

    # bank_confidence: 根据解析路径映射为连续值 0.0-1.0
    bank_confidence = 0.0
    if evidence:
        last_evidence = evidence[-1]
        if "指定参数" in last_evidence and "非标准" not in last_evidence:
            bank_confidence = 1.0
        elif "指定参数(非标准)" in last_evidence:
            bank_confidence = 0.85
        elif "公众号映射" in last_evidence:
            bank_confidence = 0.9
        elif "作者名包含" in last_evidence:
            bank_confidence = 0.75
        elif "标题包含" in last_evidence:
            bank_confidence = 0.7
        elif "正文包含" in last_evidence:
            bank_confidence = 0.5
        elif "未识别到银行信息" in last_evidence:
            bank_confidence = 0.0

    return {
        "bank": bank,
        "issuer_bank": bank,
        "publisher_name": publisher_name,
        "source_name": source_name,
        "evidence": evidence,
        "bank_confidence": bank_confidence,
    }


def resolve_source_name(source: str, bank: str = "", author: str = "") -> str:
    """Resolve display-friendly source name."""
    if bank and bank != "未知":
        return bank
    if author:
        return author
    return source or "未知"
