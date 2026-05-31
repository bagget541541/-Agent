"""
审核队列生成模块

设计目标：
- 根据 CreditCardItem 中的 confidence / evidence / structured 等字段
  自动生成 review_flags
- 输出 review_queue.json（机器可读）和 review_queue.md（人工可读）
- 让人工工作从"全文通读"转为"按标记筛查异常项"

使用方式：
    from common.review import generate_review_flags, build_review_queue, export_review_queue

    items = [item1, item2, ...]
    export_review_queue(items, "data/")
    # 输出: data/review_queue.json, data/review_queue.md
"""

import json
import os
from datetime import datetime

from common.schema import CreditCardItem

# ── 审核标记枚举 ────────────────────────────────────────

FLAG_RULES = {
    "needs_category_review": "分类可信度低或分类依据不足",
    "needs_source_review": "来源不可识别或银行名缺失",
    "needs_title_review": "标题为空、过短或明显为噪音",
    "needs_detail_review": "structured 为空（缺少结构化信息）",
    "needs_time_review": "发布时间缺失",
    # 多主题拆分相关
    "needs_topic_split_review": "多主题拆分置信度偏低，需人工确认拆分是否正确",
    "topic_boundary_low_confidence": "主题边界检测置信度低，可能拆分位置不准确",
    # 图片相关
    "needs_image_review": "图片路径不包含 item_id，可能有串图风险",
}


# ── 标记生成 ────────────────────────────────────────────

def generate_review_flags(item: CreditCardItem) -> list[str]:
    """根据连续 confidence 分数生成审核标记。

    阈值校准（适配 0.0-1.0 连续分数）：
    - category 0<score<0.7 或 top_candidate<0.5 → needs_category_review
    - bank < 0.5 → needs_source_review
    - title < 0.6 或标题长度 < 3 → needs_title_review
    - structured < 0.5 或 structured 为空 → needs_detail_review
    - publish_time 为空 → needs_time_review
    - overall < 0.5 → needs_overall_review
    """
    flags = []
    conf = item.confidence or {}

    # Category
    cat_conf = conf.get("category", 0.0)
    if 0 < cat_conf < 0.7:
        flags.append("needs_category_review")
    if item.category_candidates:
        top_score = item.category_candidates[0][1] if item.category_candidates[0] else 0
        if top_score < 0.5:
            flags.append("needs_category_review")

    # Bank
    bank_conf = conf.get("bank", 0.0)
    if bank_conf < 0.5:
        flags.append("needs_source_review")

    # Title
    title_conf = conf.get("title", 0.0)
    if title_conf < 0.6:
        flags.append("needs_title_review")
    title_text = item.title or item.raw_title or ""
    if not title_text or len(title_text.strip()) < 3:
        flags.append("needs_title_review")

    # Detail (structured)
    struct_conf = conf.get("structured", 0.0)
    if struct_conf < 0.5:
        flags.append("needs_detail_review")
    if not item.structured:
        flags.append("needs_detail_review")

    # Time
    if not item.publish_time:
        flags.append("needs_time_review")

    # Overall quality gate
    overall = conf.get("overall", 0.0)
    if overall < 0.5:
        flags.append("needs_overall_review")

    # 多主题拆分
    if item.is_multi_topic_split:
        if item.topic_split_confidence < 0.6 and item.topic_split_confidence > 0:
            if "needs_topic_split_review" not in flags:
                flags.append("needs_topic_split_review")
        if item.topic_split_confidence < 0.4 and item.topic_split_confidence > 0:
            if "topic_boundary_low_confidence" not in flags:
                flags.append("topic_boundary_low_confidence")

    # P1-4: 图片归属校验
    if item.images:
        for img_path in item.images:
            if isinstance(img_path, str) and item.item_id not in img_path:
                flags.append("needs_image_review")
                break

    # 去重
    return list(dict.fromkeys(flags))


# ── 严重度分级 ──────────────────────────────────────────

_CRITICAL_FLAGS = {"needs_category_review", "needs_source_review", "needs_overall_review"}


def _severity(flags: list[str]) -> str:
    """根据标记类型和数量判定严重度。"""
    if any(f in _CRITICAL_FLAGS for f in flags):
        return "high"
    if len(flags) >= 3:
        return "medium"
    return "low"


# ── 审核队列构建 ────────────────────────────────────────

def build_review_queue(items: list[CreditCardItem]) -> dict:
    """构建审核队列。

    Returns:
        {
            "meta": {"total": N, "flagged_count": M, "generated_at": "..."},
            "flagged_items": [
                {
                    "item_id": "...",
                    "title": "...",
                    "url": "...",
                    "bank": "...",
                    "category": "...",
                    "flags": ["needs_category_review", ...],
                    "confidence": {...},
                    "evidence": {...},
                },
                ...
            ],
        }
    """
    flagged = []
    for item in items:
        flags = item.review_flags or generate_review_flags(item)
        if flags:
            flagged.append({
                "item_id": item.item_id,
                "title": item.display_title or item.title or item.raw_title,
                "url": item.url,
                "bank": item.bank,
                "category": item.category,
                "flags": flags,
                "severity": _severity(flags),
                "confidence": item.confidence,
                "evidence": item.evidence,
            })

    # 按 overall confidence 升序排列（最低分 = 最优先审核）
    flagged.sort(key=lambda x: (x.get("confidence") or {}).get("overall", 0.0))

    return {
        "meta": {
            "total": len(items),
            "flagged_count": len(flagged),
            "high_severity": sum(1 for f in flagged if f["severity"] == "high"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "flagged_items": flagged,
    }


# ── 审核队列输出 ───────────────────────────────────────

def _format_queue_md(queue_data: dict) -> str:
    """将审核队列格式化为 Markdown。"""
    meta = queue_data["meta"]
    lines = [
        f"# 审核清单 — 待复核条目",
        f"",
        f"**总计**: {meta['total']} 条 | **待复核**: {meta['flagged_count']} 条 | "
        f"**高优先级**: {meta.get('high_severity', '?')} 条 | "
        f"**生成时间**: {meta['generated_at']}",
        f"",
    ]
    if not queue_data["flagged_items"]:
        lines.append("无可疑条目。")
        return "\n".join(lines)

    _sev_labels = {"high": "!!! 高", "medium": "!! 中", "low": "! 低"}

    for i, fi in enumerate(queue_data["flagged_items"], 1):
        conf = fi.get("confidence") or {}
        sev = fi.get("severity", "low")
        sev_label = _sev_labels.get(sev, sev)

        lines.append(f"---")
        lines.append(f"### {i}. [{sev_label}] {fi['title']}")
        lines.append(f"")
        lines.append(f"- **银行**: {fi.get('bank', '未知')}")
        lines.append(f"- **分类**: {fi.get('category', '未知')}")
        lines.append(f"- **URL**: {fi.get('url', '无')}")
        lines.append(f"- **审核标记**: {', '.join(fi.get('flags', []))}")
        lines.append(f"- **综合置信度**: {conf.get('overall', '?'):.3f}")
        lines.append(f"  - 分类: {conf.get('category', '?'):.3f} | "
                     f"银行: {conf.get('bank', '?'):.3f} | "
                     f"标题: {conf.get('title', '?'):.3f} | "
                     f"结构化: {conf.get('structured', '?'):.3f}")
        if fi.get("evidence"):
            evidence_str = "; ".join(
                f"{k}: {', '.join(v)}" for k, v in fi["evidence"].items() if v
            )
            lines.append(f"- **依据**: {evidence_str}")
        lines.append(f"")

    return "\n".join(lines)


def export_review_queue(
    items: list[CreditCardItem],
    output_dir: str,
    batch_label: str = "",
) -> tuple[str, str]:
    """输出审核队列 JSON 和 Markdown 文件。

    Args:
        items: 条目列表
        output_dir: 输出目录
        batch_label: 批次标签（用于文件名）

    Returns:
        (json_path, md_path) 绝对路径
    """
    os.makedirs(output_dir, exist_ok=True)

    queue_data = build_review_queue(items)

    label_suffix = f"_{batch_label}" if batch_label else ""
    json_path = os.path.abspath(os.path.join(output_dir, f"review_queue{label_suffix}.json"))
    md_path = os.path.abspath(os.path.join(output_dir, f"review_queue{label_suffix}.md"))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, ensure_ascii=False, indent=2)

    md_content = _format_queue_md(queue_data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path
