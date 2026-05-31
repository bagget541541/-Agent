"""
通用工具函数
"""

from datetime import datetime
import hashlib
import os
import re
from typing import Optional
from urllib.parse import urlparse

import requests

from .config import DEFAULT_IMAGES_DIR


def get_week_label(dt: datetime = None) -> str:
    """生成周报标签，如 '2026年5月第4周'。"""
    dt = dt or datetime.now()
    year = dt.year
    month = dt.month
    first_day = dt.replace(day=1)
    week_num = (dt.day + first_day.weekday()) // 7 + 1
    return f"{year}年{month}月第{week_num}周"


def extract_bank_name(title: str, text: str = "") -> str:
    """尝试从标题/正文中提取银行名称。

    常见银行关键词匹配，返回首个匹配到的银行名，未知返回空串。
    """
    banks = [
        "工商银行", "农业银行", "中国银行", "建设银行", "交通银行",
        "招商银行", "中信银行", "浦发银行", "民生银行", "兴业银行",
        "光大银行", "华夏银行", "广发银行", "平安银行", "邮储银行",
        "北京银行", "上海银行", "宁波银行", "南京银行",
        "花旗银行", "汇丰银行", "渣打银行",
        "工行", "农行", "中行", "建行", "交行",
        "招行", "中信", "浦发", "民生", "兴业",
        "光大", "华夏", "广发", "平安", "邮储",
        "北京银行", "上海银行",
    ]
    full_text = f"{title} {text}"
    for bank in banks:
        if bank in full_text:
            return bank
    # 二次尝试：正则匹配 "XX银行"
    m = re.search(r"([\u4e00-\u9fa5]{2,4}银行)", full_text)
    return m.group(1) if m else ""


def safe_save_text(filepath: str, content: str) -> str:
    """安全写入文本文件。返回绝对路径。"""
    abs_path = os.path.abspath(filepath)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return abs_path


def ensure_dir(path: str) -> str:
    """确保目录存在。返回绝对路径。"""
    abs_path = os.path.abspath(path)
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


# ── 图片集中存储工具（Route B） ──────────────────────────

def get_central_image_dir(item_id: str) -> str:
    """返回某个 item 的集中图片存储目录 data/images/{item_id}/。"""
    d = os.path.join(str(DEFAULT_IMAGES_DIR), item_id)
    ensure_dir(d)
    return d


def download_image_from_url(img_url: str, item_id: str) -> Optional[str]:
    """从 URL 下载图片到 data/images/{item_id}/，返回本地绝对路径。

    Args:
        img_url: 图片 URL
        item_id: 所属 CreditCardItem 的 item_id

    Returns:
        str: 本地文件绝对路径，失败返回 None
    """
    try:
        save_dir = get_central_image_dir(item_id)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(img_url, headers=headers, timeout=30)
        resp.raise_for_status()

        url_hash = hashlib.md5(img_url.encode('utf-8')).hexdigest()
        ext = os.path.splitext(urlparse(img_url).path)[1] or '.jpg'
        filename = f"{url_hash}{ext}"
        filepath = os.path.join(save_dir, filename)

        with open(filepath, 'wb') as f:
            f.write(resp.content)

        return os.path.abspath(filepath)
    except Exception as e:
        print(f"[图片工具] 下载失败 {img_url}: {e}", file=__import__('sys').stderr)
        return None


def copy_to_central_image_dir(src_path: str, item_id: str) -> Optional[str]:
    """将已有本地图片复制到 data/images/{item_id}/，返回新路径。

    Args:
        src_path: 源图片本地路径
        item_id: 所属 CreditCardItem 的 item_id

    Returns:
        str: 新文件绝对路径，失败返回 None
    """
    try:
        if not os.path.isfile(src_path):
            return None
        save_dir = get_central_image_dir(item_id)
        basename = os.path.basename(src_path)
        dest = os.path.join(save_dir, basename)
        # 避免重名覆盖
        if os.path.exists(dest):
            root, ext = os.path.splitext(basename)
            dest = os.path.join(save_dir, f"{root}_{item_id[:8]}{ext}")
        import shutil
        shutil.copy2(src_path, dest)
        return os.path.abspath(dest)
    except Exception as e:
        print(f"[图片工具] 复制失败 {src_path}: {e}", file=__import__('sys').stderr)
        return None


def centralize_images(images: list, item_id: str) -> list:
    """将图片列表全部集中到 data/images/{item_id}/，返回更新后的路径列表。

    自动判断输入是 URL 还是本地路径：
      - 以 http:// 或 https:// 开头 → 下载
      - 否则 → 复制

    Args:
        images: 原始图片路径/URL 列表
        item_id: 所属 item 的 item_id

    Returns:
        list[str]: 集中后的本地绝对路径列表
    """
    new_paths = []
    for img in images:
        if not img:
            continue
        img = str(img).strip()
        if img.startswith(('http://', 'https://')):
            local = download_image_from_url(img, item_id)
            if local:
                new_paths.append(local)
        else:
            local = copy_to_central_image_dir(img, item_id)
            if local:
                new_paths.append(local)
    return new_paths
