"""测试 Selenium 降级抓取部分JS渲染银行。"""
import sys, os

# 设置标准输出编码为 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'buffer'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from website_scraper import BANK_CONFIGS, fetch_list_page, HAS_SELENIUM

print(f"Selenium 可用: {HAS_SELENIUM}")
print()

# 测试需要 JS 渲染的银行
selenium_banks = ["招商银行", "浦发银行", "交通银行", "北京银行", "建设银行"]
for name in selenium_banks:
    if name not in BANK_CONFIGS:
        print(f"[跳过] {name} 无配置")
        continue
    bank = BANK_CONFIGS[name]
    print(f"── {name} ──")
    print(f"  URL: {bank.list_url}")
    items = fetch_list_page(bank)
    print(f"  抓取到 {len(items)} 条公告")
    for it in items[:3]:
        title = it.get('title','').replace('\u25aa','').strip()
        print(f"    - {it.get('date_str',''):<12} {title}")
    print()
