# 代码审查报告

> 日期：2026-07-18  
> 审查范围：`docx_to_wechat.py`（413 行）、`weekly_report_to_wechat.py`（644 行）、`run.bat`（277 行）、`src/agent.py`（working tree 差分）

---

## P1 — 正确性（0 项）

无发现。

---

## P2 — 可靠性 & 健壮性（3 项）

### 2.1 `weekly_report_to_wechat.py` · 未使用的导入 `parse_docx`

**文件**：`weekly_report_to_wechat.py` 第 28 行  
**严重度**：P2  
**描述**：
```python
from docx_to_wechat import parse_docx, _read_rels, esc, inline, color_for
```
`parse_docx` 被导入但从未被使用——`weekly_report_to_wechat.py` 有自己的 `_parse_paragraph()` 加 `convert()` 里直接读 `word/document.xml` 解析段落。多余的导入不会报错，但会让读者困惑。

**建议**：删除未使用的导入 `parse_docx`。

---

### 2.2 两个脚本的 `_read_rels` 逻辑重复

**文件**：`docx_to_wechat.py` 第 44 行 / `weekly_report_to_wechat.py` 第 28 行  
**严重度**：P2  
**描述**：`weekly_report_to_wechat.py` 通过 `from docx_to_wechat import _read_rels` 复用关系映射函数，但两脚本的 `convert()` 入口各自独立调用了 `_read_rels` + 直接读 XML，没有真正的段落解析层复用。若后续需要修改 docx 解析逻辑（如添加表格支持、图片提取），需要两处同步更新。

**建议**：将 `docx_to_wechat.parse_docx()` 重构为通用 docx 段落解析器，两脚本共享同一入口。

---

### 2.3 `docx_to_wechat.py` · `ElementTree` 未使用

**文件**：`docx_to_wechat.py` 第 21 行  
**严重度**：P2  
**描述**：
```python
from xml.etree import ElementTree as ET
```
`ET` 模块被导入但从未被调用——`docx_to_wechat.py` 全用正则解析 XML，没有用到 `ET.fromstring()` 或 `ET.parse()`。这是之前 XML 命名空间剥离失败尝试的残留。

**建议**：删除未使用的 `import`。

---

## P3 — 可维护性 & 代码质量（5 项）

### 3.1 `docx_to_wechat.py` · `W_NS` 和 `R_NS` 常量未使用

**文件**：`docx_to_wechat.py` 第 40-41 行  
**严重度**：P3  
**描述**：
```python
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
```
这两个常量定义后从未在文件中被引用——是 `ElementTree` 解析未遂的残留。

**建议**：删除未使用的常量。

---

### 3.2 `weekly_report_to_wechat.py` · `color_for` 未使用

**文件**：`weekly_report_to_wechat.py` 第 28 行  
**严重度**：P3  
**描述**：`color_for` 被导入（来自 `docx_to_wechat`），但 `weekly_report_to_wechat.py` 有自己的 `_h1_color()` + `_h2_priority()` 配色逻辑，没有调用 `color_for`。

**建议**：删除未使用的导入项。

---

### 3.3 两脚本的 HTML 样式风格不一致

**文件**：`docx_to_wechat.py` 第 352-379 行 / `weekly_report_to_wechat.py` 第 541-608 行  
**严重度**：P3  
**描述**：两个脚本面向不同 docx 格式，但生成的公众号 HTML 风格不一致：

| 项目 | `docx_to_wechat.py` | `weekly_report_to_wechat.py` |
|---|---|---|
| 外壳 max-width | `680px` | `640px` |
| 条目样式 | `<h3>` + `<p>` + `<blockquote>` | 圆角卡片（`border-radius:8px`）+ 左侧 4px 色条 |
| 链接汇总 | `<ol><li>` | `<p>` 堆叠，无 OL 标签 |
| 总览条 | 简单文字 | 类别统计 + 蓝色 `<strong>` |
| AI 声明 | 无 | `background:#fff7ed` 声明 |
| CTA 收尾 | 无 | `background:#0f172a` 互动 CTA |

如果用户想把两类文章混发在同一公众号，会显得不统一。

**建议**：统一 `docx_to_wechat.py` 的外壳和字号，使其与 `weekly_report_to_wechat.py` 的参考风格对齐。非阻塞，可后续按需优化。

---

### 3.4 `docx_to_wechat.py` · `is_title_line()` 函数未使用

**文件**：`docx_to_wechat.py` 第 153-155 行  
**严重度**：P3  
**描述**：
```python
def is_title_line(text: str) -> bool:
    return bool(re.match(r"^.+?\s*-\s*.+$", text)) and not text.startswith(...)
```
该函数定义后从未被 `parse_structure()` 或任何其他函数调用——`parse_structure` 直接用 `if cur is not None: items.append(cur)` 来判断是否为新标题行。

**建议**：删除未使用的函数。

---

### 3.5 `weekly_report_to_wechat.py` · `item_count` 变量未使用

**文件**：`weekly_report_to_wechat.py` 第 549 行  
**严重度**：P3  
**描述**：
```python
item_count = 0
...
for item in cat["items"]:
    item_count += 1
```
`item_count` 一直被递增，但从未被用于输出或作为返回值（总览条已用 `total_items` 统计）。

**建议**：删除未使用的变量，或用于其他统计输出。

---

## S — 安全（0 项）

无发现。`inline()` 中用 `esc()` 对用户输入做 HTML 转义，预防 XSS；`esc(lnk["url"])` 对 URL 做转义，预防注入。

---

## 汇总

| 等级 | 数量 | 关键项 |
|---|---|---|
| P1 正确性 | 0 | — |
| P2 可靠性 | 3 | 未使用的导入、`_read_rels` 重复、`ElementTree` 残留 |
| P3 可维护性 | 5 | 未使用的常量/变量/函数、样式漂移 |
| S 安全 | 0 | — |

**总计 8 项**，均为 P2/P3。最值得先修的 3 项：

1. **P2** `docx_to_wechat.py` 第 21 行：删 `from xml.etree import ElementTree as ET`（未使用）
2. **P2** `docx_to_wechat.py` 第 40-41 行：删 `W_NS`、`R_NS` 常量（未使用）
3. **P2** `weekly_report_to_wechat.py` 第 28 行：删 `parse_docx`、`color_for` 未使用导入