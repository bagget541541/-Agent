"""word-merger 公共工具：共享常量、docx 延迟导入缓存、文本截断等。"""
from functools import lru_cache
import sys
import json


IMAGE_WIDTH_CM = 13


@lru_cache(maxsize=1)
def setup_docx_cached():
    """延迟并缓存 python-docx 的导入，返回与原 setup_docx() 一致的元组。

    适用于多处多次调用 setup_docx() 的场景，减少重复导入开销。
    """
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        return (Document, Pt, RGBColor, Inches, Cm,
                WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement)
    except ImportError:
        msg = json.dumps({"error": "python-docx 未安装，请运行: pip install python-docx"}, ensure_ascii=False)
        print(msg)
        sys.exit(1)


def safe_truncate(text: str, max_chars: int = 30) -> str:
    """安全截断字符串（按字符），尾部添加省略号并去除尾部空白。"""
    if not text:
        return ''
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + '…'
