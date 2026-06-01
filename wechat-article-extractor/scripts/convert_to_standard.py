"""
wechat-article-extractor → 标准统一格式 转换脚本

功能：将 wechat-article-extractor 的 batch_result.json 输出
      转换为 CreditCardBatch 标准格式，统一分类命名。

用法：
    python scripts/convert_to_standard.py --input batch_result.json --output 标准格式.json
    python scripts/convert_to_standard.py --input batch_result.json --output 标准格式.json --batch-label "2026年5月第2周"
"""

import json
import sys
import os
import re
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from common.schema import CreditCardItem, CreditCardBatch, normalize_category
from common.utils import extract_bank_name; from common.images import centralize_images, ensure_dir
from common.config import ensure_dirs
from common.normalizer import _build_structured_for_category


def convert(input_path: str, batch_label: str = "") -> CreditCardBatch:
    """读取 wechat-article-extractor 的 batch_result.json 输出, 转为标准格式。"""
    with open(input_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    batch = CreditCardBatch(batch_label=batch_label)

    # batch_result.json 是以 URL 为 key 的 dict
    for url, article in raw_data.items():
        title = article.get("title", "") or article.get("original_title", "")
        text = article.get("text", "") or article.get("summary", "")
        images = article.get("images", [])

        # 标准化分类
        raw_category = article.get("category", "")
        category = normalize_category(raw_category)

        # 提取银行名
        bank = article.get("bank", "") or extract_bank_name(title, text)

        # 结构化内容（已有 structured 字段则直接使用，否则重建）
        structured = article.get("structured", None)
        if not structured or not isinstance(structured, dict):
            structured = _build_structured_for_category(category, title, text)

        # 清理 structured 中的空值/无用字段
        structured = {k: v for k, v in structured.items() if v and v != "[]"}

        # 清理 raw_text 中的特殊标记
        clean_text = re.sub(r"\[.*?\]", "", text).strip()

        # 先创建 item（自动生成 item_id）
        item = CreditCardItem(
            source="wechat",
            category=category,
            bank=bank,
            title=title,
            url=url,
            raw_text=clean_text or text,
            images=images,
            structured=structured,
            author=article.get("author", ""),
            publish_time=article.get("publish_time", ""),
        )

        # 集中图片到 data/images/{item_id}/
        ensure_dirs()
        if images:
            item.images = centralize_images(images, item.item_id)

        batch.add(item)

    return batch


def _build_structured(category: str, title: str, text: str) -> dict:
    """为缺失 structured 字段的文章重建结构化内容。"""
    summary = text[:300] if text else ""
    if category == "活动":
        # 尝试从文本中提取时间
        time_match = re.search(r"(\d{4}[-.]\d{1,2}[-.]\d{1,2})", text or "")
        time_str = time_match.group(1) if time_match else ""
        return {"活动内容": summary, "活动时间": time_str, "适用人群": ""}
    elif category == "新卡":
        return {"卡种": title, "卡亮点": "", "适用人群": "", "来源": "", "详情": summary}
    elif category == "权益变更":
        return {"消息时间": "", "影响范围": "", "变更内容": summary, "变更分析": ""}
    elif category == "公告":
        return {"消息内容": summary, "点评": ""}
    else:
        return {"详细内容": summary or title}


def main():
    parser = argparse.ArgumentParser(description="wechat-article-extractor 输出转标准格式")
    parser.add_argument("--input", required=True, help="batch_result.json 文件路径")
    parser.add_argument("--output", default="", help="标准格式 JSON 输出路径（默认与输入同目录）")
    parser.add_argument("--batch-label", default="", help="批次标签（如'2026年5月第2周'）")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(json.dumps({"error": f"输入文件不存在: {args.input}"}, ensure_ascii=False))
        sys.exit(1)

    batch = convert(args.input, batch_label=args.batch_label)

    output_path = args.output or os.path.splitext(args.input)[0] + "_标准格式.json"
    abs_path = batch.save_json(output_path)

    summary = {
        "success": True,
        "output": abs_path,
        "total": batch.size(),
        "categories": {
            cat: len(batch.by_category(cat)) for cat in ["新卡", "权益变更", "活动", "公告", "其他"]
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
