"""
图片生命周期管理 — 统一管理图片的下载、存储、过滤、去重。

消除 utils.py 分散的图片工具函数 与 src/agent.py 的过滤逻辑。

功能：
    1. 下载图片到集中目录 data/images/{item_id}/
    2. 复制本地图片到集中目录
    3. 批量集中管理（自动判断 URL/本地路径）
    4. 过滤无意义装饰图片（文件大小、尺寸、像素方差）
    5. 按内容哈希去重

用法：
    from common.images import (
        get_central_image_dir,
        centralize_images,
        filter_meaningful_images,
        deduplicate_images,
        image_hash,
    )
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional
from urllib.parse import urlparse

import requests

from .config import DEFAULT_IMAGES_DIR


# ── 目录管理 ─────────────────────────────────────────

def ensure_dir(path: str) -> str:
    """确保目录存在。返回绝对路径。"""
    abs_path = os.path.abspath(path)
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


def get_central_image_dir(item_id: str) -> str:
    """返回某个 item 的集中图片存储目录 data/images/{item_id}/。"""
    d = os.path.join(str(DEFAULT_IMAGES_DIR), item_id)
    ensure_dir(d)
    return d


# ── 下载 & 复制 ──────────────────────────────────────

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
        print(f"[图片] 下载失败 {img_url}: {e}", file=__import__('sys').stderr)
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
        print(f"[图片] 复制失败 {src_path}: {e}", file=__import__('sys').stderr)
        return None


# ── 批量集中管理 ────────────────────────────────────────

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


# ── 按内容哈希去重 ─────────────────────────────────────

def image_hash(filepath: str) -> Optional[str]:
    """计算图片文件的 SHA-256 内容哈希。

    Returns:
        十六进制哈希字符串，无法读取时返回 None
    """
    try:
        if not os.path.isfile(filepath):
            return None
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            # 只需读前 64KB + 尾部 4KB（大多数图片差异在文件头/尾）
            head = f.read(65536)
            h.update(head)
            f.seek(-4096, os.SEEK_END)
            tail = f.read(4096)
            h.update(tail)
        return h.hexdigest()
    except Exception:
        return None


def deduplicate_images(image_paths: list[str]) -> list[str]:
    """按内容哈希去重，相同内容的图片只保留第一个。

    使用 SHA-256 快速哈希（前 64KB + 尾部 4KB），
    兼顾速度和区分度。

    Args:
        image_paths: 图片路径列表

    Returns:
        去重后的图片路径列表
    """
    seen: set[str] = set()
    result: list[str] = []
    for p in image_paths:
        h = image_hash(p)
        if h is None:
            result.append(p)  # 无法读取时保守保留
        elif h not in seen:
            seen.add(h)
            result.append(p)
    return result


# ── 无意义装饰图过滤 ──────────────────────────────────

def filter_meaningful_images(image_paths: list[str]) -> list[str]:
    """过滤无意义装饰图片，保留有实质内容的图片。

    过滤规则（满足任一即跳过）：
    1. 文件 < 5KB（图标/占位图）
    2. 宽高都 < 50px（小图标）
    3. 任一方 < 30px（极窄装饰条/分割线）
    4. 像素标准差 < 8（纯色/简单渐变，无文字内容）

    Args:
        image_paths: 图片路径列表（本地路径或 HTTP URL）

    Returns:
        过滤后的图片列表，至少保留一张
    """
    if not image_paths:
        return []

    # 检查 PIL 是否可用
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return image_paths  # 没有 PIL 就全部保留

    meaningful = []
    for img_path in image_paths:
        try:
            # 远程 URL 暂不处理（后续下载时再过滤）
            if img_path.startswith("http://") or img_path.startswith("https://"):
                meaningful.append(img_path)
                continue

            if not os.path.exists(img_path):
                continue

            # 1. 文件大小过滤
            if os.path.getsize(img_path) < 5 * 1024:
                continue

            # 2-3. 尺寸过滤
            img = Image.open(img_path)
            w, h = img.size
            if w < 30 or h < 30:
                continue
            if w < 50 and h < 50:
                continue

            # 4. 像素方差过滤（转为灰度，缩到 64x64 加速）
            gray = img.convert("L")
            gray.thumbnail((64, 64))
            stat = ImageStat.Stat(gray)
            std = stat.stddev[0]  # 灰度图只有一个通道

            if std < 8:
                continue  # 低方差 = 几乎纯色 = 装饰图

            meaningful.append(img_path)
        except Exception:
            # 无法处理的图片保留
            meaningful.append(img_path)

    # 至少保留一张图，避免文章完全无图
    return meaningful if meaningful else (image_paths[:1] if image_paths else [])
