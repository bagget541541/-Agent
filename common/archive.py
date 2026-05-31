"""
知识库归档模块

每次管线执行完成后调用 archive_batch()，将当前批次数据归档到：
    data/archive/{YYYY}/{MM}/{batch_label}/

产出物：
    batch.json      — 批次完整数据
    周报.docx       — Word 周报（若有）
    持卡分析.md      — 持卡分析 Markdown（若有）
    持卡分析.json    — 持卡分析结构化数据（若有）
    images/         — 批次关联图片
    manifest.json   — 归档清单（元数据）
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import ARCHIVE_DIR


def archive_batch(
    batch,
    docx_path: Optional[str] = None,
    analysis_md_path: Optional[str] = None,
    analysis_json_path: Optional[str] = None,
) -> str:
    """归档一个批次的所有产出物。

    Args:
        batch: CreditCardBatch 实例
        docx_path: Word 周报文件路径
        analysis_md_path: 持卡分析 Markdown 文件路径
        analysis_json_path: 持卡分析 JSON 文件路径

    Returns:
        str: 归档目录的绝对路径
    """
    label = batch.batch_label or datetime.now().strftime("batch_%Y%m%d_%H%M%S")
    now = datetime.now()

    # 安全文件名：去掉非法字符
    safe_label = "".join(c if c.isalnum() or c in " _-." else "_" for c in label)
    archive_path = ARCHIVE_DIR / str(now.year) / f"{now.month:02d}" / safe_label
    archive_path.mkdir(parents=True, exist_ok=True)

    # 1. 批次 JSON
    batch_json = archive_path / "batch.json"
    batch.save_json(str(batch_json))
    print(f"  [归档] 批次数据 → {batch_json}")

    # 2. Word 周报
    if docx_path and os.path.isfile(docx_path):
        shutil.copy2(docx_path, archive_path / "周报.docx")
        print(f"  [归档] 周报 → {archive_path / '周报.docx'}")

    # 3. 持卡分析
    if analysis_md_path and os.path.isfile(analysis_md_path):
        shutil.copy2(analysis_md_path, archive_path / "持卡分析.md")
        print(f"  [归档] 分析报告 → {archive_path / '持卡分析.md'}")
    if analysis_json_path and os.path.isfile(analysis_json_path):
        shutil.copy2(analysis_json_path, archive_path / "持卡分析.json")
        print(f"  [归档] 分析数据 → {archive_path / '持卡分析.json'}")

    # 4. 关联图片
    img_dir = archive_path / "images"
    copied_images = 0
    for item in batch.items:
        for img_path in item.images:
            if os.path.isfile(img_path):
                img_dir.mkdir(exist_ok=True)
                dest = img_dir / os.path.basename(img_path)
                if not dest.exists():
                    shutil.copy2(img_path, dest)
                    copied_images += 1
    if copied_images:
        print(f"  [归档] 图片 × {copied_images} → {img_dir}")

    # 5. Manifest
    manifest = {
        "archive_time": datetime.now().isoformat(timespec="seconds"),
        "batch_label": label,
        "total_items": len(batch.items),
        "categories": {
            cat: len(batch.by_category(cat))
            for cat in ["新卡", "权益变更", "活动", "公告", "其他"]
        },
        "banks": sorted(set(it.bank for it in batch.items if it.bank)),
        "has_docx": bool(docx_path and os.path.isfile(docx_path)),
        "has_analysis": bool(
            analysis_md_path and os.path.isfile(analysis_md_path)
        ),
        "image_count": copied_images,
    }
    with open(archive_path / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 6. 更新全局索引
    _update_archive_index()

    return str(archive_path)


def list_archives() -> list[dict]:
    """列出所有已归档批次。

    Returns:
        list[dict]: 按归档时间倒序排列的 manifest 列表
    """
    index_file = ARCHIVE_DIR / "index.json"
    if index_file.exists():
        return json.loads(index_file.read_text(encoding="utf-8"))
    return []


def _update_archive_index() -> None:
    """扫描 archive 目录，重建 index.json。"""
    index = []
    if not ARCHIVE_DIR.exists():
        return

    for year_dir in sorted(ARCHIVE_DIR.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            for batch_dir in sorted(month_dir.iterdir()):
                manifest_file = batch_dir / "manifest.json"
                if manifest_file.exists():
                    manifest = json.loads(
                        manifest_file.read_text(encoding="utf-8")
                    )
                    rel_path = batch_dir.relative_to(
                        ARCHIVE_DIR.parent.parent
                    )
                    manifest["path"] = str(rel_path.as_posix())
                    index.append(manifest)

    index.sort(key=lambda x: x.get("archive_time", ""), reverse=True)
    with open(ARCHIVE_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
