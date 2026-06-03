#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pipeline.py — 根级别 stub，委派到 src/agent

被 run.bat 按 python run_pipeline.py 调用（兼容旧入口）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.agent import main

if __name__ == "__main__":
    main()
