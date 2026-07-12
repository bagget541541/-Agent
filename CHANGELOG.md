# 修订记录

## v0.20.5 — 2026-07-12

### Mode E：公众号发布 HTML

- 发布稿优化：自动生成文章标题，并将编辑摘要/主题整合压缩为总量、分类数量和三条以内的重点观察
- 发布稿隐藏来源、方法、行动建议、来源清单及内部声明等编辑过程内容
- 发布稿末尾新增精简的“原文链接”模块，按文章标题集中展示可点击链接
- 同步更新 README 与 Mode D 设计文档，明确 Mode E 发布稿流程
- 支持通过 --title 覆盖自动生成标题
- 将 Markdown → 公众号可粘贴 HTML 独立为 Mode E
- run.bat 新增 [E] WeChat publish mode
- 默认读取 data/mode_d_merged.md，自动生成公众号粘贴版 HTML 和元数据 JSON
- 交互入口隐藏图片映射等高级参数，降低使用复杂度
- HTML 使用纯内联样式，支持标题、表格、列表、引用、链接和图片占位

## v0.20.4 — 2026-07-12

### Mode D：Markdown 合并、点评与整合

- 新增根级入口 md_merge.py，支持一份或多份 Markdown 文档合并
- 采用“证据层 → 合并层 → 编辑层”三层结构：
  - 保留原文事实、点评、来源、图片引用和条目审计信息
  - 按标题规范化键去重，并生成来源映射 JSON
  - 生成类别统计、主题整合、交叉点评和行动建议
- run.bat 新增 [D] Markdown editorial mode
- 支持 --llm 调用统一 LLM 客户端增强跨条目点评；不可用时自动降级为本地规则结果
- 新增 docs/mode-d-design.md 和 tests/test_md_merge.py
- 使用 data/公众号文章整理_20260708.md、data/公众号文章整理_20260711.md 验证：
  - 2 份 Markdown → 6 条去重资讯
  - 结果保留于 data/mode_d_merged.md
  - 审计信息保留于 data/mode_d_merged.json
- 已完成 Python 编译检查和手工断言验证；当前环境未安装 pytest

## v0.20.3 — 2026-07-11

### Mode C 官网公告发现增强

- **公告链接兜底扫描**：`news-analyzer/scripts/website_scraper.py`
  - 邮储、中信、华夏增加基于详情 URL 规则的全页面扫描，降低官网列表 DOM 改版导致的漏抓风险
  - 支持中信 `news_260709.shtml` 形式的紧凑日期解析
  - 列表页缺少日期时保留候选，改由详情页二次识别并执行时间范围校验
- **回归测试**：`tests/test_news_analyzer/test_website_scraper.py`
  - 覆盖中信紧凑 URL 日期
  - 覆盖华夏 `138840.shtml` 详情链接发现

## v0.20.2 — 2026-07-10

### 周报亮点摘要增强 + LLM 配置回退统一

- **亮点摘要增强**：`common/display_fields.py`
  - 新卡类摘要改为优先提炼 `卡种 + 核心权益 + 年费信息`
  - 权益变更类摘要改为优先提炼 `时间 + 影响范围 + 前后变化/核心调整`
  - 活动类摘要改为优先提炼 `适用卡种/参与人群 + 时间 + 核心优惠内容`
- **LLM 配置优先级调整**：`common/llm_client.py`
  - 新增项目根目录 `apikey.txt` 解析
  - 配置读取优先级调整为 `显式参数/环境变量 → apikey.txt → ~/.llm_config.json`
  - 避免历史 `~/.llm_config.json` 中的过期配置覆盖项目当前可用 key
- **配置源对齐**：
  - `wechat-article-extractor/scripts/fetch_wechat_article.py` 复用统一配置读取
  - `card-holding-suggestion/scripts/scorer.py` 复用统一配置读取
- **测试补充**：
  - `tests/test_common/test_display_fields.py`
  - `tests/test_common/test_llm_client_integration.py`
  - `tests/test_wechat_extractor/test_fetch.py`
- **成稿修正**：
  - 重新修正 `data/Weekly_Report_2026年7月第2周.md` 中两条兴业银行公告的标题、亮点、结构化信息与原文摘要
  - 说明：归档 `data/archive/2026/07/2026年7月第2周/batch.json` 仍保留旧污染数据，若仅按该归档重生成成稿会再次覆盖人工修正

## v0.20.1 — 2026-07-10

### 官网抽取修复：兴业银行公告正文导航污染

- **正文抽取增强**：`news-analyzer/scripts/website_scraper.py`
  - 为兴业银行补充更具体的详情页标题、日期、正文选择器
  - 新增 `_cleanup_detail_content()`，统一清理详情页导航、页脚、模板噪音
  - 新增 `_looks_like_navigation_noise()`，识别“加入收藏/在线申请信用卡/产品介绍”等导航型误抓正文，并自动回退到 `body` 文本重清洗
  - `_clean_title()` 增强，去除 `兴业银行信用卡欢迎您` 这类站点模板前缀
- **回归测试**：`tests/test_news_analyzer/test_website_scraper.py`
  - 覆盖兴业银行标题清洗
  - 覆盖导航噪音识别
  - 覆盖公告正文清洗后保留真实内容、移除导航尾巴
- **周报修正**：`data/Weekly_Report_2026年7月第2周.md`
  - 修复两条兴业银行公告的标题、亮点、结构化信息、原文摘要
  - 清除导航文本误入摘要的问题

## v0.20.0 — 2026-06-07

### Phase 1-3: 条目结构化 + 优先级标注 + 综合建议升级

#### Phase 1: 条目结构化重写 + 优先级标注
- **Schema 扩展**：`common/schema.py` 新增 5 个字段：`target_audience`（定位）、`key_benefits`（核心权益）、`fee_assessment`（年费回报评估）、`worth_applying`（是否值得申请）、`priority_emoji`（优先级 emoji）
- **评分引擎扩展**：`card-holding-suggestion/scripts/scorer.py`
  - `ROI_Score` 新增 4 个富字段 + `priority_emoji`
  - 新增 `score_to_emoji()` 函数：score>=7->🔴, 4-6->🟡, <=3->⚪; 权益变更>=7->🟢
  - LLM prompt 扩展：要求输出 target_audience/key_benefits/fee_assessment/worth_applying
  - keyword fallback：从 raw_text/structured 提取富字段
- **Pipeline 顺序调整**：`src/agent.py` Step 5 移到 Step 4 之前，富字段回写 batch.items
- **报告渲染改造**：`word-merger/scripts/generate_report.py`
  - H2 标题追加 priority_emoji
  - 新增亮点/定位/核心权益/年费回报评估/是否值得申请渲染块
  - 🟢 正面变更跳过"建议"段落；⚪ 低价值活动精简显示
  - 目录改为手写风格（每条带 emoji + 摘要），删除"内容概览"和"本期亮点"
- **41 个新测试**：Phase 1 (19) + Phase 2 (9) + Phase 3 (13)

#### Phase 2: 标题优化 + highlight 增强 + 综合建议升级
- **LLM 标题压缩**：`generate_report.py` `build_report_title()` 新增 LLM 路径，top-3 高亮条目压缩为 <=50 字标题，失败 fallback
- **highlight 增强**：`common/display_fields.py` 新增 `key_benefits`/`fee_assessment` 参数，高亮摘要追加核心权益/年费评估
- **综合建议升级**：`src/agent.py` Step 6 新增 4 个段落
  - 建议销卡/放弃（score<=3）
  - 建议保留但需调整（score 4-6）
  - 近期关键时间节点（从 notes 提取日期）
  - 市场趋势提醒
- **格式统一**：移除新卡"卡亮点"重复渲染

#### Phase 3: 跨条目分析 + 年收益 + 跨期趋势 + QA 闭环
- **年收益估算**：`_extract_annual_benefit()` 从 recommendation/summary/key_benefits 正则提取年收益
- **推荐排名**：推荐申请段落按 score 降序，每条附带年收益
- **同类卡对比**：基于 key_benefits 场景关键词分组，同场景>=2 张高分卡输出对比
- **跨期趋势**：`_load_historical_batches()` 加载最近 3 期归档，检测降级趋势
- **QA 反馈闭环**：`common/qa_review.py` 同时输出 `qa_findings.json`（结构化问题 + quality_score）
- **keyword fallback 增强**：target_audience 从 structured 读取；fee_assessment 增加"首年免/刷卡免/刚性年费"模式；worth_applying 基于 score 生成

#### E2E 修复（6 个问题）
- **P0-1**：target_audience 0% -> 73%（从 structured["适用人群"] 读取 + title fallback）
- **P0-2**：highlight_summary 0% -> 100%（enrichment 始终执行 + fallback 生成）
- **P0-3**：噪音过滤（移除"其他"类 + raw_text 段落去重 + 低价值活动标记 + 标题清理）
- **P1-4**：fee_assessment 10% -> 13%（从 structured["详情"] 提取）
- **P1-5**：评分区分度优化（structured 字段也计分）
- **P1-6**：worth_applying 0% -> 40%（keyword 模式基于 score 生成）

#### raw_text 段落去重（方案B）
- 汇丰条目 48523 -> 3000 chars（移除 1185 个重复段落）
- 去重逻辑：按段落拆分，取前 30 字符作为去重 key，跳过已见前缀
- 去重后仍超 3000 字符则截断兑底


## v0.19.0 — 2026-06-06

### merge_docs.py 重构 — LLM 智能合并

#### 重构: merge_docs.py — 主流程改造
- **新流程**：read_docx → contents_to_items → llm_merge → JSON → generate_report.py → Word
- **删除**：`merge_contents()`、`create_merged_docx()`、`extract_items_for_analysis()`、`generate_suggestions()`
- **新增**：
  - `contents_to_items()` — H1/H2 结构转标准 JSON items
  - `llm_merge()` — LLM 智能合并（去重 + 分类 + highlight_summary）
  - `_fallback_merge()` — 标题相似度去重兜底
  - `convert_batch_to_merged()` — JSON batch 转旧 merged dict（供建议生成）
  - 辅助函数：`categorize_h1()`、`extract_bank_from_content()`、`extract_structured_fields()`、`resolve_image_paths()`
- **LLM 参数**：`max_tokens=16384, timeout=300`（适配 32 条合并）
- **JSON 解析增强**：支持裸 JSON / code block / 正则提取三种容错

#### 重构: common/llm_client.py — 多 Provider 支持
- **新增 mimo provider**：`_ENV_PROVIDERS` 增加 mimo（`MIMO_API_KEY`/`MIMO_MODEL`/`MIMO_API_URL`）
- **配置文件回退**：`_get_provider_config()` 在环境变量未设时自动读 `~/.llm_config.json`
- **自动 fallback**：`call_llm_simple()` 主 provider 失败时自动尝试 mimo（timeout 取 max 值）

#### 配置变更
- `~/.llm_config.json` model: `mimo-v2.5` → `mimo-v2-pro`（mimo-v2.5 为推理模型，content 为空）

#### 踩坑经验
- Python pycache：编辑公共模块后需清理 `__pycache__`，否则旧字节码继续执行
- reasoning model 不适合结构化输出：mimo-v2.5 reasoning tokens 耗尽导致 content 为空
- prompt 精简：去重场景只发 title+bank+category，不发 raw_text，避免超时
- provider fallback timeout 需独立设置，不能复用原始 timeout

## v0.18.0 — 2026-06-05

### RAG 混合检索升级

#### 新增 1: common/hybrid_retriever.py — 混合检索核心模块（280 行）
- `_EmbeddingIndex` 类：轻量级向量索引，numpy 数组 + pickle 序列化
- `HybridRetriever` 类：BM25 + 向量检索 + RRF 融合
- `build_or_load_hybrid()`: 构建或从缓存加载混合检索器
- `invalidate_vector_cache()`: 删除向量缓存

#### 新增 2: 本地 embedding 模型
- 下载 `BAAI/bge-small-zh-v1.5` 到 `D:/models/bge-small-zh-v1.5/`
- 512 维中文 embedding，适合信用卡领域检索

#### 修改 1: src/rag_query.py — 集成混合检索
- 使用 `HybridRetriever` 替代纯 BM25 检索
- 添加 `/mode` CLI 命令，切换 hybrid/bm25_only 模式
- 更新欢迎界面，显示混合检索状态

#### 修改 2: common/config.py — 添加向量配置
- `VECTOR_CACHE`: 向量索引缓存路径
- `EMBEDDING_MODEL`: 默认 embedding 模型路径

#### 修改 3: scripts/rag/kb_add_article.py — 添加向量缓存失效
- KB 更新后同时删除 BM25 和向量缓存

#### 修改 4: requirements.txt — 添加向量检索依赖
- `numpy>=1.24.0`
- `sentence-transformers>=2.2.0`

#### 新增 3: tests/test_hybrid_retriever.py — 混合检索单元测试
- 11 个测试用例，覆盖 EmbeddingIndex、HybridRetriever、缓存管理、Fallback 机制

#### 技术细节
- **RRF 融合公式**: `score(d) = bm25_w * Σ(1/(k + rank_bm25(d))) + vector_w * Σ(1/(k + rank_vector(d)))`
- **缓存策略**: BM25 和向量索引分别缓存，KB 更新后自动失效
- **Fallback 机制**: sentence-transformers 不可用时自动降级到 BM25-only

#### 测试
- 单元测试：10 passed, 1 skipped（集成测试因 torch 环境跳过）
- 手动测试：390 条 KB 条目混合检索正常

---

## v0.17.0 — 2026-06-13

### 修复 5 + 优化 1 + 经验沉淀 → TOOLS.md

#### Fix 1: news-analyzer generate_docx.py 重写 — 图片嵌入 + LLM 点评 + 中文字体
- 完全重写 `news-analyzer/scripts/generate_docx.py`，支持 `images` 字段嵌入图片、LLM `comment` 点评段插入、中文字体 eastAsia 双设
- 废弃旧版纯文本输出方案，与 word-merger 的 generate_report.py 对齐

#### Fix 2: requirements.txt — 取消 Pillow 注释
- Pillow 依赖取消注释，确保 `from PIL import Image` 在图片过滤脚本中可用

#### Fix 3: eastAsia 中文字体双设修复（4 个文件）
- `wechat-article-extractor/scripts/export_document.py` — 3 处添加 `run.font.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')`
- `word-merger/scripts/generate_report.py` — run.font.name 与 run._element 双设
- `word-merger/scripts/merge_docs.py` — 添加 eastAsia 字体

#### Fix 4: ensure_dir 导入修复
- `common/utils.py` — `ensure_dir` 改为从 `common.images` 导入并保留别名，确保 utils re-export 兼容性

#### Fix 5: word-merger generate_merged_docx.py — 新建独立 CLI 入口
- `word-merger/scripts/generate_merged_docx.py` 新建文件，支持 `--input` `--output` 参数，复用 `generate_report.py` 核心逻辑
- 解决旧 `word-merger` skill 调用时缺少独立入口的问题

#### Bonus: llm_review.py 银行列表去重
- `common/llm_review.py` — BANKS 列表去重（交行、浦发各出现两次），修复 LLM 审核输出中对同一银行给出重复分析

#### Optimization: src/rag_query.py 路径配置统一
- `os.path.dirname(__file__)` + `os.path.join` → `from common.config import DATA_DIR`，与全项目路径约定一致

#### 经验教训（已追加到 TOOLS.md）
- **eastAsia 双设**：python-docx 中文字体仅设 `run.font.name` 无效，必须额外设底层 XML `w:eastAsia`
- **Pillow 不可注释**：注释掉 `requirements.txt` 中 Pillow 会让 `from PIL import Image` 抛出 ImportError
- **路径统一**：新模块路径优先从 `common.config` 导入，不应本地 re-compute
- **常量去重**：硬编码常量列表应检查重复项，避免重复输出低级别 bug

### 测试
- 全量 420 passed，无回归

---

## v0.16.0 — 2026-06-12

### LLM 模块统一：common/llm_client.py（新建 400 行）

统一 3 处分散的 LLM 调用代码为集中维护：

| 旧位置 | 代码量 | 新入口 | 代理行数 |
|--------|--------|--------|----------|
| `common/llm_review.py:_call_llm()` | 53 行 | `from common.llm_client import call_llm_simple_str as _call_llm` | 3 行导入 |
| `src/rag_query.py:call_llm()` | 55 行 + 10 env vars | `from common.llm_client import call_llm_simple` | 6 行薄代理 |
| `card-holding-suggestion/scripts/scorer.py` | 30 行 HTTP POST | `from common.llm_client import call_llm_file_config` | 15 行适配器 |

`LlmClient` 支持三种调用模式：
1. **环境变量模式**：自动检测 groq/grok/openrouter，兼容旧环境配置
2. **文件配置模式**：`~/.llm_config.json`，同旧 scorer
3. **显式参数模式**：最高优先级，灵活覆盖

### 图片模块统一：common/images.py（新建 257 行）

聚合 2 处分散的图片处理代码 + 按内容哈希去重：

| 旧位置 | 代码量 | 功能 | 新位置 |
|--------|--------|------|--------|
| `common/utils.py` | 98 行 | `get_central_image_dir`, `download_image_from_url`, `copy_to_central_image_dir`, `centralize_images` | `common/images.py` + utils 保留 re-export |
| `src/agent.py:_filter_meaningful_images()` | 63 行 | 图片四层过滤（大小/尺寸/像素方差） | `common/images.py:filter_meaningful_images()` |
| **新增** | — | `image_hash()`, `deduplicate_images()` | 按 SHA-256 内容哈希去重 |

### 清理

- `common/llm_review.py`：删除 53 行旧 `_call_llm` + `import os` + `import requests` + 4 个 env var
- `src/rag_query.py`：删除 55 行旧 `call_llm` + 10 个 env var
- `src/agent.py`：删除 63 行 `_filter_meaningful_images`
- `common/utils.py`：删除 96 行图片相关代码移入 images.py

### 测试
- 全量 336 passed，无回归

---

## v0.15.0 — 2026-06-10

### Mode C: 仅数据处理（Step1-4，跳过持卡分析+归档）
- `_agent.py` 新增 `mode == "c"` 分支，只执行 step1-4（微信/银行抓取 → 分类合并 → Word 周报）
- `run_pipeline.py` 新增 `--mode c` 支持
- `run.bat` [C] 选项更新菜单和提示文本

### 图片四层过滤（`_filter_meaningful_images`）
- **文件大小** < 5KB → 纯色图/空白占位图/压缩后无内容图
- **最小尺寸** 任一方 < 30px → 分割线/极窄装饰条
- **图标尺寸** 宽高都 < 50px → 小图标/二维码/分享关注引导图
- **像素方差** 灰度标准差 < 8 → 纯色底图/简单渐变（无文字/无内容）
- 安全保护：Http URL 不分析直接保留、至少保留 1 张兜底、异常保护
- 应用位置：`_normalize_wechat_article()` 微信图片入库前 + `step4_generate_md_report()` 所有最终输出前

### 数据质量修复
- **标题"未知推出优惠活动"**：`display_fields.py` 新增 `_extract_meaningful_activity_name()` — 跳过样板话（"一、活动时间""二、活动对象"）和长日期前缀，提取真实活动名；纯样板话无有效内容时回退保留原标题
- **标题"活动活动"重复**：`display_fields.py` 去重 `_deduplicate_title()` — 去除标题中连续重复词，并正确保留原标题（不再退化为"未知推出"）
- **样板话跳过**（编号标题如"一、活动时间"）：`generate_display_fields()` 新增检测逻辑，逐句跳过样板话再取有效活动名；遍历已有 `headline_block/description` 时也跳过样板话

### run.bat
- 菜单文本增加 `[C] Mode C 仅数据处理（Step1-4，跳过持卡分析+归档）`
- 提示符从 `(A/B/Q)` 改为 `(A/B/C/Q)`

---

## v0.14.0 — 2026-06-08

### P3 — 目录结构整理

#### 核心源码迁移

- `src/` 包创建，核心模块迁移（`agent.py`, `pipeline.py`, `rag_query.py`），路径经修正
- 根级 stub 委派（`_agent.py`, `rag_query.py`, `run_pipeline.py`），所有 `.bat` / 命令行入口无感使用
- 调试脚本 → `scripts/debug/`（`check_dups`, `check_item`, `check_item2`, `e2e`）
- RAG 知识库维护 → `scripts/rag/`（`kb_add_article`）
- 工具脚本独立（`scripts/cleanup_images.py`）
- 文档 → `docs/`（9 个 `.md` 文件整理归档）
- 陈旧文件清理（`tests/test_output*.docx`）+ `.gitignore` 已有屏蔽规则

#### P1 — 迁移 Word 层内容修复逻辑到 normalizer

- `normalizer.py` 新增 `_trim_marketing_intro()` — 自动过滤公众号营销引言段
- `normalizer.py` 新增 `_safe_truncate()` — 按句号/感叹号/问号边界截断，不在词/句中切断
- `normalizer.py` 新增 `structured_clean` 填充逻辑，对 structured 各字段去营销/去噪音
- `word-merger/generate_report.py` 删除本地重复的截断/过滤逻辑，全部委派 normalizer
- `display_fields.py` 参数化调用，避免 self 传递，消除循环引用
- 删除 3 处本地分类函数，全部统一到 `common/classifier`

#### P2 — 优化 confidence 打分区分度

- 多维度打分因子重构（关键词匹配 + 实体数 + 来源权威性 + 时效性）
- 分数分布更平滑，审核队列实际可用
- `common/review.py` 同步适配新的 confidence 范围

#### 测试

- 新增 6 个测试文件（classifier / confidence / display_fields / entity_resolver / llm_review / normalizer）
- 全量 188 passed，无回归

---


### 验收修复 — 跨模块标准化收口

#### 修复
- **来源字段**：`entity_resolver.resolve_bank()` 将"未知公众号"等垃圾 author 值视为空，fallthrough 到银行名，不再依赖 Word fallback
- **分类逻辑统一**：删除 `news-analyzer/convert_to_standard.py` 和 `website_scraper.py` 中 3 处本地 `_guess_category()` / `_guess_category_from_title()`，全部委派到 `common/classifier.classify_item()`；`wechat-article-extractor/convert_to_standard.py` 本地 `_build_structured()` 改为 `normalizer._build_structured_for_category()`
- **structured 内容清洁**：
  - 新增 `_trim_marketing_intro()` — 自动过滤公众号营销引言段落（"说在前头！自从公众号推送机制改变后..." 等）
  - 新增 `_safe_truncate()` — 按句号/感叹号/问号边界截断，不在词/句中切断
  - `_build_structured_for_category` 优先使用清洗后的 raw_text 而非硬截断 `source_text[:500]`
  - 新增 `structured_clean` 填充逻辑，对 structured 各字段去营销/去噪音
- **display_fields 循环引用**：`generate_display_fields` 避免传递 `self`，通过方法参数传递需要的值

#### 修改文件
- `common/entity_resolver.py` — publisher_name 未知公众号过滤
- `common/normalizer.py` — 新增 `_trim_marketing_intro()` / `_safe_truncate()` / `structured_clean` 填充
- `common/display_fields.py` — 移除 self 传递，方法参数化
- `news-analyzer/scripts/convert_to_standard.py` — 删除本地 `_guess_category()`
- `news-analyzer/scripts/website_scraper.py` — 删除本地 `_guess_category_from_title()`
- `wechat-article-extractor/scripts/convert_to_standard.py` — 改用 `_build_structured_for_category()`

#### 测试
- 全量 165 passed，无回归

## v0.12.0 — 2026-06-06

### 多主题公众号文章拆分

#### 新增
- `common/article_envelope.py` — 文章信封构建器：统一微信文章的 URL/标题/发布时间/正文块/图片封装，自动生成 `article_id`、预检测「单主题/多主题」标记
- `common/topic_splitter.py` — 主题拆分引擎：
  - `detect_multi_topic()` — 6 种信号检测（编号小标题/活动模板重复/银行名称/命名实体/heading_like 块/CTA 噪音比），置信度打分 0.0~1.0
  - `split_article_into_topics()` — 按 `_is_topic_start()` 切点分割 + 尾分配法（`tail_assignment`）合并零散结尾
  - `merge_small_topics()` — 过拆修正：短 topic（≤3 blocks）吞并到前一个
  - 无信号/低置信度 → 单主题回退，`split_signals` 写入原文
- `common/normalizer.py` — `normalize_topic()` 桥接函数：TopicDict → CreditCardItem，字段映射 + `is_multi_topic_split` + `topic_split_confidence` + `topic_split_signals`
- `common/schema.py` — `CreditCardItem` 新增 4 个主题拆分字段：`is_multi_topic_split` / `topic_id` / `topic_split_confidence` / `topic_split_signals`
- `_agent.py` `step3_merge()` — 微信文章链路集成：`content_blocks` 存在 → `build_article_envelope` → `detect_multi_topic` → `split_article_into_topics` → `normalize_topic` → 逐 topic 入 batch

#### 测试
- `tests/test_topic_splitter.py` — 27 个测试用例覆盖：
  - `_has_numbered_prefix`（中/英/活动编号，3 条）
  - `_detect_template_group`（activity/卡种/否定，3 条）
  - `TestDetectSingleTopic`（单主题检测+回退，2 条）
  - `TestDetectMultiTopic`（编号标题检测/三分拆/块完整性/模板组检测/模板拆分，5 条）
  - `TestMergeSmallTopics`（合并/不合并/空输入，3 条）
  - `TestNormalizeTopic`（字段映射/低置信度标记/空安全，3 条）
  - `TestEdgeCases`（空块/单标题/全噪音/银行识别/topic_start/命名实体，6 条）
  - `TestArticleEnvelope`（构建/ID生成，2 条）
- 全量 165 passed，无回归

## v0.11.0 — 2026-06-05

### 架构重构 — 第 3 批：微信 content_blocks + 官网 DOM 级清洗

#### 新增
- `wechat-article-extractor/fetch_wechat_article.py` 新增 `_classify_text_block()` — 启发式分类 OCR/LLM 结果为 4 种 block 类型：`article_text` / `ocr_fact` / `ocr_noise` / `image_cta`；输出 `content_blocks`，`full_text` 仅含实质内容
- `news-analyzer/website_scraper.py` — `BankConfig` 新增 3 个配置字段：`detail_remove_selectors`（DOM 选择器列表）、`detail_start_markers` / `detail_end_markers`（文本层精确截取）；`fetch_detail_page` 双层过滤（DOM 层删除噪音节点 → 文本层按 marker 截取）
- `common/normalizer.py` 优先从 `content_blocks` 构建清洁文本；OCR 噪音 / CTA 文字 → `noise_flags`，不进结构化/展示字段
- `common/display_fields.py` — 展示字段生成器（标题策略 + 摘要策略，支持 `title_source` 审计）
- `common/entity_resolver.py` — 来源/银行识别器（优先级链：参数 > 公众号名 > 标题 > 正文 > 未知），17 家银行映射 + 15 个公众号对照表

#### 架构重构 — 第 2 批：统一标准化口径

- `common/classifier.py` — 三层分类器（强规则层 + 弱规则打分 + 低置信度降级），输出 `category` / `category_candidates` / `evidence`
- `common/normalizer.py` 集成：`normalize_item()` 顺序调用 classifier → entity_resolver → structured → display_fields → review_flags
- `_agent.py` `step3_merge()` 重写为标准化入口（WeChat 走 `normalize_item(source="wechat")`，官网走 `normalize_item(source="website", skip_auto_classify=True)`）
- 删除 150+ 行手动 CreditCardItem 构造代码，5 个旧函数保留为薄适配器

#### 架构重构 — 第 1 批：最小重构建立可审核性

- `common/schema.py` — `CreditCardItem` 新增 16 个审核/质量字段：`issuer_bank`、`publisher_name`、`source_name`、`source_type`、`raw_title`、`normalized_title`、`display_title`、`highlight_summary`、`title_source`、`confidence`、`evidence`、`noise_flags`、`review_flags`、`category_candidates`、`content_blocks`、`structured_clean`
- `common/normalizer.py` — 统一 Normalizer 入口 `normalize_item(raw_item, source, bank)` → CreditCardItem
- `common/review.py` — 审核队列生成器 `generate_review_flags()` / `build_review_queue()` / `export_review_queue()` → `data/review/review_queue.md`

### 测试
- 138 passed（schema 测试 + e2e 新模块链全链路验证 + batch 3 验证）

### 清理
- 删除 150+ 行 _agent.py 手动构造代码

## v0.10.0 — 2026-05-31
### 新增
- 持卡建议输出规范：`ROI_Score` 新增 `notes`（注意事项）和 `activity_value`（活动参与方式）字段
- 提取 `_generate_notes()` 辅助函数：四分类（新卡/变更/活动/公告）自动生成注意事项
- `scorer.py` 双评分路径（keyword + llm）统一使用 `_generate_notes()`
- 代码审查报告 `code_review_by_module.md`：覆盖 6 大模块，标注 P1/P2/P3 问题级别

### 修复
- `_agent.py` step6 分类标题重复（标题移出 for 循环）
- `_agent.py` step6 新增综合持卡策略段（推荐申请/优先活动/需关注变动）
- `scorer.py` LLM 评分路径 notes 字段缺失
- `scorer.py` 公告分类 `calc_highlight_for_announcement` 引用错误

### 测试
- 新增 `tests/test_card_holding/test_scorer_highlight.py`：42 个测试用例
  - `TestGenerateNotes`：14 个，覆盖四分类各评分路径
  - `TestKeyWordScoring`：11 个，覆盖关键词评分分类边界
  - `TestROIScore`：2 个，数据类序列化
- 新增 `tests/test_common/test_schema.py`：17 个测试用例
  - 数据契约 CreditCardItem / CreditCardBatch 序列化与校验
- `conftest.py`：共享 fixture（DIMENSION_TEMPLATES）
- 修复测试文件 sys.path 路径错误

### 清理
- 删除 9 个临时调试脚本（test_vision*.py, test_vision.ps1, tmp_run_gf_test.py, verify_modeA.py）
- 删除 news-analyzer 临时测试文件 3 个（tmp_test.py, test_articles.json, test_all_banks.py）
- 删除 data/ 临时产出 3 个（articles_kb.json.bak, test_merge_output.*）
- 删除空目录 data/temp/
- 清理 .pytest_cache/

## v0.9.0 — 2026-05-30
### 新增
- RAG 知识库问答系统：BM25 检索 + LLM（Groq / OpenRouter API）生成回答
- `rag_query.py`：交互式 RAG 问答入口（支持 `/debug` 模式）
- `kb_add_article.py`：单篇/批量新增文章到知识库
- `convert_rag_batch.py` / `convert_rag_final.py`：全量 KB 转换器
- `RAG知识库.md`：RAG 系统完整项目复盘文档

### 知识库清洗
- `_clean_kb.py` 执行清洗：去除非信用卡相关条目（135 篇 → 59 篇，793 条 → 405 条）
- 补全 4 条缺失日期（从 frontmatter / 文件名提取）
- BM25 索引缓存 `data/bm25_cache.pkl`，秒级加载

### 模型选择
- 主力：`llama-3.3-70b-versatile`（Groq）
- 备选：`qwen/qwen3-32b`（OpenRouter）
- 通过 `LLM_PROVIDER` 环境变量切换

### 项目清理
- 删除根目录 30+ 个临时/调试文件（`_*.py`、`_*.txt`、`_*.ps1`、`_*.bat`、`_*.json`、日志文件）
- 更新 `README.md`：新增 RAG 知识库问答章节、更新开发路线图（M3 知识库检索 ✅）
- 更新 `README.md`：项目文件清单、修订记录 v0.8 条目

## v0.7.0 — 2026-05-30
- `generate_report.py` 新增 `is_ad_image()` 广告图过滤函数，写入 Word 前自动跳过无价值图片

### 过滤规则（满足任一即跳过）
- 文件 < 15KB 且短边 < 100px（分隔线/图标）
- 宽高比 > 3.5（超宽横幅广告条、关注引导）
- 宽高比 < 0.15 且宽度 < 200px（极窄竖条装饰）
- 短边 < 200px 且文件 < 50KB（微信操作引导小图）

### 效果
- 实测 152 张图过滤 39 张（26%），超长内容图（活动详情长图）正确保留
### 修复
- `scorer.py` LLM 评分路径实际不可用：`~/.llm_config.json` 中 model 配置错误（`mimo-v2.5` 为推理模型，内部 reasoning 耗尽 token 导致 content 为空）
- 修正 model 为 `mimo-v2-pro`（非推理模型，正常输出 JSON 评分）
- `max_tokens` 从 1024 提升至 2048，避免长 prompt 截断

### 新增
- `scorer.py` 首次调用时打印配置摘要（api_base / model / key 后4位），方便确认配置
- `ROI_Score` 新增 `scorer_used` 字段（`"llm"` / `"keyword"` / `"keyword_fallback"`），评分结果可审计
- LLM 配置缺失时输出明确警告及配置示例
- LLM 调用失败时 summary 标注失败原因，调用方可区分降级来源

### 清理
- 删除根目录临时脚本：`__tmp_llm_test.py`、`__tmp_short_test.py`、`__tmp_models_test.py`、`__tmp_json_test.py`、`__llm_stderr.log`
- 删除 `data/` 临时脚本及日志：`tmp_*.py`、`__tmp_check_batch.py`、`*.log`

## v0.4.0 — 2026-05-17
### 新增
- 知识库归档机制 `common/archive.py`
- 全流程编排 Agent `_agent.py`
- 项目计划文档 `PROJECT_PLAN.md`
- 修订记录 `CHANGELOG.md`

### 变更
- `_pipeline.py` 新增归档步骤
- 统一路径配置，所有归档路径从 `common/config.py` 获取

## v0.3.0 — 2026-05-17
### 新增
- 统一数据契约 `CreditCardItem` / `CreditCardBatch`
- 图片集中存储（Route B）：`data/images/{item_id}/`
- `common/schema.py`、`common/config.py`、`common/utils.py`

### 修复
- `convert_to_standard.py` 中文弯引号语法错误
- 微信公众号文章编码问题（UTF-8 BOM）
- `generate_report.py` 模块级 `Pt()` 求值错误

### 变更
- `_pipeline.py` 管线脚本（微信 → 网站 → 合并 → Word → 分析）
- 所有 skill 输入输出统一为 CreditCardBatch JSON 格式

## v0.2.0 — 2026-05-16
### 新增
- `word-merger` skill：Word 周报生成
- `card-holding-suggestion` skill：持卡用卡建议分析
- `_pipeline.py` 管线脚本原型

## v0.1.0 — 2026-05-15
### 新增
- 项目初始化
- `wechat-article-extractor` skill：微信公众号文章抓取
- `news-analyzer` skill：网站公告抓取整理

## v0.5.0 — 2026-05-30
### 新增
- 追加持卡建议到Word周报末尾章节+目录字段更新

### 变更
- `generate_report.py` 新增目录生成功能
- `_agent.py` 新增 Step 6
