#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信文章抓取工具 - 混合模式
requests 优先，Playwright 兜底，OCR 提取图片内容
"""
import json
import os
import re
import sys
import time
import base64
import logging
from pathlib import Path
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

# 日志
logger = logging.getLogger(__name__)

# 导入图片内容提取器
try:
    from image_content_extractor import ImageContentExtractor
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

PLAYWRIGHT_IMPORT_OK = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_IMPORT_OK = True
except ImportError:
    pass

# ── LLM 配置（复用 scorer.py / merge_docs.py 的共享配置） ──
LLM_CONFIG_FILE = os.path.expanduser("~/.llm_config.json")
DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_VISION_MODEL = "mimo-v2.5"  # 通用视觉模型；使用 OpenRouter 或兼容 API 时生效


def _load_llm_config() -> dict:
    """读取共享 LLM 配置，返回 (api_key, api_base, vision_model)。"""
    cfg = {}
    try:
        from common.llm_client import _load_file_config
        cfg = _load_file_config() or {}
    except Exception:
        if os.path.exists(LLM_CONFIG_FILE):
            try:
                with open(LLM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
    return {
        "api_key": cfg.get("api_key") or os.environ.get("LLM_API_KEY", ""),
        "api_base": cfg.get("api_base") or os.environ.get("LLM_API_BASE", DEFAULT_API_BASE),
        "vision_model": cfg.get("vision_model") or os.environ.get("LLM_VISION_MODEL", DEFAULT_VISION_MODEL),
        "vision_api_base": cfg.get("vision_api_base") or os.environ.get("LLM_VISION_API_BASE", ""),
    }


def llm_extract_images(image_paths: list[str], llm_cfg: dict) -> list[dict]:
    """
    用多模态 LLM 提取图片核心内容（非逐字 OCR）。

    Args:
        image_paths: 本地图片路径列表
        llm_cfg: LLM 配置（api_key, api_base/vision_api_base, vision_model）

    Returns:
        [{"image": path, "content": "提取的核心内容"}, ...]
    """
    api_key = llm_cfg["api_key"]
    if not api_key:
        logger.warning("  [LLM-Img] 未配置 API Key，跳过图片内容提取")
        return []

    # vision_api_base 可选覆盖；默认与 api_base 一致
    api_base = (llm_cfg["vision_api_base"] or llm_cfg["api_base"]).rstrip("/")
    model = llm_cfg["vision_model"]

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("  [LLM-Img] openai 库未安装 (pip install openai)，跳过")
        return []

    client = OpenAI(api_key=api_key, base_url=api_base)
    results = []

    for img_path in image_paths:
        if not os.path.exists(img_path):
            continue

        # 编码为 base64 data URL
        try:
            with open(img_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
            ext = os.path.splitext(img_path)[1].lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
            mime = mime_map.get(ext, "image/png")
            data_url = f"data:{mime};base64,{b64_data}"
        except Exception as e:
            logger.warning(f"  [LLM-Img] 编码失败: {os.path.basename(img_path)}: {e}")
            results.append({"image": img_path, "content": ""})
            continue

        sys_msg = (
            "你是一个信用卡资讯提取助手。请从图片中提取对用户决策有价值的核心信息，包括但不限于："
            "银行名称、卡种名称、核心权益、活动时间、适用条件、年费、奖励金额、积分规则等。"
            "不要逐字OCR全文——只提炼关键要点，按要点分行输出。"
            "如果图片不是信用卡相关内容，请注明图片主题。"
        )
        user_msg = "请提取这张图片中的核心信用卡资讯信息。"

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_msg},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                max_tokens=1024,
                temperature=0.1,
            )
            content = (resp.choices[0].message.content or "").strip()
            results.append({"image": img_path, "content": content})
            logger.info(f"  [LLM-Img] OK {os.path.basename(img_path)} ({len(content)} chars)")
        except Exception as e:
            logger.warning(f"  [LLM-Img] 提取失败: {os.path.basename(img_path)}: {e}")
            results.append({"image": img_path, "content": ""})

        time.sleep(0.3)  # 限流

    return results


REQUEST_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': (
        'text/html,application/xhtml+xml,'
        'application/xml;q=0.9,*/*;q=0.8'
    ),
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def find_chrome():
    """Find Chrome executable using common install paths."""
    candidates = [
        os.path.join('C:', os.sep, 'Program Files',
                     'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join('C:', os.sep, 'Program Files (x86)',
                     'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.environ.get('CHROME_PATH', ''),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def _classify_text_block(text: str) -> str:
    """分类 OCR/LLM 提取的文本块类型。
    
    Returns:
        'ocr_fact': 实质性的信用卡资讯信息
        'ocr_noise': 图片描述、非实质性文字
        'image_cta': 图片中的行动号召文字
    """
    text_stripped = text.strip()
    if not text_stripped:
        return 'ocr_noise'
    # CTA 检测：短文本 + 行动号召关键词
    cta_kw = ['扫码', '申请', '下载', '点击', '立即', '开通', '办理']
    if len(text_stripped) < 40 and any(kw in text_stripped for kw in cta_kw):
        return 'image_cta'
    # 噪音检测：图片描述、装饰性文字
    noise_patterns = ['图片为', '图（', 'picture', '插画', '背景图', '示意图']
    for pat in noise_patterns:
        if pat in text_stripped.lower():
            return 'ocr_noise'
    if len(text_stripped) < 4:
        return 'ocr_noise'
    return 'ocr_fact'


def fetch_with_requests(url):
    """Fetch page using requests library."""
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        r.raise_for_status()
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        print(f'  [requests] failed: {e}', file=sys.stderr)
        return None


def fetch_with_playwright(url):
    """Fetch page using Playwright with local Chrome."""
    if not PLAYWRIGHT_IMPORT_OK:
        print('  [Playwright] library not installed', file=sys.stderr)
        return None
    chrome_path = find_chrome()
    if not chrome_path:
        print('  [Playwright] Chrome not found', file=sys.stderr)
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=chrome_path,
            )
            try:
                page = browser.new_page()
                page.goto(url, wait_until='networkidle', timeout=30000)
                page.wait_for_selector('#js_content', timeout=10000)
                return page.content()
            finally:
                browser.close()
    except Exception as e:
        print(f'  [Playwright] failed: {e}', file=sys.stderr)
        return None


def extract_article(html, url):
    """Extract article data from HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    result = {'url': url, 'title': '', 'content_html': '',
              'content_text': '', 'images': []}

    title_elem = (
        soup.find('h1', class_='rich_media_title')
        or soup.find('h1', id='activity-name')
        or soup.find('meta', property='og:title')
    )
    if title_elem:
        if title_elem.name == 'meta':
            result['title'] = title_elem.get('content', '')
        else:
            result['title'] = title_elem.get_text(strip=True)

    content_div = (
        soup.find('div', id='js_content')
        or soup.find('div', class_='rich_media_content')
        or soup.find('div', id='page_content')
        or soup.find('div', class_='rich_media_area_primary')
    )
    if content_div:
        result['content_html'] = str(content_div)
        text = content_div.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        result['content_text'] = text.strip()
        for img in content_div.find_all('img'):
            src = img.get('data-src') or img.get('src') or ''
            if src and not src.startswith('data:'):
                result['images'].append(src)
    return result


def process_single(url, download_images=False, images_dir=None, extract_ocr=False, extract_llm=False, max_images=0):
    """Process a single article URL.

    Args:
        extract_llm: 用多模态 LLM 提取图片中的核心内容（替代逐字 OCR）
        max_images: 最多保留的图片数，0 表示不限（取全部）
    """
    print(f'Processing: {url}')
    html = fetch_with_requests(url)
    source = 'requests'
    if not html:
        html = fetch_with_playwright(url)
        source = 'playwright'
    if not html:
        print(f'  [FAILED] Cannot fetch page', file=sys.stderr)
        return {'url': url, 'error': 'Cannot fetch page'}

    article = extract_article(html, url)
    article['source'] = source
    content_blocks = [{'type': 'article_text', 'text': article.get('content_text', ''), 'confidence': 0.95}]

    # 提前截断图片列表：只保留前 max_images 张（0 = 不限）
    if max_images > 0 and article.get('images'):
        if len(article['images']) > max_images:
            article['images'] = article['images'][:max_images]

    if download_images and images_dir and article.get('images'):
        save_dir = Path(images_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        local_paths = []
        for i, img_url in enumerate(article['images']):
            local = download_image(img_url, save_dir, i)
            if local:
                local_paths.append(local)
        article['images'] = local_paths

        # OCR 提取图片文字 + 构建 content_blocks
        if extract_ocr and OCR_AVAILABLE and local_paths:
            print(f'  [OCR] 提取图片文字...')
            extractor = ImageContentExtractor()
            if extractor.is_available:
                ocr_results = extractor.extract_text_from_images(local_paths)
                article['ocr_text'] = {k: v for k, v in ocr_results.items() if v}
                for path, text in article['ocr_text'].items():
                    for line in text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        block_type = _classify_text_block(line)
                        content_blocks.append({
                            'type': block_type,
                            'text': line,
                            'confidence': 0.7 if block_type == 'ocr_fact' else 0.3,
                            'source': f'ocr:{Path(path).name}'
                        })
            else:
                print(f'  [OCR] Tesseract 未安装，跳过图片文字提取', file=sys.stderr)

        # LLM 提取图片核心内容（多模态，提取关键信息而非逐字OCR）
        if extract_llm and local_paths:
            print(f'  [LLM-Img] 提取图片核心内容 ({len(local_paths)} 张)...')
            llm_cfg = _load_llm_config()
            llm_results = llm_extract_images(local_paths, llm_cfg)
            if llm_results:
                article['llm_text'] = {r['image']: r['content'] for r in llm_results if r.get('content')}
                for r in llm_results:
                    if r.get('content'):
                        content_blocks.append({
                            'type': 'ocr_fact',
                            'text': r['content'],
                            'confidence': 0.7,
                            'source': f'llm:{Path(r["image"]).name}'
                        })

        # 从 content_blocks 重建 full_text（只含实质内容，不含噪音）
        clean_blocks = [
            b['text'] for b in content_blocks
            if b['type'] in ('article_text', 'ocr_fact')
        ]
        article['full_text'] = '\n\n'.join(clean_blocks)

    article['content_blocks'] = content_blocks
    return article


def download_image(img_url, save_dir, index):
    """Download a single image."""
    try:
        r = requests.get(img_url, headers=REQUEST_HEADERS, timeout=30)
        r.raise_for_status()
        ext = '.jpg'
        ct = r.headers.get('content-type', '')
        if 'png' in ct:
            ext = '.png'
        elif 'gif' in ct:
            ext = '.gif'
        elif 'webp' in ct:
            ext = '.webp'
        fname = f'img_{index:04d}{ext}'
        fpath = save_dir / fname
        with open(fpath, 'wb') as f:
            f.write(r.content)
        return str(fpath)
    except Exception as e:
        print(f'  [Download] failed {img_url[:50]}...: {e}', file=sys.stderr)
        return None


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description='WeChat article fetcher')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', help='Single article URL')
    group.add_argument('--batch', action='store_true',
                       help='Batch mode (read URLs from stdin)')
    parser.add_argument('--download-images', action='store_true',
                        help='Download images')
    parser.add_argument('--images-dir', default='./images',
                        help='Images save directory')
    parser.add_argument('--extract-ocr', action='store_true',
                         help='Extract text from images using OCR')
    parser.add_argument('--extract-llm', action='store_true',
                         help='Extract core content from images using LLM (multimodal)')
    parser.add_argument('--output', '-o', help='Output JSON file')
    parser.add_argument('--delay', type=float, default=1.0,
                         help='Delay (seconds) between batch requests (default 1.0)')
    args = parser.parse_args()

    urls = []
    if args.url:
        urls = [args.url]
    elif args.batch:
        urls = [line.strip() for line in sys.stdin if line.strip()]

    if not urls:
        print('No URLs provided', file=sys.stderr)
        sys.exit(1)

    images_dir = Path(args.images_dir) if args.download_images else None
    if len(urls) == 1:
        result = process_single(urls[0],
                                download_images=args.download_images,
                                images_dir=images_dir,
                                extract_ocr=args.extract_ocr,
                                extract_llm=args.extract_llm)
    else:
        results = []
        for url in urls:
            results.append(process_single(url,
                                          download_images=args.download_images,
                                          images_dir=images_dir,
                                          extract_ocr=args.extract_ocr,
                                          extract_llm=args.extract_llm))
            time.sleep(args.delay)
        result = results

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f'Results saved: {args.output}')
    else:
        print(output)


if __name__ == '__main__':
    main()
