"""
L1 直抓模块 — 微信公众号文章页面抓取与元数据解析

依据 doc/mode_c_公众号文章解析改进规范.md 第 7.6 / 7.7 节实现：
- 抓取策略：requests + UA，超时/重试/退避/大小限制/协议校验；
- URL 规范化与幂等：按 canonical_url / url_hash 缓存，重复抓取直接复用；
- 元数据解析：og:title、公众号名、发布时间、正文文本、data-src 图片地址；
- 页面结构变化时输出 FETCH_FAILED / NEEDS_REVIEW 诊断信息，不静默失败。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from common.config import DATA_DIR
from common.extraction import (
    build_content_block,
    canonicalize_url,
    extract_url_meta,
)

# ── HTTP 策略（规范 7.6） ────────────────────────────────
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://mp.weixin.qq.com/",
}

CONNECT_TIMEOUT = 15          # 连接超时（秒）
READ_TIMEOUT = 30             # 读取超时（秒）
MAX_RETRIES = 2               # 重试次数（不含首次）
RETRY_BACKOFF = [1.0, 3.0]    # 退避秒数（按重试次数索引）
MAX_RESPONSE_BYTES = 25 * 1024 * 1024   # 最大响应 25MB
ALLOWED_SCHEMES = {"http", "https"}

# 页面结构变化诊断（规范 7.6：结构变化时 FETCH_FAILED / NEEDS_REVIEW）
CACHE_DIR = DATA_DIR / "temp" / "wechat_fetch"


# ── 抓取结果结构 ─────────────────────────────────────────

def _empty_result(url: str, error: str = "", status: str = "FETCH_FAILED") -> dict:
    return {
        "url": url,
        "ok": False,
        "status": status,
        "error": error,
        "fetch_status": "failed",
        **extract_url_meta(url),
    }


# ── URL 安全校验（规范 7.6：限制协议/重定向目标） ────────

def validate_url(url: str) -> Optional[str]:
    """校验 URL 协议与格式，返回错误信息（None = 合法）。"""
    if not url or not url.strip():
        return "URL 为空"
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        return f"协议不允许: {parts.scheme!r}"
    if not parts.netloc:
        return "缺少主机名"
    return None


def is_safe_redirect(url: str) -> bool:
    """重定向目标是否安全（仅 http/https）。"""
    parts = urlsplit(url)
    return parts.scheme in ALLOWED_SCHEMES


# ── 主抓取函数 ───────────────────────────────────────────

def fetch_article_html(
    url: str,
    *,
    use_cache: bool = True,
    save_cache: bool = True,
    force_refresh: bool = False,
    max_retries: int = MAX_RETRIES,
    timeout: tuple = (CONNECT_TIMEOUT, READ_TIMEOUT),
) -> dict:
    """抓取微信文章页面 HTML。

    Args:
        url: 文章 URL
        use_cache: 命中缓存时直接复用（幂等）
        save_cache: 抓取成功后写入缓存
        force_refresh: 忽略缓存强制重新抓取
        max_retries: 最大重试次数
        timeout: (连接超时, 读取超时)

    Returns:
        {
          "ok": bool,
          "status": "ok" | "FETCH_FAILED",
          "error": "",
          "html": str,               # 原始 HTML（ok 时有）
          "fetch_status": "ok" | "failed",
          "fetched_at": str,         # ISO 时间
          "source_url"/"canonical_url"/"article_id"/"url_hash": ...,
        }
    """
    err = validate_url(url)
    if err:
        return _empty_result(url, error=f"URL 校验失败: {err}")
    meta = extract_url_meta(url)
    url_hash = meta["url_hash"]

    # 幂等：命中缓存
    cache_path = CACHE_DIR / f"{url_hash}.html"
    if use_cache and not force_refresh and cache_path.exists():
        try:
            html = cache_path.read_text(encoding="utf-8", errors="ignore")
            if html:
                return {
                    "ok": True,
                    "status": "ok",
                    "error": "",
                    "html": html,
                    "fetch_status": "ok",
                    "fetched_at": "cache",
                    "from_cache": True,
                    **meta,
                }
        except OSError:
            pass

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(
                url,
                headers=REQUEST_HEADERS,
                timeout=timeout,
                allow_redirects=True,
                stream=True,
            )
            # 重定向目标校验
            if resp.url and not is_safe_redirect(resp.url):
                return _empty_result(url, error=f"重定向到非 http(s) 目标: {resp.url[:80]}")
            resp.raise_for_status()

            # 响应大小限制
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                return _empty_result(url, error=f"响应过大: {content_length} bytes")

            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    return _empty_result(url, error=f"响应超过上限 {MAX_RESPONSE_BYTES} bytes")
                chunks.append(chunk)
            html_bytes = b"".join(chunks)

            # 编码处理：优先响应头 charset，其次 HTML meta，默认 utf-8
            encoding = resp.encoding or "utf-8"
            try:
                html = html_bytes.decode(encoding, errors="replace")
            except LookupError:
                html = html_bytes.decode("utf-8", errors="replace")

            if save_cache:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(html, encoding="utf-8")

            return {
                "ok": True,
                "status": "ok",
                "error": "",
                "html": html,
                "fetch_status": "ok",
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "from_cache": False,
                **meta,
            }
        except requests.exceptions.Timeout as e:
            last_error = f"timeout: {e}"
        except requests.exceptions.RequestException as e:
            last_error = f"request_error: {e}"
        except OSError as e:
            last_error = f"os_error: {e}"

        if attempt < max_retries:
            backoff = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            time.sleep(backoff)

    return _empty_result(url, error=last_error or "fetch failed")


# ── 元数据解析 ───────────────────────────────────────────

def parse_wechat_metadata(html: str) -> dict:
    """解析微信文章页面元数据。

    Returns:
        {
          "raw_title": str,       # og:title / h1 标题
          "publisher_name": str,  # 公众号名称
          "publish_time": str,    # 发布时间（尽力提取）
          "description": str,     # meta description
          "og_title": str,
          "content_text": str,    # js_content 可见文本（含图片 alt 噪音）
          "images": [str],        # data-src 图片 URL 列表
          "parse_notes": [str],   # 解析诊断（结构缺失等）
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    notes: list[str] = []

    # 标题：og:title > h1#activity-name > h1.rich_media_title
    og_title = ""
    og_meta = soup.find("meta", property="og:title")
    if og_meta:
        og_title = (og_meta.get("content") or "").strip()
    h1 = (
        soup.find("h1", id="activity-name")
        or soup.find("h1", class_="rich_media_title")
    )
    raw_title = (h1.get_text(strip=True) if h1 else "") or og_title

    # 公众号名：var nickname / strong#js_name / meta author
    publisher_name = ""
    nickname_m = re.search(r'var nickname\s*=\s*"([^"]+)"', html)
    if nickname_m:
        publisher_name = nickname_m.group(1).strip()
    if not publisher_name:
        name_el = soup.find("strong", id="js_name") or soup.find("a", id="js_name")
        if name_el:
            publisher_name = name_el.get_text(strip=True)
    if not publisher_name:
        author_meta = soup.find("meta", name="author")
        if author_meta:
            publisher_name = (author_meta.get("content") or "").strip()

    # 发布时间：var ct 时间戳 / meta
    publish_time = ""
    ct_m = re.search(r'var ct\s*=\s*"(\d+)"', html)
    if ct_m:
        try:
            publish_time = time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(int(ct_m.group(1))),
            )
        except (ValueError, OSError):
            pass
    if not publish_time:
        pub_meta = soup.find("em", id="publish_time")
        if pub_meta:
            publish_time = pub_meta.get_text(strip=True)

    description = ""
    desc_meta = soup.find("meta", attrs={"name": "description"})
    if desc_meta:
        description = (desc_meta.get("content") or "").strip()

    # 正文：js_content > rich_media_content > page_content
    content_div = (
        soup.find("div", id="js_content")
        or soup.find("div", class_="rich_media_content")
        or soup.find("div", id="page_content")
    )
    content_text = ""
    images: list[str] = []
    if content_div:
        text = content_div.get_text(separator=" ", strip=True)
        content_text = re.sub(r"\s+", " ", text).strip()
        for img in content_div.find_all("img"):
            src = img.get("data-src") or img.get("data-original") or img.get("src") or ""
            if src and not src.startswith("data:"):
                images.append(src)
    else:
        notes.append("未找到正文容器 (js_content / rich_media_content / page_content)")

    if not og_title and not h1:
        notes.append("未找到标题 (og:title / h1)")
    if not publisher_name:
        notes.append("未找到公众号名称 (nickname / js_name / meta author)")

    return {
        "raw_title": raw_title,
        "og_title": og_title,
        "publisher_name": publisher_name,
        "publish_time": publish_time,
        "description": description,
        "content_text": content_text,
        "images": images,
        "parse_notes": notes,
    }


def detect_image_body(
    content_text: str,
    images: list,
    parse_notes: list[str],
) -> dict:
    """正文图片化检测（规范 7.5）。

    Returns:
        {
          "content_text_ratio": float,  # 有效文本占比（0-1，1=纯文本）
          "image_count": int,
          "is_image_body": bool,        # 是否需要 OCR
          "reason": str,
        }
    """
    text_len = len(content_text.strip())
    image_count = len(images)
    # 有效文本字符数阈值：正文纯文本至少 50 字；有图无字视为图片化
    effective_text = content_text
    # 去页脚/广告/导航噪声（近似）
    for noise in ("以上内容为广告", "预览时标签不可点", "阅读原文", "微信扫一扫"):
        effective_text = effective_text.replace(noise, "")
    effective_len = len(effective_text.strip())

    is_image_body = image_count > 0 and effective_len < 50
    if image_count == 0 and effective_len < 50:
        # 无图无字：可能是 JS 渲染页面或抓取失败
        reason = "正文既无有效文本也无图片，可能渲染失败"
    elif is_image_body:
        reason = f"正文图片化：图片 {image_count} 张，有效文本 {effective_len} 字"
    else:
        reason = f"有文本内容：{effective_len} 字，图片 {image_count} 张"

    ratio = 1.0 if not is_image_body else round(effective_len / max(1, effective_len + image_count * 80), 3)
    return {
        "content_text_ratio": ratio,
        "image_count": image_count,
        "is_image_body": is_image_body,
        "reason": reason,
    }


# ── 组合入口：抓取 + 解析 ────────────────────────────────

def fetch_and_parse(
    url: str,
    *,
    use_cache: bool = True,
    save_cache: bool = True,
    force_refresh: bool = False,
) -> dict:
    """L1 完整流程：抓取页面 → 解析元数据 → 检测正文图片化。

    Returns 统一 ArticleEnvelope 风格的 dict（含 extraction_status）。
    """
    result = fetch_article_html(
        url,
        use_cache=use_cache,
        save_cache=save_cache,
        force_refresh=force_refresh,
    )
    if not result.get("ok"):
        return {
            "url": url,
            "ok": False,
            "extraction_status": result.get("status", "FETCH_FAILED"),
            "fetch_status": "failed",
            "error": result.get("error", ""),
            "source_url": url,
            "canonical_url": canonicalize_url(url),
            "article_id": extract_url_meta(url)["article_id"],
            "url_hash": extract_url_meta(url)["url_hash"],
            "review_reasons": [f"fetch_failed: {result.get('error', '')}"],
        }

    meta = parse_wechat_metadata(result["html"])
    body_detect = detect_image_body(meta["content_text"], meta["images"], meta["parse_notes"])

    envelope = {
        "url": url,
        "ok": True,
        "source_url": url,
        "canonical_url": result["canonical_url"],
        "article_id": result["article_id"],
        "url_hash": result["url_hash"],
        "fetch_status": "ok",
        "fetched_at": result.get("fetched_at", ""),
        "from_cache": result.get("from_cache", False),
        "raw_html": result["html"],
        "raw_title": meta["raw_title"],
        "og_title": meta["og_title"],
        "publisher_name": meta["publisher_name"],
        "publish_time": meta["publish_time"],
        "description": meta["description"],
        "content_text": meta["content_text"],
        "images": meta["images"],
        "content_blocks": (
            [build_content_block("article_text", text=meta["content_text"])]
            if meta["content_text"].strip()
            else []
        ),
        "content_text_ratio": body_detect["content_text_ratio"],
        "image_count": body_detect["image_count"],
        "is_image_body": body_detect["is_image_body"],
        "body_detect_reason": body_detect["reason"],
        "parse_notes": meta["parse_notes"],
        "extraction_status": (
            "SUCCESS" if not body_detect["is_image_body"] and not meta["parse_notes"]
            else "PARTIAL" if not body_detect["is_image_body"]
            else "NEEDS_REVIEW"
        ),
        "review_reasons": list(meta["parse_notes"]),
        "ocr_status": "pending" if body_detect["is_image_body"] else "skipped",
    }
    if body_detect["is_image_body"]:
        envelope["review_reasons"].append("image_body_detected: 需 OCR")
    return envelope
