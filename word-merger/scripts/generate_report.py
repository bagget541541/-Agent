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

from common.utils import extract_bank_name
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


def _normalize_highlight_text(text: str) -> str:
    text = clean_xml_text(text or "")
    if not text:
        return ""

    text = re.sub(r"\[图片核心内容\s*-\s*[^\]]+\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    for prefix in [
        "尊敬的客户：", "尊敬的持卡人：", "附件：", "点击可查阅：",
        "一、活动时间", "二、活动对象", "三、活动内容", "四、活动细则",
    ]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    text = re.sub(r"^(关于)?启用新版", "启用新版", text)
    text = re.sub(r"^(关于)?新增", "新增", text)
    text = text.replace("特此公告。", "").strip()
    text = re.sub(r"\s+", " ", text).strip(" ：:;；，,。")
    return text


def _skip_intro_marketing(text: str) -> str:
    """跳过文章开头的广告/引言段落，定位到核心内容开始处。"""
    if not text:
        return text

    # 常见广告/引言关键词
    intro_kw = [
        '说在前头', '星标', '扫码', '可以扫码', '添加客服', '一手线报',
        '公众号推送机制改变', '推送机制改变', '★星标', '星标方法',
        '进群', '撸毛', '一起撸毛', '卡友交流群', '往期精彩',
    ]
    # 跳过以广告/引言开头的段落
    for kw in intro_kw:
        pos = text.find(kw)
        if 0 <= pos <= 50:  # 引言在开头 50 字内
            # 找到这段结束位置（下一个句号或换行）
            end = text.find('。', pos)
            if end > 0 and end < len(text) - 10:
                return _skip_intro_marketing(text[end + 1:].strip())
    return text


def _build_highlight(item: dict) -> str:
    title = clean_xml_text(item.get('title', '')).strip()
    bank = clean_xml_text(item.get('bank', '')).strip()
    cat = item.get('category', '')
    structured = item.get('structured', {}) or {}

    def _first_sentence(text: str) -> str:
        normalized = _normalize_highlight_text(text)
        if not normalized:
            return ''
        parts = re.split(r'[。！？!?；;]', normalized)
        for part in parts:
            part = part.strip(' ：:;；，,。')
            if len(part) >= 6:
                return part
        return normalized

    def _strip_marketing_tail(text: str) -> str:
        text = re.sub(r'珍藏周边礼等你领.*$', '', text).strip()
        text = re.sub(r'【[^】]+】$', '', text).strip()
        text = re.sub(r'\s+', '', text)
        return text

    def _extract_object_from_title(text: str) -> str:
        text = text.replace('关于', '').replace('的公告', '').replace('的通告', '').strip()
        m = re.search(r'《([^》]+)》', text)
        if m:
            obj = m.group(1)
            obj = obj.replace('广发银行信用卡中心', '')
            obj = obj.replace('招商银行股份有限公司信用卡中心', '')
            obj = obj.strip()
            return obj
        return text

    if cat == '新卡':
        detail = structured.get('详情', '')
        card_name = ''
        if 'Visa全球支付白金卡' in detail or 'Visa全球支付白金卡' in title:
            card_name = 'Visa全球支付白金卡'
        theme = '世界杯版' if ('世界杯版' in detail or '世界杯版' in title or '世界杯' in title) else ''
        if card_name:
            bank_prefix = '农行' if ('农业银行' in detail or '农行' in title or '农行' in bank) else bank.replace('未知公众号', '').replace('银行', '')
            summary = f'{bank_prefix}{card_name}{theme}首发'.strip()
            return safe_truncate(summary, 28)
        return safe_truncate(_strip_marketing_tail(title), 28)

    if cat == '权益变更':
        # P1-2: 优先使用 raw_title（含原始标题如"关于启用新版《敏感个人信息处理授权书》的通告"）
        raw_title = clean_xml_text(item.get('raw_title', '')).strip()
        source = structured.get('变更内容', '') or raw_title or title
        # 跳过广告/引言段落（说在前头、星标、扫码等）
        source = _skip_intro_marketing(source)
        summary = _first_sentence(source)
        # 如果摘要仍是广告/空，尝试在 text 中找变更关键词后的第一句
        if not summary or len(summary) < 6 or any(kw in summary for kw in ['说在前头', '星标', '扫码', '可以扫码']):
            fallback_text = source or raw_title or title
            # 找「下架」「调整」「变更」「取消」「新增」后的内容
            for kw in ['下架', '调整', '取消', '变更', '上线', '发布']:
                pos = fallback_text.find(kw)
                if pos >= 0:
                    summary = _first_sentence(fallback_text[pos:])
                    if summary and len(summary) >= 6:
                        break
        action = ''
        for kw in ['启用新版', '新增', '调整', '修订', '更新', '生效']:
            if kw in title or kw in summary or kw in raw_title:
                action = kw
                break
        # 优先从 raw_title 提取对象
        obj = _extract_object_from_title(raw_title or title)
        if action and obj:
            if obj.startswith(action):
                return safe_truncate(obj, 28)
            return safe_truncate(f'{action}{obj}', 28)
        if obj:
            return safe_truncate(obj, 28)
        return safe_truncate(summary, 28)

    if cat == '活动':
        cleaned_title = clean_xml_text(title).strip()
        if cleaned_title and not cleaned_title.startswith('一、'):
            return safe_truncate(cleaned_title, 28)
        source = structured.get('活动内容', '') or title
        return safe_truncate(_first_sentence(source), 28)

    if cat == '公告':
        return safe_truncate(_first_sentence(structured.get('消息内容', '') or title), 28)

    if cat == '其他':
        return safe_truncate(_first_sentence(structured.get('详细内容', '') or title), 28)

    return ''


def _resolve_highlight_source_name(item: dict) -> str:
    bank = clean_xml_text(item.get('bank', '')).strip()
    if bank and bank not in {'未知公众号', '未知', '公众号'}:
        return bank

    title = clean_xml_text(item.get('title', '')).strip()
    structured = item.get('structured', {}) or {}
    detail_text = ' '.join(str(v) for v in structured.values() if v)
    guessed = extract_bank_name(title, detail_text)
    if guessed:
        return guessed

    author = clean_xml_text(item.get('author', '')).strip()
    if author and author not in {'未知公众号', '未知', '公众号'}:
        return author
    return bank or author


def _normalize_detail_text(key: str, value: str, item: dict) -> str:
    text = clean_xml_text(value or '')
    if key != '详情' or not text:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful_lines = []
    inside_core_section = False
    for line in lines:
        # 跳过纯图描述（无信用卡信息）
        if line.startswith('[图片核心内容 - '):
            continue
        if '未包含任何信用卡相关信息' in line:
            continue
        if '仅显示一个用于申卡的微信二维码' in line:
            continue
        # P1-1: 识别新 OCR 结构化摘要格式
        # 进入「核心信用卡资讯」段后，只保留该段内容
        if '核心信用卡资讯' in line:
            inside_core_section = True
            continue
        if '补充说明' in line or 'image_description' in line.lower():
            inside_core_section = False
            continue
        if inside_core_section:
            useful_lines.append(line)
            continue
        # 旧格式：- 银行：- 卡种：
        if any(line.startswith(prefix) for prefix in ['- 银行：', '- 卡种：', '- 卡面级别：', '- 卡面主题：', '- 活动：', '- 合作：']):
            useful_lines.append(line.lstrip('- ').strip())
            continue
        # 新格式：1. 发卡银行：2. 卡种名称：3. 卡片级别：4. 卡面特色：5. 上线状态：
        if re.match(r'^\d+\.\s*(发卡银行|卡种名称|卡片级别|卡面特色|上线状态|年费信息|权益亮点)', line):
            # 去掉序号前缀
            cleaned = re.sub(r'^\d+\.\s*', '', line)
            useful_lines.append(cleaned)
            continue
        # 旧 fallback：首段无噪音文字
        if not useful_lines and len(line) >= 8 and '二维码' not in line:
            useful_lines.append(line)

    if useful_lines:
        return '；'.join(useful_lines[:6])
    return _normalize_highlight_text(text)


setup_docx = setup_docx_cached


# ── 样式工具 ────────────────────────────────────────────────


def set_run_font(run, name='Microsoft YaHei', size=None, color=None, bold=False):
    """统一设置 run 字体属性。"""
    Document, Pt, RGBColor, Inches, Cm, WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement = setup_docx()
    if size is None:
        size = Pt(10.5)
    run.font.name = name
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

    # ── 创建文档 ──────────────────────────────────────────
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Microsoft YaHei'
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

        highlight_idx += 1
        # P0-1: 优先消费标准化字段
        bank = it.get('source_name') or _resolve_highlight_source_name(it)
        summary = (
            it.get('highlight_summary')
            or it.get('display_title')
            or _build_highlight(it)
            or it.get('title', '')
        )
        # 对 highlight_summary / display_title 不再二次 safe_truncate
        # 仅对其他来源做长度保护
        if summary == it.get('title', ''):
            summary = safe_truncate(summary, 60)
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
        '其他':     [('详细内容', '详细内容')],
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
            structured = item.get('structured', {})
            images = item.get('images', [])

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
                    if key == '来源' and str(val).strip() in {'未知公众号', '未知', '公众号'}:
                        val = _resolve_highlight_source_name(item) or val
                    val = _normalize_detail_text(key, val, item)
                    p = doc.add_paragraph()
                    p.paragraph_format.space_after = Pt(2)
                    p.paragraph_format.space_before = Pt(1)
                    p.paragraph_format.first_line_indent = Cm(0)
                    label_run = p.add_run(clean_xml_text(f'{label_name}：'))
                    set_run_font(label_run, size=Pt(10.5), bold=True)
                    value_run = p.add_run(clean_xml_text(val))
                    set_run_font(value_run, size=Pt(10.5))
                doc.add_paragraph()  # 字段组后空行

            # ── 图片嵌入（插入在结构化字段与详细内容之间） ──
            if add_images and images:
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
