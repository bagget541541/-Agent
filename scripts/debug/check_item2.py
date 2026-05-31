import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
base = Path(__file__).resolve().parent.parent.parent
with open(str(base / 'data' / 'batch_merged.json'), encoding='utf-8') as f:
    bm = json.load(f)

dup_url_items = [it for it in bm['items'] if '2247537786' in it.get('url','')]
for it in dup_url_items:
    print(f'item_id:    {it["item_id"]}')
    print(f'title:      {it.get("title")}')
    print(f'is_multi_topic_split: {it.get("is_multi_topic_split")}')
    print(f'url:        {it.get("url","")[:120]}')
    print(f'source_article_title: {it.get("source_article_title","")}')
    print(f'raw_title:  {it.get("raw_title","")}')
    print()
