#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多Word文档整合 + 持卡建议生成

模式B核心脚本：
1. 读取多个Word文档
2. 提取内容并整合
3. 生成持卡建议
4. 输出整合后的Word文档
"""

import json
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "word-merger" / "scripts"))
try:
    from utils import IMAGE_WIDTH_CM
except Exception:
    IMAGE_WIDTH_CM = 13


def read_docx_content(docx_path: str) -> dict:
    """
    读取Word文档内容，保留 Heading 1 → Heading 2 层级结构，追踪图片位置

    Returns:
        包含层级章节的字典
    """
    try:
        from docx import Document
        from lxml import etree

        doc = Document(docx_path)
        content = {
            "file": docx_path,
            "title": "",
            "h1_sections": [],  # Heading 1 级别的大分类
            "full_text": ""
        }

        full_text_parts = []
        current_h1 = None
        current_h2 = None
        images_map = _extract_docx_images(docx_path)

        # XML 命名空间
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
              'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
              'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
              'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

        for para in doc.paragraphs:
            text = para.text.strip()
            style = para.style.name

            # 检查段落中是否有图片
            drawings = para._element.findall('.//w:drawing', ns)
            para_images = []
            for d in drawings:
                blips = d.findall('.//a:blip', ns)
                for b in blips:
                    rid = b.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                    if rid and rid in images_map:
                        para_images.append(rid)

            # 跳过空段落（但保留有图片的段落）
            if not text and not para_images:
                continue

            # 识别 Heading 1
            if style == 'Heading 1':
                current_h1 = {
                    "title": text,
                    "h2_items": [],  # 下级 Heading 2 条目
                    "content": []
                }
                content["h1_sections"].append(current_h1)
                current_h2 = None
            # 识别 Heading 2
            elif style == 'Heading 2' and current_h1 is not None:
                current_h2 = {
                    "title": text,
                    "content": [],
                    "images": []  # 存储该条目的图片 rId
                }
                current_h1["h2_items"].append(current_h2)
            # 普通段落或列表
            elif current_h2 is not None:
                if text:
                    current_h2["content"].append(text)
                # 将图片关联到当前 h2
                current_h2["images"].extend(para_images)
            elif current_h1 is not None:
                if text:
                    current_h1["content"].append(text)
            else:
                if not content["title"] and len(text) < 80:
                    content["title"] = text

            if text:
                full_text_parts.append(text)

        content["full_text"] = "\n".join(full_text_parts)
        content["images_map"] = images_map

        return content

    except Exception as e:
        print(f"  [Error] Read failed {docx_path}: {e}")
        return {"file": docx_path, "title": Path(docx_path).stem, "h1_sections": [], "full_text": ""}


def _extract_docx_images(docx_path: str) -> dict:
    """提取 docx 中的所有图片，返回 {rId: bytes} 映射"""
    import zipfile
    from lxml import etree

    images = {}
    try:
        with zipfile.ZipFile(docx_path, 'r') as zf:
            # 读取 rels 文件获取 rId → media 映射
            rels_xml = zf.read('word/_rels/document.xml.rels')
            rels_root = etree.fromstring(rels_xml)
            ns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}

            rid_to_target = {}
            for rel in rels_root.findall('r:Relationship', ns):
                rid = rel.get('Id')
                target = rel.get('Target')
                rel_type = rel.get('Type', '')
                if 'image' in rel_type and target:
                    rid_to_target[rid] = target

            # 提取图片文件
            for rid, target in rid_to_target.items():
                img_path = f'word/{target}' if not target.startswith('/') else target[1:]
                try:
                    img_data = zf.read(img_path)
                    images[rid] = img_data
                except KeyError:
                    pass

    except Exception:
        pass

    return images


def merge_contents(contents: list) -> dict:
    """整合多个文档内容，保留层级结构"""
    merged = {
        "title": "信用卡周报（整合版）",
        "generated_at": datetime.now().isoformat(),
        "sources": [],
        "h1_sections": [],  # Heading 1 级别的大分类
        "all_images": {},   # 所有图片数据
        "items": []
    }

    for content in contents:
        merged["sources"].append(Path(content["file"]).name)

        # 合并图片
        merged["all_images"].update(content.get("images_map", {}))

        # 合并 h1 层级
        for h1 in content.get("h1_sections", []):
            # 检查是否已存在同名 h1
            existing_h1 = None
            for s in merged["h1_sections"]:
                if s["title"] == h1["title"]:
                    existing_h1 = s
                    break

            if existing_h1:
                # 合并 h2 条目
                existing_h1["h2_items"].extend(h1.get("h2_items", []))
                existing_h1["content"].extend(h1.get("content", []))
            else:
                merged["h1_sections"].append(h1)

    return merged


def extract_items_for_analysis(merged: dict) -> list:
    """从整合内容中提取待分析的条目（使用层级结构）"""
    items = []

    for h1 in merged.get("h1_sections", []):
        category = h1.get("title", "活动")

        for h2 in h1.get("h2_items", []):
            content_text = "\n".join(h2.get("content", []))

            # 尝试识别银行
            bank = ""
            for keyword in ["银行", "信用卡", "金融"]:
                if keyword in h2["title"]:
                    bank = h2["title"].split(keyword)[0] + keyword
                    break

            items.append({
                "title": h2["title"],
                "bank": bank,
                "raw_text": content_text[:500],
                "category": category
            })

    return items


def generate_holistic_suggestion(merged: dict) -> dict:
    """从整体汇总角度生成持卡建议（使用 LLM）"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "card-holding-suggestion" / "scripts"))
        from scorer import load_config, CONFIG_FILE, DEFAULT_API_BASE, DEFAULT_MODEL

        # 汇总所有内容（使用层级结构）
        full_text_parts = []
        for h1 in merged.get("h1_sections", []):
            full_text_parts.append(f"【{h1['title']}】")
            for h2 in h1.get("h2_items", []):
                full_text_parts.append(f"  {h2['title']}")
                full_text_parts.extend(h2.get("content", [])[:5])
        full_text = "\n".join(full_text_parts)

        if len(full_text) < 50:
            return {"overall": None, "items": [], "error": "内容过少，无法生成建议"}

        # 尝试 LLM 整体分析
        cfg = load_config()
        api_key = cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
        api_base = cfg.get("api_base") or os.environ.get("LLM_API_BASE", DEFAULT_API_BASE)
        model = cfg.get("model") or os.environ.get("LLM_MODEL", DEFAULT_MODEL)

        # 如果可用，补充 RAG 检索上下文以提高建议准确性
        rag_context = None
        try:
            import rag_query
            entries = rag_query.load_kb()
            bm25 = rag_query.build_or_load_bm25(entries)
            scores = bm25.search(full_text, top_k=3)
            if scores:
                _, _, sources = rag_query.build_prompt(full_text[:200], entries, scores)
                # sources 为列表，build_prompt 返回 (system_msg, user_msg, sources)
                rag_context = sources
        except Exception as e:
            print(f"  [Warn] RAG query failed (proceeding without RAG context): {e}")
            rag_context = None

        if api_key:
            prompt = f"""你是一个专业的信用卡分析师。请基于以下信用卡资讯汇总，从持卡人角度给出综合分析和建议。

【本期资讯汇总】
{full_text[:3000]}

【参考知识库检索（RAG）】
{json.dumps(rag_context, ensure_ascii=False) if rag_context else '无'}

### 分析要求：
1. 识别本期最重要的3-5条资讯（对持卡人影响最大的）
2. 从持卡人角度给出综合建议：
   - 哪些活动值得参与？为什么？
   - 哪些卡片值得关注/办理？
   - 有哪些风险需要注意？
   - 整体用卡策略建议
3. 按银行分类给出建议（如有明显差异）

### 输出格式（严格 JSON）：
```json
{{
  "highlights": [
    {{"title": "重要资讯标题", "bank": "银行", "reason": "重要性说明"}}
  ],
  "action_items": [
    {{"action": "建议动作", "priority": "高/中/低", "detail": "具体说明"}}
  ],
  "risk_warnings": ["风险提示1", "风险提示2"],
  "overall_strategy": "整体用卡策略建议（100字内）",
  "bank_summary": {{
    "银行名": "该银行本期要点总结"
  }}
}}
```"""

            import requests as req
            resp = req.post(
                f"{api_base.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=90,
            )
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"]

            # 解析 JSON
            import re
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", reply, re.DOTALL)
            json_text = m.group(1) if m else reply

            # 尝试多种方式解析 JSON
            overall = None

            # 方式1：直接解析
            try:
                overall = json.loads(json_text.strip())
            except json.JSONDecodeError:
                pass

            # 方式2：提取第一个完整的 JSON 对象
            if not overall:
                m2 = re.search(r"\{[\s\S]*\}", json_text)
                if m2:
                    try:
                        overall = json.loads(m2.group())
                    except json.JSONDecodeError:
                        # 尝试修复常见问题（尾部逗号等）
                        fixed = re.sub(r',\s*([}\]])', r'\1', m2.group())
                        try:
                            overall = json.loads(fixed)
                        except json.JSONDecodeError:
                            pass

            if overall:
                return {"overall": overall, "items": [], "generated_at": datetime.now().isoformat(), "scorer": "llm"}

        # 降级：关键词整体分析
        return _keyword_holistic_suggestion(full_text)

    except Exception as e:
        print(f"  [警告] LLM整体分析失败: {e}")
        return _keyword_holistic_suggestion("") if not full_text else {"overall": None, "items": [], "error": str(e)}


def _keyword_holistic_suggestion(full_text: str) -> dict:
    """关键词降级的整体分析"""
    highlights = []
    action_items = []
    risk_warnings = []

    # 简单关键词匹配
    if "免年费" in full_text:
        action_items.append({"action": "关注免年费卡", "priority": "高", "detail": "有多款免年费卡可选"})
    if "返现" in full_text:
        action_items.append({"action": "参与返现活动", "priority": "中", "detail": "多个返现活动进行中"})
    if "缩水" in full_text or "取消" in full_text:
        risk_warnings.append("部分权益有缩水风险，请关注")
    if "升级" in full_text or "新增" in full_text:
        highlights.append({"title": "权益升级资讯", "bank": "多银行", "reason": "有新增或升级的权益"})

    overall = {
        "highlights": highlights[:5],
        "action_items": action_items[:5],
        "risk_warnings": risk_warnings[:3],
        "overall_strategy": "建议关注本期免年费卡和返现活动，注意权益变更风险。",
        "bank_summary": {}
    }
    return {"overall": overall, "items": [], "generated_at": datetime.now().isoformat(), "scorer": "keyword"}


def generate_suggestions(items: list) -> dict:
    """生成逐条建议（保留作为补充数据）"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "card-holding-suggestion" / "scripts"))
        from scorer import score_with_llm, score_with_keywords, _activity_dimensions, DIMENSION_TEMPLATES

        results = []
        for item in items:
            category = item.get("category", "活动")
            dim_builder = DIMENSION_TEMPLATES.get(category, _activity_dimensions)
            dims = dim_builder()
            # 优先使用 LLM 评分
            score = score_with_llm(item)
            results.append({
                "title": item["title"],
                "bank": item.get("bank", ""),
                "score": score.overall_score,
                "roi": score.overall_roi,
                "recommendation": score.recommendation,
                "summary": score.summary
            })

        return {"items": results, "generated_at": datetime.now().isoformat()}

    except Exception as e:
        print(f"  [Error] Suggestion generation failed: {e}")
        return {"items": [], "error": str(e)}


def create_merged_docx(merged: dict, suggestions: dict, output_path: str):
    """生成整合后的Word文档，保留层级结构和图片"""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from io import BytesIO

        doc = Document()

        # 设置默认字体
        style = doc.styles['Normal']
        style.font.name = 'Microsoft YaHei'
        style.font.size = Pt(10.5)

        # 标题
        title = doc.add_heading(merged["title"], level=0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # 生成信息
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = sub.add_run(f'生成时间: {datetime.now().strftime("%Y年%m月%d日 %H:%M")}')
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        # 数据来源
        if merged.get("sources"):
            src_para = doc.add_paragraph()
            src_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            src_run = src_para.add_run(f'整合来源: {", ".join(merged["sources"])}')
            src_run.font.size = Pt(9)
            src_run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        doc.add_paragraph()

        # 目录（带层级）
        doc.add_heading('目录', level=1)
        h1_sections = merged.get("h1_sections", [])
        for i, h1 in enumerate(h1_sections, 1):
            doc.add_paragraph(f'{i}. {h1["title"]}')
            for j, h2 in enumerate(h1.get("h2_items", [])[:5], 1):
                doc.add_paragraph(f'   {i}.{j} {h2["title"]}')
        if suggestions.get("overall"):
            doc.add_paragraph(f'{len(h1_sections)+1}. 持卡用卡建议')

        doc.add_paragraph()

        # 内容详情（带层级和图片）
        doc.add_heading('内容详情', level=1)
        all_images = merged.get("all_images", {})

        for h1 in h1_sections:
            doc.add_heading(h1["title"], level=2)

            # h1 级别的说明内容
            for line in h1.get("content", [])[:5]:
                if line.strip():
                    doc.add_paragraph(line)

            # h2 级别的具体条目
            for h2 in h1.get("h2_items", []):
                doc.add_heading(h2["title"], level=3)

                # 条目内容
                for line in h2.get("content", [])[:15]:
                    if line.strip():
                        doc.add_paragraph(line)

                # 插入该条目的图片
                for img_rid in h2.get("images", []):
                    img_data = all_images.get(img_rid)
                    if img_data:
                        try:
                            from io import BytesIO
                            from PIL import Image as PILImage

                            img_stream = BytesIO(img_data)
                            pil_img = PILImage.open(img_stream)
                            img_width, img_height = pil_img.size

                            # 计算合适的插入尺寸（最大宽度：来自 IMAGE_WIDTH_CM 常量，保持比例）
                            max_width_inches = IMAGE_WIDTH_CM / 2.54
                            max_height_inches = 4.0
                            dpi = 96  # 标准 DPI

                            width_inches = img_width / dpi
                            height_inches = img_height / dpi

                            # 按宽度限制缩放
                            if width_inches > max_width_inches:
                                scale = max_width_inches / width_inches
                                width_inches = max_width_inches
                                height_inches = height_inches * scale

                            # 按高度限制缩放（防止纵向图片过高）
                            if height_inches > max_height_inches:
                                scale = max_height_inches / height_inches
                                height_inches = max_height_inches
                                width_inches = width_inches * scale

                            img_stream.seek(0)
                            para = doc.add_paragraph()
                            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            run = para.add_run()
                            run.add_picture(img_stream, width=Inches(width_inches), height=Inches(height_inches))

                        except Exception:
                            pass  # 图片插入失败不影响文档生成

        # 持卡建议（整体分析）
        overall = suggestions.get("overall")
        if overall:
            doc.add_paragraph()
            doc.add_heading('持卡用卡建议', level=1)

            # 重点资讯
            highlights = overall.get("highlights", [])
            if highlights:
                doc.add_heading('重点关注', level=2)
                for h in highlights:
                    p = doc.add_paragraph()
                    run = p.add_run(f'[{h.get("bank", "")}] {h.get("title", "")}')
                    run.bold = True
                    if h.get("reason"):
                        doc.add_paragraph(f'  原因: {h["reason"]}')

            # 建议动作
            actions = overall.get("action_items", [])
            if actions:
                doc.add_heading('建议动作', level=2)
                for a in actions:
                    p = doc.add_paragraph()
                    priority = a.get("priority", "中")
                    priority_mark = {"高": "!!!", "中": "!!", "低": "!"}.get(priority, "")
                    run = p.add_run(f'[{priority}{priority_mark}] {a.get("action", "")}')
                    run.bold = priority == "高"
                    if a.get("detail"):
                        doc.add_paragraph(f'  {a["detail"]}')

            # 风险提示
            risks = overall.get("risk_warnings", [])
            if risks:
                doc.add_heading('风险提示', level=2)
                for r in risks:
                    doc.add_paragraph(f'  - {r}')

            # 整体策略
            strategy = overall.get("overall_strategy", "")
            if strategy:
                doc.add_heading('整体策略', level=2)
                doc.add_paragraph(strategy)

            # 银行小结
            bank_summary = overall.get("bank_summary", {})
            if bank_summary:
                doc.add_heading('各银行要点', level=2)
                for bank, summary in bank_summary.items():
                    p = doc.add_paragraph()
                    run = p.add_run(f'{bank}: ')
                    run.bold = True
                    p.add_run(summary)

        # 保存
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        doc.save(output_path)
        return True

    except Exception as e:
        print(f"  [Failed] Generation failed: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='多Word文档整合')
    parser.add_argument('--input', nargs='+', required=True, help='输入docx文件列表')
    parser.add_argument('--output', default='', help='输出文件路径')

    args = parser.parse_args()

    print("="*60)
    print("  Multi-Document Merge + Card Holding Suggestions")
    print("="*60)

    # 1. Read all documents
    print("\n[Read Documents]")
    contents = []
    for path in args.input:
        content = read_docx_content(path)
        h1_count = len(content.get('h1_sections', []))
        h2_count = sum(len(s.get('h2_items', [])) for s in content.get('h1_sections', []))
        img_count = len(content.get('images_map', {}))
        contents.append(content)
        print(f"  OK {Path(path).name}: {h1_count} categories, {h2_count} items, {img_count} images")

    # 2. Merge
    print("\n[Merge] Merging content...")
    merged = merge_contents(contents)
    h1_count = len(merged.get('h1_sections', []))
    h2_count = sum(len(s.get('h2_items', [])) for s in merged.get('h1_sections', []))
    print(f"  Merged: {h1_count} categories, {h2_count} items")

    # 3. Extract items
    items = extract_items_for_analysis(merged)
    print(f"  Extracted: {len(items)} items")

    # 4. Generate holistic suggestions (priority) + per-item suggestions (supplement)
    print("\n[Analyze] Generating suggestions...")
    holistic = generate_holistic_suggestion(merged)
    print(f"  Holistic analysis: {'Success' if holistic.get('overall') else 'Fallback'}")

    # Per-item suggestions as supplement (optional, skip for speed)
    # suggestions = generate_suggestions(items)
    suggestions = {"items": [], "overall": holistic.get("overall")}
    print(f"  Analysis complete")

    # 5. Output file
    if not args.output:
        week_label = f"{datetime.now().year}年{datetime.now().month}月第{(datetime.now().day + datetime.now().replace(day=1).weekday()) // 7 + 1}周"
        args.output = str(PROJECT_ROOT / "data" / f"Merged_Report_{week_label}.docx")

    print(f"\n[Generate] Generating document: {Path(args.output).name}")
    success = create_merged_docx(merged, suggestions, args.output)

    if success:
        print(f"\n[Success] Merge complete: {args.output}")

        # Also output JSON data
        json_output = args.output.replace('.docx', '.json')
        # Build hierarchy summary (without full content and image data)
        hierarchy = []
        for h1 in merged.get("h1_sections", []):
            h1_data = {"title": h1["title"], "h2_items": []}
            for h2 in h1.get("h2_items", []):
                h1_data["h2_items"].append({
                    "title": h2["title"],
                    "content_preview": h2.get("content", [])[:2],
                    "image_count": len(h2.get("images", []))
                })
            hierarchy.append(h1_data)

        with open(json_output, 'w', encoding='utf-8') as f:
            json.dump({
                "merged": {
                    "title": merged["title"],
                    "sources": merged["sources"],
                    "hierarchy": hierarchy
                },
                "suggestions": suggestions
            }, f, ensure_ascii=False, indent=2)
        print(f"[Data] JSON file: {Path(json_output).name}")
    else:
        print("\n[Failed] Merge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
