#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_docs.py — 根级别 stub，委派到 src/merge_docs。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# re-export src/merge_docs 的全部公开+私有名，供测试 `from merge_docs import ...` 使用
from src.merge_docs import *  # noqa: F401,F403
import src.merge_docs as _m  # noqa: E402
for _name in dir(_m):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_m, _name)

from src.merge_docs import main  # noqa: E402

if __name__ == "__main__":
    main()