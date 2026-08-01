# P1 优化工作计划（活动时间 / 去重阈值 / semantic 块清理）

**时间**：2026-08-01  
**状态**：✅ 已完成（三项 P1 优化已集成并通过验证）  
**前置**：P0 三项优化已完成（2026-08-01，见 `docs/P0_OPTIMIZATION_STATUS.md`）

---

## 📌 优化总览

| 编号 | 优化项 | 文件 | 优先级 | 预期效果 |
|------|--------|------|-------|---------|
| P1-1 | 修复活动时间字段 | `src/md_to_wechat.py` | P1 | 活动时间准确率 30% → 95% |
| P1-2 | 调整去重相似度阈值 | `src/md_to_wechat.py` | P1 | 活动类重复条目 3 → 0 |
| P1-3 | 改进 semantic 块清理 | `src/weekly_report_to_wechat.py` | P1 | 消除 semantic 块中的垃圾内容 |

**总目标**：周报质量评分 7.5/10 → 8.5/10

---

## 🔧 P1-1：修复活动时间字段

### 问题

活动条目的时间字段显示的是生成/发布时间，而非实际活动时间（"2026.07.31 是什么时间？"），造成用户困惑。

### 现状分析（`src/md_to_wechat.py`）

- `_extract_publish_items()` 提取条目时只记录 `title / category / body / source_url`，**没有活动时间字段**
- `_extract_activity_essence()` 能从 body 中提取"期间：xxx"，但只用于生成"活动要点"摘要块
- 时间提取正则只匹配 `\d{4}年\d{1,2}月\d{1,2}日[^。]*` 一类完整日期格式

### 实施方案

1. **新增 `_extract_activity_time(body: str) -> str`**：从活动内容中提取实际活动时间
   - 匹配模式（按优先级）：
     - `活动(?:时间|期间)[：:]\s*(\d{4}年\d{1,2}月\d{1,2}日[^。，；]*)`
     - `自(\d{4}年\d{1,2}月\d{1,2}日).*?至(\d{4}年\d{1,2}月\d{1,2}日)`（返回 `X至Y`）
     - `(\d{4}年\d{1,2}月\d{1,2}日)起`
     - 兜底：`(\d{4}年\d{1,2}月\d{1,2}日)` 首次出现
   - 返回空字符串表示无法提取（调用方回退原逻辑）

2. **`_extract_publish_items()` 增加 `activity_time` 字段**：
   ```python
   items.append({
       "title": title, "category": category, "body": body,
       "source_url": source_url,
       "activity_time": _extract_activity_time(body) if ("活动" in category or "优惠" in category) else "",
   })
   ```

3. **`build_publish_markdown()` 输出活动时间**：
   - 在活动类条目的 body 前插入 `**活动时间：** {activity_time}`（若有值）
   - 与 `**活动要点：**` 共存，避免重复

### 验证

- 单元：`_extract_activity_time("活动期间：2026年8月1日至8月31日")` → 非空
- 单元：`_extract_activity_time("自2026年9月13日起，航空类联名信用卡...")` → 非空
- 端到端：对比 8 个活动条目，时间准确率 ≥ 7/8

---

## 🔧 P1-2：调整去重相似度阈值

### 问题

当前固定阈值 0.8，导致部分实质重复的活动条目（如多个"农业银行活动"）未被识别。16 条中仍有 3 处重复。

### 现状分析（`src/md_to_wechat.py` `build_publish_markdown()`）

```python
if _similarity_score(item["title"], items[j]["title"]) > 0.8:
    is_duplicate = True
```

阈值对所有类别一刀切，活动类标题相似度高（都是"农业银行 xxx 活动"），需要更激进的去重。

### 实施方案

1. **新增 `_should_deduplicate(title1: str, title2: str, category: str) -> bool`**：
   ```python
   def _should_deduplicate(title1: str, title2: str, category: str) -> bool:
       """判断是否应该去重，考虑分类信息。"""
       score = _similarity_score(title1, title2)
       if "活动" in category or "优惠" in category:
           return score > 0.75  # 活动类更激进
       return score > 0.8       # 其他类保持原阈值
   ```

2. **替换去重循环中的判断**：传入当前条目的 `category`。

### 风险控制

- 阈值 0.75 只对"活动/优惠"类生效，权益变更、新卡等其他类别不受影响
- 相似度函数 `_similarity_score` 已剔除数字/年月日干扰，误杀风险低

### 验证

- 端到端：最终条目数 13-14 条（无重复）
- 抽查：确认没有误删不同银行的不同活动

---

## 🔧 P1-3：改进 semantic 块内容清理

### 问题

`weekly_report_to_wechat.py` 的 `_render_semantic()` 渲染语义段（亮点/活动内容/详情等）时，body 中仍混有垃圾内容（"附件："、推卡菜单、门户引用等）。

### 现状分析（`src/weekly_report_to_wechat.py` `_render_semantic()` 575-625 行）

```python
body = b["body"].strip() if b.get("body") else ""
...
# 空内容检测后直接截断、渲染，无垃圾清理步骤
body = _truncate_semantic_body(prefix, body)
```

### 实施方案

在 `_render_semantic()` 的 body 处理中，`_truncate_semantic_body()` 之前加入清理：

```python
# 清理语义块中的垃圾内容
body = re.sub(r"附件[\s：:]*[^\n]*", "", body)          # 附件引用
body = re.sub(r"（?点击[^）)]*[)）]", "", body)           # 门户/APP 引用
body = re.sub(r"查看附近适用门店.*?[)）]", "", body)     # 门店引用
body = re.sub(r"\s+", " ", body).strip()
```

清理后再执行原有的空内容检测与截断逻辑。

### 验证

- 端到端：生成 HTML，检查 semantic 块（亮点/活动内容）中无"附件""点击"等残留
- 影响范围：8/13 活动条目

---

## 📅 实施步骤

| 步骤 | 任务 | 工作量 | 验证 |
|------|------|-------|------|
| 1 | P1-1：`_extract_activity_time` + 接入 | 1.5h | 活动时间准确率检查 |
| 2 | P1-2：`_should_deduplicate` 阈值调整 | 1h | 重复条目数量检查 |
| 3 | P1-3：`_render_semantic` 清理 | 1.5h | weekly_report HTML 输出检查 |
| 4 | 测试与集成 | 1h | 端到端验证 |

**总计**：约 5 小时

---

## 📈 预期改进对比

```
问题类型        | 改进前 | 改进后 | 改进率
────────────────┼────────┼────────┼────────
活动时间准确    |  3/8   |  7/8   |  133%
重复条目        |   3    |   0    |  100%
semantic 垃圾   |  多    |   0    |  100%
────────────────┼────────┼────────┼────────
整体评分        | 7.5/10 | 8.5/10 |  13%
```

---

## ✅ 实际验证结果（2026-08-01）

使用 `data/Weekly_Report_2026年8月第1周.md` 端到端生成 HTML 验证：

| 检查项 | 验证方法 | 结果 |
|-------|--------|------|
| 语法检查 | `python -m py_compile src/md_to_wechat.py src/weekly_report_to_wechat.py` | ✅ 通过 |
| 活动时间提取 | `_extract_publish_items()` 直接验证 | ✅ 10 条活动全部提取成功 |
| 活动时间字段 | HTML 中 `**活动时间：**` 字段 | ✅ 10 条，无重复、无粘连 |
| 条目数 | HTML 中 h3 标题统计 | ✅ 16 → 13 条（去重生效） |
| 垃圾关键词 | 27 项关键词残留检查 | ✅ 0 处 |
| semantic 清理 | `_render_semantic()` 4 组单元用例 | ✅ 附件/门店/点击引用均清除 |

> 实施中修正的问题：初版 `_extract_activity_time` 只支持中文日期（`2026年8月1日`），而真实数据为点分格式（`2026.07.31`），已扩展支持 `2026.07.31` / `2026-07-31` / `2026/07/31` 四种格式；正文中已有的 `- **活动时间**：` 行由统一输出替代，避免重复显示。

测试产物：`data/test_p1_after.html`（含元数据 `data/test_p1_after.json`）。

---

## 🔧 代码审查修复记录（2026-08-01）

P1 修订后经两轮代码审查，共修复 5 处问题：

| # | 位置 | 审查问题 | 修复方案 |
|---|------|---------|---------|
| 1 | `weekly_report_to_wechat.py` `_render_semantic()` | 空内容判断在垃圾清理之前执行，body 清空后仍渲染空块 | 清理后重新判空：`if not body and not links: return ""` |
| 2 | `md_to_wechat.py` `_should_deduplicate()` | 去重只使用当前条目 category，活动条目与其他类别比较时阈值不对称，可能跨类别误删相似标题 | 改为双 category 参数，两条目类别不一致直接不去重 |
| 3 | `md_to_wechat.py` `_extract_activity_time()` | `[^\n]+` / `[^\n。；;]+` 把整行内容作为时间值（如"2026.07.31，周末有效，详情见"） | 新增 `_match_time()` 从字段值中提取日期区间/时间短语，丢弃附加文本 |
| 4 | `md_to_wechat.py` `_is_garbage_line()` | 宽泛规则 `^[^：：]*银行.*?信用卡\s*$` 误删"中国银行发布新款主题信用卡"等正文标题；228 行 `.*?主题` 同样误杀 | 收窄为菜单项形态（银行名前缀 ≤12 字、银行与信用卡间 ≤15 字、无句子标点）+ 动词负向前瞻（发布/推出/新增/发行/公告等），区分菜单项与正文标题 |
| 5 | `md_to_wechat.py` `_extract_activity_time()` | `time_phrase` 起始日期强制四位年份，`6月1日-6月30日` 等无年份区间无法提取 | 起始日期改用 `date_short`（年份可选），无年份时保留原文 |

### 审查修复验证

| 检查项 | 结果 |
|-------|------|
| `py_compile`（两个脚本） | ✅ 通过 |
| 推卡菜单识别（6 例） / 正文标题保留（8 例） | ✅ 全部通过 |
| 原 33 个垃圾模式回归 | ✅ 无遗漏 |
| 活动时间：无年份区间 / 有年份回归 / 附加文本剔除 | ✅ 全部通过 |
| 去重：同类别去重 / 跨类别不去重 | ✅ 全部通过 |
| semantic 空块：纯垃圾→空 / 垃圾+有效→保留 | ✅ 全部通过 |
| 端到端：活动时间 10 条无附加文本、垃圾 0、亮点 13 条 ≤100 字 | ✅ 通过 |

---

## 🔗 相关文档

- **P0 状态**：`docs/P0_OPTIMIZATION_STATUS.md`
- **优化总计划**：`docs/SCRIPT_OPTIMIZATION_PLAN.md`
- **QA 分析报告**：`docs/QA_ANALYSIS_WEEKLY_REPORT.md`
