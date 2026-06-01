#!/usr/bin/env python3
"""
generate_merged_docx.py — 从合并后的 JSON 数据生成带图片的 Word 文档。

用法：
    python word-merger/scripts/generate_merged_docx.py --input merged.json --output 输出.docx

输入 JSON 格式（由 merge_docs.py 的 merge_contents 等产生）：
    {
        "title": "...",
        "sources": ["..."],
        "generated_at": "...",
        "h1_sections": [...],
        "all_images": { "rid": base64_or_bytes, ... }
    }
"""
import json
import os
import sys
import argparse
from pathlib import Path

# 确保项目根目录在 sys.path 中
_HERE = Path(__file__).resolve().parent  # word-merger/scripts/
_WM_ROOT = _HERE.parent                  # word-merger/
_PROJECT_ROOT = _WM_ROOT.parent          # project root
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from merge_docs import create_merged_docx


def load_input(path: str) -> dict:
    """读取合并后的 JSON 并拆分为 merged 和 suggestions 两部分。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 兼容两种输入格式：
    # A) {"merged": {...}, "suggestions": {...}}
    # B) 直接是 merged dict
    if "merged" in raw:
        merged = raw["merged"]
        suggestions = raw.get("suggestions", {"items": [], "overall": {}})
    else:
        merged = raw
        suggestions = raw.get("suggestions", {"items": [], "overall": {}})
        raw.pop("suggestions", None)

    return merged, suggestions


def main():
    parser = argparse.ArgumentParser(
        description="从合并 JSON 生成带图片的 Word 文档",
    )
    parser.add_argument("--input", required=True,
                        help="合并后的 JSON 文件路径")
    parser.add_argument("--output", required=True,
                        help="输出 .docx 文件路径")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(json.dumps({"error": f"输入文件不存在: {args.input}"},
                         ensure_ascii=False))
        sys.exit(1)

    merged, suggestions = load_input(args.input)
    print(f"[Info] 已加载合并数据: {len(merged.get('h1_sections', []))} 个分类")
    for h1 in merged.get("h1_sections", []):
        n = len(h1.get("h2_items", []))
        print(f"  - {h1['title']}: {n} 条")

    ok = create_merged_docx(merged, suggestions, args.output)
    if ok:
        print(json.dumps({"success": True, "output": args.output},
                         ensure_ascii=False))
    else:
        print(json.dumps({"error": "生成 Word 文档失败"},
                         ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
