import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[2] / "news-analyzer" / "scripts" / "website_scraper.py"
_SPEC = importlib.util.spec_from_file_location("website_scraper", _MODULE_PATH)
website_scraper = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(website_scraper)


def test_clean_title_removes_cib_template_prefix():
    title = "兴业银行信用卡欢迎您 关于兴业银行信用卡积分规则调整的公告"
    assert website_scraper._clean_title(title) == "关于兴业银行信用卡积分规则调整的公告"


def test_navigation_noise_is_detected():
    text = "\n".join([
        "银行卡",
        "贵宾",
        "加入收藏",
        "兴业银行信用卡",
        "在线申请信用卡",
        "产品介绍",
        "白金卡系列",
        "标准卡系列",
        "主题卡系列",
        "全面客户服务",
    ])
    assert website_scraper._looks_like_navigation_noise(text) is True


def test_cleanup_detail_content_keeps_real_cib_announcement_body():
    bank = website_scraper.BANK_CONFIGS["兴业银行"]
    raw = "\n".join([
        "银行卡",
        "贵宾",
        "加入收藏",
        "兴业银行信用卡",
        "在线申请信用卡",
        "产品介绍",
        "关于兴业银行信用卡积分规则调整的公告",
        "尊敬的客户：",
        "我行将于北京时间2026年8月24日起调整《兴业银行信用卡积分活动细则》中积分兑换部分内容。",
        "具体兑换规则以活动页面展示为准。",
        "全面客户服务",
    ])
    cleaned = website_scraper._cleanup_detail_content(
        raw,
        bank,
        "关于兴业银行信用卡积分规则调整的公告",
    )
    assert cleaned.startswith("尊敬的客户：")
    assert "调整《兴业银行信用卡积分活动细则》中积分兑换部分内容" in cleaned
    assert "在线申请信用卡" not in cleaned


def test_extract_date_supports_citic_compact_url_date():
    assert website_scraper._extract_date("https://creditcard.citicbank.cn/gonggao/news_260709.shtml") == "2026-07-09"


def test_fallback_links_finds_hxb_detail_when_list_item_selector_changes():
    soup = website_scraper.BeautifulSoup(
        '<div class="new-row"><a href="/card/cn/khfw/zygg/2026/07/138840.shtml">关于信用卡服务调整的公告</a></div>',
        "html.parser",
    )
    bank = website_scraper.BANK_CONFIGS["华夏银行"]
    items = website_scraper._fallback_detail_links(
        soup, bank, "https://creditcard.hxb.com.cn/card/cn/khfw/zygg/index.shtml"
    )
    assert any(item["url"].endswith("/138840.shtml") for item in items)


def test_hxb_uses_real_list_and_detail_containers():
    bank = website_scraper.BANK_CONFIGS["华夏银行"]
    assert bank.list_item_selector == ".news_list > li"
    assert bank.detail_content_selector == ".Details_main_main"
    assert bank.is_low_value("华夏银行股份有限公司信用卡中心2026年第8期信用卡债权转让公告")
    assert not bank.is_low_value("关于延续华夏银行美国运通Safari信用卡费用优惠的公告")


def test_hkbea_ignores_navigation_and_filters_maintenance():
    bank = website_scraper.BANK_CONFIGS["东亚银行"]
    soup = website_scraper.BeautifulSoup(
        """
        <div class="mainRightInner announcement">
          <ul>
            <li><a href="/PersonalBusiness/CreditCards/Announcements/202607/t20260729_24601.shtml" title="关于东亚中国因系统维护暂停部分银行服务的公告">公告</a></li>
            <li><a href="https://www.hkbea.com.cn/PersonalBusiness/CreditCards/SCC/" title="信用卡产品">信用卡产品</a></li>
          </ul>
        </div>
        """,
        "html.parser",
    )
    items = website_scraper._fallback_detail_links(
        soup,
        bank,
        bank.list_url,
    )
    assert items == []
    assert bank.is_low_value("关于东亚中国因系统维护暂停部分银行服务的公告")
