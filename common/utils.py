"""
通用工具函数

注意：图片相关功能已迁移到 common.images，此处仅保留向后兼容的 re-export。
新代码请直接从 common.images 导入。
"""

from datetime import datetime
import hashlib
import os
import re
from typing import Optional
from urllib.parse import urlparse

import requests

from .config import DEFAULT_IMAGES_DIR
from common.images import get_central_image_dir, download_image_from_url, copy_to_central_image_dir, centralize_images


def safe_truncate(text: str, max_chars: int = 500) -> str:
    """按句子边界截断文本，避免在词中间截断。"""
    if not text or len(text) <= max_chars:
        return text
    # 优先在句号/感叹号/问号处截断
    candidates = []
    for sep in ['。', '！', '？', '\n']:
        idx = text.rfind(sep, 0, max_chars)
        if idx > max_chars * 0.5:
            candidates.append((idx + 1, sep))
    if not candidates:
        # 退到空格截断
        idx = text.rfind(' ', 0, max_chars)
        return text[:idx] + '…' if idx > 10 else text[:max_chars] + '…'
    # 选最接近 max_chars 的切分点
    best = max(candidates, key=lambda x: x[0])
    return text[:best[0]]


def get_week_label(dt: datetime = None) -> str:
    """生成周报标签，如 '2026年5月第4周'。"""
    dt = dt or datetime.now()
    year = dt.year
    month = dt.month
    first_day = dt.replace(day=1)
    week_num = (dt.day + first_day.weekday()) // 7 + 1
    return f"{year}年{month}月第{week_num}周"


def extract_bank_name(title: str, text: str = "") -> str:
    """尝试从标题/正文中提取银行名称，未知返回空串。

    委托给 entity_resolver.resolve_bank 以避免两套银行识别逻辑。
    """
    from .entity_resolver import resolve_bank
    result = resolve_bank(title=title, text=text)
    return result["bank"] if result["bank"] != "未知" else ""


def safe_save_text(filepath: str, content: str) -> str:
    """安全写入文本文件。返回绝对路径。"""
    abs_path = os.path.abspath(filepath)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return abs_path


# 从 common.images 导入（避免函数重复定义）
from common.images import ensure_dir


# ── 向后兼容：图片功能已迁移到 common.images ──
# 以下 re-export 供旧 import 语句使用
# 新代码请直接 from common.images import ...
