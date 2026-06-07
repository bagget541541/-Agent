# Phase 2 实施方案：标题优化 + highlight 增强 + 综合建议升级 + 格式统一

## 概述

Phase 1 完成了条目结构化（富字段渲染 + emoji 优先级 + 目录改造），Phase 2 聚焦三个方向：
1. **标题质量提升**：LLM 压缩标题 + highlight_summary 增强
2. **综合建议升级**：Step 6 从"机械拼接"升级为"决策参考"（排名、时间节点、趋势）
3. **格式统一**：确保全文 emoji/字体/间距一致性

---

## Feature 清单

### F1：LLM 标题压缩

当前 `build_report_title()` 简单拼接 top-2 条目标题，产出如"2026年6月第1周亮点：标题A、标题B"。目标是用 LLM 从 top-3 高亮条目压缩为一句话（≤50字），更像人工版的"2026年6月上旬｜平安百夫长权益缩水、中信i白金返现顶流、广发双标卡延长"。

### F2：highlight_summary 增强

当前 `_build_highlight_summary()` 只从 structured 原始字段提取摘要。Phase 1 已有 `key_benefits` 和 `fee_assessment` 富字段，但 highlight_summary 在 Step 3 生成时还没有这些字段。需要在 Step 5 富字段回写后，用富字段增强 highlight_summary。

### F3：综合建议升级 — 建议销卡 + 市场趋势 + 时间节点

当前 Step 6 只输出"推荐申请/优先参与/需关注"三类。需要新增：
- **建议销卡清单**：score≤3 的权益变更/活动到期条目
- **建议保留但需调整**：score 4-6 的条目
- **市场趋势提醒**：从多期归档数据提取趋势信号
- **近期关键时间节点**：从 structured 中提取截止日期，排序输出

### F4：格式统一

- 新卡 structured_fields 中"卡亮点"字段不再单独渲染（已被富字段"亮点"行覆盖）
- 权益变更 structured_fields 中"变更分析"字段对 🟢 条目跳过（Phase 1 已做）
- 目录条目 emoji 与正文 H2 emoji 一致
- 全文字体统一为微软雅黑 10.5pt

---

## 实施方案

### 1. `word-merger/scripts/generate_report.py` — F1: LLM 标题压缩

**改动 A**：`build_report_title()` 增加 LLM 压缩路径

在现有 keyword 拼接逻辑之前，尝试用 LLM 从 top-3 高亮条目生成压缩标题：

```python
def build_report_title(items, batch_label="", use_llm=True):
    # 1. 收集 top-3 高亮条目
    scored_items = []
    for it in items:
        emoji = it.get('priority_emoji', '')
        score = 0
        if emoji == '🔴': score = 3
        elif emoji == '🟡': score = 2
        elif emoji == '🟢': score = 1
        scored_items.append((score, it))
    scored_items.sort(key=lambda x: -x[0])
    top3 = [it for _, it in scored_items[:3]]
    
    # 2. 尝试 LLM 压缩
    if use_llm and top3:
        try:
            from common.llm_client import call_llm_file_config
            summaries = [f"{it.get('bank','')} {it.get('highlight_summary','')}" for it in top3]
            prompt = f"将以下3条信用卡资讯压缩为一句话标题（≤50字），用顿号分隔：\n" + "\n".join(summaries)
            reply, err = call_llm_file_config(prompt=prompt, max_tokens=100, timeout=10)
            if reply and not err and len(reply) <= 60:
                return f"{batch_label}｜{reply.strip()}"
        except Exception:
            pass
    
    # 3. fallback: 现有 keyword 拼接逻辑
    ...
```

**改动 B**：`generate_report()` 调用 `build_report_title()` 时传入 `use_llm=True`（默认）。

**影响**：标题质量提升。LLM 不可用时自动 fallback 到 keyword 拼接。`doc_title` 参数仍可覆盖。

---

### 2. `common/display_fields.py` — F2: highlight_summary 增强

**改动**：`generate_display_fields()` 新增可选参数 `key_benefits: list = None` 和 `fee_assessment: str = ""`。

当这两个参数有值时，在 highlight_summary 末尾追加核心信息：

```python
# 在 return 之前
if key_benefits:
    benefits_short = '、'.join(key_benefits[:2])
    highlight_summary += f'（{benefits_short}）'
elif fee_assessment:
    highlight_summary += f'（{fee_assessment}）'
```

**调用方改动**：`src/agent.py` 的 Step 5 富字段回写循环中，调用 `generate_display_fields()` 时传入新参数：

```python
# 在 agent.py 的富字段回写循环中
dr = generate_display_fields(
    bank=item.bank, category=item.category,
    structured=item.structured, raw_title=item.raw_title,
    raw_text=item.raw_text,
    key_benefits=item.key_benefits,
    fee_assessment=item.fee_assessment,
)
item.highlight_summary = dr["highlight_summary"]
```

**影响**：highlight_summary 从纯结构化字段摘要升级为包含核心权益/年费评估的增强摘要。目录条目的摘要质量同步提升。

---

### 3. `src/agent.py` Step 6 — F3: 综合建议升级

**改动 A**：新增"建议销卡清单"段落

在现有"综合持卡策略"段落之后，新增：

```python
# 建议销卡
all_cancel = []
for cat in ['权益变更', '活动']:
    for item in cat_summary.get(cat, {}).get('items', []):
        ev = item.get('evaluation', {})
        if ev.get('overall_score', 5) <= 3:
            all_cancel.append(f"{item.get('bank','')} · {item.get('title','')}")
if all_cancel:
    doc.add_paragraph()
    r = doc.add_paragraph().add_run('🗑️ 建议销卡/放弃：')
    r.bold = True
    doc.add_paragraph('、'.join(all_cancel))
```

**改动 B**：新增"建议保留但需调整"段落

```python
all_adjust = []
for cat in cat_order:
    for item in cat_summary.get(cat, {}).get('items', []):
        ev = item.get('evaluation', {})
        score = ev.get('overall_score', 5)
        if 4 <= score <= 6 and ev.get('is_highlight'):
            all_adjust.append(f"{item.get('bank','')} · {item.get('title','')}")
if all_adjust:
    doc.add_paragraph()
    r = doc.add_paragraph().add_run('🔧 建议保留但需调整：')
    r.bold = True
    doc.add_paragraph('、'.join(all_adjust))
```

**改动 C**：新增"近期关键时间节点"段落

从 analysis 中的 structured 字段提取日期信息：

```python
import re
time_nodes = []
for cat_data in cat_summary.values():
    for item in cat_data.get('items', []):
        ev = item.get('evaluation', {})
        if not ev.get('is_highlight'):
            continue
        title = item.get('title', '')
        notes = ev.get('notes', '')
        rec = ev.get('recommendation', '')
        # 从 notes/recommendation 中提取日期
        dates = re.findall(r'(\d{1,2}[\.月]\d{1,2}[日号]?)', f"{notes} {rec}")
        for d in dates:
            time_nodes.append(f"{d} — {title}")
if time_nodes:
    doc.add_heading('📅 近期关键时间节点', level=2)
    for tn in time_nodes[:5]:
        doc.add_paragraph(f'• {tn}')
```

**改动 D**：新增"市场趋势提醒"段落（从 analysis 中提取趋势信号）

```python
trends = []
for cat_data in cat_summary.values():
    for item in cat_data.get('items', []):
        ev = item.get('evaluation', {})
        if ev.get('overall_score', 5) <= 3 and ev.get('highlight_reason'):
            trends.append(f"{item.get('bank','')} {item.get('title','')}：{ev['highlight_reason']}")
if trends:
    doc.add_heading('📈 市场趋势提醒', level=2)
    for t in trends[:3]:
        doc.add_paragraph(f'• {t}')
```

**影响**：Step 6 从"数据罗列"升级为"决策参考"。新增段落仅在有数据时渲染，向后兼容。

---

### 4. `word-merger/scripts/generate_report.py` — F4: 格式统一

**改动 A**：新卡 structured_fields 中移除"卡亮点"（已被富字段"亮点"行覆盖）

```python
# 原
'新卡': [('卡种', '卡种'), ('卡亮点', '亮点'), ('适用人群', '适用人群'), ('来源', '来源'), ('详情', '详情')],
# 新
'新卡': [('卡种', '卡种'), ('适用人群', '适用人群'), ('来源', '来源'), ('详情', '详情')],
```

**改动 B**：目录条目 emoji 与正文 H2 emoji 一致性检查 — 当前已一致（都从 `item.get('priority_emoji')` 读取），无需改动。

**改动 C**：全文段落间距统一 — 确保富字段渲染块之间 `space_after=Pt(2)` 一致。

**影响**：消除"亮点"字段的重复渲染（structured 中的"卡亮点"和富字段"亮点"行）。格式更统一。

---

## 测试计划

### 新增测试用例

| 测试 | 覆盖 |
|------|------|
| `test_build_report_title_llm_fallback` | LLM 不可用时 fallback 到 keyword 拼接 |
| `test_build_report_title_with_emoji_items` | 含 emoji 的 items 生成标题 |
| `test_highlight_summary_with_key_benefits` | 传入 key_benefits 后 highlight_summary 增强 |
| `test_highlight_summary_without_enrichment` | 无富字段时 highlight_summary 不变 |
| `test_step6_cancel_list` | score≤3 条目出现在"建议销卡"段落 |
| `test_step6_time_nodes` | 含日期的 notes 提取为时间节点 |
| `test_no_duplicate_highlights` | 新卡不重复渲染"卡亮点"和"亮点" |

### 回归测试

`python -m pytest tests/ -x` 全量通过（与 Phase 1 共 128+ 测试）。

---

## 假设与默认值

1. **LLM 标题压缩**：默认启用，timeout=10s，失败自动 fallback。不影响无 LLM 环境。
2. **highlight_summary 增强**：仅在 Step 5 富字段回写时触发，Step 3 阶段的 highlight_summary 保持原有逻辑。
3. **综合建议升级**：新增段落仅在有数据时渲染，空数据不输出。
4. **格式统一**：移除新卡"卡亮点"字段渲染，因为富字段"亮点"行已覆盖该信息。
5. **市场趋势**：Phase 2 仅从当前批次提取趋势信号，跨期趋势分析留到 Phase 3。