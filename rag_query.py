#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rag_query.py — 根级别 stub，委派到 src/rag_query

被 _agent.py、merge_docs.py import。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.rag_query import *

if __name__ == "__main__":
    main()
