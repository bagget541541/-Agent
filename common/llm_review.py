"""
LLM 审核模块 — 对低置信度条目做语义审核和修正建议。

设计目标：
- 消费 review_queue 中 high/medium severity 条目
- 用 LLM 判断分类是否正确、银行是否识别对、标题是否需要重写
- 输出结构化修正建议，由调用方决定是否采纳

使用方式：
    from common.llm_review import llm_review_items
    suggestions = llm_review_items(flagged_items)
"""

import json
import re

from common.llm_client import call_llm_simple_str as _call_llm
from common.config import VALID_CATEGORIES

# ── 信用卡领域合法银行名（部分常用）



# 信用卡领域合法银行名（部分常用）
_VALID_BANKS = [
    "招商银行", "工商银行", "建设银行", "农业银行", "中国银行", "交通银行",
    "中信银行", "光大银行", "民生银行", "广发银行", "浦发银行", "兴业银行",
    "华夏银行", "平安银行", "邮储银行", "北京银行", "上海银行",
    "江苏银行", "宁波银行", "南京银行", "杭州银行",
]





def _parse_json_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON。"""
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试从 markdown code block 提取
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return {}


# ── Prompt 模板 ───────────────────────────────────────────

_SYSTEM_PROMPT = """你是一个信用卡资讯审核助手。你的任务是检查结构化数据的准确性，并给出修正建议。

审核维度：
1. category（分类）：新卡 / 权益变更 / 活动 / 公告 / 其他
2. bank（银行名）：标准银行全称，如"招商银行"
3. title（标题）：简洁、通顺、无噪音的标题

规则：
- 如果当前值正确，correction 留空
- 如果需要修正，correction 填写修正后的值
- 标题应简洁（≤30字），去掉"尊敬的客户"、"一、活动时间"等结构化噪音
- 银行名必须是标准全称，如"农业银行"（不是"农业银行活动"）
- 只输出 JSON，不要其他文字"""


def _build_user_prompt(item: dict) -> str:
    """构建单条审核的 user prompt。"""
    return json.dumps({
        "title": item.get("title", ""),
        "category": item.get("category", ""),
        "bank": item.get("bank", ""),
        "highlight_summary": (item.get("highlight_summary", "") or "")[:150],
        "confidence": item.get("confidence", {}),
        "review_flags": item.get("review_flags", []),
    }, ensure_ascii=False)


# ── 主入口 ────────────────────────────────────────────────

def llm_review_items(
    items: list[dict],
    max_items: int = 10,
) -> list[dict]:
    """对 flagged items 做 LLM 审核，返回修正建议列表。

    Args:
        items: review_queue 中的 flagged_items（已含 title/bank/category/flags）
        max_items: 最多审核几条（控制成本）

    Returns:
        [
            {
                "item_id": "...",
                "suggestion": {
                    "category": {"current": "...", "correction": "..."},
                    "bank": {"current": "...", "correction": "..."},
                    "title": {"current": "...", "correction": "..."},
                },
                "reason": "...",
            },
            ...
        ]
    """
    if not items:
        return []

    # 只审核 high/medium severity
    to_review = [
        it for it in items
        if it.get("severity") in ("high", "medium")
    ][:max_items]

    if not to_review:
        return []

    print(f"  [LLM Review] Reviewing {len(to_review)} flagged items...")

    results = []
    for item in to_review:
        user_prompt = _build_user_prompt(item)
        raw = _call_llm(_SYSTEM_PROMPT, user_prompt)
        if not raw:
            continue

        parsed = _parse_json_response(raw)
        if not parsed:
            continue

        suggestion = {}
        for field in ("category", "bank", "title"):
            current = item.get(field, "")
            correction = parsed.get(field, "")
            # 只有修正值与当前值不同时才记录
            if correction and correction != current:
                # 分类合法性校验
                if field == "category" and correction not in VALID_CATEGORIES:
                    continue
                suggestion[field] = {"current": current, "correction": correction}

        results.append({
            "item_id": item.get("item_id", ""),
            "title": item.get("title", ""),
            "suggestion": suggestion,
            "reason": parsed.get("reason", ""),
        })

    accepted = sum(1 for r in results if r["suggestion"])
    print(f"  [LLM Review] {accepted}/{len(results)} items have corrections")
    return results


def apply_suggestions(
    items: list,  # CreditCardItem list
    suggestions: list[dict],
) -> int:
    """将 LLM 修正建议应用到 CreditCardItem 对象。

    Returns:
        实际修改的条目数
    """
    suggestion_map = {s["item_id"]: s["suggestion"] for s in suggestions}
    modified = 0

    for item in items:
        s = suggestion_map.get(item.item_id, {})
        if not s:
            continue

        if "category" in s:
            new_cat = s["category"]["correction"]
            item.category = new_cat
            item.evidence.setdefault("category", []).append(f"LLM 修正分类: {new_cat}")

        if "bank" in s:
            new_bank = s["bank"]["correction"]
            item.bank = new_bank
            item.evidence.setdefault("bank", []).append(f"LLM 修正银行: {new_bank}")

        if "title" in s:
            new_title = s["title"]["correction"]
            item.title = new_title
            item.display_title = new_title
            item.normalized_title = new_title
            item.evidence.setdefault("title", []).append(f"LLM 修正标题: {new_title}")

        if s:
            modified += 1

    return modified
