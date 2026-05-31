"""深度诊断中信银行页面结构"""
import sys
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from website_scraper import BANK_CONFIGS, create_session

bank = BANK_CONFIGS['中信银行']
session = create_session(bank)
r = session.get(bank.list_url, timeout=20)
r.encoding = 'utf-8'  # force utf-8

from bs4 import BeautifulSoup
soup = BeautifulSoup(r.text, 'html.parser')

# 找带有公告内容的容器
print("=== 搜索 gg_date ===")
for el in soup.select('.gg_date'):
    parent = el.parent
    print(f"  parent tag: {parent.name}, class: {parent.get('class','')}")
    print(f"  text: {el.get_text(strip=True)}")

print("\n=== 搜索 a 标题包含公告的 li ===")
for li in soup.find_all('li'):
    a = li.find('a', href=True)
    if a:
        title = a.get('title','') or a.get_text(strip=True)
        if '公告' in title:
            print(f"  li: {title[:60]}")
            print(f"    a href: {a.get('href','')}")
            gg = li.select_one('.gg_date')
            if gg:
                print(f"    .gg_date: {gg.get_text(strip=True)}")
            # show HTML snippet
            print(f"    HTML: {str(li)[:200]}")

print("\n=== 搜索公告正文区域 ===")
# 可能内容在 main/div.content 等区域里
for sel in ['.content', '.main', 'main', '#content', '.list', '.gg_list', '.article-list', '.news-list', '.notice-list']:
    els = soup.select(sel)
    if els:
        print(f"  {sel}: {len(els)} elements")
        for el in els[:2]:
            print(f"    HTML: {str(el)[:200]}")
