import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
base = Path(__file__).resolve().parent.parent.parent
with open(str(base / 'data' / 'batch_merged.json'), encoding='utf-8') as f:
    bm = json.load(f)

# 找出重复 URL 的两个 item
dup_url = [it for it in bm['items'] if '2247537786' in it.get('url','')]
for it in dup_url:
    print(f'item_id: {it["item_id"]}')
    print(f'  title: {it.get("title")}')
    print(f'  category: {it.get("category")}')
    print(f'  bank: {it.get("bank")}')
    print(f'  extracted_at: {it.get("extracted_at")}')
    print()
