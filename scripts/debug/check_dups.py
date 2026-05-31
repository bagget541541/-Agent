#!/usr/bin/env python3
"""检查数据库重复内容"""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent

print("=" * 60)
print("1. batch_merged.json — 当前批次合并数据")
print("=" * 60)
bm_path = BASE / "data/batch_merged.json"
if bm_path.exists():
    with open(bm_path, encoding="utf-8") as f:
        bm = json.load(f)
    items = bm.get("items", [])
    ids = [it["item_id"] for it in items]
    urls = [it.get("url", "") for it in items]
    titles = [
        it.get("normalized_title") or it.get("raw_title") or it.get("title", "")
        for it in items
    ]
    print(f"  total items: {len(items)}")
    print(f"  unique item_ids: {len(set(ids))}")
    print(f"  unique urls: {len(set(urls))}")
    print(f"  unique titles: {len(set(titles))}")

    # 重复 URL
    url_dup = {k: v for k, v in Counter(urls).items() if v > 1}
    if url_dup:
        print(f"\n  ⚠ 重复 URL ({len(url_dup)} 组):")
        for url, cnt in sorted(url_dup.items(), key=lambda x: -x[1])[:10]:
            print(f"    x{cnt}: {url[:100]}")
    else:
        print("  ✅ URL 全部唯一")

    # 重复标题
    title_dup = {k: v for k, v in Counter(titles).items() if v > 1}
    if title_dup:
        print(f"\n  ⚠ 重复标题 ({len(title_dup)} 组):")
        for t, cnt in sorted(title_dup.items(), key=lambda x: -x[1])[:10]:
            print(f"    x{cnt}: {t[:80]}")
    else:
        print("  ✅ 标题全部唯一")

    # 来源分布
    sources = Counter(it.get("source", "unknown") for it in items)
    print(f"\n  来源分布:")
    for src, cnt in sources.most_common():
        print(f"    {src}: {cnt}")
else:
    print("  (文件不存在)")

print()
print("=" * 60)
print("2. articles_kb.json — RAG 知识库(分块)")
print("=" * 60)
kb_path = BASE / "data/articles_kb.json"
if kb_path.exists():
    with open(kb_path, encoding="utf-8") as f:
        kb = json.load(f)
    entries = kb.get("entries", [])
    article_ids = [e["article_id"] for e in entries]
    aid_counter = Counter(article_ids)
    dup_aids = {k: v for k, v in aid_counter.items() if v > 1}
    print(f"  total entries: {len(entries)}")
    print(f"  total articles (unique id): {len(set(article_ids))}")
    print(f"  (分块是正常现象，每个 article_id 对应多个 chunk)")
    if dup_aids:
        max_chunks = max(dup_aids.values())
        print(f"  单篇文章最多分块数: {max_chunks}")
    kb_articles_count = len(kb.get("entries", []))
else:
    print("  (文件不存在)")

print()
print("=" * 60)
print("3. articles_kb_index.json — RAG 知识库索引")
print("=" * 60)
idx_path = BASE / "data/articles_kb_index.json"
if idx_path.exists():
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    arts = idx.get("articles", [])
    a_ids = [a["id"] for a in arts]
    dup_ids = {k: v for k, v in Counter(a_ids).items() if v > 1}
    print(f"  total articles: {len(arts)}")
    print(f"  unique ids: {len(set(a_ids))}")
    card_related = sum(1 for a in arts if a.get("card_related"))
    print(f"  card_related 文章: {card_related}")
    if dup_ids:
        print(f"\n  ⚠ 重复 article id ({len(dup_ids)} 组):")
        for aid, cnt in sorted(dup_ids.items(), key=lambda x: -x[1])[:10]:
            print(f"    x{cnt}: {aid}")
    else:
        print("  ✅ article ids 全部唯一")
else:
    print("  (文件不存在)")

print()
print("=" * 60)
print("4. wechat_articles.json — 微信抓取原始数据")
print("=" * 60)
wa_path = BASE / "data/wechat_articles.json"
if wa_path.exists():
    try:
        with open(wa_path, encoding="utf-8") as f:
            wa = json.load(f)
    except UnicodeDecodeError:
        with open(wa_path, encoding="gbk") as f:
            wa = json.load(f)
    print(f"  total URL entries: {len(wa)}")
else:
    print("  (文件不存在)")

print()
print("=" * 60)
print("5. data/archive/ 下的历史归档")
print("=" * 60)
archive_dir = BASE / "data/archive"
if archive_dir.exists():
    json_files = list(archive_dir.rglob("*.json"))
    total_archived = 0
    for jf in sorted(json_files):
        if jf.name == "index.json":
            continue
        try:
            with open(jf, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "items" in d:
                n = len(d["items"])
                total_archived += n
                print(f"  {jf.relative_to(BASE)}: {n} items")
        except:
            pass
    print(f"\n  历史归档总计: {total_archived} items")
else:
    print("  (目录不存在)")

print()
print("=" * 60)
print("6. 图片目录中的图片数量")
print("=" * 60)
img_dir = BASE / "data/images"
if img_dir.exists():
    img_files = list(img_dir.rglob("*"))
    imgs = [f for f in img_files if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif")]
    print(f"  images 总数: {len(imgs)}")
    # 子目录
    subdirs = sorted([d for d in img_dir.iterdir() if d.is_dir()])
    print(f"  按 item_id 分组的子目录: {len(subdirs)} 个")
else:
    print("  (目录不存在)")
