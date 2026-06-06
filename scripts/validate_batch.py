#!/usr/bin/env python3
"""Validate a batch JSON produced by merge_docs.py

Checks:
 - each item has title/raw_text
 - url exists (top-level or structured)
 - images paths exist on disk
 - image size and aspect ratio (flag likely-ad images)

Usage:
  python scripts/validate_batch.py --input data/merge_test_0606_generated.json --output data/merge_test_0606_report.json
"""
import os
import json
import argparse
from PIL import Image


def is_ad_like(path):
    try:
        size_kb = os.path.getsize(path) / 1024
        with Image.open(path) as im:
            w, h = im.size
        if w == 0 or h == 0:
            return True
        ratio = w / h
        short_side = min(w, h)
        if size_kb < 15 and short_side < 100:
            return True
        if ratio > 3.5:
            return True
        if ratio < 0.15 and w < 200:
            return True
        if short_side < 200 and size_kb < 50:
            return True
        return False
    except Exception:
        return False


def validate(input_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        batch = json.load(f)

    report = {
        'input': input_path,
        'total_items': 0,
        'items': [],
        'missing_images': [],
        'ad_like_images': [],
    }

    items = batch.get('items', [])
    report['total_items'] = len(items)

    for i, it in enumerate(items):
        rec = {'index': i, 'title': it.get('title',''), 'issues': [], 'images': []}
        if not it.get('title'):
            rec['issues'].append('missing_title')
        if not it.get('raw_text'):
            rec['issues'].append('missing_raw_text')

        url = it.get('url') or (it.get('structured') or {}).get('原文链接') or (it.get('structured') or {}).get('来源')
        if not url:
            rec['issues'].append('missing_url')

        imgs = it.get('images') or []
        for p in imgs:
            img_rec = {'path': p, 'exists': False, 'ad_like': None, 'w': None, 'h': None}
            if os.path.isfile(p):
                img_rec['exists'] = True
                try:
                    with Image.open(p) as im:
                        w,h = im.size
                    img_rec['w'] = w
                    img_rec['h'] = h
                    img_rec['ad_like'] = is_ad_like(p)
                    if img_rec['ad_like']:
                        report['ad_like_images'].append(p)
                except Exception:
                    rec['issues'].append('image_load_error:'+os.path.basename(p))
            else:
                report['missing_images'].append(p)
                rec['issues'].append('image_missing:'+os.path.basename(p))
            rec['images'].append(img_rec)

        report['items'].append(rec)

    # deduplicate lists
    report['missing_images'] = sorted(list(set(report['missing_images'])))
    report['ad_like_images'] = sorted(list(set(report['ad_like_images'])))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    rpt = validate(args.input)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(rpt, f, ensure_ascii=False, indent=2)
    print('Wrote report to', args.output)


if __name__ == '__main__':
    main()
