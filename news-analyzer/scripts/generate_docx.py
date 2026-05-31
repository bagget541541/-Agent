#!/usr/bin/env python3
"""
Word文档生成脚本
功能：将公告分析结果生成为格式化的Word文档
"""

import json
import sys
import argparse
from datetime import datetime
from typing import List, Dict


def setup_docx():
    """导入python-docx模块"""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        return Document, Pt, RGBColor, Inches, WD_ALIGN_PARAGRAPH
    except ImportError:
        print(json.dumps({"error": "python-docx未安装，请运行: pip install python-docx"}, ensure_ascii=False))
        sys.exit(1)


def generate_word_document(data: List[Dict], output_path: str) -> bool:
    """
    生成Word文档

    Args:
        data: 公告数据列表，每个元素包含title, url, message
        output_path: 输出文件路径

    Returns:
        是否成功生成文档
    """
    Document, Pt, RGBColor, Inches, WD_ALIGN_PARAGRAPH = setup_docx()
    doc = Document()

    # 文档标题
    title = doc.add_heading('公告分析报告', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 生成时间
    time_paragraph = doc.add_paragraph()
    time_run = time_paragraph.add_run(f'生成时间：{datetime.now().strftime("%Y年%m月%d日 %H:%M")}')
    time_run.font.size = Pt(10)
    time_run.font.color.rgb = RGBColor(128, 128, 128)
    time_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 添加分隔线
    doc.add_paragraph('_' * 80)

    # 为每个公告添加内容
    for idx, item in enumerate(data, 1):
        print(f"正在处理第 {idx} 条公告...", file=sys.stderr)
        print(f"标题: {item.get('title', '无')}", file=sys.stderr)
        print(f"消息内容: {item.get('message', '无')[:50] if item.get('message') else '空'}...", file=sys.stderr)

        # 公告标题
        heading = doc.add_heading(f'{idx}. {item.get("title", "无标题")}', level=2)

        # 原文链接
        link_paragraph = doc.add_paragraph()
        link_run = link_paragraph.add_run(f'原文链接：{item.get("url", "")}')
        link_run.font.size = Pt(9)
        link_run.font.color.rgb = RGBColor(0, 102, 204)

        # 消息内容
        doc.add_heading('消息内容', level=3)
        message_text = item.get("message", "")
        if not message_text:
            message_text = "（无消息内容）"
        message_paragraph = doc.add_paragraph(message_text)
        message_paragraph.paragraph_format.left_indent = Inches(0.25)

        # 公告之间添加空行（最后一个除外）
        if idx < len(data):
            doc.add_paragraph()

    # 保存文档
    doc.save(output_path)
    return True


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='生成公告分析Word文档')
    parser.add_argument('--input', type=str, required=True,
                       help='输入JSON文件路径，包含公告分析数据')
    parser.add_argument('--output', type=str, default='公告分析报告.docx',
                       help='输出Word文件路径（默认: 公告分析报告.docx）')

    args = parser.parse_args()

    # 读取输入数据
    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"找不到输入文件: {args.input}"}, ensure_ascii=False))
        sys.exit(1)
    except json.JSONDecodeError:
        print(json.dumps({"error": "输入文件格式错误，应为有效的JSON"}, ensure_ascii=False))
        sys.exit(1)

    # 生成Word文档
    try:
        if not isinstance(data, list):
            print(json.dumps({"error": "输入数据应为JSON数组"}, ensure_ascii=False))
            sys.exit(1)
        generate_word_document(data, args.output)
        print(json.dumps({
            "success": True,
            "output": args.output,
            "count": len(data)
        }, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"生成文档失败: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
