#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_agent.py — 根级别 stub，委派到 src/agent

bat 文件和 run_pipeline.py 按 python _agent.py 调用此文件。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.agent import main

if __name__ == "__main__":
    main()
