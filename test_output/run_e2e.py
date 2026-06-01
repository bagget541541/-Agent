#!/usr/bin/env python3
"""端到端测试：读取实际业务文档"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Redirect output to file
os.makedirs('test_output', exist_ok=True)
f = open('test_output/e2e_result.txt', 'w', encoding='utf-8')

from merge_docs import read_docx_content, merge_contents

# 文件路径
files = [
    '用户上传_农行0529公告分析.docx',
    '用户上传_微信文章解析_南京秦农_0531.docx',
]

contents = []
for fp in files:
    if not os.path.exists(fp):
        f.write(f'[SKIP] File not found: {fp}\n')
        continue
    c = read_docx_content(fp)
    h1 = len(c.get('h1_sections', []))
    h2 = sum(len(s.get('h2_items', [])) for s in c.get('h1_sections', []))
    imgs = len(c.get('images_map', {}))
    f.write(f'\n### {os.path.basename(fp)}\n')
    f.write(f'H1={h1}, H2={h2}, images={imgs}\n')
    for s in c.get('h1_sections', []):
        f.write(f'  H1: {s["title"]}\n')
        for i, h2 in enumerate(s.get('h2_items', [])):
            title = h2['title'][:50]
            url = h2.get('url', '')[:60]
            meta = h2.get('metadata', {})
            f.write(f'    H2[{i}]: {title}\n')
            if url:
                f.write(f'      URL: {url}\n')
            if meta:
                f.write(f'      Meta: {meta}\n')
    contents.append(c)

# Merge
if len(contents) >= 2:
    merged = merge_contents(contents)
    f.write(f'\n### 合并结果\n')
    f.write(f'H1={len(merged["h1_sections"])}\n')
    for s in merged['h1_sections']:
        f.write(f'  H1: {s["title"]} -> {len(s.get("h2_items",[]))} items\n')
        for i, h2 in enumerate(s.get('h2_items', [])):
            f.write(f'    H2[{i}]: {h2["title"][:50]}\n')
    f.write(f'\nSources: {merged["sources"]}\n')

f.write('\n=== DONE ===\n')
f.close()
print('Test completed, see test_output/e2e_result.txt')
