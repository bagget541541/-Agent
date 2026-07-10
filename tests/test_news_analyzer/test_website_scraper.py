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
