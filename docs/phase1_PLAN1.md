
# Phase 1 实施方案：条目结构化重写 + 优先级标注

## 概述

Phase 1 目标是让 Pipeline 输出的每条条目具备人工精编版 80% 的结构完整度，同时引入 emoji 优先级标注体系。核心改动分两条线：

**线 1（P0 条目结构化）**：在 Step 5 评分阶段，LLM 同时生成 4 个富结构化字段（定位/核心权益/年费回报评估/是否值得申请），写回 batch.items；调整 Pipeline 顺序让 Step 4 在 Step 5 之后执行，这样 docx 渲染时可以直接使用富字段。

**线 2（P1 优先级标注）**：评分结果映射为 🔴🟡⚪🟢 emoji，注入到 H2 标题、目录、条目结构中。

---

## Feature 清单

### F1：Pipeline 顺序调整 — Step 5 先于 Step 4

当前顺序是 Step 3 → Step 4(生成docx) → Step 5(评分) → Step 6(追加建议)。需要改为 Step 3 → Step 5(评分+富字段生成) → Step 4(用富字段生成docx) → Step 6(追加综合策略)。

### F2：Step 5 LLM 评分扩展 — 生成富结构化字段

在 `analyze_batch.py` 的 `extract_key_points()` 中，当 scorer 为 `llm` 时，让 LLM 一次性输出评分 + 4 个富字段；当 scorer 为 `keyword` 时，用规则引擎从 raw_text 中提取这些字段的 fallback 版本。

4 个新字段：
- **定位**（target_audience）：一句话说明目标人群，如"境外消费返现+球迷收藏卡面"
- **核心权益**（key_benefits）：结构化 bullet 列表，每条一个权益点
- **年费回报评估**（fee_assessment）：定量分析年费 vs 回报，如"0年费，境外消费有返现就赚"
- **是否值得申请**（worth_applying）：条件分支列表，每条带 ✅/❌/⚠️ 前缀 + 条件 + 结论

### F3：priority_emoji 字段 — 评分到 emoji 映射

在评分完成后，根据 `overall_score` 映射为 emoji 并写入 item：score≥7→🔴，4-6→🟡，≤3→⚪；权益变更中 score≥7 的正面变更映射为🟢。

### F4：generate_report.py 渲染新字段

H2 标题末尾追加 emoji；新增"亮点"行（加粗首行）；新增"定位"行；新增"核心权益"bullet 列表；新增"年费回报评估"行；新增"是否值得申请"条件分支列表；🟢 类变更不生成"建议"段落；⚪ 类活动合并为简表。

### F5：generate_report.py 目录改为手写风格摘要

替换当前 TOC 占位符，改为每个分类下每条带 emoji + 一句话摘要（取 highlight_summary），每条一行 Normal 样式。删除"内容概览"和"本期亮点"章节。

### F6：Schema 扩展 — 新增字段持久化

`CreditCardItem` 新增 5 个字段（target_audience, key_benefits, fee_assessment, worth_applying, priority_emoji），同步更新 `__init__`、`to_dict`、`from_dict`。

### F7：单元测试

覆盖评分→emoji 映射、富字段生成（keyword fallback）、generate_report 新渲染逻辑。

---

## 实施方案

### 1. `common/schema.py` — 新增 5 个字段

**改动**：`CreditCardItem.__init__` 签名新增 5 个 keyword-only 参数，默认空值：

```
target_audience: str = ""      # 定位
key_benefits: list[str] = None # 核心权益列表
fee_assessment: str = ""       # 年费回报评估
worth_applying: list[dict] = None  # 是否值得申请 [{icon, condition, conclusion}]
priority_emoji: str = ""       # 🔴🟡⚪🟢
```

同步修改 `to_dict()` 输出这 5 个字段，`from_dict()` 读取这 5 个字段（用 `.get()` 兼容旧数据）。`key_benefits` 和 `worth_applying` 默认 `None`，序列化时 `or []` 不输出空列表以保持 JSON 简洁。

**影响**：所有 `CreditCardItem` 的消费者自动获得新字段，`from_dict` 向后兼容旧 JSON（新字段缺失时默认空值）。`batch_merged.json` 格式向前兼容。

---

### 2. `card-holding-suggestion/scripts/scorer.py` — 评分扩展 + emoji 映射

**改动 A**：`ROI_Score` dataclass 新增 4 个字段：

```python
target_audience: str = ""
key_benefits: list = field(default_factory=list)
fee_assessment: str = ""
worth_applying: list = field(default_factory=list)
```

**改动 B**：新增函数 `score_to_emoji(category, score, roi) -> str`：

```python
def score_to_emoji(category: str, score: float, roi: str = "") -> str:
    if category == "权益变更" and score >= 7:
        return "🟢"
    if score >= 7:
        return "🔴"
    if score >= 4:
        return "🟡"
    return "⚪"
```

**改动 C**：`score_with_llm()` 的 prompt 扩展 — 在 `_build_prompt()` 中增加 4 个输出字段要求：

对新卡/活动类，LLM prompt 增加：
```
"target_audience": "一句话目标人群定位",
"key_benefits": ["权益1", "权益2", ...],
"fee_assessment": "年费回报评估：...",
"worth_applying": [
  {"icon": "✅", "condition": "有境外消费需求", "conclusion": "值得申"},
  {"icon": "❌", "condition": "纯境内消费为主", "conclusion": "不推荐"},
  {"icon": "⚠️", "condition": "注意：返现活动6.30截止", "conclusion": "需抓紧报名"}
]
```

对权益变更类，不生成 `worth_applying`，改为 `impact_analysis`（按持卡人类型分述）。🟢 类正面变更不生成建议。

**改动 D**：`_parse_llm_response()` 扩展解析这 4 个新字段到 `ROI_Score`。

**改动 E**：`score_with_keywords()` 新增 keyword fallback 逻辑 — 从 raw_text 中用正则/关键词提取 `target_audience`（匹配"适用人群"后的文字）、`key_benefits`（匹配"权益"/"亮点"后的 bullet）、`fee_assessment`（匹配"年费"相关句子）。`worth_applying` 在 keyword 模式下留空（需 LLM 判断）。

**影响**：`score_with_llm` 和 `score_with_keywords` 签名不变，返回值扩展（向后兼容）。`analyze_batch.py` 中 `result.to_dict()` 自动包含新字段。

---

### 3. `card-holding-suggestion/scripts/analyze_batch.py` — 富字段写回 batch

**改动**：`extract_key_points()` 获取评分结果后，将 4 个富字段 + priority_emoji 写回原始 item dict：

```python
evaluation = result.to_dict()
points['evaluation'] = evaluation

# 写回富字段到原始 item（供 generate_report.py 使用）
item['target_audience'] = evaluation.get('target_audience', '')
item['key_benefits'] = evaluation.get('key_benefits', [])
item['fee_assessment'] = evaluation.get('fee_assessment', '')
item['worth_applying'] = evaluation.get('worth_applying', [])
item['priority_emoji'] = score_to_emoji(cat, evaluation.get('overall_score', 5), evaluation.get('overall_roi', ''))
```

同时在 `build_context()` 结束后，将修改后的 items 写回一个 `_enriched_batch.json` 文件（供 Step 4 使用）。

**影响**：`analyze_batch.py` 的输出 JSON 新增 `enriched_items` 字段。Step 5 的调用方（`src/agent.py`）需要在 Step 5 完成后用 enriched items 替换 batch.items。

---

### 4. `src/agent.py` — Pipeline 顺序调整

**改动 A**：`run_pipeline()` 中将 Step 5 移到 Step 4 之前：

```python
# 当前顺序: Step 3.5 → Step 4 → Step 5 → Step 6
# 新顺序:   Step 3.5 → Step 5 → Step 4 → Step 6 → Step 6.5 → Step 7
```

具体操作：将 Step 5 的代码块（约 1480-1489 行）移到 Step 4 代码块（约 1466-1478 行）之前。

**改动 B**：Step 5 完成后，将分析结果中的富字段写回 `batch.items`：

```python
# Step 5 完成后，将富字段写回 batch
if analysis and analysis.get('category_summary'):
    enriched_map = {}
    for cat_data in analysis['category_summary'].values():
        for item_data in cat_data.get('items', []):
            title = item_data.get('title', '')
            enriched_map[title] = item_data
    for item in batch.items:
        enriched = enriched_map.get(item.title, {})
        ev = enriched.get('evaluation', {})
        if ev:
            item.target_audience = ev.get('target_audience', '') or item.target_audience
            item.key_benefits = ev.get('key_benefits', []) or item.key_benefits or []
            item.fee_assessment = ev.get('fee_assessment', '') or item.fee_assessment
            item.worth_applying = ev.get('worth_applying', []) or item.worth_applying or []
            item.priority_emoji = ev.get('priority_emoji', '') or item.priority_emoji
```

**影响**：Step 4 的 `generate_report()` 调用时，batch JSON 已包含富字段。Step 6 不受影响（它读 docx 追加内容）。Step 6.5 QA 不受影响。

---

### 5. `word-merger/scripts/generate_report.py` — 渲染新字段 + emoji + 目录改造

**改动 A**：H2 标题追加 emoji（约第 376 行）：

```python
# 原: doc.add_heading(clean_xml_text(f'{idx}. {title_text}'), level=2)
# 新: 追加 priority_emoji
priority_emoji = item.get('priority_emoji', '')
heading_text = f'{idx}. {title_text}'
if priority_emoji:
    heading_text += f' {priority_emoji}'
doc.add_heading(clean_xml_text(heading_text), level=2)
```

**改动 B**：银行标签之后、结构化字段之前，插入 4 个新渲染块：

```python
# ── 亮点（加粗首行）──
highlight = item.get('highlight_summary', '')
if highlight:
    hp = doc.add_paragraph()
    hr = hp.add_run(f'亮点：{highlight}')
    set_run_font(hr, bold=True, size=Pt(10.5))

# ── 定位 ──
target = item.get('target_audience', '')
if target:
    tp = doc.add_paragraph()
    tr = tp.add_run(f'定位：{target}')
    set_run_font(tr, bold=True, size=Pt(10.5))

# ── 核心权益 ──
benefits = item.get('key_benefits', [])
if benefits:
    for b in benefits:
        bp = doc.add_paragraph(style='List Bullet')
        bp.add_run(clean_xml_text(b))

# ── 年费回报评估 ──
fee = item.get('fee_assessment', '')
if fee:
    fp = doc.add_paragraph()
    fr = fp.add_run(f'年费回报评估：{fee}')
    set_run_font(fr, bold=True, size=Pt(10.5))

# ── 是否值得申请 ──
worth = item.get('worth_applying', [])
if worth:
    wp = doc.add_paragraph()
    wr = wp.add_run('是否值得申请：')
    set_run_font(wr, bold=True, size=Pt(10.5))
    for w in worth:
        icon = w.get('icon', '')
        cond = w.get('condition', '')
        concl = w.get('conclusion', '')
        ip = doc.add_paragraph(style='List Bullet')
        ir = ip.add_run(f'{icon} {cond} → {concl}')
        set_run_font(ir, size=Pt(10.5))
```

**改动 C**：🟢 正面变更跳过"建议"段落 — 在权益变更的渲染逻辑中，检查 `priority_emoji == '🟢'` 时不渲染 structured 中的"点评"/"变更分析"字段。

**改动 D**：⚪ 低价值活动合并为简表 — 对 `priority_emoji == '⚪'` 的活动条目，只渲染 H2 标题 + 亮点一行 + 建议一行，跳过详细结构化字段。

**改动 E**：目录改为手写风格摘要（约第 252-272 行）：

替换当前 TOC 域代码为：

```python
# 手写风格目录
doc.add_heading('目录', level=1)
for cat in cat_order:
    cat_items = [it for it in items if it.get('category') == cat]
    if not cat_items:
        continue
    cat_label = cat_config.get(cat, (cat, cat))[0]
    cp = doc.add_paragraph()
    cr = cp.add_run(cat_label)
    set_run_font(cr, bold=True, size=Pt(11))
    for it in cat_items:
        emoji = it.get('priority_emoji', '')
        title = it.get('display_title') or it.get('title', '')
        summary = it.get('highlight_summary', '') or ''
        summary_short = safe_truncate(summary, 30)
        line = f'  {emoji} {title}'
        if summary_short:
            line += f'：{summary_short}'
        lp = doc.add_paragraph()
        lp.add_run(clean_xml_text(line))
        lp.paragraph_format.space_after = Pt(1)
```

**改动 F**：删除"内容概览"和"本期亮点"章节（约第 274-325 行），直接从目录跳到正文。

**影响**：`generate_report.py` 的输出格式变化显著。旧版 JSON（无富字段）仍可渲染，只是新字段为空时不显示对应区块（向后兼容）。`merge_docs.py` 如果也调用 `generate_report()`，同样受益。

---

### 6. `common/display_fields.py` — 亮点摘要增强

**改动**：`_build_highlight_summary()` 在当前逻辑基础上，如果 item 已有 `target_audience`，在摘要末尾追加定位信息（用于目录摘要显示）。

**影响**：`normalize_item()` 在 Step 3 阶段不生成富字段（那时没有 LLM 分析），但 Step 5 回写后 `highlight_summary` 可能被更新。`generate_report.py` 读取时取最新值。

---

### 7. 测试

**新增测试文件**：`tests/test_phase1_enrichment.py`

| 测试用例 | 覆盖 |
|----------|------|
| `test_score_to_emoji_mapping` | score≥7→🔴，4-6→🟡，≤3→⚪，权益变更≥7→🟢 |
| `test_schema_new_fields_serialization` | 5 个新字段 to_dict/from_dict 往返一致 |
| `test_schema_backward_compat` | 旧 JSON（无新字段）from_dict 不报错，字段默认空 |
| `test_keyword_fallback_extraction` | 从 raw_text 中提取 target_audience/key_benefits |
| `test_generate_report_with_enriched_fields` | 用含富字段的 JSON 生成 docx，验证 H2 含 emoji、含定位/benefits/worth_applying 段落 |
| `test_generate_report_backward_compat` | 用不含富字段的旧 JSON 生成 docx，验证不报错、无新段落 |
| `test_green_change_no_advice` | 🟢 条目不渲染"建议"段落 |
| `test_low_value_activity_condensed` | ⚪ 活动条目只渲染标题+亮点 |

**既有测试回归**：`python -m pytest tests/ -x` 全量通过。

---

## 假设与默认值

1. **LLM 可用性**：keyword scorer 模式下，富字段通过规则提取（质量较低但可用）；LLM scorer 模式下，富字段质量高。默认行为：keyword 模式先跑，LLM 可用时覆盖。
2. **emoji 渲染**：Word 文档中的 emoji 使用 Segoe UI Symbol 字体，需要目标机器安装该字体（Windows 10+ 自带）。
3. **目录格式**：放弃 Word TOC 域代码（需手动 F9 更新），改为静态手写目录（每次生成即是最新的）。
4. **向后兼容**：旧版 batch_merged.json 不含新字段，generate_report.py 对缺失字段不渲染对应区块。
5. **Pipeline 顺序调整**：Step 5 结果回写到 batch.items 内存对象后，Step 4 用更新后的 batch 生成 docx。不需要额外的 JSON 文件中转。

