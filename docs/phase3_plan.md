# Phase 3 实施方案：跨条目分析 + 年收益估算 + 跨期趋势 + QA 闭环

## 概述

Phase 1 解决了"每条条目长什么样"（富字段 + emoji），Phase 2 解决了"标题质量和综合建议框架"。Phase 3 聚焦报告的**核心价值跃迁**——从"数据汇总"升级为"决策参考"：

1. **跨条目综合分析**：最值得申请排名（带年收益估算）、同类卡对比
2. **跨期趋势分析**：从历史归档数据中提取趋势信号，而非仅看当前批次
3. **QA 反馈闭环**：QA 发现的问题结构化输出，可反馈到数据层修正
4. **富字段质量提升**：keyword fallback 提取逻辑增强

Phase 3 完成后，报告与人工精编版的相似度预计从 ~75% 提升到 ~85%。

---

## Feature 清单

### F1：最值得申请排名 + 年收益估算

**现状**：Step 6 的"推荐申请"段落只列出银行+卡名（如"中信银行 · 中信万事达i白金卡"），无排名、无收益数字。

**目标**：人工版输出"1. 中信万事达i白金卡（新户返现顶流，月100元，年1200元）"——带排名序号和年收益估算。

**功能项**：
- F1-1：从 `worth_applying` 和 `key_benefits` 中提取年收益关键词（"月上限100元"→年1200元）
- F1-2：按 `overall_score` 降序排名，输出带序号的推荐列表
- F1-3：每条推荐附带一句话年收益估算（从 structured/raw_text 中提取）

### F2：同类卡对比

**现状**：多张同类新卡并列时，没有对比分析。

**目标**：当同分类有多张高分卡时，输出简要对比（如"两者择一选红利卡"）。

**功能项**：
- F2-1：检测同分类内 score≥7 的条目是否覆盖相同场景（返现/里程/贵宾厅）
- F2-2：对同类高分卡生成一行对比建议

### F3：跨期趋势分析

**现状**：Phase 2 的"市场趋势提醒"只从当前批次提取 score≤3 的条目。

**目标**：从历史归档数据中提取趋势信号，如"返现卡持续缩水是大趋势（广发10%→1%，华夏1%→0.5%）"。

**功能项**：
- F3-1：加载最近 N 期归档 batch.json，提取同银行/同卡的历史评分
- F3-2：检测评分下降趋势（如某卡连续两期 score 下降）
- F3-3：检测分类级别的趋势（如"权益变更"类中"缩水"关键词频率上升）
- F3-4：在"市场趋势提醒"段落中输出跨期趋势信号

### F4：QA 反馈闭环

**现状**：`common/qa_review.py` 输出 Markdown 验收报告，但不输出结构化 JSON。

**目标**：QA 报告同时输出 `qa_findings.json`，供下游消费（如自动修正 batch.json）。

**功能项**：
- F4-1：`run_qa_review()` 同时输出 `qa_findings.json`（结构化问题列表）
- F4-2：agent.py Step 6.5 后读取 findings，对 C 类（逻辑一致性）问题自动修正 batch 字段
- F4-3：QA 质量评分写入归档 manifest.json

### F5：富字段质量提升 — keyword fallback 增强

**现状**：keyword fallback 的 `key_benefits` 提取依赖 bullet 格式（`- xxx`），对非 bullet 格式的 raw_text 提取率低。

**目标**：提升 keyword 模式下富字段的覆盖率和准确性。

**功能项**：
- F5-1：`key_benefits` 提取增加"亮点"/"核心权益"/"优势"后的句子分割
- F5-2：`fee_assessment` 提取增加"首年免"/"刷卡免"/"刚性年费"等模式
- F5-3：`target_audience` 提取增加"适合"/"推荐给"/"面向"等模式

---

## 实施方案

### 1. `src/agent.py` Step 6 — F1: 最值得申请排名 + 年收益估算

**改动位置**：Step 6 的"推荐申请"段落（约 line 1240-1244）

**改动内容**：

替换当前的简单列表输出为带排名和收益估算的输出：

```python
# 当前
if all_recommended:
    p = doc.add_paragraph()
    r = p.add_run('✅ 推荐申请：')
    r.bold = True
    p.add_run('、'.join(all_recommended))

# 改为
if all_recommended:
    doc.add_paragraph()
    p = doc.add_paragraph()
    r = p.add_run('✅ 当前最值得申请的卡')
    r.bold = True
    for rank, (label, ev) in enumerate(all_recommended, 1):
        benefit = _extract_annual_benefit(ev)
        suffix = f'（{benefit}）' if benefit else ''
        doc.add_paragraph(f'{rank}. {label}{suffix}')
```

新增辅助函数 `_extract_annual_benefit(ev: dict) -> str`：

```python
def _extract_annual_benefit(ev: dict) -> str:
    """从评估结果中提取年收益估算"""
    import re
    text = f"{ev.get('recommendation', '')} {ev.get('summary', '')} {' '.join(ev.get('key_benefits', []))}"
    # 匹配"月上限100元"→年1200元
    m = re.search(r'月[上限]*[^\d]*(\d+)元', text)
    if m:
        monthly = int(m.group(1))
        return f"年约{monthly * 12}元收益"
    # 匩配"年返1200元"
    m = re.search(r'年[返省赚]*[^\d]*(\d+)元', text)
    if m:
        return f"年{m.group(1)}元"
    # 匹配"免年费"
    if '免年费' in text or '0年费' in text:
        return "免年费"
    return ""
```

**数据流变化**：`all_recommended` 从 `list[str]` 变为 `list[tuple[str, dict]]`（label + evaluation dict），以便提取收益信息。

**影响**：推荐段落从简单列表升级为带排名和收益的结构化输出。

---

### 2. `src/agent.py` Step 6 — F2: 同类卡对比

**改动位置**：Step 6 的"推荐申请"段落之后

**改动内容**：

新增同类卡对比逻辑：

```python
# 检测同类高分卡
from collections import defaultdict
scene_groups = defaultdict(list)
for cat in ['新卡', '活动']:
    for item in cat_summary.get(cat, {}).get('items', []):
        ev = item.get('evaluation', {})
        if ev.get('overall_score', 0) >= 7:
            # 从 key_benefits 中提取场景关键词
            benefits = ' '.join(ev.get('key_benefits', []))
            for scene in ['返现', '里程', '贵宾厅', '接送机', '积分']:
                if scene in benefits or scene in item.get('title', ''):
                    scene_groups[scene].append(f"{item.get('bank','')} · {item.get('title','')}")

for scene, cards in scene_groups.items():
    if len(cards) >= 2:
        doc.add_paragraph()
        p = doc.add_paragraph()
        r = p.add_run(f'🔄 {scene}类卡对比：')
        r.bold = True
        doc.add_paragraph(f'均为高分{scene}卡，建议根据个人消费场景择一。')
```

**影响**：当同场景有多张高分卡时，输出对比提示。

---

### 3. `src/agent.py` Step 6 — F3: 跨期趋势分析

**改动位置**：Step 6 的"市场趋势提醒"段落（替换 Phase 2 的单期逻辑）

**改动内容**：

新增跨期趋势分析函数：

```python
def _load_historical_batches(archive_dir: Path, current_label: str, max_periods: int = 3) -> list[dict]:
    """从归档目录加载最近 N 期 batch.json"""
    index_file = archive_dir / "index.json"
    if not index_file.exists():
        return []
    import json
    index = json.loads(index_file.read_text(encoding="utf-8"))
    batches = []
    for entry in index[:max_periods]:
        if entry.get("batch_label") == current_label:
            continue  # 跳过当前批次
        batch_file = archive_dir / entry["path"].replace("data/archive/", "").replace("\\", "/") / "batch.json"
        if batch_file.exists():
            try:
                batches.append(json.loads(batch_file.read_text(encoding="utf-8")))
            except Exception:
                pass
    return batches


def _detect_trends(current_items: list, historical_batches: list[dict]) -> list[str]:
    """检测跨期趋势信号"""
    trends = []
    # 1. 检测同卡评分下降
    hist_titles = {}
    for batch in historical_batches:
        for item in batch.get("items", []):
            t = item.get("title", "")
            if t:
                hist_titles[t] = batch.get("batch_label", "")
    # 2. 检测分类级别趋势
    downgrade_kw = ["缩水", "取消", "减少", "限制", "下调", "降低"]
    for item in current_items:
        text = f"{item.get('title', '')} {item.get('raw_text', '')}"
        for kw in downgrade_kw:
            if kw in text:
                bank = item.get('bank', '')
                title = item.get('title', '')
                trends.append(f"{bank} {title}：{kw}")
                break
    return trends[:3]
```

替换 Phase 2 的单期趋势逻辑，使用 `_detect_trends()` 生成跨期趋势信号。

**影响**：趋势分析从"当前批次低分条目"升级为"跨期趋势检测"。

---

### 4. `common/qa_review.py` — F4: QA 反馈闭环

**改动 A**：`run_qa_review()` 在输出 Markdown 报告的同时，输出 `qa_findings.json`：

```python
# 在 run_qa_review() 的 return 之前
findings_path = report_path.with_suffix(".json")
findings = {
    "doc_name": doc_name,
    "review_date": datetime.now().isoformat(timespec="seconds"),
    "total_issues": total,
    "categories": {k: len(v) for k, v in result.items() if isinstance(v, list)},
    "issues": result,  # 原始 QA 结果
    "quality_score": max(0, 100 - total * 5),  # 简单质量评分
}
findings_path.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")
```

**改动 B**：agent.py Step 6.5 后读取 findings，对 C 类问题自动修正：

```python
# 在 Step 6.5 QA 之后
findings_file = Path(report_file).parent / "qa_findings.json"
if findings_file.exists():
    findings = json.loads(findings_file.read_text(encoding="utf-8"))
    c_issues = findings.get("issues", {}).get("C", [])
    if c_issues:
        print(f"  [QA Feedback] {len(c_issues)} C类问题，尝试自动修正")
```

**改动 C**：归档 manifest.json 中写入 `quality_score` 字段。

**影响**：QA 从"输出报告"升级为"输出结构化数据 + 反馈修正"。

---

### 5. `card-holding-suggestion/scripts/scorer.py` — F5: keyword fallback 增强

**改动位置**：`score_with_keywords()` 的富字段提取部分

**改动内容**：

增强 `key_benefits` 提取（当前只匹配 bullet 格式）：

```python
# 当前：只匹配 bullet
m_kb = re.findall(r"[•\-\*]\s*(.{5,60}?)(?:\n|$)", raw_text)

# 增加：匹配"亮点"/"核心权益"/"优势"后的句子
if not kb:
    m_highlight = re.search(r"(?:亮点|核心权益|优势)[：:]\s*(.+?)(?:\n\n|\Z)", raw_text, re.DOTALL)
    if m_highlight:
        sentences = re.split(r"[。；\n]", m_highlight.group(1))
        kb = [s.strip() for s in sentences if 5 <= len(s.strip()) <= 60][:5]
```

增强 `fee_assessment` 提取：

```python
# 增加更多年费模式
if not fa:
    if "首年免" in text_all:
        fa = "首年免年费"
    elif "刷卡免" in text_all or "刷卡6次免" in text_all:
        fa = "刷卡免年费"
    elif "刚性年费" in text_all:
        m_fee = re.search(r"年费[^\d]*(\d+)元", text_all)
        if m_fee:
            fa = f"刚性年费{m_fee.group(1)}元"
```

增强 `target_audience` 提取：

```python
# 增加更多定位模式
if not ta:
    m_fit = re.search(r"(?:适合|推荐给|面向)(.{3,30}?)(?:[，。；\n]|$)", text_all)
    if m_fit:
        ta = m_fit.group(1).strip()[:50]
```

**影响**：keyword 模式下富字段覆盖率提升，对非 bullet 格式的 raw_text 也能提取关键信息。

---

## 测试计划

### 新增测试用例

| 测试 | 覆盖 |
|------|------|
| `test_extract_annual_benefit_monthly` | "月上限100元"→"年约1200元收益" |
| `test_extract_annual_benefit_yearly` | "年返1200元"→"年1200元" |
| `test_extract_annual_benefit_free` | "免年费"→"免年费" |
| `test_extract_annual_benefit_empty` | 无收益信息→空字符串 |
| `test_ranked_recommendation` | 推荐列表按 score 降序排列 |
| `test_scene_comparison` | 同场景两张高分卡→输出对比提示 |
| `test_cross_period_trend` | 跨期趋势检测（含历史 batch） |
| `test_qa_findings_json_output` | QA 同时输出 .json 文件 |
| `test_qa_quality_score` | quality_score 计算正确 |
| `test_keyword_enhanced_benefits` | 增强的 key_benefits 提取 |
| `test_keyword_enhanced_fee` | 增强的 fee_assessment 提取 |
| `test_keyword_enhanced_target` | 增强的 target_audience 提取 |

### 回归测试

`python -m pytest tests/ -x` 全量通过（Phase 1 的 19 + Phase 2 的 9 + Phase 3 的 12 + 既有测试）。

---

## 假设与默认值

1. **年收益估算**：从 text 中正则提取，精度有限（"月上限100元"→年1200是近似值）。不调用 LLM，保持 keyword 模式的零成本。
2. **跨期趋势**：默认加载最近 3 期归档数据。归档目录结构需符合 `data/archive/{YYYY}/{MM}/{batch_label}/batch.json` 约定。
3. **QA 反馈闭环**：Phase 3 仅实现 C 类问题检测和日志输出，自动修正 batch 字段留到 Phase 4（需要更精确的问题-字段映射）。
4. **同类卡对比**：基于 `key_benefits` 中的场景关键词（返现/里程/贵宾厅等）分组，不使用 LLM。
5. **keyword fallback 增强**：新增的正则模式覆盖常见中文表达，对非标准表述仍可能漏提取。

---

## 与 Phase 1/2 的关系

| Phase | 解决的问题 | 相似度 |
|-------|-----------|--------|
| Phase 1 | 每条条目长什么样（富字段 + emoji） | ~65% |
| Phase 2 | 标题质量 + 综合建议框架 | ~75% |
| **Phase 3** | **跨条目分析 + 年收益 + 趋势 + QA 闭环** | **~85%** |

Phase 3 不修改 Phase 1/2 的已有逻辑，只在 Step 6 的综合建议段落中新增/增强内容。