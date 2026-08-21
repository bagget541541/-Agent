#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信用卡周报 Word docx → 公众号编辑器可粘贴 HTML 片段。

输入 docx 结构（Word 原生样式）：
    Title       文章总标题
    Heading1    一级分类（新卡资讯/权益变更/优惠活动/重要公告/💡持卡建议）
    Heading2    二级条目标题（带 ⚪🟡🔴 优先级 emoji 和 🆕📊📈🏦 子分类）
    ListBullet  项目符号列表
    normal      正文段落（亮点/定位/原文链接/活动内容/适用人群/详情/时间/…）

输出风格参考 D:\\ckl\\个人\\bat\\flyertrss\\_site\\公众号粘贴版_*.html：
- 外壳 max-width:640px + 浅灰背景
- 条目卡片：圆角 + 左侧 4px 色条 + 银行标签
- 亮点块：白底 + 浅灰边框 + ✨ 前缀
- 原帖链接：底部汇总区 + 11px 浅灰
- AI 声明 + 互动 CTA 收尾
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

# 兜底：确保项目根（src 的父目录）在 sys.path 中，避免从其他 CWD 运行时
# `from src.docx_to_wechat import ...` 因找不到 src package 而失败
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 复用 docx_to_wechat 的基础能力
from src.docx_to_wechat import parse_docx, _read_rels, esc, inline
from common.llm_client import LlmClient, _load_apikey_txt_configs


# ── 银行识别 + 标签配色 ──────────────────────────────────────────────
BANK_KEYWORDS: list[tuple[str, str]] = [
    ("邮政储蓄", "#0ea5e9"),
    ("邮储", "#0ea5e9"),
    ("中信", "#dc2626"),
    ("交通", "#1e40af"),
    ("交行", "#1e40af"),
    ("农业", "#16a34a"),
    ("农行", "#16a34a"),
    ("光大", "#7c3aed"),
    ("华夏", "#0ea5e9"),
    ("招商", "#dc2626"),
    ("平安", "#0891b2"),
    ("浦发", "#dc2626"),
    ("兴业", "#0891b2"),
    ("汇丰", "#dc2626"),
    ("建设", "#0ea5e9"),
    ("建行", "#0ea5e9"),
    ("上海银行", "#7c3aed"),
    ("工行", "#dc2626"),
    ("工商银行", "#dc2626"),
    ("民生", "#dc2626"),
]

# 一级分类配色（Heading1，去掉 emoji 后匹配关键词）
H1_COLORS: list[tuple[str, str]] = [
    ("新卡", "#6366f1"),
    ("权益", "#6366f1"),
    ("活动", "#6366f1"),
    ("公告", "#dc2626"),
    ("持卡建议", "#0f766e"),
    ("建议", "#0f766e"),
]
H1_DEFAULT = "#6366f1"

# 一级分类前缀 emoji
H1_EMOJI: list[tuple[str, str]] = [
    ("新卡", "🆕"),
    ("权益", "⚠️"),
    ("活动", "🎁"),
    ("公告", "📢"),
    ("持卡建议", "💡"),
    ("建议", "💡"),
]

# Heading2 优先级 emoji → 配色
PRIORITY_COLORS = {
    "🔴": "#dc2626",
    "🟡": "#d97706",
    "⚪": "#64748b",
}

# normal 段落语义前缀 → (label, color, is_block)
# is_block=True 的前缀会渲染成独立白底块（亮点/活动内容/详情等）
PREFIX_STYLES: dict[str, tuple[str, str, bool]] = {
    "亮点": ("✨ 亮点", "#0ea5e9", True),
    "原文链接": ("🔗 原帖", "#94a3b8", False),
    "定位": ("🎯 定位", "#6366f1", False),
    "活动内容": ("📋 活动内容", "#334155", True),
    "适用人群": ("👥 适用人群", "#334155", False),
    "详情": ("📝 详情", "#334155", True),
    "时间": ("📅 时间", "#334155", False),
    "影响范围": ("🌐 影响范围", "#334155", False),
    "变更内容": ("🔄 变更内容", "#334155", True),
    "卡种": ("💳 卡种", "#475569", False),
    "来源": ("📨 来源", "#94a3b8", False),
    "年费回报评估": ("💰 年费回报评估", "#475569", False),
    "是否值得申请": ("✅ 是否值得申请", "#0f766e", True),
    "是否值得": ("✅ 是否值得", "#0f766e", True),
    "核心理由": ("💡 核心理由", "#0f766e", False),
    "注意事项": ("⚠️ 注意事项", "#dc2626", True),
}


# ── 辅助函数 ──────────────────────────────────────────────────────────
def _strip_emoji(text: str) -> str:
    """去掉标题里的 emoji 和特殊符号。"""
    return re.sub(
        r"[💡🆕📊📈🏦🟡🔴⚪▸🗑📌✅❌⚠️📢🎁🆕\u200d]",
        "",
        text,
    ).strip()


def _h1_color(text: str) -> str:
    clean = _strip_emoji(text)
    for key, color in H1_COLORS:
        if key in clean:
            return color
    return H1_DEFAULT


def _h1_emoji(text: str) -> str:
    clean = _strip_emoji(text)
    for key, emoji in H1_EMOJI:
        if key in clean:
            return emoji
    return ""


def _strip_heading_number(text: str) -> str:
    """剥掉 Heading2 标题里的 '1.' '2.' 这类编号前缀。"""
    return re.sub(r"^\d+[.、)]\s*", "", text).strip()


def _h2_priority(text: str) -> tuple[str, str]:
    """从 Heading2 标题提取优先级配色 + 清理后标题（剥 N. 前缀）。"""
    # 先剥编号前缀
    text = _strip_heading_number(text)
    for emoji, color in PRIORITY_COLORS.items():
        if emoji in text:
            clean = text.replace(emoji, "").strip()
            return color, clean
    return "#475569", text


def _detect_bank(text: str) -> tuple[str, str] | None:
    """从文本里识别银行名 + 配色。返回 (bank_name, color) 或 None。"""
    for keyword, color in BANK_KEYWORDS:
        if keyword in text:
            return keyword, color
    return None


def _parse_paragraph(p_xml: str, rel_map: dict) -> dict:
    """解析单个 <w:p> 段落。"""
    style_m = re.search(r'<w:pStyle w:val="([^"]+)"', p_xml)
    style = style_m.group(1) if style_m else "normal"

    links: list[dict] = []
    for hl_m in re.finditer(r'<w:hyperlink\b[^>]*>(.*?)</w:hyperlink>', p_xml, re.S):
        hl_tag = hl_m.group(0)
        hl_inner = hl_m.group(1)
        rid = None
        m = re.search(r'\br:id="([^"]+)"', hl_tag)
        if m:
            rid = m.group(1)
        if rid and rid in rel_map:
            hl_text = "".join(
                html.unescape(t) for t in re.findall(r'<w:t[^>]*>(.*?)</w:t>', hl_inner, re.S)
            )
            links.append({"url": rel_map[rid], "text": hl_text})

    texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', p_xml, re.S)
    text = "".join(html.unescape(t) for t in texts).strip()
    has_img = "<w:blip" in p_xml or "<w:drawing" in p_xml
    return {"style": style, "text": text, "links": links, "has_img": has_img}


# ── 结构解析 ──────────────────────────────────────────────────────────
def parse_structure(paras: list[dict]) -> dict:
    """把段落列表切成结构化数据。

    返回：
    {
        "title": str,              # Title 段
        "categories": list[dict],  # 一级分类块：{name, color, emoji, items: [条目]}
        "standalone": list[dict],  # 不属于任何分类的块（💡持卡建议的子项等）
    }
    """
    title = ""
    categories: list[dict] = []
    standalone: list[dict] = []

    # 当前分类上下文
    cur_cat: dict | None = None
    # 当前条目上下文（Heading2 触发）
    cur_item: dict | None = None
    # 当前条目内块的累积器
    # blocks: list[dict]  每项 {type: paragraph/semantic/ul/bullet/spacer, ...}

    for p in paras:
        style = p["style"]
        text = p["text"]

        if style == "Title":
            title = text
            continue

        if style == "Heading1":
            # flush 上一条目
            if cur_item is not None and cur_cat is not None:
                cur_cat["items"].append(cur_item)
                cur_item = None
            # 新分类
            cur_cat = {
                "name": _strip_emoji(text),
                "raw": text,
                "color": _h1_color(text),
                "emoji": _h1_emoji(text),
                "items": [],
            }
            categories.append(cur_cat)
            continue

        if style == "Heading2":
            # flush 上一条目
            if cur_item is not None and cur_cat is not None:
                cur_cat["items"].append(cur_item)
            # 新条目
            color, clean = _h2_priority(text)
            cur_item = {
                "title": clean,
                "raw": text,
                "priority_color": color,
                "blocks": [],
                "links": [],
            }
            continue

        # ListBullet
        if style == "ListBullet":
            block = {"type": "bullet", "text": text}
            if cur_item is not None:
                cur_item["blocks"].append(block)
            else:
                standalone.append(block)
            continue

        # normal
        if not text:
            # 空段当分隔
            if cur_item is not None and cur_item["blocks"] and cur_item["blocks"][-1]["type"] != "spacer":
                cur_item["blocks"].append({"type": "spacer"})
            continue

        # 识别语义前缀
        block = _classify_normal(text, p["links"])
        if cur_item is not None:
            cur_item["blocks"].append(block)
            if block.get("links"):
                cur_item["links"].extend(block["links"])
        elif cur_cat is not None:
            # 分类下的"游离"段落（如目录里的 ⚪ 行）
            cur_cat.setdefault("preamble", []).append(block)
        else:
            standalone.append(block)

    # flush 末尾条目
    if cur_item is not None and cur_cat is not None:
        cur_cat["items"].append(cur_item)

    return {"title": title, "categories": categories, "standalone": standalone}


def _heading_level(paragraph: Paragraph) -> int | None:
    """Return a Word heading level while accepting English and Chinese styles."""
    name = paragraph.style.name or ""
    match = re.search(r"(?:Heading|标题)\s*(\d+)", name, re.I)
    if match:
        return int(match.group(1))
    style_id = paragraph.style.style_id or ""
    match = re.fullmatch(r"Heading([1-9])|([1-9])", style_id, re.I)
    if match:
        return int(match.group(1) or match.group(2))
    return None


def _iter_top_level_blocks(document: Document):
    """Yield paragraphs and tables in document order without flattening table cells."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _priority_from_blocks(blocks: list[dict]) -> tuple[str, str]:
    """从条目的 blocks 里判定价值等级。

    合并点评版文档的价值标注在"点评："行开头（如"点评：🔴高价值 — ..."）。
    只扫描 blocks 里以"点评"开头的文本，取其首个 emoji 作为价值等级；
    找不到点评行时返回"常规"——不再用"拼所有 blocks 文本搜 emoji"的
    旧逻辑，因为旧逻辑会把散落在子活动正文里的 🔴/🟡 误判为整体价值。

    返回 (priority_color, priority_label)。
    """
    for block in blocks:
        text = block.get("text", block.get("body", ""))
        # 去掉列表符号 + 点评 emoji 前缀（• ◦ ▪ 💬 等）再匹配"点评"
        stripped = re.sub(r"^[•◦▪▸‣∙💬\s]+", "", text).strip()
        if not stripped.startswith(("点评", "点评：", "点评:")):
            continue
        # 点评行开头可能是"🔴高价值"或"🟡中等"等
        for emoji, color in PRIORITY_COLORS.items():
            if emoji in stripped[:6]:  # 只看前 6 字（emoji+等级词）
                return color, {"🔴": "高价值", "🟡": "中等", "⚪": "常规"}.get(emoji, "常规")
        # 找到点评行但无 emoji，视为常规
        return "#64748b", "常规"
    # 没有点评整行：扫 semantic 块里"🔴/🟡/⚪ + 等级词 —"开头的小节点评
    for block in blocks:
        text = block.get("text", block.get("body", ""))
        # 形如"🔴高价值 — ..."或"🟡中等 — ..."
        m = re.match(r"^\s*[•◦▪▸‣∙💬\s]*([🔴🟡⚪])\s*(高价值|中等|套路|常规)", text)
        if m:
            emoji = m.group(1)
            color = PRIORITY_COLORS[emoji]
            return color, {"🔴": "高价值", "🟡": "中等", "⚪": "常规"}.get(emoji, "常规")
    # 没有点评行，回退常规
    return "#64748b", "常规"


def _outline_category(item: dict) -> str:
    """Classify merged-article entries into reader-facing categories."""
    text = " ".join(
        [item["title"]]
        + [block.get("text", block.get("body", "")) for block in item["blocks"]]
    )
    if re.search(r"停发|退市|调整|变更|公告|到期|终止", text):
        return "重要提醒"
    if re.search(r"新卡|首发|发行|卡种|Visa.*信用卡|信用卡.*Visa", text, re.I):
        return "新卡与权益"
    if re.search(r"权益|年费|里程|积分", text):
        return "权益变更"
    return "优惠活动"


def _table_rows(table: Table) -> list[list[str]]:
    return [[cell.text.strip() for cell in row.cells] for row in table.rows]


def _parse_outline_structure(docx_path: Path) -> dict | None:
    """Parse merged commentary documents: H1 title, H2 institution, H3 article.

    This structure differs from the legacy weekly-report schema (H1 category,
    H2 item). Keeping it separate prevents summaries and native tables from
    being turned into faux article cards.
    """
    document = Document(docx_path)
    blocks = list(_iter_top_level_blocks(document))
    levels = [
        _heading_level(block)
        for block in blocks
        if isinstance(block, Paragraph) and block.text.strip()
    ]
    if not ({1, 2, 3} <= set(level for level in levels if level is not None)):
        return None

    title = ""
    bank = ""
    current: dict | None = None
    entries: list[dict] = []
    summary_title = ""
    summary_rows: list[list[str]] = []
    recommendations: list[str] = []
    section = ""

    def flush_entry() -> None:
        nonlocal current
        if current is None:
            return
        color, priority = _priority_from_blocks(current["blocks"])
        current["priority_color"] = color
        current["priority"] = priority
        entries.append(current)
        current = None

    for block in blocks:
        if isinstance(block, Table):
            flush_entry()
            if section == "summary":
                summary_rows = _table_rows(block)
            continue

        text = block.text.strip()
        if not text:
            continue
        level = _heading_level(block)
        if level == 1:
            title = text
            section = ""
            continue
        if level == 2:
            flush_entry()
            if "汇总对比" in text:
                summary_title = text
                section = "summary"
            elif "重点推荐" in text or "本期推荐" in text:
                section = "recommendations"
            else:
                bank = text
                section = "article"
            continue
        if level == 3 and bank and section == "article":
            flush_entry()
            current = {
                "title": f"{bank}｜{text}",
                "raw": text,
                "blocks": [],
                "links": [],
            }
            continue
        if section == "recommendations":
            recommendations.append(text)
        elif current is not None:
            current["blocks"].append(_classify_normal(text, []))

    flush_entry()
    if not entries:
        return None

    category_order = ("优惠活动", "新卡与权益", "权益变更", "重要提醒")
    grouped: dict[str, list[dict]] = {name: [] for name in category_order}
    for item in entries:
        grouped[_outline_category(item)].append(item)
    categories = [
        {"name": name, "raw": name, "color": _h1_color(name), "emoji": _h1_emoji(name), "items": items}
        for name, items in grouped.items()
        if items
    ]
    return {
        "title": title or docx_path.stem,
        "categories": categories,
        "standalone": [],
        "outline": True,
        "summary_table": {"title": summary_title, "rows": summary_rows} if summary_rows else None,
        "recommendations": recommendations,
    }


# ── 价值提炼标题 ──────────────────────────────────────────────────────
# 价值等级排序：高价值(0) > 中等(1) > 常规(2)
_PRIORITY_RANK = {"高价值": 0, "中等": 1, "常规": 2}

# 利益词：含这些词的"活动卖点"短句最适合做标题
_BENEFIT_WORDS = (
    "返现", "立减", "免手", "免年费", "免货币", "换", "送", "赠", "加赠",
    "积分", "里程", "门票", "满减", "折扣", "立减", "随机减", "达标",
)
# 抽象评价/元描述词：这类短句不是活动卖点，应跳过
_ABSTRACT_WORDS = (
    "本质", "聊胜", "门槛不高", "门槛适中", "门槛极低", "波动大",
    "性价比", "实用性", "刚需", "顺手", "意义不大", "价值不低",
    "名列前茅", "硬权益", "硬核", "套路", "实打实",
)
# 负面/限制性词：含这些词的短句是风险提示而非卖点，应跳过
_NEGATIVE_WORDS = (
    "不透明", "需抢", "聊胜", "波动大", "意义不大", "套路", "秒不到",
    "别抱", "波动", "限制", "不免", "不可", "除外", "注意",
)


def _smart_truncate_title(text: str, limit: int = 22) -> str:
    """把卖点短语软截断到 limit 字内，在标点处收尾，不留裸省略号。

    规则：
    1. 已短于 limit：原样返回。
    2. 在 limit 字内找最后一个标点（含顿号），从那里截断。
    3. 找不到合适标点时，在 limit+4 字内找最近标点。
    4. 实在没标点，硬截断到 limit 字。
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind("，"), head.rfind(","), head.rfind("。"),
              head.rfind("；"), head.rfind(";"), head.rfind("、"))
    if cut >= limit // 2:
        return head[:cut]
    window = text[:limit + 4]
    cut2 = max(window.rfind("，"), window.rfind("、"), window.rfind("；"),
               window.rfind(";"), window.rfind("。"))
    if cut2 >= limit // 2:
        return window[:cut2]
    return head


def _pick_essence_segment(body: str) -> str:
    """从点评正文里挑出最适合做标题的"活动卖点"短句。

    评分优先级（从高到低）：
    1. 含数字 + 利益词，且不含负面词/抽象评价词 —— 最具象、最吸引人
    2. 含利益词但无数字的短句
    3. 含数字但无利益词的短句
    4. 第一个非抽象、非负面短句（兜底）

    短句按 [，,。：:（(；;] 切分。返回空串表示无可提取卖点。
    """
    segs = [s.strip() for s in re.split(r"[，,。：:（(；;]", body) if s.strip()]
    if not segs:
        return ""

    def score(s: str) -> tuple[int, int, int]:
        has_num = 1 if re.search(r"\d", s) else 0
        has_benefit = 1 if any(w in s for w in _BENEFIT_WORDS) else 0
        is_abstract = 1 if any(w in s for w in _ABSTRACT_WORDS) else 0
        is_negative = 1 if any(w in s for w in _NEGATIVE_WORDS) else 0
        if is_negative or is_abstract:
            return (-1, -1, -1)
        return (has_benefit + has_num, has_benefit, has_num)

    best = max(segs, key=score)
    if score(best)[0] < 0:
        return ""
    return best


def _build_value_title(struct: dict) -> str | None:
    """从合并点评版文档的条目里，提炼价值最高的两条卖点生成标题。

    标题结构：`信用卡资讯精选｜浦发5万消费换国际机票｜上海笔笔2%返现`
    - 优先取 🔴高价值 条目，同等级按文档原始顺序取前两条。
    - 卖点保留"机构+活动名"格式：从 item["title"]（"机构｜活动名"）取
      机构前缀 + 活动名后半段，机构名用 `_short_name` 去掉"银行"后缀。
    - 卖点用 `_smart_truncate_title` 软截断到 22 字内，在标点处收尾，
      不留裸省略号。
    - 多条并列时用"｜"分隔，避免"×"这种像乱码的连接符。

    返回标题字符串，或 None 表示无可用条目（调用方回退到默认标题）。
    """
    # 收集所有条目，扁平化为 (priority, item) 列表
    all_items: list[tuple[str, dict]] = []
    for cat in struct["categories"]:
        for item in cat["items"]:
            pri = item.get("priority", "常规")
            all_items.append((pri, item))

    if not all_items:
        return None

    # 按价值等级排序（rank 小的优先）
    all_items.sort(key=lambda x: _PRIORITY_RANK.get(x[0], 3))

    picks: list[str] = []
    seen_orgs: set[str] = set()  # 避免同一机构重复出现
    for pri, item in all_items:
        if len(picks) >= 2:
            break
        # 活动名：从 "机构｜活动名" 里取后半段；机构名取前半段
        title_full = item.get("title", "")
        org = ""
        activity = ""
        if "｜" in title_full:
            org, activity = title_full.split("｜", 1)
            org = org.strip()
            activity = activity.strip()
        else:
            activity = title_full.strip()

        # 同一机构只取一条（避免浦发🔴+浦发🟡都进标题）
        org_key = org or activity
        if org_key in seen_orgs:
            continue
        seen_orgs.add(org_key)

        # 卖点：activity 优先，缺失时从 blocks 里找点评正文提取 essence
        sell = activity
        if not sell:
            for b in item.get("blocks", []):
                body = b.get("text", b.get("body", ""))
                essence = _pick_essence_segment(body)
                if essence:
                    sell = essence
                    break

        if not sell:
            continue

        # 保留机构名前缀，机构名去掉"银行"后缀更紧凑
        org_short = re.sub(r"银行$", "", org) if org else ""
        sell = _smart_truncate_title(sell)
        picks.append(f"{org_short}{sell}")

    if not picks:
        return None

    return "信用卡资讯精选｜" + "｜".join(picks)


def _similarity_score(s1: str, s2: str) -> float:
    """计算两个字符串的相似度（0-1，1为完全相同）。"""
    if s1 == s2:
        return 1.0
    s1_clean = re.sub(r"[\d年月日天~-]", "", s1.lower())
    s2_clean = re.sub(r"[\d年月日天~-]", "", s2.lower())
    if s1_clean == s2_clean:
        return 0.95
    common = len(set(s1_clean) & set(s2_clean))
    total = len(set(s1_clean) | set(s2_clean))
    return common / total if total > 0 else 0.0


def _extract_activity_essence(title: str, body: str) -> str:
    """从活动内容中提取核心要素（时间、门槛、奖励）。"""
    essence = []

    # 提取时间
    time_match = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日[^。]*)|(\d{1,2}月\d{1,2}日[^。]*)", body)
    if time_match:
        time_str = time_match.group(0)[:30].rstrip("~")
        essence.append(f"期间：{time_str}")

    # 提取门槛（满XX元）
    threshold_matches = re.findall(r"满(\d+)元", body)
    if threshold_matches:
        thresholds = sorted(set(threshold_matches), key=lambda x: int(x))
        essence.append(f"门槛：满{thresholds[0]}元起")

    # 提取奖励（返XX元/积分）
    reward_matches = re.findall(r"(?:返|优惠|满.*?(?:返|减))(\d+)(?:元|积分)", body)
    if reward_matches:
        rewards = sorted(set(reward_matches), key=lambda x: int(x), reverse=True)
        essence.append(f"奖励：返{rewards[0]}元")
    else:
        reward_match = re.search(r"((?:满\d+)?(?:返|减|优惠|免费|赠送|券)[^。]*?)(?:。|$)", body)
        if reward_match:
            reward_text = reward_match.group(1)[:20]
            essence.append(f"奖励：{reward_text}")

    if essence:
        return " | ".join(essence)
    return ""


def _llm_json(text: str) -> dict | None:
    """Parse a JSON object from a model response, including fenced JSON."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _llm_facts_are_grounded(value: dict, source: str) -> bool:
    """Reject summaries that introduce numeric facts absent from the source."""
    source_digits = set(re.findall(r"\d+(?:\.\d+)?", source))
    output = " ".join(str(value.get(k, "")) for k in ("summary", "action"))
    return all(token in source_digits for token in re.findall(r"\d+(?:\.\d+)?", output))


def _mode_e_enrich(struct: dict) -> None:
    """Add constrained reader-facing summaries; failures keep the rule output."""
    configs = _load_apikey_txt_configs()
    clients = [LlmClient(api_key=c["api_key"], api_base=c["api_base"], model=c.get("model") or None) for c in configs]
    if not clients:
        clients = [LlmClient(config_source="file")]
    active_index = 0
    system = (
        "你是信用卡周报编辑。只能依据用户提供的原文工作，禁止补充原文没有的日期、金额、门槛、名额、银行或链接。"
        "输出严格 JSON，不要 Markdown：{\"summary\":\"一句话说明核心变化\","
        "\"action\":\"一句话说明持卡人下一步\",\"importance\":\"high|medium|low\"}。"
        "若信息不完整，明确写‘原文未明确’，不要猜测。每个字段分别不超过80字。"
    )
    total = 0
    enriched = 0
    for cat in struct.get("categories", []):
        for item in cat.get("items", []):
            total += 1
            source = " ".join(
                [item.get("title", ""), item.get("raw", "")] +
                [b.get("text", b.get("body", "")) for b in item.get("blocks", [])]
            )
            if not source.strip():
                continue
            response = None
            for offset in range(len(clients)):
                index = (active_index + offset) % len(clients)
                candidate = clients[index].call(system, f"分类：{cat.get('name', '')}\n原文：{source[:5000]}", temperature=0.1, max_tokens=220, timeout=30)
                if candidate:
                    response = candidate
                    active_index = index
                    break
            value = _llm_json(response.content) if response else None
            if not value or not value.get("summary") or not value.get("action"):
                continue
            if not _llm_facts_are_grounded(value, source):
                print(f"  [Mode E] 跳过未通过事实回查：{item.get('title', '')[:40]}", flush=True)
                continue
            importance = str(value.get("importance", "medium")).lower()
            if importance not in {"high", "medium", "low"}:
                importance = "medium"
            item["_mode_e"] = {
                "summary": str(value["summary"]).strip()[:160],
                "action": str(value["action"]).strip()[:160],
                "importance": importance,
            }
            enriched += 1
    print(f"  [Mode E] LLM 摘要写入 {enriched}/{total} 条", flush=True)


def _is_garbage(text: str) -> bool:
    """检测垃圾内容（导航菜单、文件附件等）。"""
    garbage_keywords = [
        r"^附件[：:]",
        r"^网上银行",
        r"^登录网上银行",
        r"^卡片激活",
        r"^卡片挂失",
        r"^活动查询",
        r"^申请信用卡",
        r"^在线申请",
        r"^进度查询",
        r"^推卡活动",
        r"^安全说明",
        r"^站点导航",
        r"^友情链接",
        r"^营业网点",
        r"^加入收藏",
        r"^关于我们",
        r"^人才招聘",
        r"^地址[：:]",
        r"^免费申请",
        r"^下一篇",
        r"^中信银行[·•]",
        r"^农业银行[·•]",
        r"^建设银行[·•]",
        r"^[^：：]*银行.*?信用卡\s*$",
        r"^[^：：]*[·•].*?信用卡\s*(申请|激活|详情)",
        r"^上海市",
        r"^浙江省",
        r"^江苏省",
        r"^北京市",
        r"^（回复.{1,10}可查看详情）$",
        r"^点击阅读原文",
        r"^更多内容敬请关注",
        r"^编辑：",
        r"^来源：",
    ]
    for pattern in garbage_keywords:
        if re.match(pattern, text, re.I):
            return True
    return False


def _classify_normal(text: str, links: list[dict]) -> dict:
    """把 normal 段落分类成 semantic / plain / bullet-emoji 段。"""
    # 垃圾内容过滤
    if _is_garbage(text):
        return {"type": "spacer"}  # 返回空的分隔符

    # emoji bullet：▸ • 📌 🗑 等
    if re.match(r"^[▸•📌🗑🟡🔴⚪🆕📊📈🏦]", text):
        return {"type": "bullet", "text": text}

    # 语义前缀：前缀：内容 或 前缀:内容
    m = re.match(r"^([^：:\n]{2,15})[：:]\s*(.*)$", text, re.S)
    if m:
        prefix = m.group(1).strip()
        body = m.group(2).strip()
        # 去掉 prefix 里可能混入的 emoji
        prefix_clean = re.sub(r"[🟡🔴⚪💡]", "", prefix).strip()
        if prefix_clean in PREFIX_STYLES:
            label, color, is_block = PREFIX_STYLES[prefix_clean]
            return {
                "type": "semantic",
                "prefix": label,
                "color": color,
                "body": body,
                "links": links,
                "is_block": is_block,
            }
        # 未登记前缀也走 semantic，用默认色
        return {
            "type": "semantic",
            "prefix": prefix_clean or prefix,
            "color": "#475569",
            "body": body,
            "links": links,
            "is_block": False,
        }

    # 普通段落
    return {"type": "paragraph", "text": text, "links": links}


# ── HTML 渲染（参考 flyertrss 公众号粘贴版风格）──────────────────────
def render_shell(body: str) -> str:
    """外壳 + 字体 + 行高。max-width 与 docx_to_wechat.py 保持一致。"""
    return (
        f'<div style="max-width:680px;margin:0 auto;background:#fff;'
        f'padding:20px 16px 30px;font-family:\'PingFang SC\','
        f'\'Microsoft YaHei\',sans-serif;line-height:1.8">{body}</div>'
    )


def render_title_block(title: str, subtitle: str) -> str:
    """主标题 + 副标题分隔线。"""
    return (
        f'<div style="font-size:20px;font-weight:700;line-height:1.4;'
        f'margin-bottom:8px;color:#1a1a1a">{inline(title)}</div>'
        f'<div style="font-size:13px;color:#999;margin-bottom:20px;'
        f'padding-bottom:16px;border-bottom:1px solid #eee">{esc(subtitle)}</div>'
    )


def render_overview_bar(overview_html: str) -> str:
    """周报概览条（📊 周报概览）。

    overview_html 已是拼好的 HTML 片段（含 <strong> 标签），直接插入。
    """
    return (
        f'<p style="font-size:14px;color:#666;margin-bottom:20px;'
        f'padding:12px 14px;background:#f8f9fa;border-radius:8px;'
        f'line-height:1.6">{overview_html}</p>'
    )


def render_h1(cat: dict) -> str:
    """一级分类标题（带 emoji + 左侧色条）。"""
    emoji = cat["emoji"]
    color = cat["color"]
    name = cat["name"]
    prefix = f"{emoji} " if emoji else ""
    return (
        f'<p style="font-size:15px;font-weight:600;color:#333;'
        f'margin-bottom:10px;margin-top:24px;padding-left:10px;'
        f'border-left:3px solid {color}">{prefix}{inline(name)}</p>'
    )


def render_item_card(item: dict, cat: dict) -> str:
    """单条资讯卡片：圆角 + 左侧 4px 色条 + 银行标签 + 标题 + blocks。"""
    color = item["priority_color"]
    bank = _detect_bank(item["title"] + " " + item.get("raw", ""))

    parts: list[str] = []
    # 卡片外壳
    parts.append(
        f'<div style="position:relative;background:#f8fafc;border-radius:8px;'
        f'padding:12px 14px 12px 16px;margin-bottom:10px;'
        f'border:1px solid #e5e7eb;overflow:hidden">'
    )
    # 左侧色条
    parts.append(
        f'<div style="position:absolute;left:0;top:0;bottom:0;width:4px;'
        f'background:{color}"></div>'
    )

    # 银行标签 + 来源标签
    if bank:
        bank_name, bank_color = bank
        parts.append(
            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">'
            f'<span style="display:inline-block;font-size:10px;font-weight:700;'
            f'padding:2px 8px;border-radius:4px;color:#fff;background:{bank_color}">'
            f'{esc(bank_name)}</span>'
            f'<span style="display:inline-block;font-size:10px;font-weight:600;'
            f'padding:2px 6px;border-radius:4px;color:{bank_color};'
            f'background:#fff;border:1px solid {bank_color}">website</span></div>'
        )

    # 条目标题
    parts.append(
        f'<div style="font-size:15px;font-weight:600;color:#0f172a;'
        f'line-height:1.4;margin-top:2px">{inline(item["title"])}</div>'
    )

    mode_e = item.get("_mode_e")
    if mode_e:
        importance_label = {"high": "优先关注", "medium": "值得留意", "low": "常规信息"}[mode_e["importance"]]
        parts.append(
            f'<p style="font-size:12px;color:#475569;margin:7px 0 4px;line-height:1.65">'
            f'<span style="color:#2563eb;font-weight:700">🧭 读者要点：</span>{inline(mode_e["summary"])}'
            f'</p>'
        )
        parts.append(
            f'<p style="font-size:12px;color:#475569;margin:4px 0;line-height:1.65">'
            f'<span style="color:#0f766e;font-weight:700">✅ {importance_label}：</span>{inline(mode_e["action"])}'
            f'</p>'
        )

    # blocks 渲染
    for b in item["blocks"]:
        parts.append(_render_block(b, item))

    parts.append("</div>")
    return "".join(parts)


# 要从条目卡片里干掉的长正文前缀（详细内容）
SKIP_DETAIL_PREFIXES = {
    "活动内容",
    "详情",
    "变更内容",
    "时间",
    "影响范围",
    "适用人群",
    "年费回报评估",
    "注意事项",
    "核心理由",
    "卡种",
    "来源",
}


def _render_block(b: dict, item: dict) -> str:
    """渲染条目内的单个 block。详细内容前缀直接跳过。"""
    t = b["type"]

    # semantic 段：过滤详细内容前缀
    if t == "semantic":
        prefix = b.get("prefix", "")
        # 去掉 emoji 后比较
        prefix_clean = re.sub(r"[✨📋📝🔄📅🌐👥💰💳📨✅💡⚠️]", "", prefix).strip()
        if prefix_clean in SKIP_DETAIL_PREFIXES:
            return ""
        return _render_semantic(b)

    if t == "spacer":
        return '<div style="height:4px"></div>'

    if t == "bullet":
        return (
            f'<p style="font-size:12px;color:#475569;margin:4px 0;'
            f'padding-left:8px;line-height:1.6">{inline(b["text"])}</p>'
        )

    if t == "paragraph":
        rendered = inline(b["text"])
        for lnk in b.get("links", []):
            rendered += f' <a href="{esc(lnk["url"])}" style="color:#0ea5e9;text-decoration:none">{esc(lnk["text"] or lnk["url"])}</a>'
        return (
            f'<p style="font-size:12px;color:#475569;margin:4px 0;'
            f'line-height:1.6">{rendered}</p>'
        )

    return ""


def _truncate_semantic_body(prefix: str, body: str) -> str:
    """根据前缀类型对内容进行截断。"""
    if not body:
        return body
    body = re.sub(r"\s+", " ", body).strip()
    # 对于详情、活动内容、变更内容等较长字段，限制到2-3句话
    if any(k in prefix for k in ["详情", "活动内容", "变更内容", "影响范围"]):
        sentences = re.split(r'([。！？…])', body)
        if len(sentences) > 1:
            count = 0
            result = []
            for part in sentences:
                result.append(part)
                if part and re.search(r'[。！？…]', part):
                    count += 1
                    if count >= 2:
                        return "".join(result)
    # 其他字段的长度限制
    max_len = 200 if any(k in prefix for k in ["详情", "活动内容"]) else 150
    return body if len(body) <= max_len else body[:max_len].rstrip() + "…"


def _render_semantic(b: dict) -> str:
    """渲染语义段（亮点/定位/原文链接/活动内容 等）。

    is_block=True 的前缀（亮点/活动内容/详情/是否值得/注意事项/变更内容）
    渲染成独立白底块；其余渲染成行内 strong + 内容。

    如果 body 为空，则跳过此块。
    """
    prefix = b["prefix"]
    color = b["color"]
    body = b["body"].strip() if b.get("body") else ""
    links = b.get("links", [])
    is_block = b.get("is_block", False)

    # 空内容检测：如果 body 和 links 都为空，则跳过此块
    if not body and not links:
        return ""

    # 原文链接特殊处理
    if "原帖" in prefix or "原文链接" in prefix:
        # body 通常是 URL
        url = body.strip()
        if not url:
            return ""
        return (
            f'<div style="margin-top:6px;font-size:11px;color:#94a3b8;'
            f'word-break:break-all">{esc(prefix)} '
            f'<a href="{esc(url)}" style="color:#0ea5e9;text-decoration:none">{esc(url)}</a></div>'
        )

    # 清理语义块中的垃圾内容
    body = re.sub(r"附件[\s：:]*[^\n]*", "", body)          # 附件引用
    body = re.sub(r"（?点击[^）)]*[)）]", "", body)           # 门户/APP 引用
    body = re.sub(r"查看附近适用门店.*?[)）]", "", body)     # 门店引用
    body = re.sub(r"\s+", " ", body).strip()

    # 清理后重新判空：body 可能全部是垃圾内容而被清空
    if not body and not links:
        return ""

    # 对 body 进行截断处理
    body = _truncate_semantic_body(prefix, body)
    rendered_body = inline(body)
    # 追加 links
    for lnk in links:
        rendered_body += f' <a href="{esc(lnk["url"])}" style="color:#0ea5e9;text-decoration:none">{esc(lnk["text"] or lnk["url"])}</a>'

    if is_block:
        return (
            f'<div style="font-size:12px;color:#1e293b;margin-top:6px;'
            f'padding:6px 8px;background:#fff;border:1px solid #e5e7eb;'
            f'border-radius:6px;line-height:1.6">'
            f'<span style="color:{color};font-weight:700">{esc(prefix)}：</span>'
            f'{rendered_body}</div>'
        )
    else:
        return (
            f'<p style="font-size:12px;color:#475569;margin:4px 0;line-height:1.6">'
            f'<span style="color:{color};font-weight:700">{esc(prefix)}：</span>'
            f'{rendered_body}</p>'
        )


def render_links_summary(all_links: list[dict]) -> str:
    """文末原帖链接汇总区。"""
    if not all_links:
        return ""
    items: list[str] = []
    for i, lnk in enumerate(all_links, 1):
        title = lnk.get("text") or lnk["url"]
        items.append(
            f'<p style="font-size:12px;color:#6366f1;margin:3px 0;'
            f'word-break:break-all">{i}. {inline(title)}<br>'
            f'<span style="font-size:11px;color:#94a3b8">{esc(lnk["url"])}</span></p>'
        )
    return (
        f'<div style="margin-top:24px;padding:14px 16px;background:#f8fafc;'
        f'border-radius:10px;border:1px solid #e5e7eb">'
        f'<p style="font-size:14px;font-weight:600;color:#333;margin-bottom:8px">'
        f'🔗 原帖链接</p>{"".join(items)}</div>'
    )


def render_summary_table(summary: dict | None) -> str:
    """Render a native DOCX summary table as a standalone, scrollable section."""
    if not summary or not summary.get("rows"):
        return ""
    rows = summary["rows"]
    header = rows[0]
    head_html = "".join(
        f'<th style="padding:8px 7px;background:#f1f5f9;border-bottom:1px solid #cbd5e1;'
        f'font-size:12px;color:#334155;text-align:left;white-space:nowrap">{inline(cell)}</th>'
        for cell in header
    )
    body_html = "".join(
        "<tr>" + "".join(
            f'<td style="padding:8px 7px;border-bottom:1px solid #e5e7eb;font-size:12px;'
            f'line-height:1.6;vertical-align:top;color:#475569">{inline(cell)}</td>'
            for cell in row
        ) + "</tr>"
        for row in rows[1:]
    )
    return (
        f'<div style="margin:24px 0 0"><p style="font-size:15px;font-weight:600;color:#333;'
        f'margin:0 0 10px;padding-left:10px;border-left:3px solid #6366f1">{inline(summary["title"])}</p>'
        f'<div style="overflow-x:auto;border:1px solid #e2e8f0"><table style="min-width:720px;width:100%;'
        f'border-collapse:collapse"><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table></div></div>'
    )


def render_recommendations(recommendations: list[str]) -> str:
    if not recommendations:
        return ""
    rows = "".join(
        f'<p style="font-size:13px;color:#334155;margin:6px 0;line-height:1.7">{inline(item)}</p>'
        for item in recommendations
    )
    return (
        '<div style="margin-top:24px;padding:14px 16px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px">'
        '<p style="font-size:15px;font-weight:600;color:#92400e;margin:0 0 8px">本期重点推荐</p>'
        f'{rows}</div>'
    )


def render_footer(generated_on: date) -> str:
    """Keep publication metadata outside recommendation or article cards."""
    date_text = f"{generated_on.year}年{generated_on.month}月{generated_on.day}日"
    return (
        '<div style="margin-top:24px;padding-top:14px;border-top:1px solid #e5e7eb">'
        f'<p style="font-size:12px;color:#94a3b8;margin:0 0 6px">整理时间：{date_text}</p>'
        '<p style="font-size:12px;color:#94a3b8;margin:0;line-height:1.6">'
        '本内容由 Coze AI 生成，请遵循相关法律法规及《人工智能生成合成内容标识办法》使用与传播。'
        '</p></div>'
    )


def render_html(struct: dict, docx_path: Path, mode: str = "rule") -> str:
    """主渲染入口。"""
    # 去重处理：识别并合并相同类型的重复活动
    for cat in struct["categories"]:
        deduplicated = []
        for i, item in enumerate(cat["items"]):
            is_duplicate = False
            for j in range(i):
                if _similarity_score(item["title"], cat["items"][j]["title"]) > 0.8:
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduplicated.append(item)
        cat["items"] = deduplicated

    # 内容提炼：对活动类条目提取核心要素
    for cat in struct["categories"]:
        if "活动" in cat["name"] or "优惠" in cat["name"]:
            for item in cat["items"]:
                raw_blocks = " ".join(b.get("text", b.get("body", "")) for b in item.get("blocks", []))
                essence = _extract_activity_essence(item["title"], raw_blocks)
                if essence:
                    # 在亮点前添加活动要点
                    has_highlight = any("亮点" in b.get("prefix", "") for b in item.get("blocks", []) if b.get("type") == "semantic")
                    if has_highlight:
                        item["_essence"] = essence
                    else:
                        # 添加新的语义块表示活动要点
                        item["blocks"].insert(0, {
                            "type": "semantic",
                            "prefix": "📌 活动要点",
                            "color": "#d97706",
                            "body": essence,
                            "is_block": False,
                            "links": [],
                        })

    if mode == "e":
        _mode_e_enrich(struct)

    # 标题从新卡+权益变更各取第一条，用-连接
    new_card_title = None
    change_title = None

    for cat in struct["categories"]:
        cat_name = cat["name"].strip()
        if "新卡" in cat_name and not new_card_title and cat["items"]:
            new_card_title = cat["items"][0]["title"]
        elif ("权益" in cat_name or "变更" in cat_name) and not change_title and cat["items"]:
            change_title = cat["items"][0]["title"]

    if mode == "e":
        week_match = re.search(r"(\d{4}年\d{1,2}月第\d+周)", docx_path.stem)
        week_label = week_match.group(1) if week_match else "本周"
        title = f"信用卡周报｜{week_label}"
        subtitle = "停发、协议更新与高性价比活动：本周持卡人最该关注的资讯"
    elif not struct.get("outline") and new_card_title and change_title:
        title = f"{new_card_title} - {change_title}"
        subtitle = docx_path.stem
    else:
        # 合并点评版（outline）文档：优先用价值提炼标题
        value_title = _build_value_title(struct) if struct.get("outline") else None
        title = value_title or struct["title"] or docx_path.stem
        subtitle = docx_path.stem

    # 收集所有条目的链接，供文末汇总
    all_links: list[dict] = []

    body_parts: list[str] = []
    body_parts.append(render_title_block(title, subtitle))

    # 概览条：统计各类别条目数
    cat_stats: list[tuple[str, int]] = []
    total_items = 0
    for cat in struct["categories"]:
        n = len(cat["items"])
        if n > 0:
            cat_stats.append((cat["name"], n))
            total_items += n
    if cat_stats:
        stats_html = " · ".join(
            f'<strong style="color:#6366f1">{esc(name)}</strong> {cnt}条'
            for name, cnt in cat_stats
        )
        overview = (
            f'📊 <strong>周报概览</strong> — {esc(subtitle)} · '
            f'本期共 <strong>{total_items}</strong> 条 · {stats_html}'
        )
        high_value = [
            item for cat in struct["categories"] for item in cat["items"]
            if item.get("priority") == "高价值"
        ]
        if high_value:
            names = "、".join(item["title"].split("｜", 1)[0] for item in high_value[:3])
            overview += f' · 🔴高价值 <strong>{len(high_value)}</strong> 条：{inline(names)}'
    else:
        overview = f"📊 <strong>周报概览</strong> — {esc(subtitle)} · 信用卡周报"
    body_parts.append(render_overview_bar(overview))

    # 各分类
    for cat in struct["categories"]:
        body_parts.append(render_h1(cat))
        # preamble（目录里的 ⚪ 行等）
        for b in cat.get("preamble", []):
            body_parts.append(_render_block(b, {"blocks": [], "links": []}))
        # 条目卡片
        for item in cat["items"]:
            body_parts.append(render_item_card(item, cat))
            # 收集 links：优先 item["links"]，再从 blocks 里抓 URL
            for lnk in item.get("links", []):
                all_links.append(lnk)
            for b in item["blocks"]:
                # 从 semantic 段（原文链接/原帖）body 里抓 URL
                if b.get("type") == "semantic" and ("原帖" in b.get("prefix", "") or "原文链接" in b.get("prefix", "")):
                    urls = re.findall(r"https?://[^\s）)]+", b.get("body", ""))
                    for u in urls:
                        all_links.append({"url": u, "text": item["title"]})
                # 从 paragraph/bullet 文本里抓 URL
                if b.get("type") in ("paragraph", "bullet"):
                    urls = re.findall(r"https?://[^\s）)]+", b.get("text", ""))
                    for u in urls:
                        all_links.append({"url": u, "text": item["title"]})

    # 文末链接汇总
    body_parts.append(render_links_summary(all_links))
    body_parts.append(render_summary_table(struct.get("summary_table")))
    body_parts.append(render_recommendations(struct.get("recommendations", [])))
    body_parts.append(render_footer(date.today()))

    body = "".join(body_parts)
    return render_shell(body)


def convert(docx_path: Path, output: Path | None = None, mode: str = "rule") -> Path:
    # 复用 docx_to_wechat.parse_docx()：一次解 zip + XML，返回带 style/links/has_img 的段落
    struct = _parse_outline_structure(docx_path)
    if struct is None:
        paras = parse_docx(docx_path)
        struct = parse_structure(paras)
    fragment = render_html(struct, docx_path, mode=mode)

    out = output or docx_path.with_name(docx_path.stem + "_公众号粘贴版.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(fragment, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="信用卡周报 Word docx → 公众号可粘贴 HTML")
    ap.add_argument("docx", help="输入 docx 文件")
    ap.add_argument("--output", default="", help="输出 HTML 路径")
    ap.add_argument("--mode", choices=("rule", "e"), default="rule", help="rule=规则提炼；e=规则提炼后使用 LLM 生成受约束摘要")
    args = ap.parse_args()
    source = Path(args.docx)
    if not source.is_file():
        ap.error(f"文件不存在：{source}")
    out = Path(args.output) if args.output else None
    result = convert(source, out, mode=args.mode)
    print(f"[OK] 公众号粘贴 HTML -> {result}")
    print("操作：浏览器打开 HTML 后全选复制，粘贴到公众号编辑器。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
