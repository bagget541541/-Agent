#!/usr/bin/env python3
"""检查每条 item 的图片在原始 docx 中的段落位置与 JSON 中记录的路径顺序是否一致，给出人工建议。

用法:
  python scripts/check_image_placement.py --input data/merge_test_0606.json --output data/merge_test_0606_image_placement.json
"""
import json
import argparse
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import merge_docs


def extract_rid_from_path(p: str):
    # 图片文件名 like rId9_55164b081f86.png
    base = os.path.basename(p)
    if base.startswith('rId'):
        parts = base.split('_')
        return parts[0]
    return None


def find_h2_for_item(doc_content, title, similarity_thresh=0.75):
    # 使用 merge_docs._title_similarity 进行匹配
    best = None
    best_score = 0.0
    for h1 in doc_content.get('h1_sections', []):
        for h2 in h1.get('h2_items', []):
            t = h2.get('title','')
            score = merge_docs._title_similarity(title, t)
            if score > best_score:
                best_score = score
                best = h2
    if best_score >= similarity_thresh:
        return best, best_score
    return None, best_score


def check(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        batch = json.load(f)

    report = {'input': input_path, 'items': []}

    for i, it in enumerate(batch.get('items', [])):
        rec = {'index': i, 'title': it.get('title',''), 'source': it.get('_source_file',''), 'issues': [], 'suggestions': []}

        src = it.get('_source_file')
        if not src:
            rec['issues'].append('no_source_file')
            report['items'].append(rec)
            continue

        docx_path = Path('data') / src
        if not docx_path.exists():
            rec['issues'].append('source_doc_missing')
            report['items'].append(rec)
            continue

        # parse docx using merge_docs.read_docx_content
        content = merge_docs.read_docx_content(str(docx_path))
        h2, score = find_h2_for_item(content, it.get('title',''))
        rec['match_score'] = score
        if not h2:
            rec['issues'].append('h2_not_found')
            report['items'].append(rec)
            continue

        doc_rids = h2.get('images', [])
        json_rids = [extract_rid_from_path(p) for p in (it.get('images') or [])]

        rec['doc_rids'] = doc_rids
        rec['json_rids'] = json_rids

        # compare sequences
        if doc_rids == json_rids:
            rec['suggestions'].append('ok_order')
        else:
            rec['issues'].append('order_mismatch')
            # suggest remapping to document order
            mapped_paths = []
            # build map rid -> path for available image paths
            rid2path = {}
            for p in (it.get('images') or []):
                rid = extract_rid_from_path(p)
                if rid:
                    rid2path[rid] = p

            for rid in doc_rids:
                mapped_paths.append(rid2path.get(rid))

            rec['suggestions'].append({'remap_to_doc_order': mapped_paths})
            rec['suggestions'].append('请人工打开源文档，定位条目并确认图片应按上面文档顺序显示；如需自动修正，可用脚本将 JSON 中 images 按文档顺序重写。')

        report['items'].append(rec)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print('Wrote', output_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    check(args.input, args.output)


if __name__ == '__main__':
    main()
