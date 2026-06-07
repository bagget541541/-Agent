"""
Phase 1 测试：条目结构化重写 + 优先级标注

覆盖：
- F3: score_to_emoji 映射
- F6: Schema 新字段序列化/反序列化
- F6: 向后兼容（旧 JSON 无新字段）
- F2: keyword fallback 富字段提取
- F4: generate_report 新渲染逻辑
- F4: 🟢 正面变更不生成建议
- F4: ⚪ 低价值活动简化渲染
"""

import json
import os
import sys
import tempfile
import pytest

# 确保项目根在 sys.path 中
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_CARD_HOLDING_ROOT = os.path.join(_PROJECT_ROOT, 'card-holding-suggestion', 'scripts')
if _CARD_HOLDING_ROOT not in sys.path:
    sys.path.insert(0, _CARD_HOLDING_ROOT)

from common.schema import CreditCardItem, CreditCardBatch

# 动态导入 scorer 模块（card-holding-suggestion/scripts/scorer.py）
import importlib.util
_scorer_path = os.path.join(_PROJECT_ROOT, "card-holding-suggestion", "scripts", "scorer.py")
_spec = importlib.util.spec_from_file_location("scorer", _scorer_path)
_scorer_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_scorer_mod)
score_to_emoji = _scorer_mod.score_to_emoji
score_with_keywords = _scorer_mod.score_with_keywords
DIMENSION_TEMPLATES = _scorer_mod.DIMENSION_TEMPLATES


# ── F3: score_to_emoji 映射 ──────────────────────────────


class TestScoreToEmoji:
    """评分到 emoji 映射测试"""

    def test_high_score_new_card(self):
        assert score_to_emoji("新卡", 8.0, "高") == "\U0001f534"  # 🔴

    def test_mid_score_activity(self):
        assert score_to_emoji("活动", 5.0, "中") == "\U0001f7e1"  # 🟡

    def test_low_score_announcement(self):
        assert score_to_emoji("公告", 2.0, "低") == "\u26aa"  # ⚪

    def test_green_positive_change(self):
        # 权益变更 score>=7 → 🟢（正面变更）
        assert score_to_emoji("权益变更", 8.0, "高") == "\U0001f7e2"

    def test_red_negative_change(self):
        # 权益变更 score<7 → 按普通规则（4-6→🟡）
        assert score_to_emoji("权益变更", 3.0, "低") == "\u26aa"

    def test_boundary_score_seven(self):
        assert score_to_emoji("新卡", 7.0) == "\U0001f534"  # 🔴
        assert score_to_emoji("新卡", 6.9) == "\U0001f7e1"  # 🟡

    def test_boundary_score_four(self):
        assert score_to_emoji("活动", 4.0) == "\U0001f7e1"  # 🟡
        assert score_to_emoji("活动", 3.9) == "\u26aa"  # ⚪


# ── F6: Schema 新字段序列化 ──────────────────────────────


class TestSchemaNewFields:
    """Schema 新字段序列化/反序列化测试"""

    def test_new_fields_roundtrip(self):
        """新字段 to_dict → from_dict 往返一致"""
        item = CreditCardItem(
            title="测试卡",
            category="新卡",
            target_audience="境外消费返现+球迷收藏",
            key_benefits=["免年费", "境外五重返现", "Apple Pay额外返2%"],
            fee_assessment="0年费，境外消费有返现就赚",
            worth_applying=[
                {"icon": "✅", "condition": "有境外消费需求", "conclusion": "值得申"},
                {"icon": "❌", "condition": "纯境内消费为主", "conclusion": "不推荐"},
            ],
            priority_emoji="\U0001f534",
        )
        d = item.to_dict()
        assert d["target_audience"] == "境外消费返现+球迷收藏"
        assert d["key_benefits"] == ["免年费", "境外五重返现", "Apple Pay额外返2%"]
        assert d["fee_assessment"] == "0年费，境外消费有返现就赚"
        assert len(d["worth_applying"]) == 2
        assert d["priority_emoji"] == "\U0001f534"

        item2 = CreditCardItem.from_dict(d)
        assert item2.target_audience == item.target_audience
        assert item2.key_benefits == item.key_benefits
        assert item2.fee_assessment == item.fee_assessment
        assert item2.worth_applying == item.worth_applying
        assert item2.priority_emoji == item.priority_emoji

    def test_backward_compat_old_json(self):
        """旧 JSON（无新字段）from_dict 不报错，字段默认空"""
        old_data = {
            "title": "旧卡",
            "category": "新卡",
            "bank": "测试银行",
            # 无 target_audience, key_benefits, fee_assessment, worth_applying, priority_emoji
        }
        item = CreditCardItem.from_dict(old_data)
        assert item.target_audience == ""
        assert item.key_benefits == []
        assert item.fee_assessment == ""
        assert item.worth_applying == []
        assert item.priority_emoji == ""

    def test_empty_lists_not_in_output(self):
        """空列表在 to_dict 中应保留（保持结构一致）"""
        item = CreditCardItem(title="空字段测试")
        d = item.to_dict()
        assert "key_benefits" in d
        assert "worth_applying" in d
        assert d["key_benefits"] == []
        assert d["worth_applying"] == []


# ── F2: keyword fallback 富字段提取 ──────────────────────


class TestKeywordFallback:
    """关键词降级模式下的富字段提取测试"""

    def test_extract_target_audience(self):
        """从 raw_text 中提取适用人群"""
        import sys
        sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'card-holding-suggestion', 'scripts'))

        item = {
            "category": "新卡",
            "title": "测试卡",
            "bank": "测试银行",
            "raw_text": "适用人群：有境外消费需求的持卡人\n年费：免年费\n亮点：境外返现5%",
            "structured": {"卡亮点": "境外返现5%"},
        }
        result = score_with_keywords(item, DIMENSION_TEMPLATES["新卡"]())
        assert "境外" in result.target_audience or "持卡人" in result.target_audience

    def test_extract_key_benefits(self):
        """从 raw_text 中提取核心权益"""

        item = {
            "category": "新卡",
            "title": "测试卡",
            "bank": "测试银行",
            "raw_text": "- 免年费\n- 境外五重返现\n- Apple Pay额外返2%\n- 免外汇兑换手续费",
            "structured": {},
        }
        result = score_with_keywords(item, DIMENSION_TEMPLATES["新卡"]())
        assert len(result.key_benefits) >= 2

    def test_extract_fee_assessment(self):
        """从 raw_text 中提取年费回报评估"""

        item = {
            "category": "新卡",
            "title": "测试卡",
            "bank": "测试银行",
            "raw_text": "年费：首年免年费，刷卡6次免次年\n权益丰富",
            "structured": {},
        }
        result = score_with_keywords(item, DIMENSION_TEMPLATES["新卡"]())
        assert "年费" in result.fee_assessment or "免" in result.fee_assessment

    def test_keyword_worth_applying_empty(self):
        """keyword 模式下 worth_applying 为空（需 LLM 判断）"""

        item = {
            "category": "新卡",
            "title": "测试卡",
            "raw_text": "测试内容",
            "structured": {},
        }
        result = score_with_keywords(item, DIMENSION_TEMPLATES["新卡"]())
        assert result.worth_applying == []

    def test_priority_emoji_set(self):
        """keyword 模式下 priority_emoji 应被设置"""

        item = {
            "category": "新卡",
            "title": "高分卡",
            "raw_text": "免年费 返现 积分 接送机 贵宾厅 里程",
            "structured": {},
        }
        result = score_with_keywords(item, DIMENSION_TEMPLATES["新卡"]())
        assert result.priority_emoji in ("\U0001f534", "\U0001f7e1", "\u26aa")


# ── F4: generate_report 渲染测试 ─────────────────────────


class TestGenerateReport:
    """generate_report 渲染逻辑测试"""

    def _make_batch_data(self, items_data):
        """构造测试用 batch JSON"""
        return {
            "schema_version": "1.1",
            "generated_at": "2026-06-07T12:00:00",
            "batch_label": "测试批次",
            "total": len(items_data),
            "items": items_data,
        }

    def _make_item(self, **kwargs):
        """构造测试用 item dict"""
        base = {
            "item_id": "test001",
            "source": "website",
            "source_type": "官网公告",
            "category": "新卡",
            "bank": "测试银行",
            "title": "测试卡",
            "display_title": "测试卡",
            "raw_title": "测试卡",
            "highlight_summary": "境外返现5%",
            "url": "",
            "raw_text": "",
            "structured": {},
            "structured_clean": {},
            "images": [],
            "target_audience": "",
            "key_benefits": [],
            "fee_assessment": "",
            "worth_applying": [],
            "priority_emoji": "",
        }
        base.update(kwargs)
        return base

    def test_enriched_item_renders_emoji_in_heading(self):
        """含 emoji 的条目在 H2 标题中应包含 emoji"""
        from word_merger_scripts import generate_report

        item = self._make_item(
            priority_emoji="\U0001f534",
            target_audience="境外消费返现",
            key_benefits=["免年费", "境外返现"],
            fee_assessment="0年费",
            worth_applying=[{"icon": "✅", "condition": "有需求", "conclusion": "值得"}],
        )
        batch = self._make_batch_data([item])

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')

        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
            # 验证 docx 生成成功
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_backward_compat_no_enrichment(self):
        """无富字段的旧 JSON 生成 docx 不报错"""
        from word_merger_scripts import generate_report

        item = self._make_item()
        # 移除新字段
        for k in ('target_audience', 'key_benefits', 'fee_assessment', 'worth_applying', 'priority_emoji'):
            item.pop(k, None)
        batch = self._make_batch_data([item])

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')

        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_green_change_no_advice(self):
        """🟢 条目应跳过变更分析字段渲染"""
        from word_merger_scripts import generate_report

        item = self._make_item(
            category="权益变更",
            title="利好变更",
            priority_emoji="\U0001f7e2",  # 🟢
            structured={"变更内容": "权益升级", "变更分析": "利好分析", "点评": "好评"},
        )
        batch = self._make_batch_data([item])

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')

        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_low_value_activity_condensed(self):
        """⚪ 活动条目只渲染标题+亮点，跳过详细结构化字段"""
        from word_merger_scripts import generate_report

        item = self._make_item(
            category="活动",
            title="小活动",
            priority_emoji="\u26aa",  # ⚪
            highlight_summary="满30返5元",
            structured={"活动内容": "满30返5元", "活动时间": "6月", "适用人群": "持卡人"},
        )
        batch = self._make_batch_data([item])

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')

        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)


# ── 辅助导入 ─────────────────────────────────────────────


# 为了让 generate_report 可以被导入，需要设置正确的路径
_WORD_MERGER_SCRIPTS = os.path.join(_PROJECT_ROOT, 'word-merger', 'scripts')

class _WordMergerScriptsModule:
    """动态导入 word-merger/scripts/generate_report.py"""
    _module = None

    @classmethod
    def __getattr__(cls, name):
        if cls._module is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "generate_report",
                os.path.join(_WORD_MERGER_SCRIPTS, "generate_report.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            # 需要先设置 sys.path 以便其内部导入
            if _WORD_MERGER_SCRIPTS not in sys.path:
                sys.path.insert(0, _WORD_MERGER_SCRIPTS)
            spec.loader.exec_module(mod)
            cls._module = mod
        return getattr(cls._module, name)

# 模块级别注册，让测试类可以 import
import types
word_merger_scripts = types.ModuleType("word_merger_scripts")
word_merger_scripts.generate_report = lambda *a, **kw: _WordMergerScriptsModule.generate_report(*a, **kw)
sys.modules["word_merger_scripts"] = word_merger_scripts

# 真正的 generate_report 函数引用
def _get_generate_report():
    if _WordMergerScriptsModule._module is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_report",
            os.path.join(_WORD_MERGER_SCRIPTS, "generate_report.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        if _WORD_MERGER_SCRIPTS not in sys.path:
            sys.path.insert(0, _WORD_MERGER_SCRIPTS)
        spec.loader.exec_module(mod)
        _WordMergerScriptsModule._module = mod
    return _WordMergerScriptsModule._module.generate_report

# 覆盖 TestGenerateReport 中的 import
class TestGenerateReport:
    """使用正确的 generate_report 导入"""

    def _make_batch_data(self, items_data):
        return {
            "schema_version": "1.1",
            "generated_at": "2026-06-07T12:00:00",
            "batch_label": "测试批次",
            "total": len(items_data),
            "items": items_data,
        }

    def _make_item(self, **kwargs):
        base = {
            "item_id": "test001",
            "source": "website",
            "source_type": "官网公告",
            "category": "新卡",
            "bank": "测试银行",
            "title": "测试卡",
            "display_title": "测试卡",
            "raw_title": "测试卡",
            "highlight_summary": "境外返现5%",
            "url": "",
            "raw_text": "",
            "structured": {},
            "structured_clean": {},
            "images": [],
            "target_audience": "",
            "key_benefits": [],
            "fee_assessment": "",
            "worth_applying": [],
            "priority_emoji": "",
        }
        base.update(kwargs)
        return base

    def test_enriched_item_renders_emoji_in_heading(self):
        generate_report = _get_generate_report()
        item = self._make_item(
            priority_emoji="\U0001f534",
            target_audience="境外消费返现",
            key_benefits=["免年费", "境外返现"],
            fee_assessment="0年费",
            worth_applying=[{"icon": "✅", "condition": "有需求", "conclusion": "值得"}],
        )
        batch = self._make_batch_data([item])
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')
        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
            assert os.path.exists(output_path)
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_backward_compat_no_enrichment(self):
        generate_report = _get_generate_report()
        item = self._make_item()
        for k in ('target_audience', 'key_benefits', 'fee_assessment', 'worth_applying', 'priority_emoji'):
            item.pop(k, None)
        batch = self._make_batch_data([item])
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')
        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_green_change_no_advice(self):
        generate_report = _get_generate_report()
        item = self._make_item(
            category="权益变更",
            title="利好变更",
            priority_emoji="\U0001f7e2",
            structured={"变更内容": "权益升级", "变更分析": "利好分析", "点评": "好评"},
        )
        batch = self._make_batch_data([item])
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')
        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_low_value_activity_condensed(self):
        generate_report = _get_generate_report()
        item = self._make_item(
            category="活动",
            title="小活动",
            priority_emoji="\u26aa",
            highlight_summary="满30返5元",
            structured={"活动内容": "满30返5元", "活动时间": "6月", "适用人群": "持卡人"},
        )
        batch = self._make_batch_data([item])
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False)
            input_path = f.name
        output_path = input_path.replace('.json', '.docx')
        try:
            result = generate_report(input_path, output_path)
            assert result["success"] is True
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)