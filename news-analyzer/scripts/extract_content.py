#!/usr/bin/env python3
"""
网页内容提取脚本
功能：从多个URL提取标题和正文内容，返回JSON格式数据
"""

import json
import re
import ssl
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from bs4 import BeautifulSoup
from readability import Document

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class _LegacySSLAdapter(HTTPAdapter):
    """允许 legacy renegotiation 的 SSL 适配器，用于部分银行网站。"""
    _OP_LEGACY = 0x4  # ssl.OP_LEGACY_SERVER_CONNECT

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.options |= self._OP_LEGACY
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def fetch_url(url: str, session: requests.Session, timeout: int = 15) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


_NAV_KEYWORDS = {
    '首页', '登录', '注册', '办卡', '用卡', '查账', '还款', '账单查询',
    '客户服务', '信用卡申请', '激活', '设置', '积分', '权益', '活动',
    '分期', '增值', '年费', '保险', '联系我们', '网站地图', 'English',
    '最新公告', '公告详情', '返回列表', '返回', '更多',
}
_CONTENT_START = re.compile(r'^(尊敬|您好|各位|关于|我行|我司|因|为|自\d|一、|1[.、])')


def _clean_soup(soup: BeautifulSoup) -> str:
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript']):
        tag.decompose()
    for cls_prefix in ('nav', 'menu', 'header', 'footer', 'sidebar', 'breadcrumb', 'crumb'):
        for tag in soup.find_all(class_=lambda c: c and cls_prefix in c.lower()):
            tag.decompose()
    text = soup.get_text(separator='\n', strip=True)
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if len(line) <= 6 and line in _NAV_KEYWORDS:
            continue
        # 过滤纯日期行、IPv6提示、面包屑
        if re.match(r'^\d{4}[/-]\d{1,2}[/-]\d{1,2}$', line):
            continue
        if 'IPv6' in line and len(line) < 40:
            continue
        if re.match(r'^[\s>›»]+', line) and len(line) < 20:
            continue
        lines.append(line)

    # 跳过头部噪声，找到正文真正起始
    start = 0
    for i, line in enumerate(lines):
        if _CONTENT_START.match(line) or len(line) > 30:
            start = i
            break

    return '\n'.join(lines[start:])


def extract_content(html: str, url: str) -> Dict[str, str]:
    # 从原始 HTML 提取标题（比 readability 更可靠）
    raw_soup = BeautifulSoup(html, 'html.parser')
    title_tag = raw_soup.find('meta', property='og:title')
    raw_title = (title_tag.get('content', '').strip() if title_tag else None) or \
                (raw_soup.title.string.strip() if raw_soup.title and raw_soup.title.string else None)

    doc = Document(html)
    readability_title = doc.title()
    content_html = doc.summary()

    content_soup = BeautifulSoup(content_html, 'html.parser')
    content = _clean_soup(content_soup)

    if len(content) < 100:
        # readability 提取不足，用原始 HTML 全文解析
        content = _clean_soup(raw_soup)

    title = raw_title or readability_title or "无标题"

    # 去重：正文开头如果就是标题，移除重复行
    content_lines = content.split('\n')
    first_line = content_lines[0].strip() if content_lines else ''
    title_clean = re.sub(r'\s+', '', title.strip())
    first_clean = re.sub(r'\s+', '', first_line)
    if first_clean and title_clean and (first_clean == title_clean or
            (len(first_clean) > 10 and title_clean.startswith(first_clean))):
        content = '\n'.join(content_lines[1:]).lstrip('\n')

    return {
        'url': url,
        'title': title,
        'content': content
    }


def process_urls(urls: List[str], max_workers: int = 4, insecure: bool = False) -> List[Dict]:
    session = requests.Session()
    session.headers.update({'User-Agent': DEFAULT_UA})
    if insecure:
        session.mount("https://", _LegacySSLAdapter())
    results = [None] * len(urls)
    has_error = False

    def _fetch_one(idx: int, url: str) -> Dict:
        try:
            html = fetch_url(url, session)
            return extract_content(html, url)
        except requests.RequestException as e:
            return {'url': url, 'title': '提取失败', 'content': f"错误：{e}", 'error': True}
        except Exception as e:
            return {'url': url, 'title': '提取失败', 'content': f"解析错误：{e}", 'error': True}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as pool:
        futures = {pool.submit(_fetch_one, i, url): i for i, url in enumerate(urls)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
            if results[idx].get('error'):
                has_error = True

    if has_error:
        print(json.dumps({"warning": "部分URL提取失败"}, ensure_ascii=False), file=sys.stderr)

    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description='提取网页标题和正文内容')
    parser.add_argument('--urls', type=str, required=True,
                       help='多个URL，用逗号分隔')
    parser.add_argument('--output', type=str, default='json',
                       choices=['json', 'pretty'],
                       help='输出格式：json（默认）或 pretty（美化输出）')
    parser.add_argument('--concurrency', type=int, default=4,
                       help='并发抓取数（默认 4）')
    parser.add_argument('--insecure', action='store_true',
                       help='允许 legacy SSL renegotiation（部分银行网站需要）')

    args = parser.parse_args()

    url_list = [url.strip() for url in args.urls.split(',') if url.strip()]

    if not url_list:
        print(json.dumps({"error": "未提供有效的URL"}, ensure_ascii=False))
        sys.exit(1)

    results = process_urls(url_list, max_workers=args.concurrency, insecure=args.insecure)

    if args.output == 'pretty':
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(results, ensure_ascii=False))

    if all(r.get('error') for r in results):
        sys.exit(1)


if __name__ == '__main__':
    main()
