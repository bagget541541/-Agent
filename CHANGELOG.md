# 修订记录

## v0.13.0 — 2026-06-07

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
