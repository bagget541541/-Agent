#!/usr/bin/env python3
"""
标准JSON → 持卡建议分析 预处理脚本

读取标准 JSON 批次数据，按银行/类型组织，输出结构化分析上下文。
评分使用 ROI 加权模型，支持 LLM 语义评分和关键词降级双模式。

数据流向：
  news-analyzer / wechat-article-extractor
    → 标准 JSON (含 data/images/{item_id}/ 图片路径)
    → analyze_batch.py
    → 结构化分析上下文 JSON (含评分和建议)

用法：
    # 输出 JSON 格式（默认，供 AI agent 读取）
    python scripts/analyze_batch.py --input batch_标准格式.json --output analysis_ready.json

    # 输出 Markdown 格式
    python scripts/analyze_batch.py --input batch.json --format markdown

    # 指定评分模式
    python scripts/analyze_batch.py --input batch.json --scorer llm       # LLM 评分
    python scripts/analyze_batch.py --input batch.json --scorer keyword   # 关键词评分（默认）
"""

import json
import os
import sys
import argparse
from datetime import datetime

# 确保项目根在 sys.path 中，使 from scripts.scorer 能正确导入
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)  # card-holding-suggestion/
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 导入 ROI 评分引擎
from scripts.scorer import score_with_llm, score_with_keywords, DIMENSION_TEMPLATES, score_to_emoji


# ── 上下文构建 ──────────────────────────────────────────────


def build_context(batch_data: dict, focus: str = "", scorer: str = "keyword") -> dict:
    """从标准 JSON 批次数据构建持卡建议分析上下文。"""
    items = batch_data.get('items', [])
    batch_label = batch_data.get('batch_label', '')

    # 按银行分组
    banks: dict[str, dict] = {}
    # 按分类分组
    by_category: dict[str, list] = {}

    for item in items:
        cat = item.get('category', '')
        bank_name = item.get('bank', '') or '未知银行'
        if focus and cat != focus:
            continue

        by_category.setdefault(cat, []).append(item)
        banks.setdefault(bank_name, {
            'bank': bank_name,
            'new_cards': [],
            'changes': [],
            'activities': [],
            'announcements': [],
        })
        if cat == '新卡':
            banks[bank_name]['new_cards'].append(item)
        elif cat == '权益变更':
            banks[bank_name]['changes'].append(item)
        elif cat == '活动':
            banks[bank_name]['activities'].append(item)
        elif cat == '公告':
            banks[bank_name]['announcements'].append(item)

    # 构建排序后的银行列表（活动多的排前面）
    bank_list = sorted(banks.values(),
                       key=lambda b: len(b['activities']) + len(b['new_cards']),
                       reverse=True)

    # 为每条内容生成评估要点（使用统一评分引擎）
    def extract_key_points(item: dict) -> dict:
        cat = item.get('category', '')
        structured = item.get('structured', {})
        title = item.get('title', '')
        bank = item.get('bank', '')
        url = item.get('url', '')
        images = item.get('images', [])
        raw_text = item.get('raw_text', '')

        points = {
            'title': title,
            'bank': bank,
            'url': url,
            'images': images,
            'image_count': len(images),
        }

        # 统一使用 ROI 评分引擎
        if cat in DIMENSION_TEMPLATES:
            if scorer == "llm":
                result = score_with_llm(item)
            else:
                result = score_with_keywords(item, DIMENSION_TEMPLATES[cat]())
            ev_dict = result.to_dict()
            points['evaluation'] = ev_dict
            # Phase 1: 写回富字段到原始 item（供 generate_report.py 使用）
            item['target_audience'] = ev_dict.get('target_audience', '')
            item['key_benefits'] = ev_dict.get('key_benefits', [])
            item['fee_assessment'] = ev_dict.get('fee_assessment', '')
            item['worth_applying'] = ev_dict.get('worth_applying', [])
            item['priority_emoji'] = ev_dict.get('priority_emoji', '') or score_to_emoji(
                cat, ev_dict.get('overall_score', 5), ev_dict.get('overall_roi', ''))
        else:
            points['evaluation'] = {
                'overall_score': 5.0,
                'recommendation': '无需评分',
                'summary': structured.get('消息内容', '')[:200],
            }

        return points

    context = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'batch_label': batch_label,
        'total_items': len(items),
        'bank_count': len(banks),
        'scorer': scorer,
        'category_summary': {
            cat: {
                'count': len(items),
                'items': [extract_key_points(it) for it in items],
            }
            for cat, items in by_category.items()
        },
        'banks': [
            {
                'bank': b['bank'],
                'new_card_count': len(b['new_cards']),
                'change_count': len(b['changes']),
                'activity_count': len(b['activities']),
                'announcement_count': len(b['announcements']),
                'new_cards': [extract_key_points(it) for it in b['new_cards']],
                'changes': [extract_key_points(it) for it in b['changes']],
                'activities': [extract_key_points(it) for it in b['activities']],
                'announcements': [extract_key_points(it) for it in b['announcements']],
            }
            for b in bank_list
        ],
    }

    # Phase 1: 将富字段已写回的 items 附加到 context（供 agent.py 使用）
    context['_enriched_items'] = items
    return context


# ── 输出格式 ────────────────────────────────────────────────


def format_as_markdown(context: dict) -> str:
    """将分析上下文转为 Markdown 格式（供人类阅读或直接贴给 AI）。"""
    lines = []
    lines.append(f'# 信用卡持卡分析报告\n')
    lines.append(f'批次：{context["batch_label"]}')
    lines.append(f'生成时间：{context["generated_at"]}')
    lines.append(f'评分模式：{context.get("scorer", "keyword")}')
    lines.append(f'总条目：{context["total_items"]} 条，涉及 {context["bank_count"]} 家银行\n')
    lines.append('---\n')

    # 按分类展示
    for cat, data in context['category_summary'].items():
        count = data['count']
        lines.append(f'## {cat}（共 {count} 条）\n')
        for item in data['items']:
            lines.append(f'### {item["bank"]} · {item["title"]}')
            if item.get('url'):
                lines.append(f'原文：{item["url"]}')
            if item.get('image_count', 0) > 0:
                lines.append(f'附图：{item["image_count"]} 张')
            ev = item.get('evaluation', {})
            if ev:
                score = ev.get('overall_score', '')
                roi = ev.get('overall_roi', '')
                rec = ev.get('recommendation', '')
                summary = ev.get('summary', '')
                if score:
                    lines.append(f'- ROI 评分：**{score}/10**（{roi}）— {rec}')
                if summary:
                    lines.append(f'- 小结：{summary}')
                dims = ev.get('dimensions', [])
                for d in dims:
                    lines.append(f'  - {d.get("name", "")}：{d.get("score", "")}/10（权重 {d.get("weight", 0)*100:.0f}%）')
                    if d.get('reason'):
                        lines.append(f'    → {d["reason"]}')
            lines.append('')
        lines.append('')

    # 按银行汇总
    lines.append('---\n## 按银行汇总\n')
    for bank in context['banks']:
        parts = []
        if bank['new_card_count']:
            parts.append(f'新卡 {bank["new_card_count"]}')
        if bank['change_count']:
            parts.append(f'权益变更 {bank["change_count"]}')
        if bank['activity_count']:
            parts.append(f'活动 {bank["activity_count"]}')
        if bank['announcement_count']:
            parts.append(f'公告 {bank["announcement_count"]}')
        lines.append(f'### {bank["bank"]}（{" | ".join(parts) if parts else "无条目"}）\n')

        for item in bank['new_cards']:
            ev = item.get('evaluation', {})
            score = ev.get('overall_score', '')
            roi = ev.get('overall_roi', '')
            rec = ev.get('recommendation', '')
            lines.append(f'- 🆕 **{item["title"]}**（ROI {score}/10 {roi}—{rec}）')

        for item in bank['changes']:
            ev = item.get('evaluation', {})
            score = ev.get('overall_score', '')
            roi = ev.get('overall_roi', '')
            rec = ev.get('recommendation', '')
            lines.append(f'- 🔄 **{item["title"]}**（ROI {score}/10 {roi}—{rec}）')
            summary = ev.get('summary', '')
            if summary:
                lines.append(f'  - {summary}')

        for item in bank['activities']:
            ev = item.get('evaluation', {})
            score = ev.get('overall_score', '')
            roi = ev.get('overall_roi', '')
            rec = ev.get('recommendation', '')
            lines.append(f'- 🏷️ **{item["title"]}**（ROI {score}/10 {roi}—{rec}）')

        lines.append('')

    return '\n'.join(lines)


# ── CLI ─────────────────────────────────────────────────────


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    parser = argparse.ArgumentParser(description='标准JSON → 持卡建议分析 预处理')
    parser.add_argument('--input', required=True, help='标准格式 JSON 文件路径')
    parser.add_argument('--output', default='', help='输出文件路径（JSON，use with --format json）')
    parser.add_argument('--format', choices=['json', 'markdown'], default='json',
                        help='输出格式（默认 json）')
    parser.add_argument('--scorer', choices=['keyword', 'llm'], default='keyword',
                        help='评分模式：keyword（关键词评分，默认）| llm（LLM 语义评分）')
    parser.add_argument('--focus', default='',
                        choices=['', '新卡', '权益变更', '活动', '公告'],
                        help='只分析指定分类')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(json.dumps({"error": f"输入文件不存在: {args.input}"}, ensure_ascii=False))
        sys.exit(1)

    with open(args.input, 'r', encoding='utf-8') as f:
        batch_data = json.load(f)

    context = build_context(batch_data, focus=args.focus, scorer=args.scorer)

    if args.format == 'markdown':
        output = format_as_markdown(context)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            print(json.dumps({"success": True, "output": os.path.abspath(args.output)},
                             ensure_ascii=False, indent=2))
        else:
            print(output)
    else:
        output_json = json.dumps(context, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output_json)
        sys.stdout.write(output_json + '\n')


if __name__ == '__main__':
    main()
