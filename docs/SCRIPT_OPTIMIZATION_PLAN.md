# 周报处理脚本优化计划

**关联文件**：
- `src/md_to_wechat.py`
- `src/weekly_report_to_wechat.py`

**基于**：QA 分析报告中的 18 项问题  
**目标**：将周报质量评分从 6.2/10 提升到 8.5/10  
**状态**：P0 已完成（2026-08-01）✅；P1 进行中

---

## 📌 优化总览

### 影响分析

| 脚本 | 关键改进点 | 优先级 | 预计工作量 |
|------|---------|-------|---------|
| md_to_wechat.py | 垃圾过滤、亮点提取、字段隐藏、时间修复 | P0+P1 | 6-8h |
| weekly_report_to_wechat.py | 垃圾过滤、semantic 块清理 | P1 | 2-3h |

### 总体改进效果

```
当前状态：
- 垃圾信息：7 处
- 空字段：2 处
- 亮点质量：5/10
- 重复条目：3 组
- 整体评分：6.2/10

优化后目标：
- 垃圾信息：0-1 处
- 空字段：0 处
- 亮点质量：8/10
- 重复条目：0 组
- 整体评分：8.5/10
```

---

## 🔧 具体优化方案

### 优化 1：增强垃圾行过滤规则（P0 - ✅ 已完成 2026-08-01）

**文件**：`src/md_to_wechat.py` 中的 `_is_garbage_line()` 函数

**当前代码**（第 74-104 行）：
```python
def _is_garbage_line(line: str) -> bool:
    """检测垃圾行（导航菜单、附件列表等）。"""
    stripped = line.strip()
    garbage_patterns = [
        r"^附件[：:]",
        r"^网上银行",
        # ... 其他模式
        r"^建设银行[·•]",
    ]
    for pattern in garbage_patterns:
        if re.match(pattern, stripped, re.I):
            return True
    return False
```

**问题**：
- 缺少"推卡菜单"模式（中信银行·情侣主题信用卡等）
- 缺少"地址截断"模式（"地址：\n上海市"等）
- 缺少"下一篇"链接模式
- 缺少"免费申请"菜单项

**优化方案**：
```python
def _is_garbage_line(line: str) -> bool:
    """检测垃圾行（导航菜单、附件列表等）。"""
    stripped = line.strip()
    
    # 第一层：快速前缀匹配
    garbage_patterns = [
        # 附件和来源
        r"^附件[：:]",
        r"^原文链接",
        r"^来源[：:]",
        
        # 银行菜单（网上银行功能菜单）
        r"^网上银行",
        r"^登录网上银行",
        r"^卡片激活",
        r"^卡片挂失",
        r"^活动查询",
        r"^申请信用卡",
        r"^在线申请",
        r"^进度查询",
        r"^推卡活动",
        
        # 网站导航
        r"^安全说明",
        r"^站点导航",
        r"^友情链接",
        r"^营业网点",
        r"^加入收藏",
        r"^关于我们",
        r"^人才招聘",
        r"^地址[：:]",  # 不完整的地址
        r"^[A-Za-z0-9]*市$",  # 单独的城市名（上海市、北京市等）
        r"^下一篇",
        
        # 推卡菜单（新增）
        r"^免费申请\s*$",
        r"^[信农建中招平浦兴汇工民光华]*银行[·•].*?信用卡\s*$",
        r"^[信农建中招平浦兴汇工民光华]*银行.*?卡\s*$",
        
        # 页脚/工具栏
        r"^更多内容敬请关注",
        r"^点击阅读原文",
        r"^编辑[：:]",
        r"^（回复.{1,10}可查看详情）$",
    ]
    
    for pattern in garbage_patterns:
        if re.match(pattern, stripped, re.I):
            return True
    
    # 第二层：内容模式匹配（针对多行内容块的开始）
    if re.match(r"^[银农信中建光华招平浦兴汇工民].*?主题.*?信用卡$", stripped):
        return True  # 推卡菜单
    
    return False
```

**预期效果**：
- 消除 7 处垃圾信息中的 5-6 处
- 准确率 > 99%，误杀率 < 1%

---

### 优化 2：隐藏内部标记字段（P0 - ✅ 已完成 2026-08-01）

**文件**：`src/md_to_wechat.py` 中的 `_clean_publish_body()` 函数

**问题**：`_low_value` 等内部标记字段显示在最终输出中

**当前代码**（第 177-190 行）：
```python
bullet_match = re.match(r"^-\s+\*\*([^*]+)\*\*\s*[：:]\s*(.*)$", stripped)
if dropping:
    if not bullet_match:
        continue
    dropping = False
if bullet_match:
    field = bullet_match.group(1).strip()
    value = bullet_match.group(2).strip()
    if field in drop_structured_fields:
        dropping = True
        continue
    # 删除空标题内容
    if not value:
        continue
```

**优化方案**：
```python
bullet_match = re.match(r"^-\s+\*\*([^*]+)\*\*\s*[：:]\s*(.*)$", stripped)
if dropping:
    if not bullet_match:
        continue
    dropping = False
if bullet_match:
    field = bullet_match.group(1).strip()
    value = bullet_match.group(2).strip()
    
    # 隐藏内部标记字段（以 _ 开头）
    if field.startswith("_"):
        continue
    
    if field in drop_structured_fields:
        dropping = True
        continue
    
    # 删除空标题内容
    if not value:
        continue
```

**预期效果**：
- 消除所有内部标记字段（`_low_value` 等）
- 影响范围：13/16 条目

---

### 优化 3：改进亮点字段提取（P0 - ✅ 已完成 2026-08-01）

**文件**：`src/md_to_wechat.py` 中新增函数 + 修改 `_clean_publish_body()`

**问题**：
- 亮点中混入垃圾内容（"附件："等）
- 亮点过长且不精炼
- 包含不完整的句子

**当前实现**（第 172-175 行）：
```python
highlight_match = re.match(r"^\*\*亮点[：:]\*\*\s*(.*)$", stripped)
if highlight_match:
    kept.append(f"**亮点：** {_truncate_text(highlight_match.group(1), limit=150, sentences=2)}")
    continue
```

**优化方案**：
```python
def _clean_highlight(text: str) -> str:
    """清理和优化亮点字段。"""
    # 步骤 1：移除垃圾内容
    text = re.sub(r"附件[\s：:]*", "", text)
    text = re.sub(r"查看附近适用门店.*?\)", "", text)  # 移除门户网址引用
    text = re.sub(r"点击.*?APP.*?\)", "", text)       # 移除 APP 链接
    
    # 步骤 2：移除重复的时间/人群标签
    # 如果已经在结构化信息中出现过，不需要重复
    
    # 步骤 3：补全不完整的句子
    text = re.sub(r"[""'\"]\s*$", "", text)  # 移除末尾未闭合的引号
    if not text.endswith(("。", "？", "！", ".", ")")):
        # 尝试找到最后的完整句子
        sentences = re.split(r"[。？！]", text)
        if len(sentences) > 1:
            text = "。".join(sentences[:-1]) + "。" if sentences[:-1] else text
    
    # 步骤 4：限制长度
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 100:
        text = text[:100].rstrip() + "…"
    
    return text

# 在 _clean_publish_body 中调用
highlight_match = re.match(r"^\*\*亮点[：:]\*\*\s*(.*)$", stripped)
if highlight_match:
    highlight_text = _clean_highlight(highlight_match.group(1))
    kept.append(f"**亮点：** {highlight_text}")
    continue
```

**预期效果**：
- 亮点字段质量从 5/10 提升到 8/10
- 消除 5 处中的 4 处混入的垃圾内容
- 用户可快速理解条目重点

---

### 优化 4：修复活动时间字段（P1 - 本周）

**文件**：`src/md_to_wechat.py` 中的 `_extract_publish_items()` 函数

**问题**：
- 活动时间字段显示生成/发布时间，而非实际活动时间
- 造成用户困惑（"2026.07.31 是什么时间？"）

**当前实现**：
```python
# 在提取 category 后
category = m.group(1).strip() if m else ""
if not category:
    previous_h2 = [name for line_no, name in h2_categories if line_no < start]
    category = previous_h2[-1] if previous_h2 else "其他"
```

**优化方案**：
```python
def _extract_activity_time(body: str) -> str:
    """从活动内容中提取实际活动时间（而非发布时间）。"""
    # 查找"活动时间"、"活动期间"等关键词
    patterns = [
        r"活动(?:时间|期间)[：:]\s*(\d{4}年\d{1,2}月\d{1,2}日[^。]*)",
        r"活动期间[：:]\s*(\d{4}年\d{1,2}月\d{1,2}日[^。]*)",
        r"自(\d{4}年\d{1,2}月\d{1,2}日).*?至(\d{4}年\d{1,2}月\d{1,2}日)",
    ]
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            if len(match.groups()) > 1:
                return f"{match.group(1)}至{match.group(2)}"
            return match.group(1)
    return ""

# 在 _extract_publish_items 中修改
items.append({
    "title": title, 
    "category": category, 
    "body": body, 
    "source_url": source_url,
    "activity_time": _extract_activity_time(body) if "活动" in category else ""
})

# 然后在 build_publish_markdown 中使用 activity_time
```

**预期效果**：
- 活动时间准确率从 30% 提升到 95%
- 消除用户困惑

---

### 优化 5：调整去重相似度阈值（P1 - 本周）

**文件**：`src/md_to_wechat.py` 中的 `build_publish_markdown()` 函数

**问题**：
- 目前相似度阈值 0.8，导致某些实质重复的条目（如多个"农业银行活动"）未被识别
- 从 16 条减到 13 条，仍有 3 处重复（第 188、263 条等）

**当前代码**（第 323-348 行）：
```python
deduplicated = []
for i, item in enumerate(items):
    is_duplicate = False
    for j in range(i):
        if _similarity_score(item["title"], items[j]["title"]) > 0.8:
            is_duplicate = True
            break
    if not is_duplicate:
        deduplicated.append(item)
```

**优化方案**：
```python
def _should_deduplicate(title1: str, title2: str, category: str) -> bool:
    """判断是否应该去重，考虑分类信息。"""
    score = _similarity_score(title1, title2)
    
    # 对于活动类，降低相似度阈值（更激进的去重）
    if "活动" in category:
        return score > 0.75  # 从 0.8 降至 0.75
    
    # 对于其他类，保持原阈值
    return score > 0.8

# 在 build_publish_markdown 中修改去重逻辑
deduplicated = []
for i, item in enumerate(items):
    is_duplicate = False
    for j in range(i):
        if _should_deduplicate(
            item["title"], 
            items[j]["title"],
            item["category"]
        ):
            is_duplicate = True
            break
    if not is_duplicate:
        deduplicated.append(item)
```

**预期效果**：
- 活动类重复条目从 3 个降至 0 个
- 总条目数从 13 条进一步优化

---

### 优化 6：改进 semantic 块内容清理（P1 - 本周）

**文件**：`src/weekly_report_to_wechat.py` 中的 `_render_semantic()` 函数

**问题**：某些 semantic 块中仍然包含垃圾内容

**当前实现**（第 585-625 行）：
```python
def _render_semantic(b: dict) -> str:
    """渲染语义段（亮点/定位/原文链接/活动内容 等）。"""
    prefix = b["prefix"]
    color = b["color"]
    body = b["body"].strip() if b.get("body") else ""
    # ... 渲染逻辑
```

**优化方案**：
```python
def _render_semantic(b: dict) -> str:
    """渲染语义段（亮点/定位/原文链接/活动内容 等）。"""
    prefix = b["prefix"]
    color = b["color"]
    body = b["body"].strip() if b.get("body") else ""
    links = b.get("links", [])
    is_block = b.get("is_block", False)

    # 新增：清理垃圾内容
    body = re.sub(r"附件[\s：:]*.*", "", body, flags=re.DOTALL)
    body = re.sub(r"[推卡菜单].{0,20}", "", body)
    body = re.sub(r"（点击.*?）", "", body)
    body = body.strip()

    # 空内容检测
    if not body and not links:
        return ""
    
    # ... 继续原有逻辑
```

**预期效果**：
- 消除 semantic 块中的垃圾内容
- 影响范围：8/13 活动条目

---

## 📊 实施计划与时间表

### Week 1：P0 优化（立即）

| 日期 | 任务 | 工作量 | 验证 |
|------|------|-------|------|
| Day 1 | 优化 1：增强垃圾过滤 | 1h | 生成 HTML 检查 |
| Day 1 | 优化 2：隐藏内部标记 | 0.5h | 检查输出中是否有 `_*` 字段 |
| Day 2 | 优化 3：改进亮点提取 | 2h | 亮点字段长度和清洁度检查 |
| Day 2 | 测试和集成 | 1.5h | 端到端测试 |
| **小计** | **P0 完成** | **5h** | **评分目标：7.5/10** |

### Week 2：P1 优化（本周）

| 日期 | 任务 | 工作量 | 验证 |
|------|------|-------|------|
| Day 3 | 优化 4：修复活动时间 | 1.5h | 检查 activity_time 提取准确率 |
| Day 3 | 优化 5：调整去重阈值 | 1h | 验证重复条目数量 |
| Day 4 | 优化 6：改进 semantic 块 | 1.5h | weekly_report HTML 输出检查 |
| Day 4 | 测试和优化 | 1h | 完整验证 |
| **小计** | **P1 完成** | **5h** | **评分目标：8.5/10** |

### 总投入：10 小时开发 + 2 小时测试 = 12 小时

---

## ✅ 验证清单

### 单元测试用例

```python
# 测试用例 1：垃圾行过滤
test_garbage_lines = [
    "中信银行·情侣主题信用卡",
    "免费申请",
    "网上银行",
    "地址：上海市",
    "下一篇",
]
for line in test_garbage_lines:
    assert _is_garbage_line(line) == True

# 测试用例 2：亮点清理
test_highlights = [
    "附件：XXX  内容1",  # 应去除附件
    "2026.07.31；人群；满30返5元\" 查看门店），通过刷卡...",  # 应截断
]
for hl in test_highlights:
    result = _clean_highlight(hl)
    assert "附件" not in result
    assert len(result) <= 100

# 测试用例 3：活动时间提取
test_bodies = [
    "活动期间：2026年8月1日至8月31日",
    "自2026年9月13日起，航空类联名信用卡...",
]
for body in test_bodies:
    time = _extract_activity_time(body)
    assert time != ""  # 应能提取时间
```

### 端到端验证

| 检查项 | 验证方法 | 预期结果 |
|-------|--------|--------|
| 垃圾内容 | 生成 HTML，检查推卡/菜单 | 0-1 处 |
| 空字段 | 查找 `<strong></strong>` 或 `**：** ` | 0 个 |
| 亮点质量 | 手动检查 5 个条目的亮点 | 都 < 100 字，清晰 |
| 活动时间 | 对比 8 个活动条目的时间 | 8/8 准确 |
| 重复条目 | 统计最终条目数 | 13-14 条（无重复） |

---

## 📈 预期改进对比

### 改进前后对比

```
问题类型        | 改进前 | 改进后 | 改进率
────────────────┼────────┼────────┼────────
垃圾信息        |   7    |   1    |  86%
空字段          |   2    |   0    | 100%
亮点质量        |  5/10  |  8/10  |  60%
活动时间准确    |  3/8   |  7/8   |  133%
重复条目        |   3    |   0    | 100%
────────────────┼────────┼────────┼────────
整体评分        | 6.2/10 | 8.5/10 |  37%
```

---

## 💾 相关配置和参数

### 可调参数

```python
# md_to_wechat.py
GARBAGE_PATTERN_COUNT = 35  # 垃圾模式数（从 20 增加）
HIGHLIGHT_MAX_LENGTH = 100  # 亮点最大长度（从 120 调整）
HIGHLIGHT_MAX_SENTENCES = 2  # 亮点最多句数

# 相似度阈值（按分类）
DEDUP_THRESHOLD_ACTIVITY = 0.75  # 活动类（从 0.8 降至）
DEDUP_THRESHOLD_DEFAULT = 0.8    # 其他类型
```

---

## 🔗 相关文档

- **QA 分析报告**：`docs/QA_ANALYSIS_WEEKLY_REPORT.md`
- **第二阶段实现**：`docs/PHASE2_IMPLEMENTATION.md`
- **进度总结**：`docs/PROGRESS_SUMMARY_PHASE2.md`

---

**预计完成时间**：2026-08-02 到 2026-08-05  
**负责人**：Claude Code  
**状态**：P0 已完成（2026-08-01），P1 进行中

