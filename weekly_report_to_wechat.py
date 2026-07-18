#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_report_to_wechat.py — 根级别 stub，委派到 src/weekly_report_to_wechat"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.weekly_report_to_wechat import main

if __name__ == "__main__":
    main()