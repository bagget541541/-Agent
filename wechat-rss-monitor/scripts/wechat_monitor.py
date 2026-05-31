#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号 URL 去重组件（仅保留去重逻辑）

职责：
- 基于 MD5 哈希做 URL 去重
- history.json 持久化
- 最近 5000 条 LRU 裁剪

注意：抓取功能已由 wechat-article-extractor/fetch_wechat_article.py 统一提供，
本模块不包含抓取逻辑。
"""
import json
import hashlib
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class WeChatDedup:
    """微信公众号 URL 去重器"""

    def __init__(self, config_path: str):
        """
        初始化去重器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.history_path = self.config_path.parent / "history.json"
        self.history = self._load_history()

    def _load_config(self) -> Dict:
        """加载配置"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"accounts": [], "max_articles_per_fetch": 10}

    def _load_history(self) -> Dict:
        """加载历史记录"""
        if self.history_path.exists():
            with open(self.history_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"fetched_urls": [], "last_fetch": None}

    def _save_history(self):
        """保存历史记录"""
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def _url_hash(self, url: str) -> str:
        """生成 URL 的 MD5 哈希"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    def is_fetched(self, url: str) -> bool:
        """检查文章是否已抓取"""
        url_hash = self._url_hash(url)
        return url_hash in self.history.get('fetched_urls', [])

    def mark_fetched(self, url: str):
        """标记文章已抓取"""
        url_hash = self._url_hash(url)
        if 'fetched_urls' not in self.history:
            self.history['fetched_urls'] = []

        if url_hash not in self.history['fetched_urls']:
            self.history['fetched_urls'].append(url_hash)

        # 保留最近 5000 条记录
        if len(self.history['fetched_urls']) > 5000:
            self.history['fetched_urls'] = self.history['fetched_urls'][-5000:]

    def mark_fetched_batch(self, urls: List[str]):
        """批量标记文章已抓取"""
        for url in urls:
            self.mark_fetched(url)
        self.history['last_fetch'] = datetime.now().isoformat()
        self._save_history()

    def extract_biz_from_url(self, url: str) -> Optional[str]:
        """从文章 URL 提取 biz 参数"""
        match = re.search(r'__biz=([A-Za-z0-9=]+)', url)
        return match.group(1) if match else None

    def filter_new(self, urls: List[str]) -> List[str]:
        """过滤出未抓取的新 URL"""
        return [u for u in urls if u.strip() and not self.is_fetched(u.strip())]

    def refresh_history(self, urls: List[str]):
        """替换 history 为指定的 URL 列表（用于数据修复/迁移）"""
        self.history['fetched_urls'] = [self._url_hash(u) for u in urls]
        self._save_history()

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "total_accounts": len(self.config.get('accounts', [])),
            "total_fetched": len(self.history.get('fetched_urls', [])),
            "last_fetch": self.history.get('last_fetch'),
        }


# 旧版别名，方便迁移
WeChatMonitor = WeChatDedup
