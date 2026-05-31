#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSSHub 文章抓取器

# ⚠️ DEPRECATED: RSSHub 功能已废弃（公共实例均被封锁），仅保留供自建实例参考

支持多个公共实例 + fallback 机制
"""
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)


class RSSHubFetcher:
    """RSSHub 文章抓取器"""

    # 公共 RSSHub 实例列表（按优先级排序）
    PUBLIC_INSTANCES = [
        "https://rsshub.app",
        "https://rsshub.rssforever.com",
        "https://rsshub.moeyy.cn",
        "https://rss.fatpandac.com",
    ]

    def __init__(self, base_url: str = None, fallback_urls: List[str] = None):
        """
        初始化 RSSHub 抓取器

        Args:
            base_url: 主 RSSHub 地址，None 则使用公共实例
            fallback_urls: 备用地址列表
        """
        self.instances = []

        if base_url:
            self.instances.append(base_url)

        if fallback_urls:
            self.instances.extend(fallback_urls)

        # 添加公共实例
        for url in self.PUBLIC_INSTANCES:
            if url not in self.instances:
                self.instances.append(url)

        self._current_instance = self.instances[0] if self.instances else None

    def get_wechat_articles(self, biz: str, limit: int = 10) -> List[Dict]:
        """
        获取微信公众号最新文章

        Args:
            biz: 公众号 biz 参数
            limit: 获取文章数量

        Returns:
            文章列表
        """
        for instance in self.instances:
            try:
                articles = self._fetch_from_instance(instance, biz, limit)
                if articles:
                    self._current_instance = instance
                    logger.info(f"[RSSHub] 使用实例: {instance}")
                    return articles
            except Exception as e:
                logger.warning(f"[RSSHub] {instance} 失败: {e}")
                continue

        logger.error("[RSSHub] 所有实例均不可用")
        return []

    def _fetch_from_instance(self, base_url: str, biz: str, limit: int) -> List[Dict]:
        """从指定实例抓取"""
        rss_url = f"{base_url}/wechat/mp/article/{biz}"

        response = requests.get(rss_url, timeout=15)
        response.raise_for_status()

        return self._parse_rss(response.text, limit)

    def _parse_rss(self, rss_content: str, limit: int) -> List[Dict]:
        """解析 RSS XML"""
        articles = []

        try:
            root = ET.fromstring(rss_content)
            channel = root.find('channel')

            if channel is None:
                return articles

            items = channel.findall('item')[:limit]

            for item in items:
                article = {
                    'title': self._get_text(item, 'title'),
                    'url': self._get_text(item, 'link'),
                    'pub_date': self._get_text(item, 'pubDate'),
                    'description': self._get_text(item, 'description'),
                    'guid': self._get_text(item, 'guid'),
                }

                # 解析作者信息
                author = self._get_text(item, 'author')
                if author:
                    article['author'] = author

                articles.append(article)

        except ET.ParseError as e:
            logger.error(f"[RSSHub] XML 解析失败: {e}")

        return articles

    def _get_text(self, element, tag: str) -> str:
        """安全获取 XML 元素文本"""
        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return ""

    def test_connection(self) -> Dict[str, bool]:
        """测试所有实例的连通性"""
        results = {}
        for instance in self.instances:
            try:
                response = requests.get(
                    f"{instance}/wechat/mp/article/test",
                    timeout=10
                )
                results[instance] = response.status_code == 200
            except Exception:
                results[instance] = False
        return results
