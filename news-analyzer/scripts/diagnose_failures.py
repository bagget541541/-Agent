"""诊断中信、农行抓取失败原因"""
import sys
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from website_scraper import BANK_CONFIGS, create_session

# ── 中信诊断 ──
bank = BANK_CONFIGS['中信银行']
session = create_session(bank)
print(f"=== {bank.name} ===")
print(f"URL: {bank.list_url}")
try:
    r = session.get(bank.list_url, timeout=20)
    print(f"status: {r.status_code}, encoding: {r.encoding}, length: {len(r.text)}")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, 'html.parser')
    lis = soup.find_all('li')
    print(f"li tags: {len(lis)}")
    for li in lis[:5]:
        txt = li.get_text(strip=True)[:80]
        a = li.find('a')
        a_title = a.get('title','')[:60] if a else 'n/a'
        gg = li.select_one('.gg_date')
        print(f"  li: {txt} | a.title={a_title} | .gg_date={gg}")
except Exception as e:
    print(f"错误: {e}")

print()

# ── 农行诊断 ──
for bank_name in ['农业银行', '农业银行活动']:
    bank = BANK_CONFIGS.get(bank_name)
    if not bank:
        continue
    session = create_session(bank)
    print(f"=== {bank.name} ===")
    print(f"URL: {bank.list_url}")
    try:
        r = session.get(bank.list_url, timeout=20, verify=False)
        print(f"status: {r.status_code}, encoding: {r.encoding}, length: {len(r.text)}")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        lis = soup.find_all('li')
        print(f"li tags: {len(lis)}")
        for li in lis[:3]:
            txt = li.get_text(strip=True)[:100]
            print(f"  li: {txt}")
    except Exception as e:
        print(f"错误: {e}")
    print()
