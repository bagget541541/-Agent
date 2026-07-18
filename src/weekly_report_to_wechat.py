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
import re
import sys
import zipfile
from pathlib import Path

# 兜底：确保项目根（src 的父目录）在 sys.path 中，避免从其他 CWD 运行时
# `from src.docx_to_wechat import ...` 因找不到 src package 而失败
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 复用 docx_to_wechat 的基础能力
from src.docx_to_wechat import parse_docx, _read_rels, esc, inline


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


def _classify_normal(text: str, links: list[dict]) -> dict:
    """把 normal 段落分类成 semantic / plain / bullet-emoji 段。"""
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


def _render_semantic(b: dict) -> str:
    """渲染语义段（亮点/定位/原文链接/活动内容 等）。

    is_block=True 的前缀（亮点/活动内容/详情/是否值得/注意事项/变更内容）
    渲染成独立白底块；其余渲染成行内 strong + 内容。
    """
    prefix = b["prefix"]
    color = b["color"]
    body = b["body"]
    links = b.get("links", [])
    is_block = b.get("is_block", False)

    # 原文链接特殊处理
    if "原帖" in prefix or "原文链接" in prefix:
        # body 通常是 URL
        url = body.strip()
        return (
            f'<div style="margin-top:6px;font-size:11px;color:#94a3b8;'
            f'word-break:break-all">{esc(prefix)} '
            f'<a href="{esc(url)}" style="color:#0ea5e9;text-decoration:none">{esc(url)}</a></div>'
        )

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


def render_html(struct: dict, docx_path: Path) -> str:
    """主渲染入口。"""
    title = struct["title"] or docx_path.stem
    # 副标题：从文件名提取周次
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

    body = "".join(body_parts)
    return render_shell(body)


def convert(docx_path: Path, output: Path | None = None) -> Path:
    # 复用 docx_to_wechat.parse_docx()：一次解 zip + XML，返回带 style/links/has_img 的段落
    paras = parse_docx(docx_path)

    struct = parse_structure(paras)
    fragment = render_html(struct, docx_path)

    out = output or docx_path.with_name(docx_path.stem + "_公众号粘贴版.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(fragment, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="信用卡周报 Word docx → 公众号可粘贴 HTML")
    ap.add_argument("docx", help="输入 docx 文件")
    ap.add_argument("--output", default="", help="输出 HTML 路径")
    args = ap.parse_args()
    source = Path(args.docx)
    if not source.is_file():
        ap.error(f"文件不存在：{source}")
    out = Path(args.output) if args.output else None
    result = convert(source, out)
    print(f"[OK] 公众号粘贴 HTML -> {result}")
    print("操作：浏览器打开 HTML 后全选复制，粘贴到公众号编辑器。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
