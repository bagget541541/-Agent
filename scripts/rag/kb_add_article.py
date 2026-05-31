#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
添加新文章到现有 RAG 知识库。

用法:
  python scripts/rag/kb_add_article.py <markdown文件路径>
  python scripts/rag/kb_add_article.py <目录路径>   # 批量添加目录下所有 .md 文件
"""

import os, re, json, sys
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_PATH = os.path.join(HERE, "data", "articles_kb.json")
BM25_CACHE = os.path.join(HERE, "data", "bm25_cache.pkl")

BANK_MAP = [
    ("工商银行", ["工行","工商银行","工银"]),
    ("农业银行", ["农行","农业银行"]),
    ("中国银行", ["中行","中国银行"]),
    ("建设银行", ["建行","建设银行"]),
    ("邮储银行", ["邮储","邮政储蓄","邮储银行","邮储信用卡"]),
    ("招商银行", ["招行","招商银行","招商"]),
    ("中信银行", ["中信银行","中信"]),
    ("光大银行", ["光大银行","光大"]),
    ("华夏银行", ["华夏银行","华夏"]),
    ("民生银行", ["民生银行","民生"]),
    ("广发银行", ["广发","广发银行","废行"]),
    ("平安银行", ["平安银行","平安口袋","平安"]),
    ("兴业银行", ["兴业银行","兴业"]),
    ("浦发银行", ["浦发","浦发银行"]),
    ("北京银行", ["北京银行","掌上京彩"]),
    ("交通银行", ["交行","交通银行"]),
    ("盛京银行", ["盛京","盛京银行"]),
    ("南京银行", ["南京银行"]),
    ("上海银行", ["上海银行"]),
    ("汇丰银行", ["汇丰","汇丰银行"]),
    ("宁波银行", ["宁波银行"]),
    ("天津银行", ["天津银行"]),
    ("浙商银行", ["浙商银行","浙商"]),
    ("恒丰银行", ["恒丰","恒丰银行"]),
    ("富邦华一", ["富邦华一"]),
    ("渣打银行", ["渣打","渣打银行"]),
]

CATEGORY_KWS = {
    "持卡评判": ["评分","ROI","回血","结余","年省","收益评分","年费评分","值不值"],
    "公告点评": ["公告","通知","发布","升级","缩水","调整","变更","权益变更"],
    "亮点挖掘": ["小众卡","神卡","免年费","返现","亮点"],
    "周报资讯": ["CW","周报","本周","资讯汇总"],
    "知识科普": ["兑换路径","操作路径","查询路径","怎么用"],
}

NL = chr(10)


def parse_fm(text):
    meta = {"title": "", "date": "", "tags": [], "draft": False}
    m = re.match(r"^---\s*" + NL + r"(.*?)" + NL + r"---", text, re.DOTALL)
    if not m:
        return meta
    for line in m.group(1).split(NL):
        line = line.strip()
        if line.startswith("title:"):
            meta["title"] = line[6:].strip().strip(chr(34)).strip(chr(39))
        elif line.startswith("date:"):
            meta["date"] = line[5:].strip()
        elif line.startswith("tags:"):
            ts = re.findall(r'"([^"]+)"', line)
            if ts:
                meta["tags"] = ts
        elif line.startswith("draft:"):
            meta["draft"] = "true" in line.lower()
    return meta


def strip_md(text):
    text = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL | re.MULTILINE)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#*>`~_]", "", text)
    text = re.sub(NL + r"\s*" + NL + r"\s*" + NL, NL + NL, text)
    return text.strip()


def extract_banks(text):
    found = []
    for bname, kws in BANK_MAP:
        for kw in kws:
            if kw in text:
                found.append(bname)
                break
    return found


def classify(title, text):
    cats = {}
    combined = title + " " + text
    for cat, kws in CATEGORY_KWS.items():
        for kw in kws:
            if kw in combined:
                cats[cat] = cats.get(cat, 0) + 1
    if not cats:
        cats["其他"] = 1
    return cats


def is_card_related(title, text, tags):
    if "信用卡" in tags:
        return True
    if any(kw in title for kw in ["信用卡","用卡","刷卡","积分","返现","权益","年费","额度","提额"]):
        return True
    banks_found = extract_banks(text)
    if len(banks_found) >= 2:
        return True
    return False


def smart_chunk(text, sz=500, ov=100):
    secs = re.split(r"(?=^#{1,2}\s)", text, flags=re.MULTILINE)
    chunks = []
    for sec in secs:
        sec = sec.strip()
        if not sec or len(sec) < 20:
            continue
        tm = re.match(r"^#{1,2}\s+(.*)", sec)
        st = tm.group(1).strip() if tm else ""
        sb = sec[tm.end():].strip() if tm else sec
        if len(sec) <= sz:
            chunks.append({"section": st, "text": sec})
            continue
        pars = re.split(NL + r"\s*" + NL, sb)
        cur = (st + NL if st else "") + (pars[0] if pars else "")
        for p in pars[1:]:
            p = p.strip()
            if not p:
                continue
            if len(cur) + len(p) <= sz:
                cur += NL + NL + p
            else:
                if cur.strip():
                    chunks.append({"section": st, "text": cur.strip()})
                cur = (cur[-ov:] if ov < len(cur) else cur) + NL + NL + p
        if cur.strip():
            chunks.append({"section": st, "text": cur.strip()})
    if not chunks and len(text.strip()) > 20:
        chunks.append({"section": "", "text": text.strip()})
    return chunks


def process_article(fpath):
    """处理单个 markdown 文件，返回 (article_id, chunks列表)"""
    with open(fpath, "r", encoding="utf-8") as f:
        raw = f.read()

    meta = parse_fm(raw)
    if meta.get("draft", False):
        return None, None

    fname = os.path.basename(fpath)
    title = meta["title"] or fname.replace(".md", "")
    date_str = meta["date"]
    tags = meta["tags"]

    clean = strip_md(raw)
    if len(clean) < 200:
        return None, None

    cr = is_card_related(title, clean, tags)
    cats = classify(title, clean)
    banks = extract_banks(clean)
    aid = fname.replace(".md", "")

    chunks = smart_chunk(clean)
    entries = []
    for i, ch in enumerate(chunks):
        ct = ch["text"]
        if len(ct) < 30:
            continue
        cb = extract_banks(ct) or banks
        labels = list(cats)
        if cr:
            labels.append("信用卡")
        if any(k in ct for k in ["评分", "结余", "收益", "年省", "年费"]):
            labels.append("含定量计算")
        if any(k in ct for k in ["兑换路径", "操作路径", "查询路径"]):
            labels.append("操作指南")
        entries.append({
            "id": aid + "_chunk" + str(i).zfill(3),
            "article_id": aid,
            "section": ch["section"],
            "text": ct,
            "char_count": len(ct),
            "title": title,
            "date": date_str,
            "source": "历史公众号文章",
            "filename": fname,
            "card_related": cr,
            "categories": cats,
            "labels": labels,
            "banks": cb,
        })

    return aid, entries


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/rag/kb_add_article.py <文件.md> 或 <目录>")
        sys.exit(1)

    target = sys.argv[1]

    # 收集所有要处理的 .md 文件
    files = []
    if os.path.isfile(target) and target.endswith(".md"):
        files.append(target)
    elif os.path.isdir(target):
        for f in sorted(os.listdir(target)):
            if f.endswith(".md"):
                files.append(os.path.join(target, f))
    else:
        print(f"ERROR: 无效路径: {target}")
        sys.exit(1)

    if not files:
        print("没有找到 .md 文件")
        sys.exit(0)

    # 读取现有 KB
    if os.path.isfile(KB_PATH):
        with open(KB_PATH, "r", encoding="utf-8") as f:
            kb = json.load(f)
        existing_ids = set(e["article_id"] for e in kb["entries"])
        print(f"现有 KB: {kb['total_entries']} 条目, {kb['total_articles']} 文章")
    else:
        kb = {
            "generated_at": "",
            "source": "历史公众号文章知识库",
            "total_entries": 0,
            "total_articles": 0,
            "chunk_size": 500,
            "chunk_overlap": 100,
            "entries": [],
        }
        existing_ids = set()
        print("新建 KB")

    new_count = 0
    skip_count = 0
    new_article_ids = set()

    for fpath in files:
        fname = os.path.basename(fpath)
        try:
            aid, entries = process_article(fpath)
        except Exception as e:
            print(f"  SKIP {fname}: {e}")
            skip_count += 1
            continue

        if aid is None:
            print(f"  SKIP {fname}: draft/too short")
            skip_count += 1
            continue

        if aid in existing_ids:
            print(f"  SKIP {fname}: already in KB")
            skip_count += 1
            continue

        # 只添加信用卡相关的文章
        if not entries[0].get("card_related", False):
            print(f"  SKIP {fname}: not card-related")
            skip_count += 1
            continue

        kb["entries"].extend(entries)
        existing_ids.add(aid)
        new_article_ids.add(aid)
        new_count += 1
        print(f"  ADDED {fname}: {len(entries)} chunks, card_related={entries[0]['card_related']}")

    if new_count == 0:
        print(f"\n无新文章添加 (跳过 {skip_count})")
        return

    # 更新 metadata
    all_aids = set(e["article_id"] for e in kb["entries"])
    kb["total_entries"] = len(kb["entries"])
    kb["total_articles"] = len(all_aids)
    kb["generated_at"] = datetime.now().isoformat(timespec="seconds")

    # 保存
    os.makedirs(os.path.dirname(KB_PATH), exist_ok=True)
    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

    # 删除 BM25 缓存（下次查询自动重建）
    if os.path.isfile(BM25_CACHE):
        os.remove(BM25_CACHE)
        cache_msg = "已删除缓存"
    else:
        cache_msg = "无缓存"

    print(f"\n结果: 新增 {new_count} 篇文章, {sum(1 for e in kb['entries'] if e['article_id'] in new_article_ids)} 条目")
    print(f"KB 总计: {kb['total_entries']} 条目, {kb['total_articles']} 文章")
    print(f"BM25 {cache_msg}")


if __name__ == "__main__":
    main()
