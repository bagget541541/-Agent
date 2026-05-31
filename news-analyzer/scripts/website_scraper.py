#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多银行官网公告/活动抓取器

功能：
  - 从多银行官网公告列表页抓取公告
  - 智能过滤低价值内容（数据库维护、电话更新等）
  - 可配置时间范围（只抓取近期公告）
  - 自动识别分类（新卡/活动/权益变更/公告）
  - 直接输出 CreditCardBatch 标准格式 JSON

用法：
  # 抓取所有已配置的银行
  python scripts/website_scraper.py --days 7 --output data/announcements_本周.json

  # 指定银行
  python scripts/website_scraper.py --banks 邮政储蓄银行,建设银行 --days 7

  # 指定日期范围
  python scripts/website_scraper.py --since 2026-05-01 --until 2026-05-31

  # 更多参数
  python scripts/website_scraper.py --help
"""

import json
import os
import re
import ssl
import sys
import argparse
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from bs4 import BeautifulSoup

# Selenium 可选导入
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# 确保项目根在 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from common.schema import CreditCardItem, CreditCardBatch, normalize_category
from common.classifier import classify_item

# ════════════════════════════════════════════════════════════════
# 低价值公告过滤关键词
# ════════════════════════════════════════════════════════════════

LOW_VALUE_KEYWORDS = {
    # 电话/热线/联系信息变更
    "客服电话变更", "客服热线变更", "服务热线变更", "电话变更",
    "电话号码更新", "联系电话变更", "24小时客服热线",
    "联系客服", "客服热线", "客服电话", "联系方式",
    "联系地址变更", "办公地址变更", "办公地址搬迁", "联系地址",
    # 服务暂停/维护
    "暂停服务公告", "临时暂停服务",
    "暂停服务", "服务暂停", "临时暂停", "暂停办理",
}

# SSL 兼容（部分银行需要 legacy renegotiation）
# ════════════════════════════════════════════════════════════════

_OP_LEGACY = 0x4  # ssl.OP_LEGACY_SERVER_CONNECT


class _LegacySSLAdapter(HTTPAdapter):
    """允许 legacy renegotiation 的 SSL 适配器，用于部分银行网站。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.options |= _OP_LEGACY
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


# ════════════════════════════════════════════════════════════════
# 银行配置
# ════════════════════════════════════════════════════════════════

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class BankConfig:
    """单个银行官网公告抓取配置。"""
    name: str                                    # 银行全称
    short_name: str = ""                         # 简称（自动从 name 推导）
    list_url: str = ""                           # 公告列表页 URL
    encoding: str = "utf-8"                      # 页面编码
    insecure: bool = False                       # 是否启用 legacy SSL
    needs_selenium: bool = False                 # 是否需要 Selenium 来渲染页面

    # 列表页选择器（用于从列表页提取每条公告的 URL、标题、日期）
    list_item_selector: str = "li, .item, .news-item, tr"  # 列表项容器
    # 从列表项中提取：每个字段都是 (CSS选择器, 属性名) 或 None
    link_selector: tuple = ("a", "href")         # 链接
    title_selector: tuple = ("a", "text")        # 标题（text 或 attribute）
    date_selector: tuple = ("span.date, .time, td:nth-child(2)", "text")  # 日期
    date_format: str = "%Y-%m-%d"                # 日期格式（strptime）

    # 详情页选择器
    detail_title_selector: str = "h1, .title, .article-title"  # 详情页标题
    detail_date_selector: str = ".date, .time, .article-date"   # 详情页日期
    detail_content_selector: str = ".content, .article-content, #content, .detail-content, .maintext"
    detail_remove_selectors: list = field(default_factory=list)  # DOM 选择器列表，提取正文前删除这些节点（如面包屑、页脚）
    detail_start_markers: list = field(default_factory=list)     # 正文开头标记，文本层截取从此开始（如 ["尊敬的客户", "关于", "我行"]）
    detail_end_markers: list = field(default_factory=list)       # 正文结束标记，文本层截取到此结束（如 ["网站地图", "Copyright", "免责声明"]）

    # URL 规则
    url_prefix_required: str = ""                # 链接必须包含此前缀（过滤非公告链接）
    url_prefix_skip: list = field(default_factory=lambda: ["#", "javascript"])  # 跳过链接

    def __post_init__(self):
        if not self.short_name:
            self.short_name = self.name.replace("银行", "").replace("储蓄", "")
        if not self.url_prefix_required:
            # 默认使用 list_url 的域名作为前缀要求
            from urllib.parse import urlparse
            parsed = urlparse(self.list_url)
            self.url_prefix_required = f"{parsed.scheme}://{parsed.netloc}"

    def is_low_value(self, title: str, content: str = "") -> bool:
        """判断是否为低价值公告（数据库维护、电话更新等）。"""
        text = title or content[:200]
        for kw in LOW_VALUE_KW_SUBSTRINGS:
            if kw in text:
                return True
        return False


# 从关键词构建 substring 集合（包含标题常用前缀）
LOW_VALUE_KW_SUBSTRINGS = set()
for kw in LOW_VALUE_KEYWORDS:
    LOW_VALUE_KW_SUBSTRINGS.add(kw)
    # 标题前缀常见格式
    LOW_VALUE_KW_SUBSTRINGS.add(f"关于{kw}")
    LOW_VALUE_KW_SUBSTRINGS.add(f"关于{kw}的公告")
    LOW_VALUE_KW_SUBSTRINGS.add(f"{kw}公告")
    LOW_VALUE_KW_SUBSTRINGS.add(f"{kw}的公告")


# ── 预置银行配置（按需扩展） ───────────────────────────

BANK_CONFIGS: dict[str, BankConfig] = {}

# 邮政储蓄银行（已验证可用）
BANK_CONFIGS["邮政储蓄银行"] = BankConfig(
    name="邮政储蓄银行",
    list_url="https://www.psbc.com/cn/grfw/xyk/ywgg_258/",
    encoding="utf-8",
    list_item_selector="li.clearfix",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .article-title",
    detail_date_selector=".article-date, .date",
    detail_content_selector=".article-content, .content, .maintext",
    url_prefix_required="https://www.psbc.com/cn/grfw/xyk/ywgg_258",
)


# 招商银行
BANK_CONFIGS["招商银行"] = BankConfig(
    name="招商银行",
    short_name="招行",
    list_url="https://cc.cmbchina.com/notice/",
    encoding="utf-8",
    list_item_selector="li, .notice-item, .news-item",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title",
    detail_date_selector=".date, .time",
    # 增加备选详情选择器以兼容不同页面结构
    detail_content_selector=".content, .detail-content, .article-content, .notice-content, .notice-detail, .content-main, #content",
)

# 中信银行（已按照 banks_parser_v2 的中信公告验证并修正 selectors）
BANK_CONFIGS["中信银行"] = BankConfig(
    name="中信银行",
    short_name="中信",
    list_url="https://creditcard.citicbank.cn/gonggao/",
    encoding="utf-8",
    insecure=True,
    list_item_selector="li",
    link_selector=("a", "href"),
    title_selector=("a", "title"),
    date_selector=(".gg_date", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title, .article-title",
    detail_date_selector=".date, .time, .article-date",
    detail_content_selector=".content, .article-content, .detail-content",
)

# ── 以下为从 banks_parser_v2.py 迁移的银行配置（排除恒丰/光大/工商） ──

# 华夏银行（banks_parser_v2 中为纯静态列表页，通用选择器即可）
BANK_CONFIGS["华夏银行"] = BankConfig(
    name="华夏银行",
    short_name="华夏",
    list_url="https://creditcard.hxb.com.cn/card/cn/khfw/zygg/index.shtml",
    encoding="utf-8",
    list_item_selector="li, tr, article",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 浦发银行（banks_parser_v2 使用 Selenium，此处以 requests 尝试）
BANK_CONFIGS["浦发银行"] = BankConfig(
    name="浦发银行",
    short_name="浦发",
    list_url="https://ccc.spdb.com.cn/news/zxgg/",
    encoding="utf-8",
    list_item_selector=".newsright_news",
    link_selector=(".newsright_newsb a", "href"),
    title_selector=(".newsright_newsb a", "title"),
    date_selector=(".newsright_newsc", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title, .article-title",
    detail_date_selector=".date, .time, .article-date",
    detail_content_selector=".content, .article-content, .detail-content, .newsright_main",
)

# 南京银行（banks_parser_v2 用 requests + .erji_lib 选择器）
BANK_CONFIGS["南京银行"] = BankConfig(
    name="南京银行",
    short_name="南京",
    list_url="https://www.njcb.com.cn/njcb/grjr/_301371/hdgg/index.html",
    encoding="utf-8",
    list_item_selector=".erji_lib",
    link_selector=(".erji_libtit a", "href"),
    title_selector=(".erji_libtit a", "title"),
    date_selector=(".erji_libdate", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title",
    detail_date_selector=".date, .time",
    detail_content_selector=".content, .detail-content, .article-content",
)

# 广发银行（banks_parser_v2 中为纯静态列表页，通用选择器）
BANK_CONFIGS["广发银行"] = BankConfig(
    name="广发银行",
    short_name="广发",
    list_url="https://card.cgbchina.com.cn/Channel/23357188",
    encoding="gbk",  # 广发官网实际为 GBK 编码
    list_item_selector="li, tr, article",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 兴业银行（banks_parser_v2 中为纯静态列表页，通用选择器）
BANK_CONFIGS["兴业银行"] = BankConfig(
    name="兴业银行",
    short_name="兴业",
    list_url="https://creditcard.cib.com.cn/news/notice/",
    encoding="utf-8",
    list_item_selector="li, tr, article",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 东亚银行（banks_parser_v2 中为纯静态列表页，通用选择器）
BANK_CONFIGS["东亚银行"] = BankConfig(
    name="东亚银行",
    short_name="东亚",
    list_url="https://www.hkbea.com.cn/PersonalBusiness/CreditCards/Announcements/",
    encoding="utf-8",
    list_item_selector="li, tr, article",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 平安银行（banks_parser_v2 需先抓主页面再获取 iframe，此处用主页面 URL 默认选择器尝试）
BANK_CONFIGS["平安银行"] = BankConfig(
    name="平安银行",
    short_name="平安",
    list_url="https://creditcard.pingan.com/gonggao/index.shtml",
    encoding="utf-8",
    list_item_selector="li, tr, article",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 农业银行活动（banks_parser_v2 独立 URL，使用 li.cf + .details_rightD 选择器）
BANK_CONFIGS["农业银行活动"] = BankConfig(
    name="农业银行活动",
    short_name="农行活动",
    list_url="https://www.abchina.com/cn/PersonalServices/ABCPromotion/National/",
    encoding="utf-8",
    insecure=True,
    list_item_selector="li.cf",
    link_selector=("a", "href"),
    title_selector=("a", "title"),
    date_selector=(".details_rightD", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title",
    detail_date_selector=".date, .time",
    detail_content_selector=".content, .detail-content, .article-content, .maintext",
)

# 农业银行公告（banks_parser_v2 中农行公告独立 URL，使用 li.bg_lightGray0）
BANK_CONFIGS["农业银行"] = BankConfig(
    name="农业银行",
    short_name="农行",
    list_url="https://www.abchina.com/cn/CreditCard/AboutUs/Update/",
    encoding="utf-8",
    insecure=True,
    list_item_selector="li.bg_lightGray0, li",
    link_selector=("a", "href"),
    title_selector=("a", "title"),
    date_selector=(".details_rightD", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title",
    detail_date_selector=".date, .time",
    detail_content_selector=".content, .detail-content, .article-content, .maintext",
)

# 交通银行（banks_parser_v2 使用 Selenium，此处以 requests + .cont-box .cont .item 选择器尝试）
BANK_CONFIGS["交通银行"] = BankConfig(
    name="交通银行",
    short_name="交行",
    list_url="https://creditcard.bankcomm.com/content/notice.html?tab=1&device=pc",
    encoding="utf-8",
    list_item_selector=".cont-box .cont .item, .item",
    link_selector=(".left a", "href"),
    title_selector=(".left", "text"),
    date_selector=(".right", "text"),
    date_format="%Y-%m-%d",
)

# 宁波银行（卡权益公告，banks_parser_v2 中为纯静态列表页）
BANK_CONFIGS["宁波银行"] = BankConfig(
    name="宁波银行",
    short_name="宁波",
    list_url="https://www.nbcb.com.cn/creditcard/card_guide/xykqyyl/",
    encoding="utf-8",
    list_item_selector="li, tr, article",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 汇丰银行（banks_parser_v2 使用 requests + expander 结构，此处以默认选择器尝试）
BANK_CONFIGS["汇丰银行"] = BankConfig(
    name="汇丰银行",
    short_name="汇丰",
    list_url="https://www.hsbc.com.cn/credit-cards/information/",
    encoding="utf-8",
    list_item_selector="div.A-EXPCNT-RW-RBWM.expander, li, tr, article",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 北京银行公告（banks_parser_v2 使用 Selenium + Vue 数据提取，此处以 URL 和默认选择器尝试）
BANK_CONFIGS["北京银行"] = BankConfig(
    name="北京银行",
    short_name="北京",
    list_url="https://creditcard.bankofbeijing.com.cn/creditcard/secondlist?column=1557569367380729856",
    encoding="utf-8",
    list_item_selector="li, tr, article, .el-table__row",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time, td:nth-child(2)", "text"),
    date_format="%Y-%m-%d",
)

# 中国银行（更新为 banks_parser_v2 已验证的 URL：bi2/ 而非 bc1/）
BANK_CONFIGS["中国银行"] = BankConfig(
    name="中国银行",
    short_name="中行",
    list_url="https://www.boc.cn/bcservice/bi2/",
    encoding="utf-8",
    list_item_selector="li, .news-item",
    link_selector=("a", "href"),
    title_selector=("a", "text"),
    date_selector=("span.date, .time", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title",
    detail_date_selector=".date, .time",
    detail_content_selector=".content, .detail-content, .article-content",
    url_prefix_required="https://www.boc.cn",
)

# 建设银行（更新为 banks_parser_v2 已验证的 URL，并调整选择器匹配 #zxgg li）
BANK_CONFIGS["建设银行"] = BankConfig(
    name="建设银行",
    short_name="建行",
    list_url="https://ae2.ccb.com/chn/creditcard/news.shtml",
    encoding="utf-8",
    insecure=True,
    list_item_selector="#zxgg li, li, .news-item",
    link_selector=("a", "href"),
    title_selector=("a", "title"),
    date_selector=("span", "text"),
    date_format="%Y-%m-%d",
    detail_title_selector="h1, .title",
    detail_date_selector=".date, .time",
    detail_content_selector=".content, .detail-content, .maintext",
)


# ════════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════════

def _get_text(el, selector_attr: tuple) -> str:
    """从 BeautifulSoup 元素中提取文本或属性值。"""
    selector, attr = selector_attr
    target = el.select_one(selector) if selector else el
    if not target:
        return ""
    if attr == "text":
        return target.get_text(strip=True)
    return target.get(attr, "").strip()


def _set_best_encoding(response, fallback: str = "utf-8") -> None:
    """尝试为 response 选择最佳编码。

    优先顺序：response.apparent_encoding -> fallback 参数（通常来自 BankConfig.encoding）
    -> 常见编码列表（utf-8/utf-8-sig/gb18030/gbk/gb2312）。对每个编码尝试解码 response.content，
    并挑选出包含中文字符的第一个编码；若都不匹配则使用 fallback。
    """
    try_encs = []
    if response.apparent_encoding:
        try_encs.append(response.apparent_encoding)
    if fallback and fallback not in try_encs:
        try_encs.append(fallback)
    for e in ("utf-8", "utf-8-sig", "gb18030", "gbk", "gb2312"):
        if e not in try_encs:
            try_encs.append(e)

    content_bytes = getattr(response, 'content', None)
    if not content_bytes:
        # 回退到 requests 的默认行为
        response.encoding = response.apparent_encoding or response.encoding or fallback
        return

    for enc in try_encs:
        try:
            decoded = content_bytes.decode(enc, errors='replace')
            # 如果解码后包含中文字符，认为此编码合适
            if re.search(r"[\u4e00-\u9fff]", decoded):
                response.encoding = enc
                return
        except Exception:
            continue

    # 未找到包含中文的编码，使用 fallback
    response.encoding = fallback or response.apparent_encoding or response.encoding


def _parse_date(date_str: str, fmt: str) -> Optional[datetime]:
    """尝试多种日期格式解析。"""
    if not date_str:
        return None

    date_str = date_str.strip()
    for ch in "()（）【】[]{}<>":
        date_str = date_str.replace(ch, "")
    date_str = (
        date_str.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("号", "")
        .replace("时", ":")
        .replace("分", "")
        .replace("秒", "")
        .strip()
    )

    try:
        return datetime.strptime(date_str, fmt)
    except ValueError:
        pass

    for date_format in [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y%m%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y年%m月%d日",
        "%Y年%m月%d日 %H:%M",
        "%m-%d",
        "%m/%d",
    ]:
        try:
            return datetime.strptime(date_str, date_format)
        except ValueError:
            continue

    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_str)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    return None


def _safe_filename(s: str) -> str:
    """将字符串转为安全文件名。"""
    return re.sub(r'[\\/*?:"<>|]', "_", s).strip()


def _guess_category_from_title(title: str, content: str = "") -> str:
    """根据标题和内容推测分类。"""
    text = f"{title} {content[:500]}"

    # 权益变更/调整
    if any(kw in text for kw in ["调整", "变更", "升级", "缩水", "取消", "权益",
                                  "优化", "更新", "新规", "规则调整", "修改"]):
        return "权益变更"

    # 新卡
    if any(kw in text for kw in ["新卡", "首发", "上市", "发行", "推出", "全新",
                                  "隆重", "首发上市", "全新推出"]):
        return "新卡"

    # 活动
    if any(kw in text for kw in ["活动", "优惠", "返现", "满减", "积分",
                                  "福利", "折扣", "抽奖", "送礼", "消费奖励",
                                  "刷卡", "立减", "返利"]):
        return "活动"

    return "公告"


STRICT_DATE_BANKS = {
    "邮政储蓄银行",
    "兴业银行",
    "广发银行",
    "华夏银行",
    "东亚银行",
    "宁波银行",
    "中国银行",
    "平安银行",
    "汇丰银行",
}


def create_session(bank: BankConfig) -> requests.Session:
    """创建针对某银行的 requests Session。"""
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_UA})
    if bank.insecure:
        session.mount("https://", _LegacySSLAdapter())
    return session


# ════════════════════════════════════════════════════════════════
# 核心抓取逻辑
# ════════════════════════════════════════════════════════════════

# Selenium 需要等待的银行名单（页面 JS 渲染内容）
_SELENIUM_BANKS = {"招商银行", "浦发银行", "交通银行", "北京银行", "建设银行"}
def _parse_pingan(session, bank, url):
    """平安银行：主页面 + iframe 列表，参考 banks_parser_v2 的抓取方式。"""
    try:
        response = session.get(url, timeout=15)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        iframe = soup.find("iframe", src=True)
        iframe_url = urljoin(url, iframe["src"]) if iframe else urljoin(url, "/gonggao/zuixingonggaoIndex.shtml")

        iframe_resp = session.get(iframe_url, timeout=15)
        iframe_resp.encoding = "utf-8"
        iframe_soup = BeautifulSoup(iframe_resp.text, "html.parser")

        items = []
        for li in iframe_soup.find_all("li"):
            link = li.find("a", href=True)
            if not link:
                continue

            title = _clean_title(link.get_text(" ", strip=True) or link.get("title", ""))
            date = _extract_date(li.get_text(" ", strip=True), last=True)
            if not title or not date:
                continue
            if bank.is_low_value(title):
                continue

            items.append(build_item(bank.name, title, date, urljoin(iframe_url, link["href"])))

        return items
    except Exception as exc:
        print(f"骞冲畨涓撶敤瑙ｆ瀽澶辫触 {bank.name}: {exc}")
        return []


def _parse_hsbc(session, bank, url):
    """汇丰银行：expander 结构，参考 banks_parser_v2 的抓取方式。"""
    try:
        response = session.get(url, timeout=20)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        items = []
        for expander in soup.select("div.A-EXPCNT-RW-RBWM.expander"):
            title_tag = expander.find("h3", class_=lambda value: value and "dropdown-text" in value)
            section = expander.find("section", class_=lambda value: value and "exp-content" in value)
            if not title_tag or not section:
                continue

            if section.find("div", class_=lambda value: value and "A-EXPCNT-RW-RBWM" in value):
                continue

            title = _clean_title(title_tag.get_text(" ", strip=True))
            if len(title) < 6:
                continue
            if bank.is_low_value(title):
                continue

            date = ""
            for paragraph in reversed(section.find_all("p")):
                date = _extract_date(paragraph.get_text(" ", strip=True), last=True)
                if date:
                    break

            if not date:
                continue

            anchor = title_tag.get("id", "")
            item_url = f"{url}#{anchor}" if anchor else url
            items.append(build_item(bank.name, title, date, item_url))

        return items
    except Exception as exc:
        print(f"姹囦赴涓撶敤瑙ｆ瀽澶辫触 {bank.name}: {exc}")
        return []

# ── 辅助（从 banks_parser_v2.py 移植） ────────────────────

def _clean_title(title: str) -> str:
    """清理标题中的空白和无关字符。"""
    import re
    title = re.sub(r"\s+", " ", title).strip()
    for sep in "\n\r\t":
        title = title.replace(sep, "")
    return title.strip(" ·∙•●◦")

def _extract_date(text: str, last: bool = False) -> str:
    """从文本中提取 YYYY-MM-DD 格式日期；last=True 时取最后一个匹配。"""
    import re
    if not text:
        return ""

    patterns = [
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日?",
        r"(\d{4})\.(\d{1,2})\.(\d{1,2})",
    ]

    if not last:
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                year, month, day = match.groups()
                return f"{year}-{int(month):02d}-{int(day):02d}"
        return ""

    candidates = []
    for pat in patterns:
        for match in re.finditer(pat, text):
            year, month, day = match.groups()
            candidates.append((match.start(), f"{year}-{int(month):02d}-{int(day):02d}"))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]



def build_item(bank: str, title: str, date: str, url: str) -> dict:
    """构造与 banks_parser_v2 兼容的记录。"""
    return {
        "title": _clean_title(title),
        "date": date,
        "date_str": date,
        "bank": bank,
        "url": url,
    }


def _parse_abc_promo(session, bank, url):
    try:
        response = session.get(url, timeout=15)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        items = []
        for row in soup.select("li.cf"):
            title_link = row.find("a", href=True)
            date_tag = row.select_one(".details_rightD")
            if not title_link or not date_tag:
                continue

            title = _clean_title(title_link.get("title") or title_link.get_text(" ", strip=True))
            link = urljoin(url, title_link["href"])

            date = _extract_date(date_tag.get_text(" ", strip=True))
            if not date:
                match = re.search(r"(20\d{2})(\d{2})(\d{2})", title_link.get("href", ""))
                if match:
                    year, month, day = match.groups()
                    date = f"{year}-{month}-{day}"

            if not title or not date:
                continue

            if bank.is_low_value(title, row.get_text(" ", strip=True)):
                continue

            items.append(build_item(bank.name, title, date, link))

        return items
    except Exception as exc:
        print(f"农行活动专用解析失败 {bank.name}: {exc}")
        return []


def _parse_abc_notice(session, bank, url):
    try:
        response = session.get(url, timeout=15)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        items = []
        for row in soup.select("li.bg_lightGray0"):
            title_link = row.find("a", href=True)
            date_tag = row.select_one(".details_rightD")
            if not title_link or not date_tag:
                continue

            title = _clean_title(title_link.get("title") or title_link.get_text(" ", strip=True))
            date = _extract_date(date_tag.get_text(" ", strip=True))
            if not title or not date:
                continue

            if bank.is_low_value(title, row.get_text(" ", strip=True)):
                continue

            items.append(build_item(bank.name, title, date, urljoin(url, title_link["href"])))

        return items
    except Exception as exc:
        print(f"农行公告专用解析失败 {bank.name}: {exc}")
        return []


def _parse_psbc(session, bank, url):
    """邮政储蓄银行：列表行里直接提取日期，避免正文/栏目页回退污染。"""
    try:
        response = session.get(url, timeout=20)
        _set_best_encoding(response, bank.encoding)
        soup = BeautifulSoup(response.text, "html.parser")

        items = []
        for tag in soup.select("li.clearfix, li"):
            link = tag.find("a", href=True)
            if not link:
                continue

            title = _clean_title(link.get("title") or link.get_text(" ", strip=True))
            text = tag.get_text(" ", strip=True)
            date = _extract_date(text, last=True)
            if not date:
                date = _extract_date(link.get("href", ""))
            if not title or not date:
                continue
            if bank.is_low_value(title, text):
                continue

            href = link.get("href", "").strip()
            if not href or any(href.startswith(prefix) for prefix in bank.url_prefix_skip):
                continue

            full_url = urljoin(url, href)
            if full_url.rstrip("/") == url.rstrip("/"):
                continue
            if bank.url_prefix_required and bank.url_prefix_required not in full_url:
                continue

            items.append(build_item(bank.name, title, date, full_url))

        seen = set()
        unique = []
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)
        return unique
    except Exception as exc:
        print(f"邮储专用解析失败 {bank.name}: {exc}")
        return []



def _parse_static_reference(session, bank, url):
    """参考 banks_parser_v2 的静态列表页解析方式：按整行文本提取日期。"""
    try:
        response = session.get(url, timeout=20)
        _set_best_encoding(response, bank.encoding)
        soup = BeautifulSoup(response.text, "html.parser")

        items = []
        for tag in soup.find_all(["li", "tr", "article"]):
            link = tag.find("a", href=True)
            if not link:
                continue

            title = _clean_title(link.get("title") or link.get_text(" ", strip=True))
            if len(title) < 6 or len(title) > 120:
                continue

            text = tag.get_text(" ", strip=True)
            date = _extract_date(text)
            if not date:
                date = _extract_date(link.get("href", ""))
            if not date:
                date = _extract_date(link.get_text(" ", strip=True), last=True)
            if not title or not date:
                continue

            if bank.is_low_value(title, text):
                continue

            href = link.get("href", "").strip()
            if not href or any(href.startswith(prefix) for prefix in bank.url_prefix_skip):
                continue

            full_url = urljoin(url, href)
            if full_url.rstrip("/") == url.rstrip("/"):
                continue
            if bank.url_prefix_required and bank.url_prefix_required not in full_url:
                continue

            items.append({"title": title, "url": full_url, "date_str": date})

        seen = set()
        unique = []
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)
        return unique
    except Exception as exc:
        print(f"{bank.name}静态列表页解析失败: {exc}")
        return []



_SPECIAL_LIST_FETCHERS = {
    "农业银行活动": _parse_abc_promo,
    "农业银行": _parse_abc_notice,
    "邮政储蓄银行": _parse_psbc,
    "平安银行": _parse_pingan,
    "汇丰银行": _parse_hsbc,
    "华夏银行": _parse_static_reference,
    "广发银行": _parse_static_reference,
    "兴业银行": _parse_static_reference,
    "东亚银行": _parse_static_reference,
    "宁波银行": _parse_static_reference,
    "中国银行": _parse_static_reference,
}


def _classify_items_old(items: list) -> tuple:
    """将 [{title, url, date}] 分为 (公告列表, 活动列表) —— 占位，统一返回公告。"""
    return items, []


# ── 银行专用 Selenium 解析器 ─────────────────────────────

def _create_driver():
    """创建 headless Chrome driver。"""
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def _parse_cmb(driver, bank_url: str) -> list[dict]:
    """招商银行：等待 span.c_date 渲染后解析。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    driver.get(bank_url)
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "span.c_date"))
    )
    soup = BeautifulSoup(driver.page_source, "html.parser")
    results = []
    for tag in soup.find_all(["li", "tr", "article"]):
        link = tag.find("a", href=True)
        date_span = tag.select_one("span.c_date, span.date, .time")
        if not link or not date_span:
            continue
        title = _clean_title(link.get("title") or link.get_text(" ", strip=True))
        date = _extract_date(date_span.get_text(" ", strip=True))
        if not title or not date:
            continue
        href = link.get("href", "")
        from urllib.parse import urljoin
        results.append({"title": title, "url": urljoin(bank_url, href), "date_str": date})
    return results


def _parse_spdb(driver, bank_url: str) -> list[dict]:
    """浦发银行：等待 .newsright_news 渲染后解析。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    driver.get(bank_url)
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".newsright_news"))
    )
    soup = BeautifulSoup(driver.page_source, "html.parser")
    results = []
    for row in soup.select(".newsright_news"):
        title_link = row.select_one(".newsright_newsb a[href]")
        date_tag = row.select_one(".newsright_newsc")
        if not title_link or not date_tag:
            continue
        title = _clean_title(title_link.get("title") or title_link.get_text(" ", strip=True))
        date = _extract_date(date_tag.get_text(" ", strip=True))
        if not title or not date:
            continue
        href = title_link.get("href", "")
        from urllib.parse import urljoin
        results.append({"title": title, "url": urljoin(bank_url, href), "date_str": date})
    return results


def _parse_bankcomm(driver, bank_url: str) -> list[dict]:
    """交通银行：等待 .cont .item 渲染后解析。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    driver.get(bank_url)
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".cont .item"))
    )
    soup = BeautifulSoup(driver.page_source, "html.parser")
    results = []
    for row in soup.select(".cont-box .cont .item"):
        title_link = row.select_one(".left a[href]") or row.find("a", href=True)
        date_tag = row.select_one(".right")
        if not title_link or not date_tag:
            continue
        title = _clean_title(title_link.get("title") or title_link.get_text(" ", strip=True))
        date = _extract_date(date_tag.get_text(" ", strip=True))
        if not title or not date:
            continue
        href = title_link.get("href", "")
        results.append({"title": title, "url": urljoin(bank_url, href) if href else bank_url, "date_str": date})
    return results


def _parse_bob(driver, bank_url: str) -> list[dict]:
    """北京银行：Vue 页面，通过 JS 注入提取 tableData 数据。"""
    import json, time
    extract_vue_script = """
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            if (el.__vue__ && el.__vue__.$data) {
                var d = el.__vue__.$data;
                if (d.tableData) return JSON.stringify(d.tableData);
                if (d.list) return JSON.stringify(d.list);
                if (d.dataList) return JSON.stringify(d.dataList);
            }
            if (el.__vueParentComponent) {
                try {
                    var ctx = el.__vueParentComponent.setupState || {};
                    for (var k in ctx) {
                        if (Array.isArray(ctx[k]) && ctx[k].length > 0 &&
                            (ctx[k][0].outUrl || ctx[k][0].businessPubTime)) {
                            return JSON.stringify(ctx[k]);
                        }
                    }
                } catch(e) {}
            }
        }
        return '[]';
    """
    driver.get(bank_url)
    time.sleep(4)  # 等待 Vue 渲染
    raw = driver.execute_script(extract_vue_script)
    data = json.loads(raw) if isinstance(raw, str) else []
    results = []
    from urllib.parse import urljoin
    for item in data:
        title = (item.get("title") or "").strip()
        date_str = (item.get("businessPubTime") or "").strip()
        date = _extract_date(date_str)
        rel_url = (item.get("outUrl") or "").strip()
        if not title or not date:
            continue
        item_url = urljoin(bank_url, rel_url) if rel_url else bank_url
        results.append({"title": title, "url": item_url, "date_str": date})
    return results


def _parse_ccb(driver, bank_url: str) -> list[dict]:
    """建设银行：等待 #zxgg li 渲染后解析。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    driver.get(bank_url)
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#zxgg li"))
    )
    soup = BeautifulSoup(driver.page_source, "html.parser")
    results = []
    for li in soup.select("#zxgg li"):
        link = li.find("a", href=True)
        date_tag = li.find("span")
        if not link or not date_tag:
            continue
        title = _clean_title(link.get("title") or link.get_text(" ", strip=True))
        date = _extract_date(date_tag.get_text(" ", strip=True))
        if not title or not date:
            continue
        from urllib.parse import urljoin
        href = link.get("href", "")
        results.append({"title": title, "url": urljoin(bank_url, href), "date_str": date})
    return results


# 银行名 → Selenium 解析器映射
_SELENIUM_PARSERS = {
    "招商银行": _parse_cmb,
    "浦发银行": _parse_spdb,
    "交通银行": _parse_bankcomm,
    "北京银行": _parse_bob,
    "建设银行": _parse_ccb,
}


def _fetch_with_selenium(bank: BankConfig) -> list[dict]:
    """使用 Selenium 渲染页面并返回解析后的公告列表。"""
    if not HAS_SELENIUM:
        print("  [⚠] Selenium 未安装，无法渲染 JS 页面", file=sys.stderr)
        return []

    parser = _SELENIUM_PARSERS.get(bank.name)
    if not parser:
        print(f"  [⚠] {bank.name} 没有专用 Selenium 解析器", file=sys.stderr)
        return []

    driver = _create_driver()
    try:
        print(f"  [⟳] {bank.name} 使用 Selenium 渲染...", file=sys.stderr)
        results = parser(driver, bank.list_url)
        print(f"  [✓] {bank.name} Selenium 解析到 {len(results)} 条", file=sys.stderr)
        return results
    except Exception as e:
        print(f"  [⚠] {bank.name} Selenium 解析失败: {e}", file=sys.stderr)
        return []
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def fetch_list_page(bank: BankConfig) -> list[dict]:
    """抓取银行公告列表页，返回 [{title, url, date_str}...]。"""
    session = create_session(bank)
    results = []

    special_fetcher = _SPECIAL_LIST_FETCHERS.get(bank.name)
    if special_fetcher:
        return special_fetcher(session, bank, bank.list_url)

    # JS 渲染的银行：直接使用 Selenium
    if bank.name in _SELENIUM_BANKS:
        return _fetch_with_selenium(bank)

    # 静态页面：使用 requests
    html = ""
    try:
        resp = session.get(bank.list_url, timeout=20)
        _set_best_encoding(resp, bank.encoding)
        html = resp.text
    except requests.RequestException as e:
        print(f"  [⚠] {bank.name} 列表页抓取失败: {e}", file=sys.stderr)
        return results

    if not html:
        return results

    soup = BeautifulSoup(html, "html.parser")

    items = soup.select(bank.list_item_selector)
    if not items:
        # 尝试更通用的选择器
        items = soup.find_all("li") or soup.find_all("tr")

    for item in items:
        a_tag = item.select_one(bank.link_selector[0]) if bank.link_selector[0] else item
        if not a_tag:
            continue

        # 标题
        if bank.title_selector[1] == "text":
            title = a_tag.get_text(strip=True)
        else:
            title = a_tag.get(bank.title_selector[1], "").strip()

        if not title:
            continue

        # URL
        href = a_tag.get("href", "").strip() if a_tag.name == "a" else ""
        if not href:
            continue
        # 跳过无效链接
        if any(href.startswith(p) for p in bank.url_prefix_skip):
            continue
        # 拼接完整 URL
        full_url = urljoin(bank.list_url, href)

        # 过滤链接前缀
        if bank.url_prefix_required and bank.url_prefix_required not in full_url:
            continue
        if full_url.rstrip("/") == bank.list_url.rstrip("/"):
            continue

        # 日期
        date_str = _get_text(item, bank.date_selector)

        # 跳过低价值
        if bank.is_low_value(title):
            continue

        results.append({
            "title": title,
            "url": full_url,
            "date_str": date_str,
        })

    # 去重
    seen_urls = set()
    unique = []
    for r in results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique.append(r)

    return unique


def fetch_detail_page(url: str, bank: BankConfig) -> Optional[dict]:
    """抓取公告详情页，返回 {title, date_str, content}。"""
    session = create_session(bank)
    try:
        resp = session.get(url, timeout=30)
        _set_best_encoding(resp, bank.encoding)
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None

    # 标题（优先详情页）
    title_el = soup.select_one(bank.detail_title_selector)
    title = title_el.get_text(strip=True) if title_el else ""
    if not title or len(title) < 6:
        if soup.title and soup.title.get_text(strip=True):
            title = _clean_title(soup.title.get_text(strip=True))
    # 标题仍然太短时，尝试 h2/h3/h4 作为回退（应对部分详情页无 h1 情况）
    if not title or len(title) < 6:
        for tag in ["h2", "h3", "h4"]:
            el = soup.find(tag)
            if el:
                t = _clean_title(el.get_text(strip=True))
                if len(t) >= 6:
                    title = t
                    break

    # 日期
    date_el = soup.select_one(bank.detail_date_selector)
    date_str = date_el.get_text(strip=True) if date_el else ""

    # 正文
    content_el = soup.select_one(bank.detail_content_selector)
    if content_el:
        # DOM 层过滤：按配置删除噪音节点
        if bank.detail_remove_selectors:
            for selector in bank.detail_remove_selectors:
                for node in content_el.select(selector):
                    node.decompose()
        # 清理
        for tag in content_el(["script", "style", "nav", "footer", "noscript"]):
            tag.decompose()
        content = content_el.get_text(separator="\n", strip=True)
    else:
        # 回退：取 body 文本
        body = soup.find("body") or soup
        content = body.get_text(separator="\n", strip=True)

    # 清理多余空白
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    content = "\n".join(lines)

    # 回退策略：如果正文过短或不含中文，尝试使用 Selenium 渲染页面（若可用）
    try:
        if (not re.search(r"[\u4e00-\u9fff]", content) or len(content) < 50) and HAS_SELENIUM:
            # 尝试 Selenium 渲染并重解析
            try:
                print("  [Fallback] Using Selenium to render detail page...", end=" ")
                options = ChromeOptions()
                options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument(f"--user-agent={DEFAULT_UA}")
                service = None
                driver = webdriver.Chrome(options=options)
                driver.set_page_load_timeout(30)
                driver.get(url)
                # 简单等待，让页面完成渲染（可根据需要替换为显式等待）
                import time as _time
                _time.sleep(2)
                rendered = driver.page_source
                driver.quit()
                soup2 = BeautifulSoup(rendered, "html.parser")
                content_el2 = soup2.select_one(bank.detail_content_selector)
                if content_el2:
                    for tag in content_el2(["script", "style", "nav", "footer", "noscript"]):
                        tag.decompose()
                    content2 = content_el2.get_text(separator="\n", strip=True)
                else:
                    body2 = soup2.find("body") or soup2
                    content2 = body2.get_text(separator="\n", strip=True)

                lines2 = [l.strip() for l in content2.split("\n") if l.strip()]
                content2 = "\n".join(lines2)
                if len(content2) > len(content):
                    content = content2
                    print("OK")
                else:
                    print("no better")
            except Exception as se:
                print(f"  [Fallback Selenium Error] {se}")
    except Exception:
        pass

    if title and title in content:
        content = content[content.find(title):]

    # ── 清理正文开头的导航/面包屑内容（如"您的位置：客服 > 最新公告"） ──
    header_markers = ["您的位置：", "您的位置:", "当前位置：", "首页 >", "客服 >", "最新公告"]
    content_stripped = content.lstrip()
    for marker in header_markers:
        idx = content_stripped.find(marker)
        if idx >= 0 and idx < 200:  # 只在正文前 200 字符内查找导航
            # 找到第一个中文标题/段落作为真正内容的起点
            rest = content_stripped[idx + len(marker):]
            # 跳过可能存在的换行和分隔符行
            for line in rest.split("\n"):
                line_s = line.strip()
                if len(line_s) >= 8 and re.search(r"[\u4e00-\u9fff]", line_s):
                    # 找到真实内容起始行
                    real_start = content_stripped.find(line_s)
                    if real_start >= 0:
                        content_stripped = content_stripped[real_start:]
                        break
            # 如果还没找到合适起始，至少移除导航行之前的全部内容
            content = content_stripped
            break

    footer_markers = ["网站地图", "隐私保密声明", "客户投诉渠道", "免责声明", "Copyright(C)"]
    footer_positions = [content.find(marker) for marker in footer_markers if marker in content]
    footer_positions = [pos for pos in footer_positions if pos >= 0]
    if footer_positions:
        content = content[:min(footer_positions)]

    lines = [l.strip() for l in content.split("\n") if l.strip()]

    noise_substrings = [
        "ATM/自助/网点查询", "境外拨打服务热线", "特别卡种热点问题", "高端信用卡",
        "CarCard汽车信用卡", "常用文件下载", "个人税收居民身份声明", "无限卡授权委托书下载",
        "白金卡授权委托书下载", "附赠保险申请书下载", "失卡保障申请书下载", "银行首页",
        "广发卡招聘", "帮助中心", "无障碍辅助浏览", "投诉建议", "网银登录", "热门关键字",
        "热门频道", "积分规则", "在线客服", "发现精彩APP", "信用卡官方APP", "广发银行版权所有",
        "粤ICP备", "粤公网安备", "网站声明"
    ]
    exact_noise_lines = {
        "|", "搜索", "首页", "分期", "公告", "优惠活动", "分期理财", "服务指南", "品牌历史",
        "当前位置：", "当前位置:", "【", "】", "字号：", "大", "中", "小", "< 返回", ">",
        "信用卡申请", "卡片申请", "消费者权益保护", "自助服务", "积分查询", "品牌历程"
    }

    filtered_lines = []
    for line in lines:
        if line in exact_noise_lines:
            continue
        if any(marker in line for marker in noise_substrings):
            continue
        if re.fullmatch(r"客服电话\s*[:：].*", line):
            continue
        if re.fullmatch(r"信用卡热线\s*[:：].*", line):
            continue
        if re.fullmatch(r"(?:\d+小时)?客服热线\s*[:：].*", line):
            continue
        filtered_lines.append(line)

    content = "\n".join(filtered_lines)

    # ── 配置化正文开始/结束标记截取 ──
    if bank.detail_start_markers:
        for marker in bank.detail_start_markers:
            if not marker:
                continue
            idx = content.find(marker)
            if idx >= 0 and idx < 500:
                content = content[idx:]
                break

    if bank.detail_end_markers:
        positions = [content.find(m) for m in bank.detail_end_markers if m and m in content]
        positions = [p for p in positions if p >= 0]
        if positions:
            content = content[:min(positions)]

    real_start_markers = [title, "尊敬的客户：", "尊敬的持卡人：", "为更好地", "为保障您的权益", "现将", "特此公告"]
    for marker in real_start_markers:
        if not marker:
            continue
        idx = content.find(marker)
        if idx > 0 and idx < 400:
            content = content[idx:]
            break

    footer_markers = ["热门频道", "积分规则", "在线客服", "发现精彩APP", "信用卡官方APP", "广发银行版权所有", "网站声明"]
    footer_positions = [content.find(marker) for marker in footer_markers if marker in content]
    footer_positions = [pos for pos in footer_positions if pos >= 0]
    if footer_positions:
        content = content[:min(footer_positions)]

    lines = [l.strip() for l in content.split("\n") if l.strip()]
    content = "\n".join(lines)

    # 记录噪音信息
    noise_info = {"removed_selectors": [], "markers_used": {}}
    if bank.detail_remove_selectors:
        for selector in bank.detail_remove_selectors:
            noise_info["removed_selectors"].append(selector)
    if bank.detail_start_markers:
        noise_info["markers_used"]["start"] = bank.detail_start_markers
    if bank.detail_end_markers:
        noise_info["markers_used"]["end"] = bank.detail_end_markers

    return {
        "title": title,
        "date_str": date_str,
        "content": content,
        "noise_info": noise_info,
    }


def scrape_bank(
    bank: BankConfig,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    days: int = 7,
) -> list[CreditCardItem]:
    """抓取某个银行的所有有效公告，返回 CreditCardItem 列表。"""
    if since is None:
        since = datetime.now() - timedelta(days=days)

    print(f"\n{'─' * 50}")
    print(f"[Bank] {bank.name} ({bank.short_name})")
    print(f"   列表页: {bank.list_url}")
    print(f"   时间范围: {since.strftime('%Y-%m-%d')} ~ {until.strftime('%Y-%m-%d') if until else '至今'}")
    print(f"{'─' * 50}")

    # 1. 抓取列表页
    entries = fetch_list_page(bank)
    print(f"   列表项: {len(entries)} 条（已过滤低价值公告）")

    if not entries:
        return []

    # 2. 按时间筛选
    filtered = []
    for e in entries:
        dt = _parse_date(e["date_str"], bank.date_format) if e["date_str"] else None
        e["_parsed_date"] = dt
        if bank.name in STRICT_DATE_BANKS and not dt:
            continue
        if dt:
            if dt < since:
                continue
            if until and dt > until:
                continue
        filtered.append(e)

    print(f"   时间筛选后: {len(filtered)} 条（{len(entries) - len(filtered)} 条超出范围）")

    if not filtered:
        return []

    # 3. 抓取详情页
    items = []
    for i, entry in enumerate(filtered):
        print(f"   [{i + 1}/{len(filtered)}] {entry['title'][:40]}...", end=" ", flush=True)
        detail = fetch_detail_page(entry["url"], bank)
        if not detail:
            print("❌ 详情抓取失败")
            continue

        # 标题质量兜底：如果详情页标题太短/模板词/纯序号，回退到列表页标题
        import re as _re
        _bad_title_kw = ["活动时间", "活动规则", "参与方式", "活动详情",
                         "活动对象", "活动简介", "活动内容", "活动主题"]
        _title_is_bad = (
            not detail["title"]
            or len(detail["title"]) < 8
            or any(kw in detail["title"] for kw in _bad_title_kw)
            or _re.match(r"^[一二三四五六七八九十\d]+[、.．]?\s*$", detail["title"])
        )
        if _title_is_bad and entry.get("title") and entry["title"] != detail.get("title"):
            old_title = detail["title"]
            detail["title"] = entry["title"]
            print(f"\n   标题替换: '{old_title}' → '{detail['title']}'")

        # 再次检查低价值（使用更完整的内容）
        if bank.is_low_value(detail["title"], detail["content"]):
            print("⏭ 低价值过滤")
            continue

        # 推测分类
        classifier_result = classify_item(detail["title"], detail["content"])
        category = classifier_result["category"]

        # 发布日期
        pub_date = ""
        if detail["date_str"]:
            dt = _parse_date(detail["date_str"], bank.date_format)
            if dt:
                pub_date = dt.strftime("%Y.%m.%d")
        elif entry["_parsed_date"]:
            pub_date = entry["_parsed_date"].strftime("%Y.%m.%d")

        if bank.name in STRICT_DATE_BANKS and not pub_date:
            print("跳过：缺少有效日期")
            continue

        print(f"✅ [{category}] 日期={pub_date} 正文={len(detail['content'])}字")

        # 结构化字段
        if category == "新卡":
            structured = {
                "卡种": detail["title"],
                "卡亮点": "",
                "适用人群": "",
                "来源": bank.name,
                "详情": detail["content"][:300],
            }
        elif category == "权益变更":
            structured = {
                "消息时间": pub_date,
                "影响范围": f"{bank.name}信用卡持卡人",
                "变更内容": detail["content"][:500],
                "变更分析": "",
            }
        elif category == "活动":
            structured = {
                "活动内容": detail["content"][:600] if len(detail["content"]) > len(detail["title"]) else detail["title"],
                "活动时间": pub_date,
                "适用人群": f"{bank.name}信用卡持卡人",
            }
        else:
            structured = {
                "消息内容": detail["content"][:300],
                "点评": "",
            }

        item = CreditCardItem(
            source="website",
            category=category,
            bank=bank.name,
            title=detail["title"],
            url=entry["url"],
            raw_text=detail["content"],
            images=[],
            structured=structured,
            author=bank.name,
            publish_time=pub_date,
        )
        items.append(item)

    print(f"   ✅ {bank.short_name}: 成功抓取 {len(items)} 条")
    return items


# ════════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════════

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="多银行官网公告/活动抓取器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 默认抓取最近 7 天
  python scripts/website_scraper.py

  # 指定银行
  python scripts/website_scraper.py --banks 邮政储蓄银行,建设银行

  # 指定天数
  python scripts/website_scraper.py --days 7

  # 指定日期范围
  python scripts/website_scraper.py --since 2026-05-01 --until 2026-05-31

  # 输出到指定文件
  python scripts/website_scraper.py --output data/本周公告.json

  # 列出可用银行
  python scripts/website_scraper.py --list-banks
        """,
    )
    parser.add_argument("--banks", type=str, default="",
                        help="银行名称（逗号分隔），不指定则抓取全部已配置银行")
    parser.add_argument("--days", type=int, default=7,
                        help="抓取最近 N 天的公告（默认 7）")
    parser.add_argument("--since", type=str, default="",
                        help="起始日期 YYYY-MM-DD（优先级高于 --days）")
    parser.add_argument("--until", type=str, default="",
                        help="截止日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--output", type=str, default="",
                        help="输出 JSON 路径（默认 data/announcements_YYYYMMDD.json）")
    parser.add_argument("--max-workers", type=int, default=3,
                        help="并发抓取的银行数（默认 3）")
    parser.add_argument("--list-banks", action="store_true",
                        help="列出所有已配置的银行")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    now = datetime.now()

    # 列出银行
    if args.list_banks:
        print("已配置的银行:")
        for name, cfg in sorted(BANK_CONFIGS.items()):
            print(f"  • {name} ({cfg.short_name})")
            print(f"    列表页: {cfg.list_url}")
            print(f"    SSL兼容: {'是' if cfg.insecure else '否'}")
        return

    # 确定银行列表
    if args.banks:
        bank_names = [b.strip() for b in args.banks.split(",") if b.strip()]
        unknown = [b for b in bank_names if b not in BANK_CONFIGS]
        if unknown:
            print(f"错误: 未知银行 {unknown}", file=sys.stderr)
            print(f"可用银行: {list(BANK_CONFIGS.keys())}", file=sys.stderr)
            sys.exit(1)
    else:
        bank_names = sorted(BANK_CONFIGS.keys())

    # 时间范围
    since = None
    until = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"错误: 日期格式无效 {args.since}，请使用 YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    if args.until:
        try:
            until = datetime.strptime(args.until, "%Y-%m-%d")
            until = until.replace(hour=23, minute=59, second=59)
        except ValueError:
            print(f"错误: 日期格式无效 {args.until}，请使用 YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)

    # 输出路径
    output_path = args.output
    if not output_path:
        date_tag = now.strftime("%Y%m%d")
        output_path = os.path.join(_PROJECT_ROOT, "data", f"announcements_{date_tag}.json")

    print(f"📡 多银行官网公告抓取")
    print(f"   银行数: {len(bank_names)}")
    print(f"   时间范围: {'最近 ' + str(args.days) + ' 天' if not since else since.strftime('%Y-%m-%d')} ~ {until.strftime('%Y-%m-%d') if until else '至今'}")
    print(f"   输出路径: {output_path}")
    print()

    # 并发抓取
    all_items: list[CreditCardItem] = []
    bank_errors = []

    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(bank_names))) as pool:
        future_map = {
            pool.submit(scrape_bank, BANK_CONFIGS[name], since=since, until=until, days=args.days): name
            for name in bank_names
        }
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"\n  ✅ {name}: {len(items)} 条")
            except Exception as e:
                bank_errors.append(f"{name}: {e}")
                print(f"\n  ❌ {name}: 抓取失败 - {e}", file=sys.stderr)

    if not all_items:
        print("\n❌ 未抓取到任何有效公告")
        if bank_errors:
            for err in bank_errors:
                print(f"  ⚠ {err}", file=sys.stderr)
        sys.exit(1)

    # 构建批次
    batch_label = f"银行公告_{now.strftime('%Y%m%d')}"
    batch = CreditCardBatch(batch_label=batch_label)
    for item in all_items:
        batch.add(item)

    # 保存
    abs_path = batch.save_json(output_path)

    # 输出总结
    print(f"\n{'=' * 50}")
    print(f"✅ 抓取完成!")
    print(f"   路径: {abs_path}")
    print(f"   总计: {len(all_items)} 条")
    for cat in ["新卡", "权益变更", "活动", "公告"]:
        count = len(batch.by_category(cat))
        if count:
            bank_names_cat = sorted(set(it.bank for it in batch.by_category(cat)))
            print(f"   {cat}: {count} 条（{', '.join(bank_names_cat)}）")

    # 输出简要 JSON（用于管线消费）
    summary = batch.to_dict()
    summary["bank_errors"] = bank_errors
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
