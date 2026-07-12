#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mode D: Markdown 合并、点评与整合。

设计原则：先保留证据，再做编辑层整合。默认只使用本地规则，--llm
才调用项目统一 LLM 客户端；因此离线运行也能得到可审核的结果。
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _clean_title(value: str) -> str:
    value = re.sub(r"^\s*[一二三四五六七八九十0-9]+[、.．]\s*", "", value)
    value = re.sub(r"[\s·•：:，,。！!？?（）()【】\[\]‘’“”\"'_-]+", "", value)
    return value.lower()


def _meta_value(text: str, label: str) -> str:
    pattern = rf"\*{{0,2}}{re.escape(label)}\*{{0,2}}\s*[:：]\s*\*{{0,2}}([^\n]+)"
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""


def parse_markdown(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    h1 = next((x[2:].strip() for x in lines if x.startswith("# ")), path.stem)
    starts = [i for i, x in enumerate(lines) if x.startswith("## ")]
    items = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        title = re.sub(r"^##\s+", "", lines[start]).strip()
        body = "\n".join(lines[start + 1:end]).strip()
        if _clean_title(title) in {"总结", "目录", "参考资料"}:
            continue
        images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body)
        items.append({
            "title": title,
            "display_title": re.sub(r"^[一二三四五六七八九十0-9]+[、.．]\s*", "", title),
            "key": _clean_title(title),
            "category": _meta_value(body, "类别"),
            "priority": _meta_value(body, "优先级"),
            "source_url": _meta_value(body, "来源"),
            "comment": _extract_comment(body),
            "body": body,
            "source_file": str(path),
            "source_date": _extract_date(h1 + "\n" + text, path),
            "images": images,
        })
    return {"file": str(path), "title": h1, "items": items}


def _extract_comment(body: str) -> str:
    m = re.search(r"(?ms)^###?\s*点评\s*\n(.*?)(?=^#{1,4}\s|\Z)", body)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?ms)^\*\*点评：\*\*\s*\n?(.*?)(?=^#{1,4}\s|\Z)", body)
    return m.group(1).strip() if m else ""


def _extract_date(text: str, path: Path) -> str:
    m = re.search(r"20\d{2}[.年/-]\s*\d{1,2}[.月/-]\s*\d{1,2}", text)
    return m.group(0) if m else path.stem[-8:]


def merge_items(docs: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for doc in docs:
        for item in doc["items"]:
            current = grouped.get(item["key"])
            if not current:
                current = {**item, "sources": [], "duplicate_count": 0}
                grouped[item["key"]] = current
            current["sources"].append({"file": item["source_file"], "url": item["source_url"]})
            current["duplicate_count"] += 1
            if not current.get("comment") and item.get("comment"):
                current["comment"] = item["comment"]
    return list(grouped.values())


THEMES = {
    "积分与权益": (r"积分|福气值|权益|年费|贵宾厅|免年费", "积分规则和持卡权益正在成为主要变化点"),
    "AI 与联名产品": (r"AI|算力|Kimi|Qoder|智能体", "银行把 AI 会员或算力包装进信用卡权益"),
    "年轻化产品": (r"MBTI|DIY|主题|贴纸|茶咖", "卡面、社交表达和年轻消费场景成为获客抓手"),
    "短期营销活动": (r"活动|满\d+|随机|名额|消费达标", "短期活动普遍依赖指定卡、名额或消费门槛"),
}


def build_editorial(items: list[dict], docs: list[dict]) -> str:
    categories = Counter(i.get("category") or "未分类" for i in items)
    lines = [
        "# 公众号文章合并点评稿", "",
        f"> 来源：{len(docs)} 份 Markdown，{len(items)} 条去重后资讯；生成日期：{date.today().isoformat()}",
        "> 方法：保留原文事实与来源，在此基础上做主题归并、交叉点评和行动建议。", "",
        "## 一、编辑摘要", "",
        f"本批共整理 **{len(items)} 条**资讯，类别分布为：" + "、".join(f"{k} {v} 条" for k, v in categories.items()) + "。", "",
    ]
    theme_hits = []
    for name, (pattern, conclusion) in THEMES.items():
        hit = [i["display_title"] for i in items if re.search(pattern, i["display_title"] + "\n" + i["body"], re.I)]
        if hit:
            theme_hits.append((name, conclusion, hit))
    if theme_hits:
        lines += ["本批内容呈现出以下共同方向：", ""]
        for name, conclusion, hit in theme_hits:
            lines.append(f"- **{name}**：{conclusion}。涉及：" + "、".join(hit) + "。")
    lines += ["", "## 二、主题整合与交叉点评", ""]
    for name, conclusion, hit in theme_hits:
        lines += [f"### {name}", "", f"{conclusion}。从本批案例看，相关权益的价值不能只看宣传概念，还要同时核对适用卡种、达标成本、有效期、名额和兑现路径。", "", "关联条目：" + "、".join(hit), ""]
    lines += ["## 三、逐条保留与点评", ""]
    for idx, item in enumerate(items, 1):
        lines += [f"### {idx}. {item['display_title']}", ""]
        meta = [x for x in (item.get("category"), item.get("priority")) if x]
        if meta:
            lines += ["**属性**：" + "｜".join(meta), ""]
        if item.get("source_url"):
            lines += [f"**来源**：{item['source_url']}", ""]
        lines += [item["body"], ""]
        if item.get("duplicate_count", 0) > 1:
            lines += [f"> 合并说明：发现 {item['duplicate_count']} 份来源涉及同一事项，已合并展示。", ""]
    lines += ["## 四、行动建议", "", "- 涉及积分、年费和权益变更：先按申请日期、卡种和账户状态核对适用规则，再决定申请或保留。", "- 涉及 AI 联名权益：把会员月卡、算力额度折算成真实使用价值，不以“首张”“联名”等概念替代成本评估。", "- 涉及短期活动：重点关注名额、次数、指定渠道和达标门槛，顺手参加即可，避免为凑门槛增加非必要消费。", "", "## 五、来源清单", ""]
    for doc in docs:
        lines.append(f"- {doc['file']}（{len(doc['items'])} 条）")
    lines += ["", "---", "", "> 本稿由 Mode D 生成；原始事实未被删除，点评与整合内容属于编辑辅助，不替代银行官方条款。", ""]
    return "\n".join(lines)


def llm_note(items: list[dict]) -> str:
    """可选的二次点评；失败时由调用方降级为本地规则结果。"""
    try:
        from common.llm_client import LlmClient
        payload = "\n".join(
            f"- {i['display_title']}｜{i.get('category', '')}｜{i.get('comment', '')[:500]}"
            for i in items
        )
        response = LlmClient().call(
            "你是信用卡资讯编辑。只基于给定条目，输出不超过三点的跨条目观察和风险提醒，避免编造事实。",
            payload,
            temperature=0.2,
            max_tokens=800,
            timeout=45,
        )
        return response.content if response else ""
    except Exception as exc:
        print(f"  [LLM] optional enhancement skipped: {exc}")
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Mode D：Markdown 合并、点评与整合")
    parser.add_argument("--input", nargs="+", required=True, help="输入 Markdown 文件")
    parser.add_argument("--output", default="", help="输出 Markdown 路径")
    parser.add_argument("--manifest", default="", help="可选：输出审计 JSON")
    parser.add_argument("--llm", action="store_true", help="可选：使用统一 LLM 客户端增强跨条目点评")
    args = parser.parse_args()
    paths = [Path(x).resolve() for x in args.input]
    missing = [str(x) for x in paths if not x.is_file()]
    if missing:
        parser.error("文件不存在：" + ", ".join(missing))
    docs = [parse_markdown(p) for p in paths]
    items = merge_items(docs)
    output = Path(args.output) if args.output else ROOT / "data" / "mode_d_merged.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    editorial = build_editorial(items, docs)
    if args.llm:
        note = llm_note(items)
        if note:
            marker = "## 四、行动建议"
            editorial = editorial.replace(marker, "## LLM 增强点评\n\n" + note + "\n\n" + marker, 1)
    output.write_text(editorial, encoding="utf-8")
    manifest = {"mode": "D", "inputs": [str(p) for p in paths], "documents": docs, "merged_items": items}
    manifest_path = Path(args.manifest) if args.manifest else output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Mode D] {len(docs)} 份文档 → {len(items)} 条去重资讯")
    print(f"[Output] {output}")
    print(f"[Audit]  {manifest_path}")


if __name__ == "__main__":
    main()
