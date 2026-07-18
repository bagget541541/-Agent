#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md_merge.py — 根级别 stub，委派到 src/md_merge"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.md_merge import main

if __name__ == "__main__":
    main()