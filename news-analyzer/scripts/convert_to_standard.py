"""
news-analyzer → 标准统一格式 转换脚本

功能：将 news-analyzer 提取的公告 JSON 转换为 CreditCardBatch 标准格式。
支持时间范围过滤、低价值内容过滤。

用法：
    python scripts/convert_to_standard.py --input 公告数据.json --output 标准格式.json
    python scripts/convert_to_standard.py --input 公告数据.json --output 标准格式.json --batch-label "2026年5月第2周"
    python scripts/convert_to_standard.py --input 公告数据.json --output 标准格式.json --since 2026-05-01
    python scripts/convert_to_standard.py --input 公告数据.json --output 标准格式.json --days 7
"""

import json
import sys
import os
import re
import argparse
from datetime import datetime, timedelta
from typing import Optional

# 将 project 根加入 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from common.schema import CreditCardItem, CreditCardBatch, normalize_category
from common.utils import extract_bank_name; from common.images import centralize_images
from common.config import ensure_dirs
from common.classifier import classify_item

# ════════════════════════════════════════════════════════════════
# 低价值公告过滤关键词
# ════════════════════════════════════════════════════════════════

LOW_VALUE_SUBSTRINGS = [
    # 数据库维护
    "数据库维护", "数据库升级", "数据库迁移", "数据库切换", "数据库优化", "数据库割接",
    # 系统维护
    "系统升级", "系统维护", "系统优化", "系统切换", "系统更新",
    "系统改造", "系统调整", "系统暂停", "系统变更", "系统下线",
    # 电话更新
    "客服电话变更", "客服热线变更", "服务热线变更", "电话变更",
    "电话号码更新", "联系电话变更", "24小时客服热线",
    # 联系方式变更
    "联系方式变更", "联系地址变更", "办公地址变更",
    "联系地址变更公告", "办公地址搬迁",
    # 服务暂停（非权益类）
    "暂停服务", "服务暂停", "临时暂停", "暂停办理",
    # 官网维护
    "官网维护", "网站升级", "网站维护", "网页维护",
    # 网络调整
    "网络调整", "线路调整", "线路维护", "网络维护",
    "网络升级", "网络割接",
    # 通用低价值
    "电话更新", "维护公告", "升级公告",
]


def is_low_value(title: str, content: str = "") -> bool:
    """判断是否为低价值公告（数据库维护、电话更新等）。"""
    text = f"{title} {content[:200]}"
    for kw in LOW_VALUE_SUBSTRINGS:
        if kw in text:
            return True
    return False


def parse_date(date_str: str) -> Optional[datetime]:
    """尝试多种日期格式解析。"""
    if not date_str:
        return None
    date_str = date_str.strip().replace("年", "-").replace("月", "-").replace("日", "")

    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d",
                "%Y-%m-%d %H:%M", "%Y年%m月%d日", "%Y-%m-%dT%H:%M:%S"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def _guess_category(title: str, content: str) -> str:
    """根据标题和内容关键词推测分类。"""
    text = f"{title} {content[:500]}"
    if any(kw in text for kw in ["新卡", "首发", "上市", "发行", "推出", "全新", "首发上市"]):
        return "新卡"
    if any(kw in text for kw in ["调整", "变更", "升级", "缩水", "取消", "权益",
                                  "优化", "更新", "新规", "规则调整", "修改"]):
        return "权益变更"
    if any(kw in text for kw in ["活动", "优惠", "返现", "满减", "积分", "福利",
                                  "折扣", "抽奖", "送礼", "消费奖励", "刷卡",
                                  "立减", "返利"]):
        return "活动"
    return "公告"


def convert(
    input_path: str,
    batch_label: str = "",
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    days: int = 7,
    skip_low_value: bool = True,
) -> CreditCardBatch:
    """读取 news-analyzer 的 JSON 输出, 转为标准格式。

    Args:
        input_path: 输入 JSON 文件路径
        batch_label: 批次标签
        since: 起始日期（None 则使用 days 参数）
        until: 截止日期（None 则不限上限）
        days: 默认抓取天数（since 为 None 时生效）
        skip_low_value: 是否过滤低价值公告

    Returns:
        CreditCardBatch 实例
    """
    if since is None:
        since = datetime.now() - timedelta(days=days)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # news-analyzer 多种输入格式兼容
    if isinstance(data, dict):
        if "items" in data:
            raw_items = data["items"]
        elif "announcements" in data:
            raw_items = data["announcements"]
        else:
            raw_items = [data]
    elif isinstance(data, list):
        raw_items = data
    else:
        raw_items = [data]

    batch = CreditCardBatch(batch_label=batch_label)
    skipped_low_value = 0
    skipped_time = 0

    for idx, raw in enumerate(raw_items):
        title = raw.get("title", "") or raw.get("公告标题", "")
        url = raw.get("url", "") or raw.get("公告URL", "")
        content = raw.get("content", "") or raw.get("message", "") or raw.get("公告内容", "") or raw.get("raw_text", "")
        bank = raw.get("bank", "") or extract_bank_name(title, content)
        publish_time = raw.get("publish_time", "") or raw.get("date", "") or raw.get("date_str", "")

        # 低价值过滤
        if skip_low_value and is_low_value(title, content):
            skipped_low_value += 1
            continue

        # 时间范围过滤
        if publish_time:
            dt = parse_date(publish_time)
            if dt:
                if dt < since:
                    skipped_time += 1
                    continue
                if until and dt > until:
                    skipped_time += 1
                    continue

        # 分类猜测
        category = normalize_category(raw.get("category", ""))
        if not category:
            classifier_result = classify_item(title, content)
            category = classifier_result["category"]

        # 构建结构化字段
        structured = {}

        if category == "公告":
            structured = {"消息内容": content[:300], "点评": ""}
        elif category == "活动":
            # 尝试从内容中提取活动时间
            time_hint = publish_time
            m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)\s*[-至~]\s*(\d{4}年?\d{1,2}月\d{1,2}日)", content[:500])
            if m:
                time_hint = f"{m.group(1)} ~ {m.group(2)}"
            structured = {
                "活动内容": title,
                "活动时间": time_hint,
                "适用人群": f"{bank}信用卡持卡人",
            }
        elif category == "新卡":
            structured = {
                "卡种": title,
                "卡亮点": "",
                "适用人群": "",
                "来源": bank,
                "详情": content[:300],
            }
        elif category == "权益变更":
            structured = {
                "消息时间": publish_time,
                "影响范围": f"{bank}信用卡持卡人",
                "变更内容": content[:500],
                "变更分析": "",
            }
        else:
            structured = {"详细内容": content[:300] or title}

        images = raw.get("images", []) or raw.get("image_urls", [])

        item = CreditCardItem(
            source="website",
            category=category,
            bank=bank,
            title=title,
            url=url,
            raw_text=content,
            images=images,
            structured=structured,
            author=raw.get("author", ""),
            publish_time=publish_time,
        )

        # 集中图片（如有）
        if images:
            ensure_dirs()
            item.images = centralize_images(images, item.item_id)

        batch.add(item)

    # 输出过滤统计
    if skipped_low_value or skipped_time:
        print(f"  [过滤] 低价值 {skipped_low_value} 条, 超时间范围 {skipped_time} 条",
              file=sys.stderr)

    return batch


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="news-analyzer 输出转标准格式（支持过滤）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本转换
  python scripts/convert_to_standard.py --input 公告.json --output 标准格式.json

  # 附加批次标签
  python scripts/convert_to_standard.py --input 公告.json --batch-label "2026年5月第2周"

  # 仅保留最近7天
  python scripts/convert_to_standard.py --input 公告.json --days 7

  # 指定日期范围
  python scripts/convert_to_standard.py --input 公告.json --since 2026-05-01 --until 2026-05-31

  # 不过滤低价值公告
  python scripts/convert_to_standard.py --input 公告.json --no-skip-low-value
        """,
    )
    parser.add_argument("--input", required=True, help="news-analyzer 输出的 JSON 文件路径")
    parser.add_argument("--output", default="", help="标准格式 JSON 输出路径（默认与输入同目录）")
    parser.add_argument("--batch-label", default="", help="批次标签（如'2026年5月第2周'）")
    parser.add_argument("--days", type=int, default=7, help="保留最近 N 天的公告（默认 7）")
    parser.add_argument("--since", type=str, default="", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--until", type=str, default="", help="截止日期 YYYY-MM-DD")
    parser.add_argument("--no-skip-low-value", action="store_true", help="不过滤低价值公告")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(json.dumps({"error": f"输入文件不存在: {args.input}"}, ensure_ascii=False))
        sys.exit(1)

    # 时间范围
    since = None
    until = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"错误: 日期格式无效 {args.since}", file=sys.stderr)
            sys.exit(1)
    if args.until:
        try:
            until = datetime.strptime(args.until, "%Y-%m-%d")
            until = until.replace(hour=23, minute=59, second=59)
        except ValueError:
            print(f"错误: 日期格式无效 {args.until}", file=sys.stderr)
            sys.exit(1)

    batch = convert(
        args.input,
        batch_label=args.batch_label,
        since=since,
        until=until,
        days=args.days,
        skip_low_value=not args.no_skip_low_value,
    )

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
