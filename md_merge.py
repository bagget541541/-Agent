#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md_merge.py — 根级别 stub，委派到 src/md_merge。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# re-export src/md_merge 的全部公开+私有名，供测试 `from md_merge import ...` 使用
from src.md_merge import *  # noqa: F401,F403
import src.md_merge as _m  # noqa: E402
for _name in dir(_m):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_m, _name)

from src.md_merge import main  # noqa: E402

if __name__ == "__main__":
    main()