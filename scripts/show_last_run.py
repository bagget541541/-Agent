#!/usr/bin/env python3
"""显示上次运行时间，供 run.bat 调用。

用法:
  python scripts/show_last_run.py              # 默认读 data/last_run.json
  python scripts/show_last_run.py <data_dir>   # 指定 data 目录
"""
import json
import sys
from datetime import datetime
from pathlib import Path

if len(sys.argv) > 1:
    last_run_path = Path(sys.argv[1]) / "last_run.json"
else:
    last_run_path = Path(__file__).resolve().parent.parent / "data" / "last_run.json"

if not last_run_path.exists():
    print("Last run: Never")
    sys.exit(0)

try:
    d = json.loads(last_run_path.read_text(encoding="utf-8"))
    lr = d.get("last_run", "")
    old_days = d.get("bank_days", 7)

    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(lr, fmt)
            break
        except ValueError:
            continue

    if dt:
        days_ago = (datetime.now() - dt).days
        suggested = max(days_ago, old_days, 1)
        print(f"Last run: {lr}  ({days_ago} days ago)")
        print(f"Suggested --bank-days: {suggested}  (cover last {days_ago} days + buffer)")
    else:
        print(f"Last run: {lr}")
except Exception as e:
    print(f"Last run: (error reading: {e})")
