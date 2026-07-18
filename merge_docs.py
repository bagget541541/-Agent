#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_docs.py — 根级别 stub，委派到 src/merge_docs"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.merge_docs import main

if __name__ == "__main__":
    main()