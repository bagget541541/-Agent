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
import re
import sys
import hashlib
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

from common.config import KNOWN_FIELD_NAMES


def _detect_parse_mode(doc) -> str:
    """
    自动检测文档解析模式

    Returns:
        "standard" — Heading 1/2 层级清晰，原逻辑不变
        "announcement" — 只有 Heading 2 无 H1，公告模式
        "field" — 无 Heading，字段加粗占比 > 20%，字段模式
    """
    h1_count = 0
    h2_count = 0
    bold_field_count = 0
    total_para_count = 0

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        total_para_count += 1
        style = para.style.name

        if style == 'Heading 1':
            h1_count += 1
        elif style == 'Heading 2':
            h2_count += 1

        # 检测段落是否以加粗字段名开头
        if para.runs:
            first_run = para.runs[0]
            if first_run.bold and first_run.text.strip():
                for field in KNOWN_FIELD_NAMES:
                    if text.startswith(field + '：') or text.startswith(field + ':'):
                        bold_field_count += 1
                        break

    # 模式切换逻辑
    if h1_count == 0 and h2_count > 0:
        return "announcement"

    if total_para_count > 0 and bold_field_count / total_para_count > 0.2:
        return "field"

    return "standard"


def _parse_announcement_mode(doc, docx_path, images_map, ns) -> dict:
    """公告模式：无 H1，只有 H2 → 自动创建 H1 容器"""
    content = {
        "file": docx_path,
        "title": "",
        "h1_sections": [],
        "full_text": ""
    }

    # 自动创建"银行公告"作为 H1
    current_h1 = {
        "title": "银行公告",
        "h2_items": [],
        "content": []
    }
    content["h1_sections"].append(current_h1)
    current_h2 = None
    full_text_parts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        style = para.style.name

        # 检查段落中的图片
        drawings = para._element.findall('.//w:drawing', ns)
        para_images = []
        for d in drawings:
            blips = d.findall('.//a:blip', ns)
            for b in blips:
                rid = b.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if rid and rid in images_map:
                    para_images.append(rid)

        if not text and not para_images:
            continue

        if style == 'Heading 2':
            current_h2 = {
                "title": text,
                "content": [],
                "images": []
            }
            current_h1["h2_items"].append(current_h2)
        elif current_h2 is not None:
            if text:
                # 尝试从文本中识别银行名，替换 H1 标题
                bank_match = re.search(
                    r'(农行|工行|建行|招行|中行|交行|浦发|中信|光大|民生|华夏|'
                    r'兴业|广发|平安|邮储|北京银行|上海银行|南京银行|宁波银行|'
                    r'江苏银行|杭州银行|秦农银行|农商银行|徽商银行|浙商银行|'
                    r'渤海银行|恒丰银行|银行)',
                    text
                )
                if bank_match and current_h1["title"] == "银行公告":
                    bank_name = bank_match.group(1)
                    if bank_name != "银行":
                        current_h1["title"] = bank_name + "公告"
                current_h2["content"].append(text)
            current_h2["images"].extend(para_images)
        elif current_h1 is not None:
            if text:
                current_h1["content"].append(text)

        if text:
            full_text_parts.append(text)

    content["full_text"] = "\n".join(full_text_parts)
    content["images_map"] = images_map
    return content


def _parse_field_mode(doc, docx_path, images_map, ns) -> dict:
    """字段模式：解析 KNOWN_FIELD_NAMES 结构化字段"""
    content = {
        "file": docx_path,
        "title": "",
        "h1_sections": [],
        "full_text": ""
    }

    current_h1 = None
    current_h2 = None
    full_text_parts = []

    for para in doc.paragraphs:
        text = para.text.strip()

        # 检查图片
        drawings = para._element.findall('.//w:drawing', ns)
        para_images = []
        for d in drawings:
            blips = d.findall('.//a:blip', ns)
            for b in blips:
                rid = b.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if rid and rid in images_map:
                    para_images.append(rid)

        if not text and not para_images:
            continue

        # 检测字段名（优先用加粗检测，其次全文匹配）
        field_match = None
        first_run_bold = False

        if para.runs:
            first_run = para.runs[0]
            if first_run.bold and first_run.text.strip():
                first_run_bold = True
                first_text = first_run.text.strip()
                for field in KNOWN_FIELD_NAMES:
                    if first_text.startswith(field + '：') or first_text.startswith(field + ':'):
                        field_match = field
                        break

        # 全文兜底匹配
        if not field_match:
            for field in KNOWN_FIELD_NAMES:
                if text.startswith(field + '：') or text.startswith(field + ':'):
                    field_match = field
                    break

        if field_match:
            colon = '：' if '：' in text else ':'
            value = text.split(colon, 1)[1].strip()

            if field_match == '银行' or field_match == '发卡银行':
                # 创建 H1 容器，标题 = 银行名
                current_h1 = {
                    "title": value if value else "银行信息",
                    "h2_items": [],
                    "content": []
                }
                content["h1_sections"].append(current_h1)
                current_h2 = None
            elif field_match == '标题':
                # 创建 H2 条目
                current_h2 = {
                    "title": value if value else text,
                    "content": [],
                    "images": [],
                    "url": ""
                }
                if current_h1:
                    current_h1["h2_items"].append(current_h2)
                else:
                    # 无 H1 时创建默认容器
                    current_h1 = {
                        "title": "微信文章",
                        "h2_items": [],
                        "content": []
                    }
                    content["h1_sections"].append(current_h1)
                    current_h1["h2_items"].append(current_h2)
            elif field_match == '原文链接':
                if current_h2:
                    current_h2["url"] = value
                elif current_h1:
                    current_h1["content"].append(text)
            elif field_match in ('发布时间', '作者'):
                if current_h2:
                    if "metadata" not in current_h2:
                        current_h2["metadata"] = {}
                    current_h2["metadata"][field_match] = value
                elif current_h1:
                    current_h1["content"].append(text)
            else:
                # 其他字段：关键信息、点评、消息内容等 → 归入当前 H2 的 content
                if current_h2:
                    current_h2["content"].append(text)
                elif current_h1:
                    current_h1["content"].append(text)
        else:
            # 普通段落
            if current_h2:
                if text:
                    current_h2["content"].append(text)
                current_h2["images"].extend(para_images)
            elif current_h1:
                if text:
                    current_h1["content"].append(text)

        if text:
            full_text_parts.append(text)

    content["full_text"] = "\n".join(full_text_parts)
    content["images_map"] = images_map
    return content


def read_docx_content(docx_path: str) -> dict:
    """
    读取 Word 文档内容，自适应三种解析模式

    - standard: Heading 1/2 层级清晰（原逻辑不变）
    - announcement: 只有 H2 无 H1 → 自动创建 H1 容器
    - field: KNOWN_FIELD_NAMES 字段加粗 → 结构化解析

    Returns:
        包含层级章节的字典
    """
    try:
        from docx import Document

        doc = Document(docx_path)
        images_map = _extract_docx_images(docx_path)

        # XML 命名空间
        ns = {
            'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
            'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
            'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
            'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        }

        # 自动检测解析模式
        mode = _detect_parse_mode(doc)
        print(f"  [Parse Mode] {docx_path} → {mode}")

        if mode == "announcement":
            content = _parse_announcement_mode(doc, docx_path, images_map, ns)
        elif mode == "field":
            content = _parse_field_mode(doc, docx_path, images_map, ns)
        else:
            content = _parse_standard_mode(doc, docx_path, images_map, ns)

        return content

    except Exception as e:
        print(f"  [Error] Read failed {docx_path}: {e}")
        return {"file": docx_path, "title": Path(docx_path).stem, "h1_sections": [], "full_text": ""}


def _parse_standard_mode(doc, docx_path, images_map, ns) -> dict:
    """标准模式：原 Heading 1 → Heading 2 层级逻辑不变"""
    content = {
        "file": docx_path,
        "title": "",
        "h1_sections": [],
        "full_text": ""
    }

    full_text_parts = []
    current_h1 = None
    current_h2 = None

    for para in doc.paragraphs:
        text = para.text.strip()
        style = para.style.name

        # 检查段落中的图片
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
                "h2_items": [],
                "content": []
            }
            content["h1_sections"].append(current_h1)
            current_h2 = None
        # 识别 Heading 2
        elif style == 'Heading 2' and current_h1 is not None:
            current_h2 = {
                "title": text,
                "content": [],
                "images": []
            }
            current_h1["h2_items"].append(current_h2)
        # 普通段落或列表
        elif current_h2 is not None:
            if text:
                current_h2["content"].append(text)
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


def _extract_docx_images(docx_path: str) -> dict:
    """提取 docx 中的所有图片，按 byte 哈希去重，返回 {rId: bytes} 映射"""
    import zipfile
    from lxml import etree

    images = {}
    seen_hashes = set()
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

            # 提取图片文件，按 byte 哈希去重
            for rid, target in rid_to_target.items():
                img_path = f'word/{target}' if not target.startswith('/') else target[1:]
                try:
                    img_data = zf.read(img_path)
                    img_hash = hashlib.md5(img_data).hexdigest()
                    if img_hash not in seen_hashes:
                        seen_hashes.add(img_hash)
                        images[rid] = img_data
                    else:
                        # 重复图片，保留第一个出现的 rid 映射
                        for existing_rid, existing_data in images.items():
                            if hashlib.md5(existing_data).hexdigest() == img_hash:
                                # 建立别名映射 rId → 已有图片
                                images[rid] = existing_data
                                break
                except KeyError:
                    pass

    except Exception:
        pass

    return images


def _title_similarity(t1: str, t2: str) -> float:
    """
    计算两个标题的相似度（0.0 ~ 1.0），使用 Jaccard 字符二元组相似度

    阈值参考：同一银行同一条公告的标题相似度通常 ≥ 0.85
    """
    if not t1 or not t2:
        return 0.0
    # 提取非空格字符的二元组集合
    s1 = set(t1[i:i+2] for i in range(len(t1) - 1) if t1[i] != ' ')
    s2 = set(t2[i:i+2] for i in range(len(t2) - 1) if t2[i] != ' ')
    if not s1 or not s2:
        return 0.0
    intersection = s1 & s2
    union = s1 | s2
    return len(intersection) / len(union)


def merge_contents(contents: list) -> dict:
    """
    整合多个文档内容，保留层级结构，支持标题相似度去重

    去重策略（Phase 4）：
    - 两篇文章标题相似度 ≥ 0.85：保留内容更完整的一篇，丢弃重复
    - 同一银行 + 同一条公告：合并 key 信息，去除冗余
    """
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
            # 检查是否已存在同名或相似标题的 h1
            existing_h1 = None
            for s in merged["h1_sections"]:
                if s["title"] == h1["title"] or _title_similarity(s["title"], h1["title"]) >= 0.85:
                    existing_h1 = s
                    break

            if existing_h1:
                # 合并 h2 条目（带标题相似度去重）
                for new_h2 in h1.get("h2_items", []):
                    dup_h2 = None
                    for existing_h2 in existing_h1["h2_items"]:
                        if existing_h2["title"] == new_h2["title"] or _title_similarity(existing_h2["title"], new_h2["title"]) >= 0.85:
                            # 找到重复 H2，保留内容更完整的一篇
                            existing_len = len("\n".join(existing_h2.get("content", []))) + len(existing_h2.get("url", ""))
                            new_len = len("\n".join(new_h2.get("content", []))) + len(new_h2.get("url", ""))
                            if new_len > existing_len:
                                # 新条目内容更完整，替换
                                existing_h1["h2_items"].remove(existing_h2)
                                existing_h1["h2_items"].append(new_h2)
                            dup_h2 = True
                            break
                    if not dup_h2:
                        existing_h1["h2_items"].append(new_h2)
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
        # 同步设置东亚字体
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        rPr = style.element.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.insert(0, rFonts)
        rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

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
    parser.add_argument('--skip-analysis', action='store_true',
                        help='跳过持卡分析，仅输出结构化 JSON + Markdown')

    args = parser.parse_args()

    print("="*60)
    print("  Multi-Document Merge" + ("" if args.skip_analysis else " + Card Holding Suggestions"))
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

    if args.skip_analysis:
        # Phase 2: 跳过持卡分析，直接输出 JSON + MD
        print("\n[Skip Analysis] --skip-analysis 已启用，跳过持卡分析")

        if not args.output:
            week_label = f"{datetime.now().year}年{datetime.now().month}月第{(datetime.now().day + datetime.now().replace(day=1).weekday()) // 7 + 1}周"
            base_name = str(PROJECT_ROOT / "data" / f"Merged_Report_{week_label}")
        else:
            base_name = args.output.replace('.docx', '')

        # 输出 JSON（带完整结构化信息）
        hierarchy = []
        for h1 in merged.get("h1_sections", []):
            h1_data = {"title": h1["title"], "h2_items": []}
            for h2 in h1.get("h2_items", []):
                h1_data["h2_items"].append({
                    "title": h2["title"],
                    "content": h2.get("content", []),
                    "url": h2.get("url", ""),
                    "metadata": h2.get("metadata", {}),
                    "image_count": len(h2.get("images", []))
                })
            hierarchy.append(h1_data)

        json_output = base_name + ".json"
        with open(json_output, 'w', encoding='utf-8') as f:
            json.dump({
                "merged": {
                    "title": merged["title"],
                    "generated_at": merged["generated_at"],
                    "sources": merged["sources"],
                    "hierarchy": hierarchy,
                    "all_images": {k: f"[image {len(v)} bytes]" for k, v in merged.get("all_images", {}).items()}
                }
            }, f, ensure_ascii=False, indent=2)
        print(f"[Output] JSON: {Path(json_output).name}")

        # 输出 Markdown 预览
        md_output = base_name + ".md"
        with open(md_output, 'w', encoding='utf-8') as f:
            f.write(f"# {merged['title']}\n\n")
            f.write(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"**来源**: {', '.join(merged['sources'])}\n\n")
            f.write("---\n\n")
            for h1 in merged.get("h1_sections", []):
                f.write(f"## {h1['title']}\n\n")
                for line in h1.get("content", []):
                    if line.strip():
                        f.write(f"{line}\n\n")
                for h2 in h1.get("h2_items", []):
                    f.write(f"### {h2['title']}\n\n")
                    for line in h2.get("content", []):
                        if line.strip():
                            f.write(f"{line}\n\n")
                    if h2.get("url"):
                        f.write(f"🔗 原文链接: {h2['url']}\n\n")
                    for img_rid in h2.get("images", []):
                        f.write(f"![image](all_images/{img_rid})\n\n")
            f.write("---\n\n")
            f.write(f"*由 Credit Card Weekly Report - Mode B 生成*\n")
        print(f"[Output] Markdown: {Path(md_output).name}")
        print(f"\n[Success] Skip-analysis 完成，输出 JSON + MD")
        return True

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
