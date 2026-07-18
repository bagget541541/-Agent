#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 编辑稿 → 公众号编辑器可粘贴 HTML 片段。"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import re
from pathlib import Path

COLORS = {"权益": "#2563eb", "积分": "#7c3aed", "AI": "#0891b2", "活动": "#d97706", "年轻": "#db2777", "行动": "#0f766e"}
DROP_HEADINGS = {"行动建议", "来源清单", "编辑声明", "本稿声明"}


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def color_for(text: str) -> str:
    for key, color in COLORS.items():
        if key in text:
            return color
    return "#475569"


def image_html(alt: str, src: str, image_root: Path | None, embed: bool) -> str:
    path = Path(src)
    if not path.is_absolute() and image_root:
        path = image_root / path
    if embed and path.is_file():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        src = f"data:{mime};base64,{data}"
        return f'<p style="margin:16px 0;text-align:center"><img src="{esc(src)}" alt="{esc(alt)}" style="max-width:100%;height:auto;border-radius:6px"></p>'
    return f'<div style="margin:12px 0;padding:10px 12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:6px;color:#9a3412;font-size:12px;line-height:1.6">图片：{esc(alt)}<br><span style="color:#c2410c">发布前请在公众号编辑器上传原图</span></div>'


def inline(text: str, image_root: Path | None, embed: bool) -> str:
    tokens: list[str] = []

    def hold(value: str) -> str:
        tokens.append(value)
        return f"\x00{len(tokens) - 1}\x00"

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", lambda m: hold(image_html(m.group(1), m.group(2), image_root, embed)), text)
    text = esc(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" style="color:#2563eb;text-decoration:none">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\x60([^\x60]+)\x60", r'<span style="font-family:monospace;background:#f1f5f9;padding:1px 4px;border-radius:3px">\1</span>', text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    for i, value in enumerate(tokens):
        text = text.replace(f"\x00{i}\x00", value)
    return text


def _is_table(lines: list[str], i: int) -> bool:
    return i + 1 < len(lines) and "|" in lines[i] and bool(re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]))


def _cells(line: str) -> list[str]:
    return [x.strip() for x in line.strip().strip("|").split("|")]


def _strip_heading_prefix(title: str) -> str:
    return re.sub(r"^[一二三四五六七八九十0-9]+[、.．]\s*", "", title).strip()


def _extract_publish_items(md: str) -> list[dict]:
    lines = md.replace("\r\n", "\n").splitlines()
    item_section = next(
        (i for i, line in enumerate(lines)
         if line.strip().startswith("## ") and "逐条" in line),
        -1,
    )
    search_lines = lines[item_section + 1:] if item_section >= 0 else lines
    starts = [item_section + 1 + i for i, line in enumerate(search_lines) if re.match(r"^###\s+\d+[.、]\s+", line.strip())]
    items = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        next_h2 = next(
            (i for i in range(start + 1, end)
             if re.match(r"^##\s+", lines[i].strip())),
            end,
        )
        end = min(end, next_h2)
        title = _strip_heading_prefix(re.sub(r"^###\s+", "", lines[start].strip()))
        source_url = ""
        body_lines = []
        for line in lines[start + 1:end]:
            stripped = line.strip()
            source_match = re.match(r"^\*{0,2}来源\*{0,2}\s*[：:]\s*(https?://\S+)", stripped)
            if source_match:
                source_url = source_match.group(1).rstrip(")")
                continue
            if re.match(r"^\*{0,2}来源\*{0,2}\s*[：:]", stripped):
                continue
            if stripped.startswith("**来源") or stripped.startswith("来源："):
                continue
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        category = ""
        m = re.search(r"\*\*属性\*\*\s*[：:]\s*([^｜|\n]+)", body)
        if m:
            category = m.group(1).strip()
        else:
            m = re.search(r"\*\*类别\*\*\s*[：:]\s*([^\n]+)", body)
            category = m.group(1).strip() if m else "其他"
        items.append({"title": title, "category": category, "body": body, "source_url": source_url})
    return items


def build_publish_markdown(md: str, title: str = "") -> tuple[str, str]:
    items = _extract_publish_items(md)
    counts: dict[str, int] = {}
    for item in items:
        category = item["category"]
        counts[category] = counts.get(category, 0) + 1
    has_ai = any(re.search(r"AI|Kimi|Qoder|算力|智能体", i["title"] + i["body"], re.I) for i in items)
    has_points = any(re.search(r"积分|福气值|年费|权益", i["title"] + i["body"]) for i in items)
    has_young = any(re.search(r"MBTI|DIY|贴纸|茶咖", i["title"] + i["body"], re.I) for i in items)
    if not title:
        themes = []
        if has_points:
            themes.append("积分权益调整")
        if has_ai:
            themes.append("AI联名观察")
        if has_young:
            themes.append("年轻化产品")
        title = "信用卡资讯精选｜" + "与".join(themes[:2] or ["本期重点"])
    summary = "本期共 **{} 条**资讯，涵盖：{}。".format(
        len(items), "、".join(f"{k}{v}条" for k, v in counts.items())
    )
    lines = [f"# {title}", "", "## 本期速览", "", summary, ""]
    if has_points:
        lines.append("- **积分与权益**：重点关注积分口径、年费减免条件、适用卡种与规则生效时间。")
    if has_ai:
        lines.append("- **AI权益**：银行正在把会员、算力或智能体嵌入信用卡，价值取决于真实使用频率和达标成本。")
    if has_young:
        lines.append("- **年轻化产品**：主题卡和 DIY 卡面强化社交传播，但长期价值仍要回到核心权益。")
    if not lines[-1].startswith("-"):
        lines.append("- **总体判断**：优先核对门槛、期限和兑现路径，再决定是否申请或参与。")
    lines += ["", "## 逐条资讯", ""]
    for index, item in enumerate(items, 1):
        lines += [f"### {index}. {item['title']}", "", item["body"], ""]
    links = [item for item in items if item.get("source_url")]
    if links:
        lines += ["## 原文链接", ""]
        for index, item in enumerate(links, 1):
            lines.append(f"{index}. [{item['title']}]({item['source_url']})")
        lines.append("")
    return "\n".join(lines), title


def render_markdown(md: str, image_root: Path | None = None, embed: bool = False) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    i = 0

    def flush() -> None:
        if paragraph:
            text = " ".join(x.strip() for x in paragraph).strip()
            if text:
                out.append(f'<p style="margin:10px 0;color:#334155;font-size:14px;line-height:1.9;text-align:justify">{inline(text, image_root, embed)}</p>')
            paragraph.clear()

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            flush(); i += 1; continue
        if stripped == "---":
            flush(); out.append('<div style="height:1px;background:#e5e7eb;margin:24px 0"></div>'); i += 1; continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            flush()
            level, title = len(heading.group(1)), heading.group(2).strip()
            if _strip_heading_prefix(title) in DROP_HEADINGS:
                i += 1
                while i < len(lines) and not re.match(r"^#{1,4}\s+", lines[i].strip()):
                    i += 1
                continue
            if level == 1:
                out.append(f'<h1 style="font-size:24px;line-height:1.4;color:#0f172a;margin:6px 0 12px;font-weight:700">{inline(title, image_root, embed)}</h1>')
            elif level == 2:
                color = color_for(title)
                out.append(f'<div style="margin:26px 0 12px;padding:9px 12px;border-left:4px solid {color};background:#f8fafc"><h2 style="font-size:18px;line-height:1.5;color:#0f172a;margin:0;font-weight:700">{inline(title, image_root, embed)}</h2></div>')
            else:
                color = color_for(title)
                out.append(f'<h3 style="font-size:16px;line-height:1.5;color:{color};margin:20px 0 8px;font-weight:700">{inline(title, image_root, embed)}</h3>')
            i += 1; continue
        if _is_table(lines, i):
            flush(); headers = _cells(lines[i]); i += 2; rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i])); i += 1
            head = "".join(f'<th style="padding:8px;text-align:left;background:#f1f5f9;border-bottom:1px solid #cbd5e1;font-size:12px">{inline(x, image_root, embed)}</th>' for x in headers)
            body = "".join('<tr>' + "".join(f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;font-size:12px;line-height:1.6;vertical-align:top">{inline(x, image_root, embed)}</td>' for x in row) + '</tr>' for row in rows)
            out.append(f'<div style="overflow-x:auto;margin:14px 0"><table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'); continue
        if stripped.startswith(">"):
            flush(); quote = re.sub(r"^>\s?", "", stripped)
            out.append(f'<blockquote style="margin:14px 0;padding:10px 14px;border-left:4px solid #f59e0b;background:#fffbeb;color:#92400e;font-size:13px;line-height:1.8">{inline(quote, image_root, embed)}</blockquote>'); i += 1; continue
        if re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+[.)]\s+", stripped):
            flush(); ordered = bool(re.match(r"^\d+[.)]\s+", stripped)); tag = "ol" if ordered else "ul"; items = []
            while i < len(lines):
                current = lines[i].strip(); m = re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)(.+)$", current)
                if not m: break
                items.append(f'<li style="margin:4px 0;line-height:1.8">{inline(m.group(1), image_root, embed)}</li>'); i += 1
            out.append(f'<{tag} style="margin:10px 0;padding-left:24px;color:#334155;font-size:14px">{"".join(items)}</{tag}>'); continue
        if re.match(r"^!\[[^\]]*\]\([^)]+\)$", stripped):
            flush(); m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
            out.append(image_html(m.group(1), m.group(2), image_root, embed)); i += 1; continue
        paragraph.append(stripped); i += 1
    flush()
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Markdown → 公众号可粘贴 HTML")
    ap.add_argument("md", help="输入 Markdown 文件")
    ap.add_argument("--output", default="", help="输出 HTML 路径")
    ap.add_argument("--meta", default="", help="输出元数据 JSON 路径")
    ap.add_argument("--image-root", default="", help="图片相对路径根目录")
    ap.add_argument("--embed-images", action="store_true", help="将找到的本地图片转为 data URI")
    ap.add_argument("--title", default="", help="发布标题；不填则根据内容自动生成")
    args = ap.parse_args()
    source = Path(args.md)
    if not source.is_file():
        ap.error(f"文件不存在：{source}")
    raw = source.read_text(encoding="utf-8-sig")
    out = Path(args.output) if args.output else source.with_name(source.stem + "_公众号粘贴版.html")
    image_root = Path(args.image_root).resolve() if args.image_root else None
    publish_md, title = build_publish_markdown(raw, args.title)
    body = render_markdown(publish_md, image_root, args.embed_images)
    fragment = f'<div style="max-width:680px;margin:0 auto;padding:20px 16px 32px;background:#fff;font-family:PingFang SC,Microsoft YaHei,sans-serif;line-height:1.8;color:#334155">{body}</div>'
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(fragment, encoding="utf-8")
    meta_path = Path(args.meta) if args.meta else out.with_suffix(".json")
    meta_path.write_text(json.dumps({"source": str(source.resolve()), "title": title, "output": str(out.resolve()), "embed_images": args.embed_images, "publish_mode": "compact_editorial"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 公众号粘贴 HTML -> {out}"); print(f"[OK] 元数据 -> {meta_path}"); print("操作：浏览器打开 HTML 后全选复制，粘贴到公众号编辑器。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
