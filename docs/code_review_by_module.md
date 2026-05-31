# 信用卡周报自动化项目 — 分模块代码审查报告

**审查方法**：逐模块对照对应 SKILL.md 定义的职责、接口和数据契约进行评审。  
**审查时间**：2026-05-16  
**严重级别**：P0 功能错误 | P1 潜在缺陷 | P2 代码异味 | P3 建议优化

---

## 模块 1：wechat-article-extractor（微信文章提取器）

**参考文档**：`wechat-article-extractor/SKILL.md`

### 正面对照 ✅

| 要求 | 实现 | 状态 |
|------|------|------|
| requests 优先，Playwright 兜底 | `fetch_with_requests()` → `fetch_with_playwright()` | ✅ |
| `--download-images` 下载图片 | `download_image()` + `--download-images` CLI 参数 | ✅ |
| `--images-dir` 图片保存目录 | CLI 实现，默认 `./images` | ✅ |
| OCR 图片文字提取 | 集成 `ImageContentExtractor`（条件导入） | ✅ |
| 批量处理多篇文章 | `--batch` 模式，`for url in urls: process_single()` | ✅ |
| 导出 Word/Markdown 文档 | `export_document.py` 同时支持 word 和 md 格式 | ✅ |

### 发现的问题

---

#### 🔴 P1 — `export_document.py` 标题判断逻辑过于粗糙

**文件**：`wechat-article-extractor/scripts/export_document.py` 第 95-101 行

```python
# 当前实现
if line.endswith('：') or line.endswith(':'):
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(line)
    run.bold = True
    run.font.size = Pt(14)
else:
    doc.add_paragraph(line)
```

**问题**：所有以冒号结尾的行都被当作标题加粗放大。但 SKILL.md 中输出格式示例使用 `# ` Markdown 标题语法（如 `# 招商银行消费返现活动`），而脚本未处理 `#` 前缀。实际内容里很多普通行（如 `图1：活动海报`、`备注：请留意`）也会被误判为标题。

**建议**：
1. 增加对 Markdown `#` 标题语法的识别
2. 冒号结尾的加粗只应用于已知的固定字段名（活动内容、活动时间、适用人群等）
3. 或改为由调用方传入结构化数据而非纯文本

---

#### 🔴 P1 — 图片大小与 word-merger 不一致

**文件**：
- `export_document.py` 第 73 行：`run.add_picture(img_path, width=Inches(6))`（约 15.24cm）
- `generate_report.py` 第 374 行：`doc.add_picture(img_path, width=Cm(13))`

**问题**：同一项目两个文档生成脚本对图片使用了不同宽度（6 Inches vs 13cm），导致交付物风格不统一。

**建议**：统一使用 `Cm(13)` 或定义共享常量。

---

#### 🟡 P2 — `process_single` 批量模式下硬编码 sleep(1)

**文件**：`fetch_wechat_article.py` 第 237 行

```python
for url in urls:
    results.append(process_single(url, args.download_images,
                                  images_dir, args.extract_ocr))
    time.sleep(1)  # ← 硬编码
```

**问题**：批量处理时每次请求间隔固定 1 秒。如果网络环境不需要这么长的间隔，会拖慢整体速度；如果遇到限流较严的站点，1 秒可能不够。

**建议**：改为可配参数 `--delay 1`，或根据是否有 Playwright 降级动态调整。

---

#### 🟡 P2 — `PLAYWRIGHT_IMPORT_OK` 与 `USE_PLAYWRIGHT` 冗余

**文件**：`fetch_wechat_article.py` 第 24-31 行

```python
USE_PLAYWRIGHT = False
PLAYWRIGHT_IMPORT_OK = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_IMPORT_OK = True
    USE_PLAYWRIGHT = True
except ImportError:
    pass
```

**问题**：`PLAYWRIGHT_IMPORT_OK` 和 `USE_PLAYWRIGHT` 永远同时为 True/False，无独立语义。`fetch_with_playwright()` 只检查 `PLAYWRIGHT_IMPORT_OK`，`USE_PLAYWRIGHT` 全局未被使用。

**建议**：删除 `USE_PLAYWRIGHT`，只保留 `PLAYWRIGHT_IMPORT_OK`。

---

## 模块 2：wechat-rss-monitor（微信去重模块）

**参考文档**：`wechat-rss-monitor/SKILL.md`

### 正面对照 ✅

| 要求 | 实现 | 状态 |
|------|------|------|
| URL hash 去重 | `_url_hash()` 使用 MD5 | ✅ |
| `history.json` 持久化 | `_load_history()` / `_save_history()` | ✅ |
| 保留最近 5000 条 | `history['fetched_urls'][-5000:]` | ✅ |
| RSSHub 监控已废弃 | `rsshub_fetcher.py` 保留但不调用 | ✅ |

### 发现的问题

---

#### 🔴 P1 — `WeChatMonitor.fetch_article()` 与 wechat-article-extractor 功能重复

**文件**：`wechat-rss-monitor/scripts/wechat_monitor.py` 第 82-151 行

**问题**：`WeChatMonitor.fetch_article()` 也是一个微信文章抓取器，但只用了 requests（无 Playwright 兜底），且图片限制最多 10 张。而 `wechat-article-extractor/fetch_wechat_article.py` 提供了更完善的抓取能力（Playwright 兜底 + OCR + 完整图片下载）。两个模块功能严重重叠。

**影响**：`_agent.py` Step 1 实际使用 `wechat-article-extractor` 抓取，`wechat_monitor.py` 中的 `fetch_article()` 属于死代码——混淆维护者。

**建议**：
1. 将 `WeChatMonitor` 改为纯去重组件的接口（不再包含 fetch 逻辑）
2. 或将 `_is_fetched()` / `_mark_fetched()` / `add_urls()` 作为独立函数抽到 `common/` 中

---

#### 🟡 P2 — 未使用的 import

**文件**：`wechat-monitor.py` 第 10-14 行

```python
import re        # 已使用 (extract_biz_from_url)
import time      # 未使用
from pathlib import Path  # 未使用（路径用 str 操作）
```

**建议**：清理未使用的 import，降低认知负荷。

---

#### 🟢 P3 — `rsshub_fetcher.py` 标记可更明确

**建议**：在文件头部加入 `# DEPRECATED: RSSHub 功能已废弃（公共实例均被封锁），仅保留供自建实例参考` 注释。

---

## 模块 3：word-merger（Word 文档生成器）

**参考文档**：`word-merger/SKILL.md`

### 正面对照 ✅

| 要求 | 实现 | 状态 |
|------|------|------|
| 标准 JSON → Word | `generate_report()` 读取 CreditCardBatch 格式 | ✅ |
| 按分类展示（新卡/权益变更/活动/公告） | `cat_order` 循环 + `cat_config` | ✅ |
| 封面区 | 标题 + 批次标签 + 生成时间 | ✅ |
| 内容概览/统计 | 各分类条目统计 | ✅ |
| 本期亮点 | 从结构化字段自动提取亮点摘要 | ✅ |
| 原文链接 | 每个条目展示原文 URL | ✅ |
| 图片嵌入（`data/images/{item_id}/`） | `images` 字段路径检测 + 广告图过滤 | ✅ |
| `--no-images` 参数 | `add_images` 控制开关 | ✅ |
| `--title` 自定义标题 | `doc_title` 参数 | ✅ |
| XML 安全（非法字符过滤） | `clean_xml_text()` + `sanitize_structure()` | ✅ |

### 发现的问题

---

#### 🟡 P2 — `merge_docs.py` 位置不符合 SKILL.md 约定

**文件**：`merge_docs.py`（项目根目录）

**问题**：SKILL.md §资源索引中 word-merger 的脚本路径应为 `word-merger/scripts/` 下，但 `merge_docs.py` 直接放在项目根目录。`_agent.py` 通过 `from merge_docs import ...` 导入时依赖 CWD 在项目根目录。

**影响**：如果从其他目录运行 `_agent.py`，会出现 ImportError。同时其他 skill 的「目录结构」约定被打破。

**建议**：将 `merge_docs.py` 移至 `word-merger/scripts/merge_docs.py`，或在项目根目录保留一个薄转发器。

---

#### 🟡 P2 — `setup_docx()` 在多个函数中重复解包

**文件**：`generate_report.py` 第 128-161 行

```python
# set_run_font 中
Document, Pt, RGBColor, Inches, Cm, WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement = setup_docx()

# add_hr 中
Document, Pt, RGBColor, Inches, Cm, WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement = setup_docx()

# generate_report 中
(Document, Pt, RGBColor, Inches, Cm,
 WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT, qn, OxmlElement) = setup_docx()
```

**问题**：`setup_docx()` 每次调用都做 try/except + import。在生成一份周报过程中至少被调用 3 次，浪费不必要的 import 开销。

**建议**：使用模块级延迟加载 + 缓存，或 `functools.cache`。

---

#### 🟢 P3 — 亮点摘要截断不安全

**文件**：`generate_report.py` 第 271-275 行

```python
highlight = structured.get('卡亮点', '') or structured.get('详情', '')[:30]
```

**问题**：`[:30]` 可能截断在多字节 UTF-8 字符的中间产生乱码。应该使用安全截断函数确保完整性。

**建议**：已有 `clean_xml_text()`——可以增加一个配套的 `safe_truncate(text, max_len=30)` 函数。

---

#### 🟢 P3 — `read_word_docs.py` 可能是死代码

**文件**：`word-merger/scripts/read_word_docs.py`（339 行）

**问题**：SKILL.md 中标记为「旧版—Word → JSON，兼容旧数据」。检查 `_agent.py` 和全项目 grep，未找到对此脚本的任何调用或 import。

**建议**：如果确实不再使用，可添加 `DEPRECATED` 标记或归档。

---

## 模块 4：card-holding-suggestion（持卡建议分析）

**参考文档**：`card-holding-suggestion/SKILL.md`

### 正面对照 ✅

| 要求 | 实现 | 状态 |
|------|------|------|
| `--input` / `--output` / `--format` / `--focus` / `--scorer` | CLI 完整 | ✅ |
| 按银行分组 | `banks` 字典聚合 | ✅ |
| 按分类分组 | `by_category` 字典 | ✅ |
| 经排序的银行列表 | `sorted(..., key=lambda b: len(b['activities']) + len(b['new_cards']), reverse=True)` | ✅ |
| 评分引擎（keyword / llm） | `score_with_keywords()` / `score_with_llm()` | ✅ |
| Markdown 输出格式 | `format_as_markdown()` | ✅ |
| `scorer` 参数安全传递 | `build_context()` 中通过参数传递（已修复之前全局状态污染问题） | ✅ |

### 发现的问题

---

#### 🟢 P3 — `category_summary` 分类统计可简化为直接计数

**文件**：`analyze_batch.py` 第 117-128 行

```python
'category_summary': {
    cat: {
        'count': len(items),            # ✅ 实际正确（循环变量 items shadow 了外层）
        'items': [extract_key_points(it) for it in items],
    }
    for cat, items in by_category.items()
},
```

**说明**：代码审查时不慎判为 bug，经二次验证——Python 字典推导中 `for cat, items in ...` 的 `items` shadow 了外层的 `items = batch_data.get('items', [])`，所以 `len(items)` 指向的是该分类的 items 数量，**逻辑正确**。

**建议**：为提升可读性，建议将循环变量重命名以消除歧义：

```python
for cat, cat_items in by_category.items():
    ...
    'count': len(cat_items),
    'items': [extract_key_points(it) for it in cat_items],
```

---

## 模块 5：Common Schema（统一数据契约）

**参考文档**：`common/schema.py`（被所有 SKILL.md 引用）

### 正面对照 ✅

| 要求 | 实现 | 状态 |
|------|------|------|
| 标准化分类枚举 | `STANDARD_CATEGORIES = {"新卡", "权益变更", "活动", "公告"}` | ✅ |
| 非标准分类映射 | `CATEGORY_MAP` 覆盖 12 种变体 | ✅ |
| `CreditCardItem` 序列化/反序列化 | `to_dict()` / `from_dict()` | ✅ |
| `CreditCardBatch` 文件读写 | `save_json()` / `load_json()` | ✅ |
| `by_category()` 分类筛选 | 委托 `normalize_category()` | ✅ |
| `item_id` 自动生成 | `uuid.uuid4().hex[:12]` | ✅ |

### 发现的问题

---

#### 🟡 P2 — `load_json()` 丢失原始 `generated_at`

**文件**：`schema.py` 第 200-208 行

```python
@classmethod
def load_json(cls, filepath: str) -> "CreditCardBatch":
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = [CreditCardItem.from_dict(it) for it in data.get("items", [])]
    return cls(
        items=items,
        batch_label=data.get("batch_label", ""),
    )
    # 注意：data["generated_at"] 被忽略，CreditCardBatch.__init__ 重置为当前时间
```

**问题**：加载时 JSON 中的 `generated_at` 被丢弃，`__init__` 自动设为 `datetime.now().isoformat()`。这意味着重新加载一个批次文件后，原始生成时间无法追溯。

**建议**：在 `load_json` 中显式传递 `generated_at`：

```python
batch = cls(items=items, batch_label=data.get("batch_label", ""))
batch.generated_at = data.get("generated_at", batch.generated_at)
```

---

#### 🟢 P3 — `normalize_category()` 对未知分类无 fallback

**文件**：`schema.py` 第 52-56 行

```python
def normalize_category(raw: str) -> str:
    if raw in STANDARD_CATEGORIES:
        return raw
    return CATEGORY_MAP.get(raw, raw)  # 未知分类返回原文
```

**问题**：如果上游使用了一个完全不在 `CATEGORY_MAP` 中的分类名，会被原样返回。下游 `generate_report.py` 在 `cat_order` 中找不到该分类时会静默跳过。

**建议**：增加警告日志或默认 fallback 到"公告"：

```python
result = CATEGORY_MAP.get(raw, raw)
if result not in STANDARD_CATEGORIES:
    logger.warning(f"未知分类 '{raw}'，保留原值")
return result
```

---

## 模块 6：主编排层（`_agent.py`）

**参考文档**：被所有 SKILL.md 的「与全流程集成」章节引用

### 正面对照 ✅

| 要求 | 实现 | 状态 |
|------|------|------|
| Step 1：抓取（微信+网站） | 调用 `fetch_wechat_article` + `website_scraper` | ✅ |
| Step 2：RAG 分析 | `step2_rag_analysis()` 带结构化输出 | ✅ |
| Step 3：合并 | 调用 `merge_docs.py` 整合 | ✅ |
| Step 4：报告生成 | 调用 `generate_report.py` 输出 Word | ✅ |
| 微信文章去重 | 集成 `wechat_monitor` history.json | ✅ |
| 分类推测（代替硬编码） | `_guess_category_from_wechat()`（已修复） | ✅ |
| 图片集中管理 | `_centralize_images()` | ✅ |

### 发现的问题

---

#### 🟡 P2 — `merge_docs` 相对导入依赖 CWD

**问题**：`_agent.py` 中 `from merge_docs import merge_contents` 依赖于 CWD 在项目根目录。如果通过其他脚本或工具链调用，可能因 `sys.path` 不一致而 ImportError。

**建议**：在文件开头确保项目根在 `sys.path` 中（已有类似代码，确认后补充）。

---

## 问题汇总

| ID | 模块 | 级别 | 类别 | 描述 | 状态 |
|----|------|------|------|------|------|
| 1 | wechat-article-extractor | P1 | 功能缺陷 | `export_document.py` 标题加粗误判，未处理 `#` 语法 | ❌ 待处理 |
| 2 | wechat-article-extractor | P1 | 风格不一致 | 图片宽度 6 Inches vs 13cm，与 word-merger 不统一 | ❌ 待处理 |
| 3 | wechat-article-extractor | P2 | 代码异味 | 批量模式 sleep(1) 硬编码 | ❌ 待处理 |
| 4 | wechat-article-extractor | P2 | 代码异味 | `USE_PLAYWRIGHT` / `PLAYWRIGHT_IMPORT_OK` 冗余 | ✅ v0.11.0 已移除 |
| 5 | wechat-rss-monitor | P1 | 功能冗余 | `fetch_article()` 与 wechat-article-extractor 严重重复 | ✅ v0.11.0 已清理（精简为纯去重组件） |
| 6 | wechat-rss-monitor | P2 | 代码异味 | 未使用的 import：`time`, `Path` | ✅ v0.11.0 已清理 |
| 7 | word-merger | P2 | 结构问题 | `merge_docs.py` 在项目根而非 `word-merger/scripts/` | ❌ 待处理 |
| 8 | word-merger | P2 | 性能 | `setup_docx()` 在多个函数中重复解包 | ❌ 待处理 |
| 9 | word-merger | P3 | 健壮性 | 亮点摘要 `[:30]` 非安全截断 | ❌ 待处理 |
| 10 | word-merger | P3 | 维护性 | `read_word_docs.py` 可能是死代码 | ❌ 待处理 |
| 11 | card-holding-suggestion | P3 | 可读性 | `category_summary` 循环变量 `items` 歧义 | ❌ 待处理 |
| 12 | common/schema | P2 | 功能缺陷 | `load_json()` 丢失原始 `generated_at` | ❌ 待处理 |
| 13 | common/schema | P3 | 健壮性 | `normalize_category()` 未知分类无警告 | ✅ v0.11.0 已修复（默认 fallback 到"公告"） |
| 14 | _agent.py | P2 | 结构问题 | `merge_docs` 相对导入依赖 CWD | ❌ 待处理 |

---

## 高优建议（按修复价值排序）

| 优先级 | 模块 | 问题 | 当前状态 |
|--------|------|------|----------|
| P1 | card-holding-suggestion | ROI_Score 缺少 notes / activity_value 字段 | ✅ `v0.10.0` 已修复 |
| P1 | _agent.py | step6 分类标题重复 | ✅ `v0.10.0` 已修复（标题移出 for 循环） |
| P1 | _agent.py | step6 缺失综合持卡策略段 | ✅ `v0.10.0` 已新增（推荐申请/优先活动/需关注变动） |
| P1 | 测试覆盖 | 零测试覆盖 | ✅ `v0.10.0` 已补充 59 个用例 |
| P1 | wechat-rss-monitor | fetch_article() 与 wechat-article-extractor 功能重叠 | ✅ v0.11.0 已清理（精简为纯去重组件） |
| P2 | word-merger | merge_docs.py 位置不符合 SKILL.md 约定 | ❌ 待处理 |
| P2 | word-merger | setup_docx() 在多个函数中重复解包 | ❌ 待处理 |
| P2 | common/schema | load_json() 丢失原始 generated_at | ❌ 待处理 |
| P2 | _agent.py | merge_docs 相对导入依赖 CWD | ❌ 待处理 |
| P3 | 各模块 | 各 P3 级别细节问题（代码整洁、健壮性） | ❌ 待处理 |

1. **（P1）** 修复 `export_document.py` 标题判断逻辑，支持 `#` Markdown 标题并限制冒号结尾加粗仅用于已知字段名
2. **（P1）** 统一图片宽度为 13cm（或共享常量）
3. **（P1）** 精简 `wechat_monitor.py` 为纯去重组价，移除重复的 `fetch_article()` 逻辑
4. **（P2）** `schema.py` `load_json()` 保留原始 `generated_at`
5. **（P2）** 将 `merge_docs.py` 移至 `word-merger/scripts/` 下
6. **（P2）** `setup_docx()` 使用模块级缓存避免重复 import 开销
