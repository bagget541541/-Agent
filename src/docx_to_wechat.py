#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信用卡资讯「整合点评」docx → 公众号编辑器可粘贴 HTML 片段。

输入 docx 结构（每条资讯四段式）：
    标题行        例：农行 - 农行Visa全球支付尊享白金卡
    来源：xxx
    核心内容：xxx
    点评：xxx
文末含「本期总结」区块和「原始链接」列表。

输出：单文件 HTML 片段，浏览器打开后全选复制，粘贴进公众号编辑器即可。
"""
from __future__ import annotations

import argparse
import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

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
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


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
    """返回段落列表，每段含 text 和 hyperlinks (list of {url,text})."""
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        rel_map = _read_rels(zf)

    # 切成 <w:p ...> ... </w:p> 段
    paras_xml = re.findall(r"<w:p\b[^>]*>.*?</w:p>", xml, re.S)
    paragraphs: list[dict] = []
    for pxml in paras_xml:
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
        full_text = _strip_tags(t_text).strip()
        if full_text or links:
            paragraphs.append({"text": full_text, "links": links})
    return paragraphs


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


def is_title_line(text: str) -> bool:
    """标题行：『银行 - 卡名』或『银行 - 活动名』。"""
    return bool(re.match(r"^.+?\s*-\s*.+$", text)) and not text.startswith(("来源", "核心内容", "点评", "本期", "新卡", "卡组织", "年费", "原始"))


def parse_structure(paras: list[dict]) -> dict:
    """把段落切成结构化数据。"""
    article_title = ""
    for p in paras:
        t = p["text"].strip()
        if not t:
            continue
        # 文章总标题：第一段非空且不含"来源/核心内容/点评/本期/原始"前缀，
        # 且不是『银行 - 卡名』格式
        if not article_title and not t.startswith(("来源", "核心内容", "点评", "本期", "新卡", "卡组织", "年费", "原始")):
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

        # 四段式
        if t.startswith("来源：") or t.startswith("来源:"):
            if cur is not None:
                cur["source"] = t.split("：", 1)[-1].split(":", 1)[-1].strip()
            continue
        if t.startswith("核心内容：") or t.startswith("核心内容:"):
            body = t.split("：", 1)[-1].split(":", 1)[-1].strip()
            if cur is not None:
                cur["core"] = body
            continue
        if t.startswith("点评：") or t.startswith("点评:"):
            review = t.split("：", 1)[-1].split(":", 1)[-1].strip()
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
    struct = parse_structure(paras)
    if not title:
        title = f"信用卡资讯整合点评｜共 {len(struct['items'])} 条"
    fragment = render_html(struct, title)
    out = output or docx_path.with_name(docx_path.stem + "_公众号粘贴版.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(fragment, encoding="utf-8")
    return out, title


def main() -> int:
    ap = argparse.ArgumentParser(description="docx 整合点评 → 公众号可粘贴 HTML")
    ap.add_argument("docx", help="输入 docx 文件")
    ap.add_argument("--output", default="", help="输出 HTML 路径")
    ap.add_argument("--title", default="", help="发布标题；不填自动生成")
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
