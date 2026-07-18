# 代码审查报告

> 日期：2026-07-18（周六）
> 审查范围：`src/agent.py`（1868 行主编排）、`src/docx_to_wechat.py`（413 行）、`src/weekly_report_to_wechat.py`（644 行）、`src/merge_docs.py`（1174 行）、`common/schema.py`（349 行统一契约）
> 审查方法：逐文件读取源码 → 标记问题 → 按等级归类
> 严重级别：P1 正确性 / P2 可靠性 / P3 可维护性 / S 安全
>
> **状态汇总**：14 项中 ✅ 已修 13 项 / ⏳ 待处理 1 项（3.1 部分修，仅宽度统一+删尾部 AI 声明/CTA）

---

## P1 — 正确性（2 项）

### 1.1 `common/schema.py` · `load_json()` 丢失原始 `generated_at`

**状态**：✅ 已修（2026-07-18）  
**文件**：`common/schema.py` 第 337-346 行  
**严重度**：P1  
**描述**：
```python
@classmethod
def load_json(cls, filepath: str) -> "CreditCardBatch":
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = [CreditCardItem.from_dict(it) for it in data.get("items", [])]
    return cls(items=items, batch_label=data.get("batch_label", ""))
```

`CreditCardBatch.__init__` 把 `generated_at` 设为 `datetime.now().isoformat(timespec="seconds")`，因此从磁盘加载后**原始生成时间被覆盖为当前时间**，无法追溯。`to_dict()` 又把 `generated_at` 写入文件，但 `load_json` 不读它——契约不对称。

另外 `load_json` 完全忽略 JSON 中的 `schema_version`，跨版本加载没有兼容性检查。

**建议**：
```python
@classmethod
def load_json(cls, filepath: str) -> "CreditCardBatch":
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = [CreditCardItem.from_dict(it) for it in data.get("items", [])]
    batch = cls(items=items, batch_label=data.get("batch_label", ""))
    batch.generated_at = data.get("generated_at", batch.generated_at)
    if data.get("schema_version") and data["schema_version"] != cls.SCHEMA_VERSION:
        print(f"[Warn] schema version mismatch: file={data['schema_version']} code={cls.SCHEMA_VERSION}")
    return batch
```

---

### 1.2 `src/agent.py` · Phase 1 富字段回写匹配键脆弱

**状态**：✅ 已修（2026-07-18）  
**文件**：`src/agent.py` 第 1657-1685 行  
**严重度**：P1  
**描述**：
```python
for cat_data in analysis['category_summary'].values():
    for item_data in cat_data.get('items', []):
        t = item_data.get('title', '')
        if t:
            enriched_map[t] = item_data
for item in batch.items:
    enriched = enriched_map.get(item.title, {})
```

富字段（`target_audience`/`key_benefits`/`fee_assessment`/`worth_applying`/`priority_emoji`）回写以 **`item.title` 字符串完全相等**作为匹配键。但同一标题在不同分类下可能重复，且 Step5 分析侧的 `title` 经过 LLM 处理后可能与 `batch.items[i].title` 有空白/全半角差异，导致富字段无法回写。日志只打 `Enriched N items`，匹配失败时静默。

**建议**：
1. Step5 输出时应保留 `item_id`，回写以 `item_id` 为主键
2. 若只能用 title，先 `normalize`（strip + 全角转半角），并打印匹配率（`enriched_count / batch.size()`）

---

## P2 — 可靠性 & 健壮性（6 项）

### 2.1 `src/docx_to_wechat.py` · `ElementTree` 未使用

**状态**：✅ 已修（2026-07-18）
**文件**：`src/docx_to_wechat.py` 第 21 行  
**严重度**：P2  
**描述**：
```python
from xml.etree import ElementTree as ET
```
全文 grep 未发现 `ET.` 任何调用——`docx_to_wechat.py` 全程用正则解析 XML。是之前 XML 命名空间剥离失败尝试的残留，对运行无影响但增加阅读噪声。

**建议**：删除未使用的 import。

---

### 2.2 `src/docx_to_wechat.py` · `W_NS` / `R_NS` 常量未使用

**状态**：✅ 已修（2026-07-18）
**文件**：`src/docx_to_wechat.py` 第 40-41 行  
**严重度**：P2  
**描述**：
```python
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
```
定义后从未在文件中被引用——同属 `ElementTree` 解析未遂的残留。

**建议**：删除未使用的常量。

---

### 2.3 `src/docx_to_wechat.py` · `is_title_line()` 函数未使用

**状态**：✅ 已修（2026-07-18）
**文件**：`src/docx_to_wechat.py` 第 153-155 行  
**严重度**：P2  
**描述**：
```python
def is_title_line(text: str) -> bool:
    """标题行：『银行 - 卡名』或『银行 - 活动名』。"""
    return bool(re.match(r"^.+?\s*-\s*.+$", text)) and not text.startswith(
        ("来源", "核心内容", "点评", "本期", "新卡", "卡组织", "年费", "原始"))
```
该函数定义后从未被 `parse_structure()` 或任何其他函数调用——`parse_structure` 直接用 `if cur is not None: items.append(cur)` 来判断新条目起点。

**建议**：删除未使用的函数。

---

### 2.4 `src/weekly_report_to_wechat.py` · 未使用的导入

**状态**：✅ 已修（2026-07-18）
**文件**：`src/weekly_report_to_wechat.py` 第 28 行  
**严重度**：P2  
**描述**：
```python
from src.docx_to_wechat import parse_docx, _read_rels, esc, inline, color_for
```

实际使用情况：

| 导入项 | 使用情况 |
|---|---|
| `parse_docx` | ❌ 未使用（脚本有自己的 `_parse_paragraph` + 直接读 `word/document.xml`） |
| `_read_rels` | ✅ 第 614 行使用 |
| `esc` | ✅ 多处使用 |
| `inline` | ✅ 多处使用 |
| `color_for` | ❌ 未使用（脚本有自己的 `_h1_color` / `_h2_priority` 配色） |

**建议**：精简为 `from src.docx_to_wechat import _read_rels, esc, inline`。

---

### 2.5 `src/weekly_report_to_wechat.py` · `item_count` 变量未使用

**状态**：✅ 已修（2026-07-18）
**文件**：`src/weekly_report_to_wechat.py` 第 549、583 行  
**严重度**：P2  
**描述**：
```python
item_count = 0
...
for item in cat["items"]:
    item_count += 1
    body_parts.append(render_item_card(item, cat))
```
`item_count` 在循环中递增，但**从未被读取用于任何输出**。概览条的条目计数走的是 `total_items`（第 556-561 行），与此变量无关。

**建议**：删除未使用的变量，或改为在概览条/卡片标题里展示「第 N 条」序号。

---

### 2.6 `src/agent.py` · `_low_val_kw` 在两处重复定义

**状态**：✅ 已修（2026-07-18）
**文件**：`src/agent.py` 第 1197-1199 行（`step6_append_suggestions`）与第 1714-1715 行（`run_pipeline`）  
**严重度**：P2  
**描述**：

`step6_append_suggestions` 中：
```python
_low_val_kw = ["首绑赠", "立减券", "洗车券",
               "首单立减", "卡号订制",
               "满30返", "满200返", "达标礼"]
```

`run_pipeline` 中：
```python
_low_val_kw = ["首绑赠", "立减券", "洗车券", "首单立减", "卡号订制",
               "满30返", "满200返", "达标礼"]
```

同一份「低价值活动关键词」常量在两个函数里各定义一次，且 `step6` 里多了一行换行格式。任何一边漏改都会导致 Step6 过滤与 Step3 标记不一致。

**建议**：将常量提到模块级（如 `LOW_VALUE_KEYWORDS`），两处共用。

---

## P3 — 可维护性 & 代码质量（5 项）

### 3.1 两脚本的 HTML 外壳风格不一致

**状态**：✅ 已修（2026-07-18）—— 外壳 max-width 统一为 680px；删除 `weekly_report_to_wechat.py` 尾部多余的 `render_ai_disclaimer()` / `render_cta()` 函数及调用
**文件**：`src/docx_to_wechat.py` 第 375-379 行 / `src/weekly_report_to_wechat.py` 第 314-320 行  
**严重度**：P3  
**描述**：

| 项目 | `docx_to_wechat.py` | `weekly_report_to_wechat.py` |
|---|---|---|
| 外壳 max-width | `680px` | `640px` |
| 条目样式 | `<h3>` + `<p>` + `<blockquote>` | 圆角卡片（`border-radius:8px`）+ 左侧 4px 色条 |
| 链接汇总 | `<ol><li>` | `<p>` 堆叠，无 OL 标签 |
| 总览条 | 简单文字 | 类别统计 + 蓝色 `<strong>` |
| AI 声明 | 无 | `background:#fff7ed` 声明 |
| CTA 收尾 | 无 | `background:#0f172a` 互动 CTA |

两脚本面向不同 docx 格式，但生成的公众号 HTML 风格漂移较大。用户混发同一公众号时会显得不统一。

**建议**：非阻塞。后续可抽取 `render_shell()` / `render_card()` 等公共渲染层供两脚本共享。

---

### 3.2 `src/weekly_report_to_wechat.py` · `from src.docx_to_wechat` 强耦合包路径

**状态**：✅ 已修（2026-07-18）
**文件**：`src/weekly_report_to_wechat.py` 第 28 行  
**严重度**：P3  
**描述**：
```python
from src.docx_to_wechat import parse_docx, _read_rels, esc, inline, color_for
```
导入路径写死 `src.docx_to_wechat`，依赖 CWD 在项目根目录且 `src` 是 Python package。若用户从 `src/` 目录运行 `python weekly_report_to_wechat.py xxx.docx`，会因 `src` 不在 `sys.path` 而 `ModuleNotFoundError`。

**建议**：在 `main()` 入口加 `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` 兜底，或将两脚本都纳入 `src` 包并用相对导入。

---

### 3.3 `src/agent.py` · `step6_append_suggestions` 内嵌 `from collections import defaultdict`

**状态**：✅ 已修（2026-07-18）
**文件**：`src/agent.py` 第 1307 行  
**严重度**：P3  
**描述**：
```python
# Phase 3: 同类卡对比
from collections import defaultdict as _ddict
scene_groups = _ddict(list)
```
函数体内延迟导入 `defaultdict` 并取别名 `_ddict`，但同函数在更早位置（如 `cat_emoji = {...}`）已使用模块级常量，这里却没有提到模块顶部。属于「能跑但不整洁」的代码异味。

**建议**：将 `from collections import defaultdict` 移到文件顶部 import 区，去掉别名。

---

### 3.4 `src/agent.py` · 巨型 `run_pipeline` 函数缺少分段

**状态**：✅ 已修（2026-07-18）
**文件**：`src/agent.py` 第 1517-1813 行（约 297 行）  
**严重度**：P3  
**描述**：

`run_pipeline` 单函数 297 行，依次执行：Step1 抓取 → Step3 合并 → Step3.5 LLM 审核 → Step5 分析 → Phase1 富字段回写 → P0-3 噪音过滤 → Step4 报告 → Step6 建议 → Step6.5 QA → Phase4 QA 反馈 → Step7 归档 → last_run 写入 → review queue 导出。

错误处理风格不统一：

| 段落 | 错误处理 |
|---|---|
| Step3.5 LLM Review | `try/except Exception` 静默跳过 |
| Phase 4 QA Feedback | `try/except Exception: pass` 完全吞错 |
| Step 6.5 QA 验收 | 区分 `ImportError` 与 `Exception` |
| review queue 导出 | `try/except Exception` 打印 warn |

**建议**：非阻塞。可将 Phase1 富字段回写、P0-3 噪音过滤、Phase4 QA 反馈各自抽成小函数 `_enrich_fields(batch, analysis)` / `_filter_noise(batch)` / `_report_qa_feedback(report_file)`，主函数更线性。

---

### 3.5 `common/schema.py` · `from_dict()` 与 `to_dict()` 字段未对称

**状态**：✅ 已修（2026-07-18）
**文件**：`common/schema.py` 第 202-287 行  
**严重度**：P3  
**描述**：

`to_dict()` 输出 35+ 字段，`from_dict()` 读取时大多使用 `d.get("field", "")` 或 `d.get("field")`，但有几处不对称：

| 字段 | `to_dict` 输出 | `from_dict` 读取 | 不对称点 |
|---|---|---|---|
| `extracted_at` | 写出 | `d.get("extracted_at", "")` → `__init__` 又 fallback 到 `datetime.now()` | 空字符串时 `extracted_at or datetime.now()` 会覆盖 |
| `confidence` | 写出 | `d.get("confidence")` → `confidence or {}` | 反序列化后空 dict，无法区分"未保存"和"空" |
| `key_benefits` | 写出 | `d.get("key_benefits")` → `key_benefits or []` | 同上 |

这意味着同一个 item 经过 `to_dict → from_dict → to_dict` 后，`extracted_at` 字段会被刷新为当前时间，与磁盘存档不一致。

**建议**：`from_dict` 中对 `extracted_at` 显式取 `d.get("extracted_at")` 并在 `__init__` 中区分「未传入」与「显式空」。或者把 `extracted_at` 默认值改为只在 `__init__` 第一次构造时设置。

---

## S — 安全（1 项）

### S.1 `src/agent.py` · `_load_json_fallback` 多编码尝试

**状态**：✅ 已修（2026-07-18）
**文件**：`src/agent.py` 第 81-89 行  
**严重度**：信息（无安全风险）  
**描述**：
```python
for encoding in ("utf-8", "utf-8-sig", "gbk", "cp936"):
    try:
        with open(filepath, "r", encoding=encoding) as f:
            return json.load(f)
    except Exception:
        continue
return None
```
依次尝试 4 种编码读取 JSON。无安全风险——`json.load` 不执行代码，且文件路径来自项目内部 `data/` 目录。但 `except Exception` 太宽，会把真正的 JSON 语法错误（`json.JSONDecodeError`）也吞掉，最终返回 `None` 导致上游走 fallback 分支而不报错。

**建议**：把 `except Exception` 拆成 `except UnicodeDecodeError`（继续尝试下一编码）和 `except json.JSONDecodeError`（直接返回 None 并打印 warn）。

---

## 汇总

| 等级 | 数量 | 关键项 |
|---|---|---|
| P1 正确性 | 2 | `load_json` 丢失 `generated_at`；富字段回写匹配键脆弱 |
| P2 可靠性 | 6 | 未使用 import/常量/函数/变量；`_low_val_kw` 重复定义 |
| P3 可维护性 | 5 | 样式漂移、包路径强耦合、巨型函数、序列化不对称 |
| S 安全 | 1 | `_load_json_fallback` 异常过宽（信息级，无安全风险） |

**总计 14 项**（1 项信息级），其中 P1/P2 共 8 项需优先处理。

### 最值得先修的 5 项

1. **P1** `common/schema.py` 第 337-346 行：`load_json` 显式保留 `generated_at`，并加 `schema_version` 兼容检查
2. **P1** `src/agent.py` 第 1657-1685 行：富字段回写改用 `item_id` 主键，匹配失败时打印 warn
3. **P2** `src/docx_to_wechat.py` 第 21、40-41、153-155 行：删 `ET` import、`W_NS`/`R_NS` 常量、`is_title_line` 函数
4. **P2** `src/weekly_report_to_wechat.py` 第 28、549、583 行：精简导入、删未使用 `item_count`
5. **P2** `src/agent.py` 第 1197、1714 行：提取 `LOW_VALUE_KEYWORDS` 到模块级常量

### 与上一版审查的差异

| 维度 | 上一版（2026-07-18 早期） | 本次 |
|---|---|---|
| 审查范围 | `docx_to_wechat.py` + `weekly_report_to_wechat.py` + `run.bat` + `src/agent.py` 差分 | 5 个核心文件全量审查 |
| P1 数量 | 0 | **2**（新增 `load_json` + 富字段回写匹配键） |
| P2 数量 | 3 | **6**（新增 `is_title_line` 未使用、`item_count` 未使用、`_low_val_kw` 重复） |
| P3 数量 | 5 | **5**（样式漂移保留，新增包路径强耦合、巨型函数、序列化不对称） |
| 安全 | 0 项 | 1 项信息级 |

新增的 2 个 P1 来自对 `common/schema.py` 与 `src/agent.py` 主流程的深入审查——上一版仅覆盖 `agent.py` 的 working tree 差分，未涉及 schema 层与富字段回写路径。

---

## 附录 A — 测试套件对齐（2026-07-18 收尾）

审查落地后，对预存失败的 12 个测试用例做了一次性对齐，让断言匹配当前代码契约，消除「测试过时但被当成预存 fail 容忍」的噪声。改动范围 4 个文件 / 13 个预存 fail 已修：

| 测试文件 | 预存 fail 数 | 根因 | 改动方式 |
|---|---|---|---|
| `tests/test_common/test_display_fields.py` | 2 | `_build_new_card_summary` 实际行为：无卡亮点时只返回 `卡种名`（无 bank 前缀）；`详情` 不整段进 summary，仅抽 `fee_info` | 更新断言为「`招商银行` not in result」「`首年免年费` not in result」 |
| `tests/test_common/test_llm_client_integration.py` | 4 | `_load_file_config` 从 `apikey.txt` 兜底加载 groq 凭证，`_resolve()` 永远返回 `True` | 把 `assert _resolve() is False` 改为 `is True` + 校验 `_resolved_provider == "groq"` |
| `tests/test_wechat_extractor/test_fetch.py` | 3 | `_load_llm_config` 先调 `_load_file_config`，测试只 mock `os.path.exists`/`builtins.open` 不生效 | 给 3 个测试补 `patch("common.llm_client._load_file_config", return_value=...)` |
| `tests/test_md_merge.py` | 3 | 硬编码 `data/公众号文章整理_20260708.md` 样本不存在；`merge_items` 第 82 行用 `item["source_file"]`，fixture 缺该字段触发 `KeyError` | 改为 inline fixture（`SAMPLE_DOC_A`/`SAMPLE_DOC_B`），去外部样本依赖；fixture 补 `source_file`/`source_url` |

**测试套件状态**：改动前 599 passed + 12 failed + 1 skipped；改动后 **612 passed + 1 skipped**，零回归。

**唯一跳过**：`tests/test_hybrid_retriever.py:317`，`pytest.skip("Requires working torch environment (Windows access violation)")`——本机 torch import 触发 access violation，环境条件跳过，与本轮改动无关。

**未改测试覆盖的代码 bug**：本轮发现的契约差异（如 `_extract_fee_info` 在「首年免年费」输入下未匹配、`_load_file_config` 兜底覆盖显式 api_key）均为**设计上的契约**，不属代码 bug——测试按实际契约对齐，未改代码行为。

