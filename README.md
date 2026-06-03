# 信用卡周报自动化 Agent

> 全自动抓取 → 分类 → 合并 → 出报告 → 持卡建议 → 归档知识库
>
> 支持三种模式：**Mode A** 全流程 / **Mode B** 多文档整合 / **Mode C** 仅数据处理（跳过持卡分析+归档）

将信用卡周报的产出流程完全 **agent 化**，一句话触发完整流水线，归档数据沉淀为可检索的知识库。

---

## 目录

- [快速开始](#快速开始)
- [项目架构](#项目架构)
- [技能体系](#技能体系)
- [数据流](#数据流)
- [使用指南](#使用指南)
  - [一键全流程](#一键全流程)
  - [演练模式](#演练模式)
  - [分步执行](#分步执行)
  - [仅归档](#仅归档)
- [RAG 知识库问答](#rag-知识库问答)
- [知识库归档](#知识库归档)
- [配置说明](#配置说明)
- [开发路线图](#开发路线图)
- [修订记录](#修订记录)

---

## 快速开始

### 环境准备

```bash
# 安装公共依赖
pip install -r requirements.txt

# 安装各 skill 依赖
pip install -r news-analyzer/requirements.txt
pip install -r card-holding-suggestion/requirements.txt

# 安装 Playwright 浏览器（用于微信文章抓取）
cd wechat-article-extractor
python setup.ps1
```

### 交互式运行（推荐）

```bash
# 双击运行交互菜单（会提示输入微信链接和通用网页链接）
run.bat

# 或直接命令行
python run_pipeline.py --mode a                          # 全流程：默认抓取模式
python _agent.py --mode a                                # 同上
python _agent.py --webpage-url "https://..."             # 附带通用网页 URL
python _agent.py --wechat-url "https://mp.weixin.qq.com/s/xxx" --webpage-url "https://creditcard.cib.com.cn/..."  # 微信 + 网页混合
python _agent.py --mode c                                # 仅数据处理（Step1-4，跳过持卡分析+归档）
```

### 全流程编排（高级）

```bash
# 完整执行（抓取 + 合并 + 报告 + 分析 + 归档）
python _agent.py

# 跳过抓取步骤（使用已有数据重新生成）
python _agent.py --skip-fetch

# 指定公告抓取天数（默认 7 天）
python _agent.py --bank-days 7

# LLM 语义评分模式（替代关键词评分）
python _agent.py --scorer llm

# 仅归档已有中间结果
python _agent.py --archive-only
```

---

## 项目架构

```
用户触发（run.bat / _agent.py）
        │
        ├── Mode A: 全流程 ────────────────────────────────
        │   │
        │   ├── Step 1:   抓取微信文章    (wechat-article-extractor)
        │   ├── Step 1b:  抓取通用网页    (news-analyzer extract_content.py)
        │   │             信用卡产品页、新闻等非微信链接
        │   ├── Step 2:   抓取银行公告    (news-analyzer website_scraper.py)
        │   ├── Step 3:   分类合并        (common/ → src/ 桥接)
        │   ├── Step 4:   生成 Word 周报  (word-merger)
        │   ├── Step 5:   持卡分析        (card-holding-suggestion)
        │   ├── Step 6:   追加持卡建议到周报
        │   └── Step 7:   归档到知识库    (common/archive)
        │
        ├── Mode B: 整合模式 ─────────────────────────────
        │   │
        │   ├── 读取多个已有 Word 文档
        │   ├── 保留层级结构 (Heading 1 → Heading 2)
        │   ├── 提取图片并保留
        │   ├── LLM 整体分析生成持卡建议
        │   └── 输出整合版 Word 文档
        │
        └── Mode C: 仅数据处理 ────────────────────────────
            │
            ├── Step 1:   抓取微信文章
            ├── Step 1b:  抓取通用网页
            ├── Step 2:   抓取银行公告
            ├── Step 3:   分类合并（含图片自动过滤）
            └── Step 4:   生成 Markdown 周报（跳过持卡分析+归档）
```

### 目录结构

```
_agent.py               # 根级 stub → src/agent.py（向后兼容）
rag_query.py            # 根级 stub → src/rag_query.py
run_pipeline.py         # 根级 stub → run_pipeline.py
src/                    # 核心源码包
  agent.py              #   Agent 全流程编排
  rag_query.py          #   RAG 知识库问答
common/                 # 公共层：数据契约、分类、LLM、图片
  images.py             #   图片生命周期管理（去重/过滤/中心化存储）
  llm_client.py         #   统一 LLM 客户端（多 provider 自动检测）
scripts/                # 辅助脚本
  debug/                #   调试/调试工具
  rag/                  #   知识库维护
docs/                   # 架构文档
tests/                  # 全量测试（420 用例）
```

---

## 技能体系

本项目由 5 个独立 skill 和 1 个公共层组成：

| Skill | 职责 | Pipeline 集成 | 状态 |
|-------|------|--------------|------|
| `common/` | 公共层：数据契约、配置、归档 | Steps 3, 7 | ✅ 完全使用 |
| `wechat-article-extractor` | 微信文章抓取（requests + Playwright） | Step 1 | ✅ 主力抓取 |
| `wechat-rss-monitor` | URL 去重（history.json） | Step 1 | ✅ 去重模块 |
| `news-analyzer` | 抓取银行官网公告/活动 | Step 2 | ✅ 使用 |
| `card-holding-suggestion` | 持卡用卡 AI 评分建议 | Step 5 | ✅ 使用 |
| `word-merger` | 生成 Word 周报 | Step 4 | ✅ 使用 |

### 公共层 `common/`

所有 skill 共用同一套数据契约，无需重复定义：

- **`schema.py`** — `CreditCardItem` / `CreditCardBatch` 标准格式定义
- **`config.py`** — 统一路径配置，禁止硬编码
- **`utils.py`** — 工具函数（银行名识别、时间解析等）
- **`archive.py`** — 知识库归档机制
- **`classifier.py`** — 三层自动分类器（强规则 + 弱规则打分 + 低置信度降级）
- **`normalizer.py`** — 统一数据清洗入口（`normalize_item`：分类 → 识别 → 结构化 → 展示字段 → 审核标记）
- **`entity_resolver.py`** — 来源/银行自动识别（17 银行 + 15 公众号映射链）
- **`display_fields.py`** — 展示字段生成器（标题策略 + 摘要策略，支持 `title_source` 审计）
- **`review.py`** — 审核队列生成（`build_review_queue` → `data/review/review_queue.md`）
- **`article_envelope.py`** — 文章信封构建器（微信 content_blocks → 多主题检测）
- **`topic_splitter.py`** — 主题拆分引擎（6 信号检测 + 置信度打分 + 切点分割 + 过拆修正）
- **`llm_review.py`** — LLM 辅助审核/复审（底层复用 `llm_client.py`）
- **`llm_client.py`** — 统一 LLM 客户端，支持 groq/grok/openrouter 三 provider 自动检测
- **`images.py`** — 图片生命周期管理：下载/去重/过滤/中心化存储

---

## 数据流

### Mode A: 全流程

```
用户输入 URL 列表
        │
        ├── mp.weixin.qq.com → Step 1: wechat-article-extractor
        │                         (requests + Playwright)
        ├── 其他通用网页      → Step 1b: news-analyzer extract_content.py
        │                         (readability-lxml 内容提取)
        └── 银行公告列表      → Step 2: news-analyzer website_scraper.py
                                   (列表页解析 + 详情页提取)
                                   │
                                   └──────────────┬─────────────────
                                                  │
                                           ┌──────▼──────┐
                                           │  Step 3     │  合并为标准格式
                                           │  分类 + 合并 │
                                           └──────┬──────┘
                                                  │  batch_merged.json
                                                  │
                                          ┌───────┴────────┐
                                          ▼                 ▼
                                   Step 4: Word 周报   Step 5: 持卡分析
                                   (docx_utils.py)     (analyze_batch.py)
                                          │                 │
                                          └──────┬──────────┘
                                                 ▼
                                        Step 6: 追加持卡建议到 Word 周报
                                                 │
                                                 ▼
                                        Step 7: 归档 → data/archive/
```

### Mode B: 整合模式

```
多个 Word 文档
      │
      ▼
读取并保留层级结构 (Heading 1 → Heading 2)
      │
      ▼
提取图片并关联到条目
      │
      ▼
LLM 整体分析生成持卡建议
      │
      ▼
输出整合版 Word 文档（含层级目录 + 图片 + 建议）
```

### Mode C: 仅数据处理

```
用户输入 URL 列表 → wechat-article-extractor + news-analyzer
        │
        ▼
  Step 3: 分类 + 合并 → batch_merged.json
        │
        ▼
  Step 4: Word 周报 ← 图片自动过滤
        │               (装饰图/纯色图/图标/分割线)
        ▼
  输出 Word 周报（跳过持卡分析 + 归档）
```

### 统一数据格式 `CreditCardBatch`

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-17T12:00:00",
  "batch_label": "2026年5月第2周",
  "total": 10,
  "items": [
    {
      "item_id": "a1b2c3d4e5f6",
      "source": "website",
      "category": "新卡 | 权益变更 | 活动 | 公告",
      "bank": "招商银行",
      "title": "公告标题",
      "url": "详情链接",
      "raw_text": "原文内容...",
      "images": ["data/images/item_id/img1.jpg"],
      "structured": {
        "关键信息": "...",
        "点评": "影响分析"
      },
      "publish_time": "2026-05-16",
      "extracted_at": "2026-05-17T12:00:00"
    }
  ]
}
```

---

## 使用指南

### 交互式运行（推荐）

```bash
# 双击运行交互菜单
run.bat

# 或直接命令行
python _agent.py --mode a                                   # 全流程
python _agent.py --mode a --webpage-url "https://..."       # 全流程 + 通用网页
python _agent.py --mode a --wechat-url "https://mp.weixin.qq.com/s/xxx" --webpage-url "https://..."  # 混合
python _agent.py --mode c                                   # 仅数据处理（跳过持卡分析+归档）
```

**Mode A: 全流程**
- 输入公众号文章链接（空格分隔）
- 输入通用网页链接（信用卡产品页/新闻等，空格分隔）
- 输入银行官网抓取天数（默认7）
- 自动生成周报 + 持卡建议

**Mode B: 整合模式**
- 输入已有 Word 文档路径（每行一个）
- 自动整合 + 层级保留 + 图片保留 + 整体分析建议

**Mode C: 仅数据处理**
- 输入公众号文章链接（空格分隔）
- 输入通用网页链接（空格分隔）
- 输入银行官网抓取天数（默认7）
- 生成 Markdown 周报，跳过持卡分析 + 归档
- 图片自动过滤：跳过装饰图/纯色图/图标/分割线

### 全流程编排（高级）

```bash
# 完整流程（含微信+网页+银行公告）
python _agent.py

# 指定微信文章链接
python _agent.py --wechat-url "https://mp.weixin.qq.com/s/xxx"

# 指定通用网页链接（信用卡产品页、新闻等非微信页面）
python _agent.py --webpage-url "https://creditcard.cib.com.cn/apply/products/BJseries/XKseries/xing1.html"

# 微信 + 网页混合
python _agent.py --wechat-url "https://mp.weixin.qq.com/s/xxx" --webpage-url "https://..." "https://..."

# 跳过抓取，用已有 data/ 数据重新生成一切
python _agent.py --skip-fetch

# 仅归档已有中间结果
python _agent.py --archive-only

# 指定公告抓取天数（如 14 天）
python _agent.py --bank-days 14

# 指定评分模式
python _agent.py --scorer llm
```

### 分步执行（调试用）

```bash
# 单独抓取银行公告
cd news-analyzer
python scripts/website_scraper.py --days 7

# 单独执行持卡分析
python card-holding-suggestion/scripts/analyze_batch.py \
    --input data/batch_merged.json \
    --scorer llm

# 单独归档
python -c "from common.archive import archive_batch; from common.schema import CreditCardBatch; b = CreditCardBatch.load_json('data/batch_merged.json'); print(archive_batch(b))"
```

---

## RAG 知识库问答

项目内置了基于历史公众号文章的 RAG（检索增强生成）问答系统，可对历史信用卡资讯进行持卡评判、公告点评追溯、亮点挖掘对照。

### 模型选择

| 模型 | 供应商 | API Key | 接入方式 | 状态 |
|------|--------|---------|----------|------|
| `llama-3.3-70b-versatile` | Groq | `GROQ_API_KEY` | OpenAI SDK (API兼容) | ✅ 主力模型 |
| `qwen/qwen3-32b` | OpenRouter | `OPENAI_API_KEY` | OpenAI SDK | ✅ 备选模型 |

切换方式（`rag_query.py` 第 23 行附近）：
```python
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq")  # → "openai" 切换
```

### 检索方案：BM25（零外部依赖）

| 组件 | 方案 |
|------|------|
| 分词 | 中文按字+词混合，英文按空格 |
| 索引 | BM25 (k1=1.5, b=0.75) |
| 缓存 | `data/bm25_cache.pkl`，首次构建后秒加载 |
| Top-K | 5 条，每条截取前 3000 字符 |

**当前无需向量检索**：BM25 对信用卡专有名词（"温暖升级"、"缩水"、"里程兑换"）效果足够好，等有网络环境可升级为 embedding。

### 知识库现状（已清洗，2026-05-30）

| 指标 | 数值 |
|------|------|
| 来源文章数 | 59 篇（仅信用卡相关） |
| 切分条目数 | 405 条 |
| 日期范围 | 2017-03-18 ~ 2026-05-27（约 9 年） |
| 覆盖银行 | 26 家 |
| 噪声删除 | 388 条非卡内容已移除 ✅ |

### 对业务的价值评估

| 场景 | 覆盖度 | 说明 |
|------|--------|------|
| **持卡评判** | ⭐⭐⭐⭐⭐ | 历史评分文章丰富，可支撑卡片对比和推荐 |
| **公告点评** | ⭐⭐⭐⭐ | 有缩水/温暖升级历史记录，可趋势对比 |
| **亮点挖掘** | ⭐⭐⭐ | 需结合最新周报为主，KB 为辅查历史 |

### 启动方式

```cmd
set GROQ_API_KEY=gsk_你的key
python rag_query.py
```

| 命令 | 功能 |
|------|------|
| `任意问题` | BM25 检索 + LLM 生成回答 |
| `/debug` | 只看检索结果，不调 LLM |
| `/exit` | 退出 |

详见 [`RAG知识库.md`](./RAG知识库.md) 完整复盘文档。`kb_add_article.py` 可单篇/批量新增文章到知识库。

---
## 知识库归档

每次 `_agent.py` 全流程执行后，自动将本批次所有产出归档到知识库：

```
data/archive/
├── index.json                    ← 全局检索索引
├── 2026/
│   ├── 05/
│   │   ├── 2026年5月第2周/
│   │   │   ├── batch.json        ← 原始数据
│   │   │   ├── 周报.docx         ← Word 周报
│   │   │   ├── 持卡分析.md       ← 分析报告
│   │   │   ├── 持卡分析.json     ← 结构化评分
│   │   │   ├── images/           ← 关联图片
│   │   │   └── manifest.json     ← 归档元数据
│   │   └── 2026年5月第3周/
│   └── 06/
└── ...
```

### 历史查询

```python
from common.archive import list_archives
archives = list_archives()           # 按时间倒序返回所有批次
latest = archives[0]                 # 最新批次
print(latest["batch_label"])         # 批次名称
print(latest["total_items"])         # 条目数
print(latest["categories"])          # 分类统计
print(latest["banks"])               # 涉及银行
```

---

## 配置说明

### 银行配置

编辑 `news-analyzer/scripts/website_scraper.py` 中的 `BANKS` 列表，添加/修改银行抓取规则：

```python
BANKS = [
    BankConfig(
        name="邮政储蓄银行",
        short_name="邮储",
        list_url="https://www.psbc.com/cn/...",
        category="公告",
        link_selector="a[href*='.html']",
        title_selector="h1, .title",
        content_selector=".article-content, .maintext",
        date_selector=".date, .time",
        date_pattern="%Y-%m-%d",
    ),
    # 添加更多银行...
]
```

### 公众号配置

目前采用手动提供公众号文章链接的方式，未来计划接入配置化公众号列表。

### 评分配置

关键词评分规则在 `card-holding-suggestion/scripts/analyze_batch.py` 中：

```python
SCORE_RULES = {
    "新卡":          {"基础分": 70, "关键词加分": {...}},
    "权益变更":      {"基础分": 50, "关键词加分": {...}},
    "活动":          {"基础分": 40, "关键词加分": {...}},
}
```

---

## 开发路线图

### M1 — 基础设施与归档 ✅
- [x] 统一数据契约 `CreditCardItem` / `CreditCardBatch`
- [x] 图片集中存储
- [x] 项目文档
- [x] 知识库归档机制
- [x] 全流程编排 `_agent.py`

### M2 — Skill 升级 ✅
- [x] `card-holding-suggestion`: LLM 语义评分 + 加权 ROI 模型
- [x] `news-analyzer`: 多银行官网支持
- [x] `wechat-article-extractor`: 图片质量/去重优化

### M3 — 最小闭环场景 ✅
- [x] 交互式入口 `run.bat` + `run_pipeline.py`
- [x] 多文档整合 `merge_docs.py`（Mode B）
- [x] LLM 整体分析替代逐条评分
- [x] 层级结构保留（Heading 1 → Heading 2）
- [x] 图片提取与保留
- [x] 项目文件清理
- [x] RAG 知识库问答系统（BM25 + LLM）

### M4 — Agent 编排完善 ✅
- [x] 代码审查覆盖 6 大模块（P1/P2/P3 问题分级）
- [x] 补充核心单元测试（59 个用例，schema + scorer + highlight 全覆盖）
- [x] 修复 step6 标题重复 bug + 补齐综合持卡策略输出
- [x] 提取 `_generate_notes()` 四分类注意事项生成机制

### M5 — 持续优化
- [x] 三层分类器替代 LLM 自动分类（common/classifier.py）
- [x] 来源/银行自动识别（common/entity_resolver.py，17 家银行 + 15 公众号映射）
- [x] Mode C 仅数据处理（Step1-4 跳过持卡分析+归档）
- [x] 图片四层过滤（装饰图/纯色图/图标/分割线自动跳过）
- [x] 数据质量修复（标题"未知推出"、重复词去重、样板话跳跃）
- [ ] Web 管理端 / 定时任务
- [ ] 增量抓取（只抓上次归档后的新公告）

### M6 — 代码质量重构 ✅
- [x] Schema 扩字段（CreditCardItem 新增 16 个审核/质量字段）
- [x] 标准化 Normalizer 入口（normalize_item 统一处理分类/识别/结构化）
- [x] 审核队列输出（data/review/review_queue.md）
- [x] 微信 content_blocks（4 种 block 类型，OCR 噪音不进展示）
- [x] 官网 DOM 级噪音剥离（BankConfig 双层过滤）
- [x] _agent.py 瘦身（step3_merge 改标准化入口，删除 150+ 行代码）
- [x] 138 测试全通过

### M7 — 公众号多主题拆分 ✅
- [x] 文章信封构建器（common/article_envelope.py）
- [x] 主题拆分引擎（common/topic_splitter.py）：6 种信号检测 + 置信度打分 + 切点分割 + 过拆修正
- [x] 单主题安全回退：无信号/低置信度自动 fallback
- [x] 桥接函数 normalize_topic()：TopicDict → CreditCardItem
- [x] Schema 扩 4 字段：is_multi_topic_split / topic_id / topic_split_confidence / topic_split_signals
- [x] step3_merge 集成：content_blocks → 检测 → 拆分 → 逐 topic 入 batch
- [x] 27 个测试用例 + 全量 165 passed

### M8 — 验收修复与标准化收口 ✅
- [x] 来源字段净化：entity_resolver 过滤"未知公众号"
- [x] 分类逻辑统一：删除 3 处本地分类函数，全部委派 common/classifier
- [x] 结构化内容清洁：_trim_marketing_intro / _safe_truncate / structured_clean
- [x] display_fields 重构：参数化调用替代 self 传递

### M9 — 目录结构整理 + Confidence 优化 ✅
- [x] P1: Word 层内容修复逻辑迁移到 normalizer（_trim_marketing_intro / _safe_truncate / structured_clean）
- [x] P2: confidence 打分区分度优化（多维因子：关键词 + 实体数 + 来源权威 + 时效性）
- [x] P3: 目录结构整理（src/ 包 + 根级 stub + scripts/debug/ + scripts/rag/ + docs/ + 测试用例）
- [x] 全量 188 passed，无回归

### M10 — LLM/图片模块统一重构 ✅
- [x] `common/llm_client.py`: 统一 LLM 客户端（环境变量/文件配置/显式参数三模式，groq/grok/openrouter 自动检测）
- [x] `common/images.py`: 图片生命周期管理（下载/去重/过滤/中心化存储，内容哈希去重）
- [x] 聚合 3 处重复 `_call_llm` 代码（llm_review.py 53行 + rag_query.py 55行 + scorer.py 30行→各 3~15 行代理）
- [x] 聚合 2 处图片滤波代码（utils.py 98行 + agent.py 63行→images.py 独立模块）
- [x] 全量 420 passed，无回归

---

## 修订记录

详见 [CHANGELOG.md](./CHANGELOG.md)。

| 版本 | 日期 | 要点 |
|------|------|------|
| v0.18 | 2026-06-04 | 新增 Step 1b 通用网页抓取（复用 news-analyzer extract_content.py），支持 `--webpage-url` CLI 参数 + `run.bat` 交互式输入，`run_pipeline.py` 修复破损导入路径 |
| v0.17 | 2026-06-13 | 5 项修复（generate_docx 重写/Pillow 取消注释/eastAsia 双设/ensure_dir 导入/generate_merged_docx 入口）+ llm_review 银行去重 + rag_query 路径统一 + 经验教训沉淀 TOOLS.md + 420 全通过 |
| v0.16 | 2026-06-12 | 统一 LLM 客户端（common/llm_client.py）聚合 3 处重复调用代码、图片生命周期管理（common/images.py）聚合 2 处图片滤波+新增内容哈希去重、336 测试全通过 |
| v0.15 | 2026-06-10 | Mode C（仅 Step1-4，跳过持卡分析+归档）、图片四层过滤（文件大小/最小尺寸/像素方差）、3 个数据质量修复（标题"未知推出"、去重加强、样板话跳过）、run.bat 菜单补 C 选项 |
| v0.14 | 2026-06-08 | P3 目录结构整理（src/ 包 + 根级 stub + scripts/ + docs/）、P1 Word 修复逻辑迁移到 normalizer、P2 confidence 打分区分度优化、188 测试全通过 |
| v0.13 | 2026-06-07 | 验收修复：来源字段净化、分类逻辑统一（删除 3 处本地分类函数）、结构内容清洁（_trim_marketing_intro / _safe_truncate / structured_clean）、display_fields 参数化 |
| v0.12 | 2026-06-06 | 多主题公众号文章拆分：文章信封、主题拆分引擎（6 信号检测 + 切点分割 + 过拆修正 + 单主题回退）、step3_merge 集成、Schema 扩 4 字段、27 测试 + 全量 165 passed |
| v0.11 | 2026-06-05 | 三批重构：Schema 扩 16 字段、统一 Normalizer/Classifier/EntityResolver/Bank 配置 DOM 级清洗、微信 content_blocks、审核队列、138 测试全通过 |
| v0.10 | 2026-05-31 | 补充 59 个单元测试、修复 step6/step5 多个 bug、持卡建议输出规范化、代码审查报告、清理 15+ 临时文件 |
| v0.9.1 | 2026-05-30 | 修复全流程导入错误（scrape_all_banks、analyze_batch）、追加持卡建议到Word、统一英文输出 |
| v0.9 | 2026-05-30 | 最小闭环场景验证完成：交互式入口、多文档整合、LLM整体分析、层级保留、图片保留、项目清理 |
| v0.8 | 2026-05-30 | RAG 知识库问答系统（BM25 + LLM）、知识库清洗（405条/59篇）、项目文件清理 |
| v0.7 | 2026-05-30 | 图片广告过滤、LLM 评分 bugfix（mimo-v2-pro）、scorer_used 可审计 |
