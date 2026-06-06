#!/usr/bin/env python3
"""
标准JSON → Word周报 生成脚本

从上游标准的 CreditCardBatch JSON 生成格式化 Word 文档 (.docx)，
适用于信用卡周报/月报场景。自动嵌入集中存储的图片。

数据流向：
  news-analyzer / wechat-article-extractor
    → 标准 JSON (含 data/images/{item_id}/ 图片路径)
    → generate_report.py
    → 信用卡周报.docx

用法：
    python scripts/generate_report.py --input data/batch_标准格式.json --output 周报.docx
    python scripts/generate_report.py --input data/batch.json --no-images  # 不嵌入图片
    python scripts/generate_report.py --input data/batch.json --output 周报.docx --title "2026年5月第2周周报"
"""

import json
import os
import sys
import re
import argparse
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils import setup_docx_cached, safe_truncate, IMAGE_WIDTH_CM


# ── 广告图过滤 ──────────────────────────────────────────────

def is_ad_image(img_path: str) -> bool:
    """判断图片是否为无价值广告图（关注引导、置顶操作、二维码横幅等）。

    过滤规则（满足任一即判定为广告图）：
      1. 文件极小（< 15KB）且短边 < 100px  → 分隔线/图标
      2. 宽高比 > 3.5                       → 超宽横幅广告条
      3. 宽高比 < 0.25                      → 极窄竖条装饰
      4. 短边 < 200px 且文件 < 50KB         → 微信操作引导小图

    Returns:
        True  → 广告图，跳过不插入 Word
        False → 正常内容图，保留
    """
    try:
        from PIL import Image
        size_kb = os.path.getsize(img_path) / 1024
        with Image.open(img_path) as im:
            w, h = im.size
        if w == 0 or h == 0:
            return True
        ratio = w / h
        short_side = min(w, h)
        # 规则 1：极小图
        if size_kb < 15 and short_side < 100:
            return True
        # 规则 2：超宽横幅
        if ratio > 3.5:
            return True
        # 规则 3：极窄竖条（宽度很小的装饰条，不是超长内容图）
        if ratio < 0.15 and w < 200:
            return True
        # 规则 4：微信操作引导小图
        if short_side < 200 and size_kb < 50:
            return True
        return False
    except Exception:
        # 无法读取时保守处理，不过滤
        return False


INVALID_XML_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')


def clean_xml_text(value):
    if value is None:
        return ''
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='ignore')
    elif not isinstance(value, str):
        value = str(value)
    return INVALID_XML_RE.sub('', value)


def sanitize_structure(value):
    if isinstance(value, dict):
        return {clean_xml_text(key): sanitize_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_structure(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_structure(item) for item in value]
    if isinstance(value, str):
        return clean_xml_text(value)
    return value


def build_report_title(items, batch_label: str = "") -> str:
    """根据批次内容自动生成更像“亮点摘要”的标题。"""
    if not isinstance(items, list):
        items = []

    priority_map = {"新卡": 0, "权益变更": 1, "活动": 2, "公告": 3}
    candidate_items = sorted(
        items,
        key=lambda item: (
            priority_map.get(item.get("category", ""), 9),
            -len(clean_xml_text(item.get("title", ""))),
        ),
    )

    titles = []
    for item in candidate_items:
        title = clean_xml_text(item.get("title", "")).strip()
        if not title:
            continue
        title = re.sub(r"[：:]\s*公告$", "", title).strip()
        if title not in titles:
            titles.append(title)
        if len(titles) >= 2:
            break

    base = clean_xml_text(batch_label).strip() or "信用卡资讯"
    if not titles:
        return f"{base}周报"
    if len(titles) == 1:
        return f"{base}亮点：{titles[0]}"
    return f"{base}亮点：{titles[0]}、{titles[1]}"


setup_docx = setup_docx_cached


# ── 样式工具 ────────────────────────────────────────────────


def set_run_font(run, name='Microsoft YaHei', size=None, color=None, bold=False):
    """统一设置 run 字体属性（含东亚字体）。"""
    Document, Pt, RGBColor, Inches, Cm, WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement = setup_docx()
    if size is None:
        size = Pt(10.5)
    run.font.name = name
    # 同步设置东亚字体
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:eastAsia'), name)
    run.font.size = size
    if color:
        run.font.color.rgb = color
    if bold:
        run.bold = True


def add_hr(doc):
    """添加浅灰水平分割线（用底部边框模拟）。"""
    Document, Pt, RGBColor, Inches, Cm, WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement = setup_docx()
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    for attr, val in [('w:val', 'single'), ('w:sz', '6'),
                      ('w:space', '1'), ('w:color', 'CCCCCC')]:
        bottom.set(qn(attr), val)
    pBdr.append(bottom)
    pPr.append(pBdr)


# ── 核心生成逻辑 ────────────────────────────────────────────


def generate_report(input_path: str, output_path: str,
                    add_images: bool = True, doc_title: str = '') -> dict:
    """读取标准 JSON，生成 Word 文档。"""
    (Document, Pt, RGBColor, Inches, Cm,
     WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement) = setup_docx()

    # ── 读取输入数据 ─────────────────────────────────────
    with open(input_path, 'r', encoding='utf-8') as f:
        batch = json.load(f)
    batch = sanitize_structure(batch)
    items = batch.get('items', [])
    batch_label = clean_xml_text(batch.get('batch_label', ''))

    def _normalize_structured(s: dict) -> dict:
        """把上游常见的结构化字段别名映射到下游期望的字段名，返回新字典。"""
        if not isinstance(s, dict):
            return s or {}
        alias = {
            '亮点': '卡亮点',
            '卡亮点': '卡亮点',
            '生效日期': '时间',
            '活动时间': '时间',
            '时间': '时间',
            '原文链接': '原文链接',
            '来源': '来源',
            '来源链接': '来源',
            '详情': '详情',
            '适用人群': '适用人群',
            '影响范围': '影响范围',
            '变更内容': '变更内容',
            '点评': '点评',
            '消息内容': '消息',
            '消息': '消息',
            '卡种': '卡种',
        }
        out = {}
        for k, v in s.items():
            nk = alias.get(k, k)
            # 如果目标键已存在，优先保留已有值（避免覆盖更精准字段）
            if nk in out and out[nk]:
                continue
            out[nk] = v
        return out

    # ── 创建文档 ──────────────────────────────────────────
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Microsoft YaHei'
    # 同步设置东亚字体
    _, _, _, _, _, _, _, qn, OxmlElement = setup_docx()
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    style.font.size = Pt(10.5)
    style.paragraph_format.line_spacing = 1.5

    # ============ 封面区 ============
    auto_title = clean_xml_text(doc_title) or build_report_title(items, batch_label)
    title = doc.add_heading(auto_title, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if batch_label:
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = sub.add_run(batch_label)
        r.font.size = Pt(16)
        r.font.color.rgb = RGBColor(0x33, 0x66, 0x99)

    doc.add_paragraph()  # 留白

    # ============ 目录（TOC 字段） ============
    doc.add_heading('目录', level=1)
    toc_para = doc.add_paragraph()
    toc_run = toc_para.add_run()
    # TOC 域代码：需要 Word 中按 Ctrl+A → F9 更新
    fld_begin = OxmlElement('w:fldChar')
    fld_begin.set(qn('w:fldCharType'), 'begin')
    toc_run._r.append(fld_begin)
    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    toc_run._r.append(instr)
    fld_sep = OxmlElement('w:fldChar')
    fld_sep.set(qn('w:fldCharType'), 'separate')
    toc_run._r.append(fld_sep)
    placeholder = toc_para.add_run(clean_xml_text('[请在 Word 中按 Ctrl+A → F9 更新目录]'))
    set_run_font(placeholder, size=Pt(9), color=RGBColor(0x99, 0x99, 0x99))
    fld_end = OxmlElement('w:fldChar')
    fld_end.set(qn('w:fldCharType'), 'end')
    toc_run._r.append(fld_end)
    doc.add_paragraph()  # 目录后留白

    # ============ 统计概览 ============
    cat_order = ['新卡', '权益变更', '活动', '公告', '其他']
    cat_counts = {c: 0 for c in cat_order}
    for it in items:
        c = it.get('category', '')
        if c in cat_counts:
            cat_counts[c] += 1

    doc.add_heading('内容概览', level=1)
    sp = doc.add_paragraph()
    parts = [f'{c}: {cat_counts[c]}条' for c in cat_order if cat_counts[c] > 0]
    sr = sp.add_run('  |  '.join(parts))
    set_run_font(sr, size=Pt(12), bold=True)

    tp2 = doc.add_paragraph(clean_xml_text(f'共 {len(items)} 条资讯'))
    tp2.paragraph_format.space_after = Pt(6)

    # ============ 本期亮点 ============
    doc.add_heading('本期亮点', level=1)
    highlight_idx = 0
    for it in items:
        # P0-3: 过滤广告/其他类 → 不进入亮点
        cat = it.get('category', '')
        if cat == '其他':
            continue
        hs = (it.get('highlight_summary', '') or '').strip()
        if '以上内容为广告' in hs:
            continue
        # P10: 跳过纯广告/空内容标记的条目
        noise_flags = it.get('noise_flags') or []
        if 'pure_ad_or_empty' in noise_flags:
            continue

        highlight_idx += 1
        # P0-1: 优先消费标准化字段
        bank = it.get('source_name') or it.get('bank', '')
        # 优先从 highlight_summary，其次按分类使用合适的结构化字段，再 fallback 到 display_title/title
        structured_for_highlight = _normalize_structured(it.get('structured') or {})
        summary = (
            it.get('highlight_summary')
            or (structured_for_highlight.get('变更内容') if cat == '权益变更' else None)
            or (structured_for_highlight.get('活动内容') if cat == '活动' else None)
            or it.get('display_title')
            or it.get('title', '')
        )
        # P16: 统一对 highlight_summary 做长度保护
        summary = safe_truncate(summary, 80)
        label = clean_xml_text(f'{bank} · {summary}') if bank else clean_xml_text(summary)
        p = doc.add_paragraph(f'{highlight_idx}. {label}')
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(0)

    # ============ 正文：按分类展示 ============
    cat_config = {
        '新卡':       ('🆕 新卡资讯', '新卡资讯'),
        '权益变更':   ('🔄 权益变更', '权益变更'),
        '活动':       ('🏷️ 优惠活动', '优惠活动'),
        '公告':       ('📢 重要公告', '重要公告'),
        '其他':       ('其他', '其他'),
    }
    structured_fields = {
        '新卡':     [('卡种', '卡种'), ('卡亮点', '亮点'), ('适用人群', '适用人群'),
                      ('来源', '来源'), ('详情', '详情')],
        '权益变更': [('消息时间', '时间'), ('影响范围', '影响范围'),
                      ('变更内容', '变更内容'), ('变更分析', '分析')],
        '活动':     [('活动内容', '活动内容'), ('活动时间', '时间'), ('适用人群', '适用人群')],
        '公告':     [('消息内容', '消息'), ('点评', '点评')],
        '其他':     [('消息内容', '消息内容'), ('详细内容', '详细内容')],
    }

    for cat in cat_order:
        cat_items = [it for it in items if it.get('category') == cat]
        if not cat_items:
            continue

        doc.add_page_break()
        heading_label, _ = cat_config.get(cat, (cat, cat))
        doc.add_heading(f'{heading_label}（共{len(cat_items)}条）', level=1)

        for idx, item in enumerate(cat_items, 1):
            bank = item.get('bank', '')
            # P0-2: 正文标题优先消费 display_title
            title_text = item.get('display_title') or item.get('title', '')
            url = item.get('url', '')
            raw_text = item.get('raw_text', '')
            structured = item.get('structured_clean') or item.get('structured', {})
            # 规范字段名别名，确保下游模板能匹配到常见上游键名
            structured = _normalize_structured(structured)
            # 缓存回 item，避免后续重复规范化
            item['structured_clean'] = structured
            images = item.get('images', [])

            # fallback: 如果 item['url'] 为空，尝试从 structured 中提升常见的原文链接字段
            if not url and isinstance(structured, dict):
                for candidate in ('原文链接', '原文链接：', '原文链接:', '来源', '来源链接', 'source', 'source_url'):
                    v = structured.get(candidate)
                    if v:
                        url = v
                        item['url'] = v
                        break

            # ── 条目标题 ──
            doc.add_heading(clean_xml_text(f'{idx}. {title_text}'), level=2)

            # ── 银行标签 ──
            if bank:
                bp = doc.add_paragraph()
                br = bp.add_run(clean_xml_text(f'【{bank}】'))
                set_run_font(br, size=Pt(10), color=RGBColor(0xCC, 0x66, 0x00), bold=True)
                bp.paragraph_format.space_after = Pt(2)

            # ── 来源链接 ──
            if url:
                up = doc.add_paragraph()
                ur = up.add_run(clean_xml_text(f'原文链接：{url}'))
                set_run_font(ur, size=Pt(8), color=RGBColor(0x66, 0x66, 0x66))
                up.paragraph_format.space_after = Pt(4)

            # ── 结构化字段（段落文字，取代表格） ──
            fields = structured_fields.get(cat, [])
            visible = [(k, lb) for k, lb in fields if structured.get(k)]
            if visible:
                for key, label_name in visible:
                    val = structured.get(key, '')
                    p = doc.add_paragraph()
                    p.paragraph_format.space_after = Pt(2)
                    p.paragraph_format.space_before = Pt(1)
                    p.paragraph_format.first_line_indent = Cm(0)
                    label_run = p.add_run(clean_xml_text(f'{label_name}：'))
                    set_run_font(label_run, size=Pt(10.5), bold=True)
                    value_run = p.add_run(clean_xml_text(val))
                    set_run_font(value_run, size=Pt(10.5))
                doc.add_paragraph()  # 字段组后空行
            elif raw_text:
                # 兜底：结构化字段无匹配时，直接渲染 raw_text
                for para_text in raw_text.split('\n'):
                    para_text = para_text.strip()
                    if not para_text:
                        continue
                    p = doc.add_paragraph()
                    p.paragraph_format.space_after = Pt(2)
                    p.paragraph_format.space_before = Pt(1)
                    run = p.add_run(clean_xml_text(para_text))
                    set_run_font(run, size=Pt(10.5))
                doc.add_paragraph()

            # ── 图片嵌入（插入在结构化字段与详细内容之间） ──
            if add_images and images:
                # 记录不存在的图片路径，便于排查（临时目录被清理或路径错误）
                missing_files = [p for p in images if not os.path.isfile(p)]
                if missing_files:
                    print(f"  [Warn] 图片文件不存在: {', '.join([os.path.basename(p) for p in missing_files])}")

                valid_images = [p for p in images if os.path.isfile(p) and not is_ad_image(p)]
                skipped = len(images) - len(valid_images)
                if valid_images:
                    for img_path in valid_images:
                        try:
                            doc.add_picture(img_path, width=Cm(IMAGE_WIDTH_CM))
                        except Exception:
                            ep = doc.add_paragraph(clean_xml_text(f'[图片加载失败: {os.path.basename(img_path)}]'))
                            ep.paragraph_format.space_after = Pt(2)
                    doc.add_paragraph()  # 图片后空行
                elif skipped > 0:
                    pass  # 全部被过滤，不输出

            # ── 条目分隔 ──
            if idx < len(cat_items):
                add_hr(doc)

    # ── 保存 ──
    doc.save(output_path)

    return {
        "success": True,
        "output": os.path.abspath(output_path),
        "total": len(items),
        "categories": {c: cat_counts[c] for c in cat_order},
    }


# ── CLI ─────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description='标准JSON → Word周报 生成')
    parser.add_argument('--input', required=True, help='标准格式 JSON 文件路径')
    parser.add_argument('--output', default='', help='输出 Word 文件路径（默认自动生成）')
    parser.add_argument('--no-images', action='store_true', help='不嵌入图片')
    parser.add_argument('--title', default='', help='文档标题（默认: 信用卡周报）')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(json.dumps({"error": f"输入文件不存在: {args.input}"}, ensure_ascii=False))
        sys.exit(1)

    output_path = args.output or f'信用卡周报_{datetime.now().strftime("%Y%m%d")}.docx'

    try:
        result = generate_report(args.input, output_path,
                                 add_images=not args.no_images,
                                 doc_title=args.title)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"生成失败: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
