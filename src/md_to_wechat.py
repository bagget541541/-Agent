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

def _truncate_text(text: str, limit: int = 120, sentences: int = 0) -> str:
    """截断文本。

    Args:
        text: 输入文本
        limit: 字符限制（默认 120）
        sentences: 按句子数截断（0 表示按字符限制）
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return text

    # 按句子数截断
    if sentences > 0:
        sentence_split = re.split(r'([。！？…，、\n])', text)
        if len(sentence_split) > 0:
            count = 0
            result = []
            for i, part in enumerate(sentence_split):
                result.append(part)
                if part.strip() and re.search(r'[。！？…]', part):
                    count += 1
                    if count >= sentences:
                        return "".join(result)

    # 按字符限制截断
    return text if len(text) <= limit else text[:limit].rstrip() + "..."

def _similarity_score(s1: str, s2: str) -> float:
    """计算两个字符串的相似度（0-1，1为完全相同）。"""
    if s1 == s2:
        return 1.0
    s1_clean = re.sub(r"[\d年月日天~-]", "", s1.lower())
    s2_clean = re.sub(r"[\d年月日天~-]", "", s2.lower())
    if s1_clean == s2_clean:
        return 0.95
    # 基于共同字符的简单相似度
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
        # 尝试提取其他形式的奖励
        reward_match = re.search(r"((?:满\d+)?(?:返|减|优惠|免费|赠送|券)[^。]*?)(?:。|$)", body)
        if reward_match:
            reward_text = reward_match.group(1)[:20]
            essence.append(f"奖励：{reward_text}")

    if essence:
        return " | ".join(essence)
    return ""


def _is_garbage_line(line: str) -> bool:
    """检测垃圾行（导航菜单、附件列表等）。"""
    stripped = line.strip()
    garbage_patterns = [
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
        r"^免费申请\s*$",
        r"^下一篇",
        r"^原文链接",
        r"^在线客服",
        r"^联系我们",
        r"^法律声明",
        r"^隐私政策",
        r"^服务条款",
        r"^中[信农]银行[·•]",
        r"^农业银行[·•]",
        r"^建设银行[·•]",
        r"^[银农信中建光华招平浦兴汇工民].*?主题.*?信用卡$",
        r"^[^：：]*银行.*?信用卡\s*$",
        r"^[^：：]*[·•].*?信用卡\s*(申请|激活|详情)",
        r"^(北京|上海|浙江|江苏|广东|福建)市\s*$",
        r"^(天津|重庆|西安|成都|杭州|南京)\s*$",
        r"^上海市",
        r"^浙江省",
        r"^江苏省",
        r"^北京市",
        r"^（回复.{1,10}可查看详情）$",
        r"^点击阅读原文",
        r"^更多内容敬请关注",
        r"^编辑[：:]",
        r"^来源[：:]",
    ]
    for pattern in garbage_patterns:
        if re.match(pattern, stripped, re.I):
            return True
    return False


def _clean_highlight(text: str) -> str:
    """清理和优化亮点字段（去除垃圾、补全句子、限制长度）。"""
    # 1. 移除附件和门户网址引用
    text = re.sub(r"附件[\s：:]*", "", text)
    text = re.sub(r"查看附近适用门店.*?[)）]", "", text)
    text = re.sub(r"点击.*?APP.*?[)）]", "", text)

    # 2. 规范化空格
    text = re.sub(r"\s+", " ", text).strip()

    # 3. 移除末尾未闭合的引号，并补全不完整的句子
    text = re.sub(r"['\"”’]\s*$", "", text)
    if not text.endswith(("。", "？", "！", ".", ")")):
        sentences = re.split(r"[。？！]", text)
        if len(sentences) > 1:
            text = "。".join(sentences[:-1]) + "。" if sentences[:-1] else text

    # 4. 限制长度到 100 字
    if len(text) > 100:
        text = text[:100].rstrip() + "…"

    return text


def _clean_publish_body(body: str) -> str:
    lines = body.splitlines()
    kept = []
    dropping = False
    drop_structured_fields = {"活动内容", "消息内容"}
    skip_block = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 检测附件块开始：删除附件行及其后续缩进行
        if _is_garbage_line(line):
            if re.match(r"^附件[：:]", stripped):
                skip_block = True
            continue

        # 附件块内的行（缩进或列表项）也要跳过
        if skip_block:
            if stripped and not re.match(r"^[\s\-\*]", line):
                # 非缩进、非列表的行则结束附件块
                skip_block = False
            else:
                continue

        if re.match(r"^\*\*原文摘要[：:]\*\*\s*$", stripped) and "结构化信息" in body:
            dropping = True
            continue

        highlight_match = re.match(r"^\*\*亮点[：:]\*\*\s*(.*)$", stripped)
        if highlight_match:
            highlight_text = _clean_highlight(highlight_match.group(1))
            if highlight_text:
                kept.append(f"**亮点：** {highlight_text}")
            continue

        bullet_match = re.match(r"^-\s+\*\*([^*]+)\*\*\s*[：:]\s*(.*)$", stripped)
        if dropping:
            if not bullet_match:
                continue
            dropping = False
        if bullet_match:
            field = bullet_match.group(1).strip()
            value = bullet_match.group(2).strip()
            # 隐藏内部标记字段（以 _ 开头，如 _low_value）
            if field.startswith("_"):
                continue
            if field in drop_structured_fields:
                dropping = True
                continue
            # 删除空标题内容
            if not value:
                continue

        kept.append(line)

    cleaned = []
    i = 0
    while i < len(kept):
        stripped = kept[i].strip()
        if re.match(r"^\*\*结构化信息[：:]\*\*\s*$", stripped):
            j = i + 1
            while j < len(kept) and not kept[j].strip():
                j += 1
            if j >= len(kept) or not re.match(r"^-\s+\*\*", kept[j].strip()):
                i = j
                continue
        cleaned.append(kept[i])
        i += 1

    return "\n".join(cleaned).rstrip()


def _extract_publish_items(md: str) -> list[dict]:
    lines = md.replace("\r\n", "\n").splitlines()
    item_section = next(
        (i for i, line in enumerate(lines)
         if line.strip().startswith("## ") and "逐条" in line),
        -1,
    )
    search_lines = lines[item_section + 1:] if item_section >= 0 else lines
    starts = [item_section + 1 + i for i, line in enumerate(search_lines) if re.match(r"^###\s+\d+[.、]\s+", line.strip())]
    if not starts:
        starts = [i for i, line in enumerate(lines) if re.match(r"^###\s+\S", line.strip())]
    h2_categories = [
        (i, _strip_heading_prefix(re.sub(r"^##\s+", "", line.strip())))
        for i, line in enumerate(lines)
        if re.match(r"^##\s+", line.strip())
    ]
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
            link_match = re.match(r"^\[原文链接\]\((https?://[^)\s]+)\)", stripped)
            if link_match:
                source_url = link_match.group(1)
                continue
            source_match = re.match(r"^\*{0,2}来源\*{0,2}\s*[：:]\s*(https?://\S+)", stripped)
            if source_match:
                source_url = source_match.group(1).rstrip(")")
                continue
            if re.match(r"^\*{0,2}来源\*{0,2}\s*[：:]", stripped):
                continue
            if stripped.startswith("**来源") or stripped.startswith("来源："):
                continue
            body_lines.append(line)
        body = _clean_publish_body("\n".join(body_lines).strip())
        category = ""
        m = re.search(r"\*\*属性\*\*\s*[：:]\s*([^｜|\n]+)", body)
        if m:
            category = m.group(1).strip()
        else:
            m = re.search(r"\*\*类别\*\*\s*[：:]\s*([^\n]+)", body)
            category = m.group(1).strip() if m else ""
        if not category:
            previous_h2 = [name for line_no, name in h2_categories if line_no < start]
            category = previous_h2[-1] if previous_h2 else "其他"
        items.append({"title": title, "category": category, "body": body, "source_url": source_url})
    return items


def build_publish_markdown(md: str, title: str = "") -> tuple[str, str]:
    items = _extract_publish_items(md)

    # 去重处理：识别并合并相同类型的重复活动
    deduplicated = []
    seen_titles: dict[str, int] = {}
    for i, item in enumerate(items):
        is_duplicate = False
        for j in range(i):
            if _similarity_score(item["title"], items[j]["title"]) > 0.8:
                # 标记为重复但不跳过，而是添加重复标记
                is_duplicate = True
                break
        if not is_duplicate:
            deduplicated.append(item)
        seen_titles[item["title"]] = seen_titles.get(item["title"], 0) + 1

    # 内容提炼：对活动类条目提取核心要素
    for item in deduplicated:
        if "活动" in item["category"] or "优惠" in item["category"]:
            essence = _extract_activity_essence(item["title"], item["body"])
            if essence:
                # 在亮点前添加提炼的内容
                if "**亮点：**" in item["body"]:
                    item["body"] = item["body"].replace("**亮点：**", f"**活动要点：** {essence}\n\n**亮点：**")
                else:
                    item["body"] = f"**活动要点：** {essence}\n\n{item['body']}"

    items = deduplicated
    counts: dict[str, int] = {}
    for item in items:
        category = item["category"]
        counts[category] = counts.get(category, 0) + 1
    has_ai = any(re.search(r"AI|Kimi|Qoder|算力|智能体", i["title"] + i["body"], re.I) for i in items)
    has_points = any(re.search(r"积分|福气值|年费|权益", i["title"] + i["body"]) for i in items)
    has_young = any(re.search(r"MBTI|DIY|贴纸|茶咖", i["title"] + i["body"], re.I) for i in items)
    if not title:
        # 从实际条目中提取标题：新卡 + 权益变更各取第一条，用-连接
        new_card_title = None
        change_title = None
        for item in items:
            category = item.get("category", "").strip()
            if "新卡" in category and not new_card_title:
                new_card_title = item["title"]
            elif ("权益" in category or "变更" in category) and not change_title:
                change_title = item["title"]

        if new_card_title and change_title:
            title = f"{new_card_title} - {change_title}"
        else:
            # fallback: 根据主题生成
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
            lines.append(f"{index}、{item['title']}")
            lines.append(item["source_url"])
            lines.append("")
        lines.append("")
    return "\n".join(lines), title


def render_markdown(md: str, image_root: Path | None = None, embed: bool = False) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    i = 0

    def flush() -> None:
        if paragraph:
            raw_lines = [x.strip() for x in paragraph if x.strip()]
            has_url = any(re.search(r"https?://", x) for x in raw_lines)
            text = " ".join(raw_lines).strip()
            if text:
                if has_url:
                    rendered = "<br>".join(inline(x, image_root, embed) for x in raw_lines)
                    out.append(f'<p style="margin:10px 0;color:#334155;font-size:14px;line-height:1.9;text-align:left;word-break:break-all">{rendered}</p>')
                else:
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
