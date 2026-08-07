#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信用卡资讯「整合点评」docx → 公众号编辑器可粘贴 HTML 片段。

支持两种输入 docx 结构，按文档实际样式自动路由（见 `_looks_like_legacy_four_part` /
`_has_heading_hierarchy`），不依赖文件名或调用方式：

1. 旧版「四段式」扁平段落（无 Word 标题层级，`来源：`/`核心内容：`/`点评：` 成组出现 ≥2 次）：
    标题行        例：农行 - 农行Visa全球支付尊享白金卡
    来源：xxx
    核心内容：xxx
    点评：xxx
   文末含「本期总结」区块和「原始链接」列表。→ `parse_structure()` + `render_html()`

2. 「文档流」大纲结构（使用 Word `Heading2`/`Heading3` 样式分级，如 Heading2=机构名、
   Heading3=活动名，可含原生表格）：只要检测到标题层级即视为此类，即使正文段落也带
   `来源：`/`点评：` 前缀也不会被误判为四段式。→ `render_docx_flow()`，按文档顺序保留
   标题、列表、表格与引用块，并自动生成「本期速览」统计、条目编号与分隔线。

输出：单文件 HTML 片段，浏览器打开后全选复制，粘贴进公众号编辑器即可。
"""
from __future__ import annotations

import argparse
import html
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

# ── 主题色（沿用 md_to_wechat.py 思路，按关键词给标题/点评配色）──────────
COLORS = {
    "权益": "#2563eb",
    "积分": "#7c3aed",
    "AI": "#0891b2",
    "活动": "#d97706",
    "年轻": "#db2777",
    "行动": "#0f766e",
    "境外": "#0f766e",
    "返现": "#2563eb",
    "年费": "#db2777",
    "世界杯": "#d97706",
}
DEFAULT_COLOR = "#475569"


# ── docx 读取 ──────────────────────────────────────────────────────────
def _read_rels(zf: zipfile.ZipFile) -> dict[str, str]:
    """r:id -> 真实 URL"""
    try:
        rels_xml = zf.read("word/_rels/document.xml.rels").decode("utf-8", errors="replace")
    except KeyError:
        return {}
    out: dict[str, str] = {}
    for m in re.finditer(r'<Relationship\b[^>]*>', rels_xml):
        tag = m.group(0)
        if 'TargetMode="External"' not in tag:
            continue
        rid = re.search(r'Id="([^"]+)"', tag)
        target = re.search(r'Target="([^"]+)"', tag)
        if rid and target and target.group(1).startswith("http"):
            out[rid.group(1)] = target.group(1)
    return out


def _strip_tags(s: str) -> str:
    """剥掉所有 <...> 标签。"""
    return re.sub(r"<[^>]+>", "", s)


def parse_docx(path: Path) -> list[dict]:
    """返回段落列表，每段含 text / links / style / has_img。

    其中 style 与 has_img 为可选字段（早期调用方仅用 text 与 links）。
    """
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        rel_map = _read_rels(zf)

    # 切成 <w:p ...> ... </w:p> 段
    paras_xml = re.findall(r"<w:p\b[^>]*>.*?</w:p>", xml, re.S)
    paragraphs: list[dict] = []
    for pxml in paras_xml:
        # 段落样式（Title / Heading1 / Heading2 / ListBullet / normal）
        style_m = re.search(r'<w:pStyle w:val="([^"]+)"', pxml)
        style = style_m.group(1) if style_m else "normal"

        # 段内 hyperlink：可能带 r:id 指向外部 URL
        links: list[dict] = []
        for hl in re.finditer(r"<w:hyperlink\b[^>]*>(.*?)</w:hyperlink>", pxml, re.S):
            hl_inner = hl.group(1)
            # 抓 r:id（两种命名空间写法都兼容）
            rid = None
            m = re.search(r'\br:id="([^"]+)"', hl.group(0))
            if m:
                rid = m.group(1)
            elif re.search(r'\brelationships/id="', hl.group(0)):
                rid = re.search(r'relationships/id="([^"]+)"', hl.group(0)).group(1)
            hl_text = _strip_tags(
                "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", hl_inner, re.S))
            )
            if rid and rid in rel_map:
                links.append({"url": rel_map[rid], "text": hl_text})

        # 段内纯文本
        t_text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", pxml, re.S))
        full_text = html.unescape(_strip_tags(t_text)).strip()
        has_img = "<w:blip" in pxml or "<w:drawing" in pxml
        if full_text or links:
            paragraphs.append({
                "text": full_text,
                "links": links,
                "style": style,
                "has_img": has_img,
            })
    return paragraphs



def _iter_docx_blocks(document: DocxDocument) -> list[Paragraph | Table]:
    """Yield top-level paragraphs and tables in document order."""
    blocks: list[Paragraph | Table] = []
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            blocks.append(Paragraph(child, document))
        elif isinstance(child, CT_Tbl):
            blocks.append(Table(child, document))
    return blocks
# ── 内联渲染（精简自 md_to_wechat.inline）─────────────────────────────
def esc(value: str) -> str:
    return html.escape(value, quote=True)


def color_for(text: str) -> str:
    for key, color in COLORS.items():
        if key in text:
            return color
    return DEFAULT_COLOR


def inline(text: str) -> str:
    """内联转换：**加粗**、*斜体*、`代码`、URL 链接。"""
    tokens: list[str] = []

    def hold(value: str) -> str:
        tokens.append(value)
        return f"\x00{len(tokens) - 1}\x00"

    # 先占位 URL（避免被 esc 转义破坏）
    text = re.sub(
        r"(https?://[^\s）)]+)",
        lambda m: hold(f'<a href="{esc(m.group(1))}" style="color:#2563eb;text-decoration:none">{esc(m.group(1))}</a>'),
        text,
    )
    text = esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r'<span style="font-family:monospace;background:#f1f5f9;padding:1px 4px;border-radius:3px">\1</span>', text)
    for i, value in enumerate(tokens):
        text = text.replace(f"\x00{i}\x00", value)
    return text


# ── 语义块识别 ─────────────────────────────────────────────────────────
def _split_url_text(text: str) -> list[tuple[str, str]]:
    """把『… URL … 文字 … URL …』切成按顺序的 ('url', u) / ('text', t) 段。"""
    segs: list[tuple[str, str]] = []
    last = 0
    for m in re.finditer(r"https?://[^\s）)]+", text):
        if m.start() > last:
            segs.append(("text", text[last:m.start()]))
        segs.append(("url", m.group(0)))
        last = m.end()
    if last < len(text):
        segs.append(("text", text[last:]))
    # 清理空 text
    return [(k, v.strip()) if k == "text" else (k, v) for k, v in segs if not (k == "text" and not v.strip())]


def parse_structure(paras: list[dict]) -> dict:
    """把段落切成结构化数据。"""
    article_title = ""
    for p in paras:
        t = p["text"].strip()
        if not t:
            continue
        # 文章总标题：第一段非空且不含"来源/核心内容/点评/本期/原始"前缀，
        # 且不是『银行 - 卡名』格式
        t_clean = _strip_leading_markers(t)
        if not article_title and not t_clean.startswith(("来源", "核心内容", "点评", "本期", "新卡", "卡组织", "年费", "原始")):
            article_title = t
            break

    items: list[dict] = []
    cur: dict | None = None
    summary_lines: list[str] = []
    raw_link_segs: list[str] = []  # 按出现顺序记录 URL 和非 URL 文本片段
    in_summary = False
    in_links = False
    started_items = False

    for p in paras:
        t = p["text"].strip()
        if not t and not p["links"]:
            continue

        # 跳过文章总标题段
        if not started_items and article_title and t == article_title:
            started_items = True
            continue
        started_items = True

        # 原始链接区块
        if "原始链接" in t or in_links:
            in_links = True
            # 段内纯文本 URL
            if t and "原始链接" not in t:
                raw_link_segs.extend(_split_url_text(t))
            # 段内 hyperlink：仅在文本不是 URL 前缀时才作为标题使用
            for lnk in p["links"]:
                hl_text = (lnk.get("text") or "").strip()
                # 如果 hyperlink 文本是 URL 本身/前缀，或为空，就当成纯 URL 段
                if not hl_text or hl_text.startswith("http"):
                    raw_link_segs.append(("url", lnk["url"]))
                else:
                    # 形如『标题 URL』：hyperlink 文本是 URL 的标题
                    raw_link_segs.append(("text", hl_text))
                    raw_link_segs.append(("url", lnk["url"]))
            continue

        # 本期总结区块
        if t.startswith("本期总结") or t == "本期总结":
            in_summary = True
            continue
        if in_summary:
            summary_lines.append(t)
            continue

        # 四段式（处理行首前缀符号）
        t_clean = _strip_leading_markers(t)
        if t_clean.startswith("来源：") or t_clean.startswith("来源:"):
            if cur is not None:
                cur["source"] = t_clean.split("：", 1)[-1].split(":", 1)[-1].strip()
            continue
        if t_clean.startswith("核心内容：") or t_clean.startswith("核心内容:"):
            body = t_clean.split("：", 1)[-1].split(":", 1)[-1].strip()
            if cur is not None:
                cur["core"] = body
            continue
        if t_clean.startswith("点评：") or t_clean.startswith("点评:"):
            review = t_clean.split("：", 1)[-1].split(":", 1)[-1].strip()
            if cur is not None:
                cur["review"] = review
            continue

        # 否则视为新条目标题行
        if cur is not None:
            items.append(cur)
        cur = {"title": t, "source": "", "core": "", "review": ""}

    if cur is not None:
        items.append(cur)

    # 配对：把连续的 ('url', u) + ('text', t) 合并成 {url, title}
    raw_links: list[dict] = []
    seen_urls: set[str] = set()
    i = 0
    while i < len(raw_link_segs):
        kind, val = raw_link_segs[i]
        if kind == "url":
            title = ""
            # 看下一个是否为 text（同行紧随的标题）
            if i + 1 < len(raw_link_segs) and raw_link_segs[i + 1][0] == "text":
                title = raw_link_segs[i + 1][1].strip()
                i += 2
            else:
                i += 1
            if val in seen_urls:
                continue
            seen_urls.add(val)
            raw_links.append({"url": val, "title": title})
        else:
            # 孤立的 text 片段：可能是『标题 URL』模式里 URL 前的标题
            title = val.strip()
            if i + 1 < len(raw_link_segs) and raw_link_segs[i + 1][0] == "url":
                url = raw_link_segs[i + 1][1]
                if url not in seen_urls:
                    seen_urls.add(url)
                    raw_links.append({"url": url, "title": title})
                i += 2
                continue
            i += 1

    return {
        "article_title": article_title,
        "items": items,
        "summary_lines": summary_lines,
        "raw_links": raw_links,
    }


# ── HTML 渲染 ──────────────────────────────────────────────────────────
def render_card_item(item: dict, index: int) -> str:
    """单条资讯卡片。"""
    color = color_for(item["title"] + " " + item["core"])
    parts: list[str] = []
    # 标题
    parts.append(
        f'<h3 style="font-size:17px;line-height:1.5;color:{color};margin:24px 0 6px;font-weight:700">'
        f'{index}. {inline(item["title"])}</h3>'
    )
    # 来源
    if item["source"]:
        parts.append(
            f'<p style="margin:2px 0;color:#94a3b8;font-size:12px">来源：{inline(item["source"])}</p>'
        )
    # 核心内容
    if item["core"]:
        parts.append(
            f'<p style="margin:8px 0 4px;color:#334155;font-size:14px;line-height:1.85;text-align:justify">'
            f'<strong style="color:#0f172a">核心内容：</strong>{inline(item["core"])}</p>'
        )
    # 点评
    if item["review"]:
        parts.append(
            f'<blockquote style="margin:10px 0 0;padding:10px 14px;border-left:4px solid {color};'
            f'background:#f8fafc;color:#334155;font-size:13px;line-height:1.85">'
            f'<strong style="color:{color}">点评：</strong>{inline(item["review"])}</blockquote>'
        )
    return "\n".join(parts)


def render_summary(summary_lines: list[str]) -> str:
    """『本期总结』区块：标题行 + 列表。"""
    if not summary_lines:
        return ""
    out: list[str] = [
        f'<div style="margin:32px 0 12px;padding:9px 12px;border-left:4px solid #0f766e;background:#f8fafc">'
        f'<h2 style="font-size:18px;line-height:1.5;color:#0f172a;margin:0;font-weight:700">本期总结</h2></div>'
    ]
    list_items: list[str] = []
    for line in summary_lines:
        line = line.lstrip("•·- ").strip()
        if not line:
            continue
        list_items.append(
            f'<li style="margin:4px 0;line-height:1.8">{inline(line)}</li>'
        )
    if list_items:
        out.append(
            f'<ul style="margin:10px 0;padding-left:24px;color:#334155;font-size:14px">{"".join(list_items)}</ul>'
        )
    return "\n".join(out)


def render_raw_links(raw_links: list[dict]) -> str:
    if not raw_links:
        return ""
    out: list[str] = [
        f'<div style="margin:32px 0 12px;padding:9px 12px;border-left:4px solid #2563eb;background:#f8fafc">'
        f'<h2 style="font-size:18px;line-height:1.5;color:#0f172a;margin:0;font-weight:700">原文链接</h2></div>'
    ]
    items: list[str] = []
    for i, lnk in enumerate(raw_links, 1):
        title = lnk["title"] or lnk["url"]
        items.append(
            f'<li style="margin:6px 0;line-height:1.7;font-size:13px">'
            f'<a href="{esc(lnk["url"])}" style="color:#2563eb;text-decoration:none">{inline(title)}</a></li>'
        )
    out.append(
        f'<ol style="margin:10px 0;padding-left:24px;color:#334155">{"".join(items)}</ol>'
    )
    return "\n".join(out)


def _paragraph_kind(paragraph: Paragraph, index: int) -> str:
    style = paragraph.style.name if paragraph.style is not None else ""
    text = paragraph.text.strip()
    # index==0 恒为全文标题；其余情况下，实际标题样式（Heading1/2/3）优先于
    # index==1 的"副标题"猜测——否则真正的层级标题（如第一个银行名恰好是第二段）
    # 会被误判成普通副标题，丢失应有的标题渲染。
    if index == 0:
        return "title"
    if style.startswith("Heading 1"):
        return "h2"
    if style.startswith("Heading 2"):
        return "h3"
    if style.startswith("Heading 3"):
        return "h4"
    if style.startswith(("Quote", "Block")):
        return "quote"
    if style.startswith("List"):
        return "li"
    if index == 1:
        return "subtitle"
    if re.fullmatch(r"[─\-—]{6,}", text):
        return "rule"
    if text.startswith(("🔴", "🟡", "⚪", "🆕")) and len(text) <= 40:
        return "badge"
    if _strip_leading_markers(text) != text:
        return "li"
    return "p"


def _render_table(table: Table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            parts = [p.text.strip() for p in cell.paragraphs if p.text.strip()]
            cells.append("<br>".join(inline(part) for part in parts))
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""

    header = rows[0]
    head_html = "".join(
        f'<th style="padding:8px;text-align:left;background:#f1f5f9;border-bottom:1px solid #cbd5e1;font-size:12px;line-height:1.5;vertical-align:top">{cell}</th>'
        for cell in header
    )
    body_rows = []
    for row in rows[1:]:
        body_rows.append(
            "<tr>" + "".join(
                f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;font-size:12px;line-height:1.65;vertical-align:top;color:#334155">{cell}</td>'
                for cell in row
            ) + "</tr>"
        )
    return (
        '<div style="overflow-x:auto;margin:12px 0 18px">'
        '<table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb">'
        f'<thead><tr>{head_html}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'
    )


def _classify_docx_blocks(
    document: DocxDocument,
) -> tuple[list[tuple[Paragraph | Table, str | None]], list[bool]]:
    """将文档拆分为 (block, kind) 序列，并标记出真正的"条目"起点（h3 级标题后
    紧跟 h4 级子标题，与"h3 后接表格"的汇总性小节如"汇总对比"区分开）。
    供 render_docx_flow 与自动标题挑选共用，避免两处各自维护一份分类逻辑。
    """
    blocks = _iter_docx_blocks(document)
    classified: list[tuple[Paragraph | Table, str | None]] = []
    paragraph_index = 0
    for block in blocks:
        if isinstance(block, Table):
            classified.append((block, None))
            continue
        text = block.text.strip()
        if not text:
            classified.append((block, "blank"))
            continue
        kind = _paragraph_kind(block, paragraph_index)
        paragraph_index += 1
        classified.append((block, kind))

    def _next_meaningful_kind(i: int) -> str | None:
        for j in range(i + 1, len(classified)):
            k = classified[j][1]
            if k == "blank":
                continue
            return k
        return None

    entry_flags = [
        kind == "h3" and _next_meaningful_kind(i) == "h4"
        for i, (_block, kind) in enumerate(classified)
    ]
    return classified, entry_flags


_VALUE_RANK = {"🔴": 0, "🟡": 1, "⚪": 2}


def _short_name(name: str) -> str:
    """去掉条目名末尾的"银行"后缀，便于在标题/速览等紧凑场景中显示。"""
    return re.sub(r"银行$", "", name) or name


def _collect_entries(
    classified: list[tuple[Paragraph | Table, str | None]], entry_flags: list[bool]
) -> list[dict]:
    """从已分类的段落序列中提取每条"条目"的名称、点评价值等级与卖点短语。

    价值等级来自点评行开头的 🔴/🟡/⚪ 标记（`_VALUE_RANK`，未标注为 3=最低）；
    卖点短语取点评正文中去掉"高价值 —"等等级描述前缀后的第一个短句（截断至 14
    字）。供自动标题挑选（`_auto_pick_title`）与本期速览摘要（`_build_overview_html`）
    共用，只有一份提取逻辑。
    """
    entries: list[dict] = []
    current: dict | None = None
    for i, (block, kind) in enumerate(classified):
        if entry_flags[i]:
            if current:
                entries.append(current)
            current = {"name": block.text.strip(), "essence": "", "rank": 3}
            continue
        if current is None or kind not in {"p", "li"}:
            continue
        text = _strip_leading_markers(block.text.strip())
        if not text.startswith(("点评：", "点评:")):
            continue
        body = text.split("：", 1)[-1].split(":", 1)[-1].strip()
        for marker, rank in _VALUE_RANK.items():
            if body.startswith(marker):
                current["rank"] = min(current["rank"], rank)
                body = body[len(marker):].strip()
                break
        # 去掉"高价值 —"/"中等 —"等价值等级描述前缀，保留后面的实际卖点短语
        body = re.sub(r"^[^—\-，,。：:]{0,8}[—\-]\s*", "", body)
        # 括号也作为断句点，避免截断时切在括注内部产生未闭合的括号
        essence = re.split(r"[，,。：:（(]", body, maxsplit=1)[0].strip()
        if len(essence) > 14:
            essence = essence[:14] + "…"
        if essence:
            current["essence"] = essence
    if current:
        entries.append(current)
    return entries


def _auto_pick_title(docx_path: Path) -> str:
    """按各条目点评中的价值标记（🔴高价值 优先于 🟡中等 优先于 ⚪其他）自动挑选
    价值最高的两条条目，提炼卖点精简为整体标题（如"信用卡资讯精选｜A×B"）。

    仅依赖文档结构（条目起点 + 其点评行的价值 emoji），不针对任何具体银行/活动
    名称，故对任何后续周报都适用。同价值等级并列时按文档原始出现顺序取前两个。
    未标注价值等级的条目、或全文可比较条目不足两条时返回空串，由调用方回退到
    默认标题逻辑（用户仍可通过 --title 显式指定标题覆盖此结果）。
    """
    document = Document(docx_path)
    classified, entry_flags = _classify_docx_blocks(document)
    entries = _collect_entries(classified, entry_flags)

    ranked = sorted(
        (e for e in entries if e["rank"] < 3 and e["essence"]), key=lambda e: e["rank"]
    )
    if len(ranked) < 2:
        return ""

    picks = [f"{_short_name(e['name'])}{e['essence']}" for e in ranked[:2]]
    return "信用卡资讯精选｜" + "×".join(picks)


def _build_overview_html(entries: list[dict], total_entries: int) -> str:
    """生成「本期速览」摘要：除条目总数外，点出🔴高价值条目及其卖点、🟡中等条目
    数量，让读者一眼看到本期看点，引导继续往下读；无价值标注时退化为纯计数句。
    """
    high = [e for e in entries if e["rank"] == 0 and e["essence"]]
    mid = [e for e in entries if e["rank"] == 1]

    text = f'本期共 <strong>{total_entries}</strong> 条资讯'
    if high:
        shown = high[:3]
        names = "、".join(f"{_short_name(e['name'])}（{e['essence']}）" for e in shown)
        if len(high) > len(shown):
            names += " 等"
        text += f'，其中 <strong>{len(high)}</strong> 条 🔴高价值不容错过：{names}'
        if mid:
            text += f'；另有 <strong>{len(mid)}</strong> 条 🟡中等力度可按需参考'
    text += "。"

    return (
        '<div style="margin:0 0 24px;padding:12px 14px;background:#eff6ff;border:1px solid #bfdbfe;'
        'border-radius:6px;color:#1e3a8a;font-size:13px;line-height:1.8">'
        f'<strong style="color:#1e40af">本期速览</strong>　{text}</div>'
    )


def render_docx_flow(docx_path: Path, title: str = "") -> str:
    """按文档实际结构（标题层级、原生表格）渲染，不强行套用四段式解析。"""
    document = Document(docx_path)
    classified, entry_flags = _classify_docx_blocks(document)
    total_entries = sum(entry_flags)
    overview_html = _build_overview_html(_collect_entries(classified, entry_flags), total_entries)

    out: list[str] = []
    list_items: list[str] = []
    in_review = False
    entry_no = 0
    overview_inserted = False

    def flush_list() -> None:
        if list_items:
            out.append(
                f'<ul style="margin:8px 0 14px;padding-left:22px;color:#334155;font-size:14px">{"".join(list_items)}</ul>'
            )
            list_items.clear()

    for i, (block, kind) in enumerate(classified):
        if kind == "blank":
            flush_list()
            continue
        if kind is None:  # 表格
            flush_list()
            table_html = _render_table(block)
            if table_html:
                out.append(table_html)
            continue

        text = block.text.strip()

        # 本期速览：紧跟在标题（及可能的副标题）之后、第一条正文之前插入一次。
        if not overview_inserted and kind not in {"title", "subtitle"} and total_entries > 0:
            out.append(overview_html)
            overview_inserted = True

        if kind != "li":
            flush_list()
        if kind in {"h2", "h3", "h4", "title", "subtitle", "rule"}:
            in_review = False
        color = color_for(text)

        # 语义化处理：来源/核心内容/点评（可能带项目符号或 emoji 前缀，如'• 💬 点评：'）
        clean_text = _strip_leading_markers(text) if kind in {"p", "li"} else text
        if kind in {"p", "li"} and clean_text.startswith(("来源：", "来源:")):
            flush_list()
            body = clean_text.split("：", 1)[-1].split(":", 1)[-1].strip()
            out.append(f'<p style="margin:2px 0;color:#94a3b8;font-size:12px">来源：{inline(body)}</p>')
            continue
        if kind in {"p", "li"} and clean_text.startswith(("点评：", "点评:")):
            flush_list()
            body = clean_text.split("：", 1)[-1].split(":", 1)[-1].strip()
            out.append(
                f'<blockquote style="margin:10px 0 0;padding:10px 14px;border-left:4px solid {color};'
                f'background:#f8fafc;color:#334155;font-size:13px;line-height:1.85">'
                f'<strong style="color:{color}">点评：</strong>{inline(body)}</blockquote>'
            )
            continue
        if kind in {"p", "li"} and clean_text.startswith(("核心内容：", "核心内容:")):
            body = clean_text.split("：", 1)[-1].split(":", 1)[-1].strip()
            if not body:
                # 仅有标签、无正文：正文以紧随其后的要点列表形式呈现，跳过空标签行
                continue
            flush_list()
            out.append(
                f'<p style="margin:8px 0 4px;color:#334155;font-size:14px;line-height:1.85;text-align:justify">'
                f'<strong style="color:#0f172a">核心内容：</strong>{inline(body)}</p>'
            )
            continue

        if kind == "title":
            out.append(f'<h1 style="font-size:24px;line-height:1.4;color:#0f172a;margin:6px 0 8px;font-weight:700">{inline(title or text)}</h1>')
        elif kind == "subtitle":
            out.append(f'<p style="margin:0 0 16px;color:#475569;font-size:14px;line-height:1.75">{inline(text)}</p>')
        elif kind == "rule":
            out.append('<div style="height:1px;background:#e5e7eb;margin:18px 0"></div>')
        elif kind == "h2":
            out.append(f'<div style="margin:26px 0 12px;padding:9px 12px;border-left:4px solid {color};background:#f8fafc"><h2 style="font-size:18px;line-height:1.5;color:#0f172a;margin:0;font-weight:700">{inline(text)}</h2></div>')
        elif kind == "h3":
            if entry_flags[i]:
                entry_no += 1
                if entry_no > 1:
                    out.append('<div style="height:1px;background:#e5e7eb;margin:24px 0"></div>')
                out.append(f'<h3 style="font-size:17px;line-height:1.5;color:{color};margin:24px 0 6px;font-weight:700">{entry_no}. {inline(text)}</h3>')
            else:
                out.append(f'<h3 style="font-size:17px;line-height:1.5;color:{color};margin:22px 0 8px;font-weight:700">{inline(text)}</h3>')
        elif kind == "h4":
            in_review = text == "专业点评"
            out.append(f'<h4 style="font-size:15px;line-height:1.5;color:{color};margin:4px 0 8px;font-weight:700">{inline(text)}</h4>')
        elif kind == "li":
            list_items.append(f'<li style="margin:4px 0;line-height:1.75">{inline(clean_text)}</li>')
        elif kind == "badge":
            out.append(f'<p style="display:inline-block;margin:0 0 10px;padding:2px 8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:999px;color:#475569;font-size:12px;line-height:1.6">{inline(text)}</p>')
        elif kind == "quote":
            out.append(f'<p style="margin:20px 0 0;color:#94a3b8;font-size:12px;line-height:1.6">{inline(text)}</p>')
        elif in_review:
            out.append(f'<blockquote style="margin:10px 0;padding:10px 14px;border-left:4px solid {color};background:#f8fafc;color:#334155;font-size:13px;line-height:1.85;text-align:justify">{inline(text)}</blockquote>')
        else:
            out.append(f'<p style="margin:10px 0;color:#334155;font-size:14px;line-height:1.9;text-align:justify">{inline(text)}</p>')

    flush_list()
    body = "\n".join(out)
    return (
        f'<div style="max-width:680px;margin:0 auto;padding:20px 16px 32px;background:#fff;'
        f'font-family:PingFang SC,Microsoft YaHei,sans-serif;line-height:1.8;color:#334155">{body}</div>'
    )


_MARKER_CHARS = "•◦◆▪▫‣∙\\-\\*"
_EMOJI_RANGE = "\U0001F000-\U0001FFFF⌀-⏿☀-➿⬀-⯿"
_LEADING_MARKER_RE = re.compile(rf"^(?:[{_MARKER_CHARS}]|[{_EMOJI_RANGE}]️?)\s*")


def _strip_leading_markers(text: str) -> str:
    """移除行首的常见前缀符号（列表符号 • ◦ ▪ 等，以及 emoji 图标），支持多层叠加（如'• 💬 点评：'）。"""
    text = text.lstrip()
    while True:
        m = _LEADING_MARKER_RE.match(text)
        if not m:
            return text
        text = text[m.end():]


def _has_heading_hierarchy(paras: list[dict]) -> bool:
    """检测文档是否使用了 Word 标题样式（Heading2/Heading3）组织结构。

    真正的'四段式'文档是扁平的纯文本段落（标题行+来源+核心内容+点评，无标题层级）；
    若文档使用了标题样式分级（如'银行名'为 Heading2、'活动名'为 Heading3），
    说明它是层级大纲结构，不能套用四段式的『非来源/核心内容/点评行=新条目』切分逻辑，
    否则会把每一条子要点都错误拆分成独立条目。
    """
    return any(p.get("style", "").startswith(("Heading2", "Heading3")) for p in paras)


def _looks_like_legacy_four_part(paras: list[dict]) -> bool:
    """检测是否为'四段式'格式（标题-来源-核心内容-点评，扁平段落，无标题层级）"""
    if _has_heading_hierarchy(paras):
        return False

    source_count = 0
    core_count = 0
    review_count = 0

    for p in paras:
        text = _strip_leading_markers(p["text"].strip())
        if text.startswith(("来源：", "来源:")):
            source_count += 1
        elif text.startswith(("核心内容：", "核心内容:")):
            core_count += 1
        elif text.startswith(("点评：", "点评:")):
            review_count += 1

    return min(source_count, core_count, review_count) >= 2

def render_html(struct: dict, title: str = "") -> str:
    items = struct["items"]
    if not title:
        title = f"信用卡资讯整合点评｜共 {len(items)} 条"
    body_parts: list[str] = []
    body_parts.append(
        f'<h1 style="font-size:24px;line-height:1.4;color:#0f172a;margin:6px 0 16px;font-weight:700">{inline(title)}</h1>'
    )
    # 速览
    summary_intro = f"本期共 <strong>{len(items)}</strong> 条资讯，涵盖新卡发行、卡组织活动、年费优惠等。"
    body_parts.append(
        f'<div style="margin:0 0 24px;padding:12px 14px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;color:#1e3a8a;font-size:13px;line-height:1.8">'
        f'<strong style="color:#1e40af">本期速览</strong>　{summary_intro}</div>'
    )
    # 逐条
    for i, item in enumerate(items, 1):
        body_parts.append(render_card_item(item, i))
    # 本期总结
    body_parts.append(render_summary(struct["summary_lines"]))
    # 原文链接
    body_parts.append(render_raw_links(struct["raw_links"]))

    body = "\n".join(body_parts)
    fragment = (
        f'<div style="max-width:680px;margin:0 auto;padding:20px 16px 32px;background:#fff;'
        f'font-family:PingFang SC,Microsoft YaHei,sans-serif;line-height:1.8;color:#334155">{body}</div>'
    )
    return fragment


# ── 入口 ───────────────────────────────────────────────────────────────
def convert(docx_path: Path, output: Path | None = None, title: str = "") -> tuple[Path, str]:
    paras = parse_docx(docx_path)
    if _looks_like_legacy_four_part(paras):
        struct = parse_structure(paras)
        final_title = title or f"信用卡资讯整合点评｜共 {len(struct['items'])} 条"
        fragment = render_html(struct, final_title)
    else:
        first_text = next((p["text"].strip() for p in paras if p["text"].strip()), "")
        final_title = title or _auto_pick_title(docx_path) or first_text or "信用卡资讯整合点评"
        fragment = render_docx_flow(docx_path, final_title)
    out = output or docx_path.with_name(docx_path.stem + "_公众号粘贴版.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(fragment, encoding="utf-8")
    return out, final_title

def main() -> int:
    ap = argparse.ArgumentParser(description="docx 整合点评 → 公众号可粘贴 HTML")
    ap.add_argument("docx", help="输入 docx 文件")
    ap.add_argument("--output", default="", help="输出 HTML 路径")
    ap.add_argument(
        "--title", default="",
        help="发布标题；不填时按各条目点评的价值等级（🔴优先于🟡）自动挑选最高两条精简生成",
    )
    args = ap.parse_args()
    source = Path(args.docx)
    if not source.is_file():
        ap.error(f"文件不存在：{source}")
    out = Path(args.output) if args.output else None
    result, title = convert(source, out, args.title)
    print(f"[OK] 公众号粘贴 HTML -> {result}")
    print(f"[OK] 标题：{title}")
    print("操作：浏览器打开 HTML 后全选复制，粘贴到公众号编辑器。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

