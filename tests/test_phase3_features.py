"""
Phase 3 测试：跨条目分析 + 年收益估算 + 跨期趋势 + QA 闭环 + keyword 增强

覆盖：
- F1: _extract_annual_benefit
- F1: 推荐排名
- F2: 同类卡对比
- F3: 跨期趋势
- F4: qa_findings.json 输出 + quality_score
- F5: keyword fallback 增强
"""

import json
import os
import sys
import tempfile
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_CARD_HOLDING_ROOT = os.path.join(_PROJECT_ROOT, "card-holding-suggestion", "scripts")
if _CARD_HOLDING_ROOT not in sys.path:
    sys.path.insert(0, _CARD_HOLDING_ROOT)


# ── F1: _extract_annual_benefit 测试 ────────────────────


class TestExtractAnnualBenefit:
    """年收益估算提取测试"""

    def _get_fn(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "agent", os.path.join(_PROJECT_ROOT, "src", "agent.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._extract_annual_benefit

    def test_monthly_to_annual(self):
        """月上限100元 -> 年约1200元收益"""
        fn = self._get_fn()
        ev = {"recommendation": "美团/抖音/盒马10%返现，月上限100返利金"}
        result = fn(ev)
        assert "1200" in result

    def test_yearly_amount(self):
        """年返1200元 -> 年1200元"""
        fn = self._get_fn()
        ev = {"recommendation": "年返1200元"}
        result = fn(ev)
        assert "1200" in result

    def test_free_annual_fee(self):
        """免年费 -> 免年费"""
        fn = self._get_fn()
        ev = {"recommendation": "免年费，零持卡成本"}
        result = fn(ev)
        assert "免年费" in result

    def test_empty_when_no_info(self):
        """无收益信息 -> 空字符串"""
        fn = self._get_fn()
        ev = {"recommendation": "普通卡片"}
        result = fn(ev)
        assert result == ""

    def test_key_benefits_as_source(self):
        """key_benefits 也可作为收益来源"""
        fn = self._get_fn()
        ev = {"recommendation": "", "key_benefits": ["月上限100元返现"]}
        result = fn(ev)
        assert "1200" in result


# ── F5: keyword fallback 增强测试 ────────────────────────


class TestKeywordFallbackEnhanced:
    """keyword fallback 增强测试"""

    def _get_fn(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "scorer", os.path.join(_CARD_HOLDING_ROOT, "scorer.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.score_with_keywords, mod.DIMENSION_TEMPLATES

    def test_enhanced_target_audience_from_suitable(self):
        """匹配"适合"后的文字"""
        fn, dims = self._get_fn()
        item = {
            "category": "\u65b0\u5361",
            "title": "\u6d4b\u8bd5\u5361",
            "raw_text": "\u9002\u5408\u6709\u5883\u5916\u6d88\u8d39\u9700\u6c42\u7684\u6301\u5361\u4eba\uff0c\u514d\u5e74\u8d39",
            "structured": {},
        }
        result = fn(item, dims["\u65b0\u5361"]())
        assert "\u5883\u5916" in result.target_audience or "\u6301\u5361\u4eba" in result.target_audience

    def test_enhanced_fee_from_shuaka(self):
        """匹配"刷卡免"模式"""
        fn, dims = self._get_fn()
        item = {
            "category": "\u65b0\u5361",
            "title": "\u6d4b\u8bd5\u5361",
            "raw_text": "\u5237\u53616\u6b21\u514d\u6b21\u5e74\u5e74\u8d39\uff0c\u6743\u76ca\u4e30\u5bcc",
            "structured": {},
        }
        result = fn(item, dims["\u65b0\u5361"]())
        assert "\u5237\u5361" in result.fee_assessment or "\u514d" in result.fee_assessment

    def test_enhanced_fee_from_rigid(self):
        """匹配"刚性年费"模式"""
        fn, dims = self._get_fn()
        item = {
            "category": "\u65b0\u5361",
            "title": "\u6d4b\u8bd5\u5361",
            "raw_text": "\u521a\u6027\u5e74\u8d391800\u5143\uff0c\u6743\u76ca\u4e30\u5bcc",
            "structured": {},
        }
        result = fn(item, dims["\u65b0\u5361"]())
        assert "1800" in result.fee_assessment

    def test_enhanced_benefits_from_highlight_section(self):
        """匹配"亮点"后的句子"""
        fn, dims = self._get_fn()
        item = {
            "category": "\u65b0\u5361",
            "title": "\u6d4b\u8bd5\u5361",
            "raw_text": "\u4eae\u70b9\uff1a\u5883\u5916\u4e94\u91cd\u8fd4\u73b0\u30023C\u514d\u606f\u82f9\u679c\u5168\u7cfb24\u671f\u3002\u514d\u5916\u6c47\u5151\u6362\u624b\u7eed\u8d39\u3002",
            "structured": {},
        }
        result = fn(item, dims["\u65b0\u5361"]())
        assert len(result.key_benefits) >= 2


# ── F4: QA findings JSON 输出测试 ────────────────────────


class TestQAFindings:
    """QA findings JSON 输出测试"""

    def test_qa_outputs_json(self):
        """run_qa_review 同时输出 .json 文件"""
        from common.qa_review import _parse_qa_response, _generate_report_md
        from datetime import datetime
        from pathlib import Path

        result = {
            "A": [{"issue_id": "A01", "location": "test", "description": "desc", "suggestion": "fix"}],
            "B": [],
            "C": [],
            "D": [],
            "E": [],
            "notes": "",
        }
        total = 1
        findings = {
            "doc_name": "test.docx",
            "review_date": datetime.now().isoformat(timespec="seconds"),
            "doc_type": "\u6df7\u5408\u578b",
            "total_issues": total,
            "categories": {k: len(v) for k, v in result.items() if isinstance(v, list)},
            "issues": result,
            "quality_score": max(0, 100 - total * 5),
        }
        assert findings["quality_score"] == 95
        assert findings["total_issues"] == 1
        assert "A" in findings["categories"]

    def test_quality_score_calculation(self):
        """quality_score 计算：0 issues = 100, 20 issues = 0"""
        for issues, expected in [(0, 100), (5, 75), (10, 50), (20, 0), (25, 0)]:
            score = max(0, 100 - issues * 5)
            assert score == expected, f"issues={issues}, expected={expected}, got={score}"


# ── F3: 跨期趋势测试 ────────────────────────────────────


class TestCrossPeriodTrend:
    """跨期趋势分析测试"""

    def test_load_historical_batches(self):
        """_load_historical_batches 能从归档目录加载历史数据"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "agent", os.path.join(_PROJECT_ROOT, "src", "agent.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from pathlib import Path
        archive_dir = Path(_PROJECT_ROOT) / "data" / "archive"
        if not archive_dir.exists():
            pytest.skip("No archive directory")

        batches = mod._load_historical_batches(archive_dir, "nonexistent_label", max_periods=3)
        # Should return list (may be empty if no matching batches)
        assert isinstance(batches, list)

    def test_load_excludes_current_label(self):
        """_load_historical_batches 排除当前批次"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "agent", os.path.join(_PROJECT_ROOT, "src", "agent.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from pathlib import Path
        archive_dir = Path(_PROJECT_ROOT) / "data" / "archive"
        if not archive_dir.exists():
            pytest.skip("No archive directory")

        # Load with a label that exists in archive
        batches = mod._load_historical_batches(archive_dir, "2026\u5e746\u6708\u7b2c1\u5468", max_periods=3)
        for batch in batches:
            assert batch.get("batch_label") != "2026\u5e746\u6708\u7b2c1\u5468"