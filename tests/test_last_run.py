#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
last_run.json 运行记录 单元测试
覆盖: _write_last_run, scripts/show_last_run.py
"""

import json
import sys
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ═══════════════════════════════════════════════
#  _write_last_run 测试
# ═══════════════════════════════════════════════

class TestWriteLastRun:
    """测试运行记录写入。"""

    def _get_fn(self):
        from src.agent import _write_last_run
        return _write_last_run

    def test_creates_file(self, tmp_path):
        """应创建 last_run.json 文件。"""
        fn = self._get_fn()
        with patch('src.agent.PROJECT_ROOT', tmp_path):
            fn(bank_days=7)

        lr_path = tmp_path / "data" / "last_run.json"
        assert lr_path.exists()

    def test_file_content(self, tmp_path):
        """文件应包含 last_run 和 bank_days。"""
        fn = self._get_fn()
        with patch('src.agent.PROJECT_ROOT', tmp_path):
            fn(bank_days=14)

        lr_path = tmp_path / "data" / "last_run.json"
        data = json.loads(lr_path.read_text(encoding="utf-8"))
        assert "last_run" in data
        assert data["bank_days"] == 14

    def test_timestamp_format(self, tmp_path):
        """时间戳应为 YYYY-MM-DD HH:MM:SS 格式。"""
        fn = self._get_fn()
        with patch('src.agent.PROJECT_ROOT', tmp_path):
            fn(bank_days=7)

        lr_path = tmp_path / "data" / "last_run.json"
        data = json.loads(lr_path.read_text(encoding="utf-8"))
        # 验证格式
        datetime.strptime(data["last_run"], "%Y-%m-%d %H:%M:%S")

    def test_creates_data_dir(self, tmp_path):
        """应自动创建 data 目录。"""
        fn = self._get_fn()
        # data 目录不存在时也能正常工作
        with patch('src.agent.PROJECT_ROOT', tmp_path):
            fn(bank_days=7)

        assert (tmp_path / "data" / "last_run.json").exists()

    def test_overwrites_existing(self, tmp_path):
        """应覆盖已有的 last_run.json。"""
        fn = self._get_fn()
        lr_path = tmp_path / "data" / "last_run.json"
        lr_path.parent.mkdir(parents=True, exist_ok=True)
        lr_path.write_text('{"last_run": "old"}', encoding="utf-8")

        with patch('src.agent.PROJECT_ROOT', tmp_path):
            fn(bank_days=3)

        data = json.loads(lr_path.read_text(encoding="utf-8"))
        assert data["bank_days"] == 3
        assert "old" not in data["last_run"]


# ═══════════════════════════════════════════════
#  show_last_run.py 测试
# ═══════════════════════════════════════════════

class TestShowLastRun:
    """测试 show_last_run.py 辅助脚本。"""

    def _run_script(self, last_run_data=None):
        """运行 show_last_run.py 并捕获输出。"""
        import subprocess
        script = Path(__file__).resolve().parent.parent / "scripts" / "show_last_run.py"
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            if last_run_data is not None:
                (data_dir / "last_run.json").write_text(
                    json.dumps(last_run_data, ensure_ascii=False), encoding="utf-8"
                )
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(script), str(data_dir)],
                capture_output=True, text=True, encoding="utf-8",
            )
            return result.stdout.strip()

    def test_no_last_run_file(self):
        """无 last_run.json 时应输出 Never。"""
        output = self._run_script(None)
        assert "Never" in output

    def test_with_recent_run(self):
        """有最近运行记录时应显示天数。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        output = self._run_script({"last_run": now, "bank_days": 7})
        assert "0 days ago" in output
        assert "Suggested" in output

    def test_with_old_run(self):
        """有旧运行记录时应显示正确天数。"""
        old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        output = self._run_script({"last_run": old, "bank_days": 7})
        assert "10 days ago" in output
        # suggested 应取 max(10, 7, 1) = 10
        assert "10" in output

    def test_suggested_takes_max(self):
        """建议天数应取 max(days_ago, old_bank_days, 1)。"""
        # 3 天前运行，上次 bank_days=14 → suggested=14
        old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        output = self._run_script({"last_run": old, "bank_days": 14})
        assert "14" in output

    def test_iso_format_timestamp(self):
        """支持 ISO 格式时间戳 (T 分隔)。"""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        output = self._run_script({"last_run": now, "bank_days": 5})
        assert "0 days ago" in output
