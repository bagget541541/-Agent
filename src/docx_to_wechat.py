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


def _read_style_map(zf: zipfile.ZipFile) -> dict[str, str]:
    """styleId -> 显示名（如 '21' -> 'Heading 2'）。

    word/styles.xml 里每个 <w:style w:styleId="X"> 都带一个 <w:name w:val="..."/>。
    我们只关心标题/列表/引用这类语义样式，返回 id->name 映射供 parse_docx 归一化。
    """
    try:
        xml = zf.read("word/styles.xml").decode("utf-8", errors="replace")
    except KeyError:
        return {}
    out: dict[str, str] = {}
    for m in re.finditer(r'<w:style\b[^>]*>', xml):
        tag = m.group(0)
        sid_m = re.search(r'w:styleId="([^"]+)"', tag)
        if not sid_m:
            continue
        # 该 style 元素的完整块，取其 <w:name w:val="..."/>
        block = xml[m.start():xml.find("</w:style>", m.start())]
        name_m = re.search(r'<w:name\s+w:val="([^"]+)"', block)
        if sid_m and name_m:
            out[sid_m.group(1)] = name_m.group(1)
    return out


def parse_docx(path: Path) -> list[dict]:
    """返回段落列表，每段含 text / links / style / has_img。

    其中 style 与 has_img 为可选字段（早期调用方仅用 text 与 links）。
    style 字段为样式显示名（如 'Heading 2'），已通过 styles.xml 把内部
    styleId（如 '21'）归一化，便于上层用 startswith("Heading") 等判断。
    """
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        rel_map = _read_rels(zf)
        style_map = _read_style_map(zf)

    # 切成 <w:p ...> ... </w:p> 段
    paras_xml = re.findall(r"<w:p\b[^>]*>.*?</w:p>", xml, re.S)
    paragraphs: list[dict] = []
    for pxml in paras_xml:
        # 段落样式（Title / Heading1 / Heading2 / ListBullet / normal）
        style_m = re.search(r'<w:pStyle w:val="([^"]+)"', pxml)
        if style_m:
            # 优先用 styles.xml 映射成显示名；映射缺失时回退到原始 id
            style = style_map.get(style_m.group(1), style_m.group(1))
        else:
            style = "normal"

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


def _smart_truncate(text: str, limit: int = 22) -> str:
    """把卖点短语软截断到 limit 字内，尽量在标点/词边界处收尾。

    规则：
    1. 已短于 limit：原样返回。
    2. 在 limit 字内找最后一个标点（含顿号"，、；;"），从那里截断。截断点
       跳过该标点本身——这样"等值5万消费换上海-巴黎往返、积分加赠"会保留
       前一个完整短句"等值5万消费换上海-巴黎往返"，而不是带着顿号尾巴。
    3. 找不到合适标点时硬切到 limit 字并加"…"。

    不再加裸"…"：调用方需要省略号时自行追加；标题里直接用截断后的短句即可。
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    # 优先在标点处断句
    head = text[:limit]
    cut = max(head.rfind("，"), head.rfind(","), head.rfind("。"),
              head.rfind("；"), head.rfind(";"), head.rfind("、"))
    if cut >= limit // 2:
        return head[:cut]
    # 回退：在 limit 附近找最近标点（稍超 limit 也可接受，换得完整短句）
    window = text[:limit + 4]
    cut2 = max(window.rfind("，"), window.rfind("、"), window.rfind("；"),
               window.rfind(";"), window.rfind("。"))
    if cut2 >= limit // 2:
        return window[:cut2]
    # 实在没标点，硬截断
    return head


_BENEFIT_WORDS = (
    "返现", "立减", "免手", "免年费", "免货币", "换", "送", "赠", "加赠",
    "积分", "里程", "门票", "满减", "折扣", "立减", "随机减", "达标",
)
# 抽象评价/元描述词：这类短句不是活动卖点，essence 提取时应跳过
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
        # 负面/抽象评价强降权
        if is_negative or is_abstract:
            return (-1, -1, -1)
        return (has_benefit + has_num, has_benefit, has_num)

    best = max(segs, key=score)
    # 如果最高分都是负的（全是负面/抽象短句），返回空串让调用方回退
    if score(best)[0] < 0:
        return ""
    return best


def _collect_entries(
    classified: list[tuple[Paragraph | Table, str | None]], entry_flags: list[bool]
) -> list[dict]:
    """从已分类的段落序列中提取每条"条目"的名称、活动名、价值等级与卖点短语。

    每条 entry 的字段：
    - `name`: 机构名（entry h3 标题文本，如"浦发银行"）。
    - `activity`: 活动名（紧随 entry 之后的第一个 h4 标题文本，如"等值5万
      消费换上海-巴黎往返"）。这是标题里最具吸引力的"活动卖点"。
    - `rank`: 点评行的价值等级（🔴0 > 🟡1 > ⚪2，未标注为 3）。
    - `essence`: 从点评正文用 `_pick_essence_segment` 提取的卖点短句，作为
      activity 的补充；activity 优先用于标题生成。

    供自动标题挑选（`_auto_pick_title`）与本期速览摘要（`_build_overview_html`）
    共用，只有一份提取逻辑。
    """
    entries: list[dict] = []
    current: dict | None = None
    for i, (block, kind) in enumerate(classified):
        if entry_flags[i]:
            if current:
                entries.append(current)
            current = {
                "name": block.text.strip(),
                "activity": "",
                "essence": "",
                "rank": 3,
            }
            continue
        if current is None:
            continue
        # 紧随 entry h3 之后的第一个 h4 = 活动名
        if kind == "h4" and not current["activity"]:
            current["activity"] = block.text.strip()
            continue
        if kind not in {"p", "li"}:
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
        essence = _pick_essence_segment(body)
        if essence:
            current["essence"] = _smart_truncate(essence)
    if current:
        entries.append(current)
    return entries


def _auto_pick_title(docx_path: Path) -> str:
    """按各条目点评中的价值标记（🔴高价值 优先于 🟡中等 优先于 ⚪其他）自动挑选
    价值最高的条目，提炼卖点生成有吸引力的整体标题。

    标题结构：`信用卡资讯精选｜浦发5万消费换国际机票｜上海笔笔2%返现`
    - 机构名用 `_short_name` 去掉"银行"后缀，紧凑显示。
    - 卖点优先取活动名（h4 标题，如"等值5万消费换上海-巴黎往返"），
      activity 缺失时回退到 essence（点评正文提取的短句）。
    - 卖点用 `_smart_truncate` 软截断到 22 字内，在标点处收尾，不留裸省略号。
    - 多条并列时用"｜"分隔，避免"×"这种像乱码的连接符。
    - 价值等级排序：🔴(0) > 🟡(1) > ⚪(2) > 未标注(3)；同等级按文档原始顺序。
    - 仅依赖文档结构（条目起点 + 点评行价值 emoji），不针对具体银行/活动名称，
      故对任何后续周报都适用。

    未标注价值等级的条目、或可比较条目不足两条时返回空串，由调用方回退到默认
    标题逻辑（用户仍可通过 --title 显式指定标题覆盖此结果）。
    """
    document = Document(docx_path)
    classified, entry_flags = _classify_docx_blocks(document)
    entries = _collect_entries(classified, entry_flags)

    # 卖点字段：activity 优先，缺失回退 essence
    def headline(e: dict) -> str:
        return e["activity"] or e["essence"]

    # 只保留有卖点的条目，按价值等级排序（rank 小的优先）
    ranked = sorted(
        (e for e in entries if headline(e)),
        key=lambda e: e["rank"],
    )
    # 过滤掉未标注价值等级的条目（rank==3），除非它们是仅有的条目
    valued = [e for e in ranked if e["rank"] < 3]
    picks_pool = valued if len(valued) >= 2 else ranked

    if len(picks_pool) < 2:
        return ""

    # 取前两条，生成"机构+卖点"的紧凑片段
    picks = []
    for e in picks_pool[:2]:
        org = _short_name(e["name"])
        # activity（h4 标题）可能很长，截断到 22 字内
        sell = _smart_truncate(headline(e), 22).rstrip("…")
        picks.append(f"{org}{sell}")

    return "信用卡资讯精选｜" + "｜".join(picks)


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
    """检测文档是否使用了 Word 标题样式（Heading 1/2/3）组织结构。

    真正的'四段式'文档是扁平的纯文本段落（标题行+来源+核心内容+点评，无标题层级）；
    若文档使用了标题样式分级（如'银行名'为 Heading 2、'活动名'为 Heading 3），
    说明它是层级大纲结构，不能套用四段式的『非来源/核心内容/点评行=新条目』切分逻辑，
    否则会把每一条子要点都错误拆分成独立条目。

    parse_docx 已通过 styles.xml 把内部 styleId（如 '21'）归一化成显示名
    （如 'Heading 2'，注意有空格）。但不同 docx 生成器大小写不一致（Word 用
    'Heading 1'，某些 Markdown→docx 工具用 'heading 1'），这里统一小写匹配，
    覆盖 'Heading 1'/'heading 1'/'Heading1' 等变体。
    """
    heading_prefixes = (
        "heading 1", "heading 2", "heading 3", "heading 4",
        "heading1", "heading2", "heading3", "heading4",
    )
    return any(
        p.get("style", "").lower().startswith(heading_prefixes)
        for p in paras
    )


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

