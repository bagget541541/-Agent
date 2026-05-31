#!/usr/bin/env python3
"""
孤立图片清理脚本

扫描 data/images/ 目录，找出未被任何归档批次（data/archive/**/batch.json）或
当前批次（data/batch_merged.json）引用的图片文件，支持列出和删除。

用法：
    python scripts/cleanup_images.py              # 仅列出孤立图片
    python scripts/cleanup_images.py --delete     # 删除孤立图片
    python scripts/cleanup_images.py --dry-run    # 模拟删除（列出会被删的）
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # 项目根目录
IMAGES_DIR = HERE / "data" / "images"
BATCH_FILE = HERE / "data" / "batch_merged.json"
ARCHIVE_DIR = HERE / "data" / "archive"


def collect_referenced_images() -> set[str]:
    """收集所有被引用的图片绝对路径。"""
    referenced: set[str] = set()

    # 1. 当前批次 batch_merged.json
    if BATCH_FILE.exists():
        try:
            with open(BATCH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items") or data.get("entries") or (data if isinstance(data, list) else [])
            if isinstance(items, dict):
                items = items.values()
            for item in items:
                if isinstance(item, dict):
                    for img in (item.get("images") or []):
                        if img:
                            referenced.add(os.path.abspath(img))
        except Exception as e:
            print(f"[警告] 读取 {BATCH_FILE} 失败: {e}", file=sys.stderr)

    # 2. 归档批次 data/archive/**/batch.json
    if ARCHIVE_DIR.exists():
        for batch_file in ARCHIVE_DIR.rglob("batch.json"):
            try:
                with open(batch_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("items") or data.get("entries") or (data if isinstance(data, list) else [])
                if isinstance(items, dict):
                    items = items.values()
                for item in items:
                    if isinstance(item, dict):
                        for img in (item.get("images") or []):
                            if img:
                                referenced.add(os.path.abspath(img))
            except Exception as e:
                print(f"[警告] 读取 {batch_file} 失败: {e}", file=sys.stderr)

    return referenced


def find_all_images() -> list[Path]:
    """扫描 data/images/ 下所有图片文件。"""
    if not IMAGES_DIR.exists():
        return []
    return [p for p in IMAGES_DIR.rglob("*") if p.is_file() and p.suffix.lower() in (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"
    )]


def main():
    # Windows GBK 终端兼容：输出用 UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="清理未被引用的孤立图片")
    parser.add_argument("--delete", action="store_true", help="删除孤立图片")
    parser.add_argument("--dry-run", action="store_true", help="模拟删除（只列出不删除）")
    args = parser.parse_args()

    all_images = find_all_images()
    referenced = collect_referenced_images()

    # 规范化引用路径
    referenced_normalized = set()
    for ref in referenced:
        try:
            referenced_normalized.add(os.path.normcase(os.path.normpath(ref)))
        except Exception:
            pass

    orphaned: list[Path] = []
    for img_path in all_images:
        abs_path = os.path.normcase(os.path.normpath(str(img_path.resolve())))
        if abs_path not in referenced_normalized:
            orphaned.append(img_path)

    print(f"图片目录: {IMAGES_DIR}")
    print(f"总计图片文件: {len(all_images)}")
    print(f"被引用图片: {len(referenced)}")
    print(f"孤立图片: {len(orphaned)}")
    print()

    if not orphaned:
        print("✅ 没有发现孤立图片。")
        return

    print("孤立图片列表:")
    for p in orphaned:
        rel = p.relative_to(HERE)
        size = p.stat().st_size
        print(f"  {rel}  ({size / 1024:.1f} KB)")

    if args.delete or args.dry_run:
        deleted = 0
        size_freed = 0
        for p in orphaned:
            size_freed += p.stat().st_size
            if args.delete:
                p.unlink()
                deleted += 1
            else:
                print(f"  [模拟] 删除 {p.relative_to(HERE)}")
                deleted += 1

        # 尝试删除空子目录
        if IMAGES_DIR.exists():
            for subdir in sorted(IMAGES_DIR.iterdir(), reverse=True):
                if subdir.is_dir():
                    try:
                        subdir.rmdir()  # 只删除空目录
                    except OSError:
                        pass

        action = "删除" if args.delete else "模拟删除"
        print(f"\n{action}完成: {deleted} 个文件, 释放 {size_freed / 1024:.1f} KB")
    else:
        print(f"\n💡 提示: 使用 --delete 删除以上孤立图片，或 --dry-run 模拟。")

    # 列出各 item_id 子目录的文件数
    if IMAGES_DIR.exists():
        subdirs = sorted(d for d in IMAGES_DIR.iterdir() if d.is_dir())
        if subdirs:
            print(f"\n子目录文件数:")
            for d in subdirs:
                count = len(list(d.iterdir()))
                ref_count = sum(
                    1 for f in d.iterdir()
                    if os.path.normcase(os.path.normpath(str(f.resolve()))) in referenced_normalized
                )
                orphan_count = count - ref_count
                status = "✅" if orphan_count == 0 else f"⚠️ {orphan_count}个孤立"
                print(f"  {d.name}/  {count} 文件 ({status})")


if __name__ == "__main__":
    main()
