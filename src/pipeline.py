#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Credit Card Weekly Report - Interactive Entry

Mode A: WeChat URLs + Bank scraping -> Generate report
Mode B: Existing Word docs -> Merge + Suggestions -> Output
"""

import json
import os
import shlex
import sys
import subprocess
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from common.utils import get_week_label  # noqa: E402
from common.errors import log_info, log_warn, log_error  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data"
LAST_RUN_FILE = DATA_DIR / "last_run.json"


def update_last_run():
    """Update last run time"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LAST_RUN_FILE, 'w', encoding='utf-8') as f:
        json.dump({"last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)


def run_step(desc, cmd):
    """Run a step safely without shell=True."""
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"{'='*60}")
    args = shlex.split(cmd)
    result = subprocess.run(args, cwd=str(PROJECT_ROOT))
    return result.returncode == 0


def mode_a():
    """Mode A: Full pipeline"""
    print("\nEnter WeChat article URLs (one per line, empty line to finish):")
    print("  Example: https://mp.weixin.qq.com/s/xxxxx")
    print("  Tip: You can paste multiple URLs, one per line")
    print()

    urls = []
    while True:
        url = input("URL> ").strip()
        if not url:
            break
        if "mp.weixin.qq.com" in url:
            urls.append(url)
            print(f"  OK added ({len(urls)} total)")
        else:
            print(f"  SKIP Not a WeChat link, skipped")

    print(f"\nTotal: {len(urls)} WeChat URLs")

    # Bank scraping days
    days_input = input("\nBank scraping days (default 7): ").strip()
    days = int(days_input) if days_input.isdigit() else 7
    print(f"  Scraping last {days} days of bank announcements")

    # Build command
    cmd_parts = ["python _agent.py"]
    if urls:
        cmd_parts.append(f"--wechat-url {' '.join(urls)}")
    cmd_parts.append(f"--bank-days {days}")
    cmd_parts.append("--scorer llm")

    # Execute
    success = run_step("Running full pipeline", " ".join(cmd_parts))

    if success:
        print("\n" + "="*60)
        print("  Pipeline completed!")
        print("="*60)
        # List generated files
        for f in DATA_DIR.glob("*.docx"):
            print(f"  [File] {f.name}")
    else:
        print("\n[Warning] Pipeline may have errors, check output above")

    return success


def mode_b():
    """Mode B: Merge existing documents"""
    print("\nEnter Word document paths (one per line, empty line to finish):")
    print("  Example: D:\\Reports\\weekly_report.docx")
    print("  Tip: You can drag files to the window")
    print()

    docx_files = []
    while True:
        path = input("File> ").strip().strip('"')
        if not path:
            break
        if path.lower().endswith('.docx') and os.path.exists(path):
            docx_files.append(path)
            print(f"  OK {Path(path).name}")
        elif os.path.exists(path):
            print(f"  SKIP Not a docx file, skipped")
        else:
            print(f"  SKIP File not found: {path}")

    if not docx_files:
        print("No files provided, cancelled")
        return False

    print(f"\nTotal: {len(docx_files)} documents to merge")

    # Execute merge
    success = run_step("Merge documents + Generate suggestions", f"python merge_docs.py --input {' '.join(f'\"{f}\"' for f in docx_files)}")

    if success:
        print("\n" + "="*60)
        print("  Merge completed!")
        print("="*60)
        for f in DATA_DIR.glob("*.docx"):
            print(f"  [File] {f.name}")
    else:
        print("\n[Warning] Merge may have errors, check output above")

    return success


def mode_c():
    """Mode C: Steps 1-4 only, output Markdown with images"""
    print("\nEnter WeChat article URLs (one per line, empty line to finish):")
    print("  Example: https://mp.weixin.qq.com/s/xxxxx")
    print("  Tip: You can paste multiple URLs, one per line")
    print()

    urls = []
    while True:
        url = input("URL> ").strip()
        if not url:
            break
        if "mp.weixin.qq.com" in url:
            urls.append(url)
            print(f"  OK added ({len(urls)} total)")
        else:
            print(f"  SKIP Not a WeChat link, skipped")

    print(f"\nTotal: {len(urls)} WeChat URLs")

    # Bank scraping days
    days_input = input("\nBank scraping days (default 7): ").strip()
    days = int(days_input) if days_input.isdigit() else 7
    print(f"  Scraping last {days} days of bank announcements")

    # Build command
    cmd_parts = ["python _agent.py", "--mode c"]
    if urls:
        cmd_parts.append(f"--wechat-url {' '.join(urls)}")
    cmd_parts.append(f"--bank-days {days}")

    # Execute
    success = run_step("Running Mode C (Steps 1-4, MD output)", " ".join(cmd_parts))

    if success:
        print("\n" + "="*60)
        print("  Mode C completed!")
        print("="*60)
        for f in DATA_DIR.glob("*.md"):
            print(f"  [File] {f.name}")
    else:
        print("\n[Warning] Pipeline may have errors, check output above")

    return success


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description='Credit Card Weekly Report Entry')
    parser.add_argument('--mode', choices=['a', 'b', 'c'], default='a', help='Run mode (default: a)')
    args = parser.parse_args()

    if args.mode == 'a':
        success = mode_a()
    elif args.mode == 'c':
        success = mode_c()
    else:
        success = mode_b()

    update_last_run()

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
