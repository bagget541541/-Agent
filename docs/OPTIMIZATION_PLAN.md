# 优化计划

> 基于最小闭环场景自测（2026-05-30），按优先级排列

---

## ✅ 已完成（阻塞项 + P0 + 代码审查成果）

- [x] 补回 `_agent.py` 全流程入口
- [x] 创建顶层 `requirements.txt`
- [x] Playwright 浏览器自动安装（`wechat-article-extractor/setup.ps1`）
- [x] docx 编码问题修复（`word-merger/scripts/docx_utils.py` 集成）
- [x] 交互式入口 `run.bat` + `run_pipeline.py`
- [x] 多文档整合 `merge_docs.py`（Mode B）
- [x] LLM 整体分析替代逐条评分
- [x] 层级结构保留（Heading 1 → Heading 2）
- [x] 图片提取与保留
- [x] 项目文件清理（删除临时文件、重复脚本、缓存）
- [x] 修复 `_agent.py` 导入错误（`scrape_all_banks` → `scrape_bank` + `BANK_CONFIGS`）
- [x] 修复 `_agent.py` 导入错误（`analyze_batch` → `build_context`）
- [x] 修复 `step4_generate_report` 重复 except 块
- [x] 修复 `step6_append_suggestions` 追加持卡建议到 Word 文档
- [x] 修复 `step7_archive` 分析结果路径匹配
- [x] 所有 print 语句改为英文（避免 Windows cmd.exe GBK 编码问题）

## P0 优先级（第一阶段重构 — 建立可审核性）

### 0. ✅ Schema 扩字段 — CreditCardItem 审核/质量字段（已完成）
- **提交**：P0 / Task 1
- **改动**：`common/schema.py` CreditCardItem 新增 16 个字段
- **新增字段**：`issuer_bank`, `publisher_name`, `source_name`, `source_type`, `raw_title`, `normalized_title`, `display_title`, `highlight_summary`, `title_source`, `confidence`, `evidence`, `noise_flags`, `review_flags`, `category_candidates`, `content_blocks`, `structured_clean`
- **设计原则**：所有新字段有默认值（空字符串/dict/list），旧链路无需改动
- **测试**：138 passed

### 0b. ✅ 统一 Normalizer 入口 — `common/normalizer.py`（已完成）
- **提交**：P0 / Task 2
- **改动**：新增 `common/normalizer.py`
- **公开函数**：`normalize_item(raw_item, source, bank)` → CreditCardItem；`normalize_batch(raw_items, source, bank)` → CreditCardBatch
- **阶段**：当前为字段映射层，后续注入分类器/来源识别

### 0c. ✅ 审核队列输出 — `common/review.py`（已完成）
- **提交**：P0 / Task 3
- **改动**：新增 `common/review.py`
- **公开函数**：`generate_review_flags(item)` → list[str]；`build_review_queue(items)` → dict；`export_review_queue(items, dir)` → (json_path, md_path)
- **审核规则**：category 置信度低、bank 缺失、title 过短、structured 为空、time 缺失
- **输出**：`review_queue.json` + `review_queue.md` → `data/review/`

### 0d. ✅ 新字段接入 Pipeline（已完成）
- **提交**：P0 / Task 4
- **改动**：`_agent.py` — `step3_merge()` 中 CreditCardItem 构造补齐所有新字段，`run_pipeline()` 末尾自动导出审核队列
- **效果**：运行 pipeline 后可在 `data/review/review_queue.md` 查看待复核条目

---

## P1 优先级（统一标准化口径 — 已完成）

### 5. ✅ 统一分类器 — `common/classifier.py`（已完成）
- **目标**：替代 `_agent.py` 零散关键词硬判，建立三层分类体系
- **三层设计**：
  1. 强规则层：标题含"新卡/首发/发行" → 新卡 (0.92)；"调整/变更/缩水" → 权益变更 (0.88)
  2. 弱规则打分：按分类独立关键词（标题 2x 权重），归一化 0~1
  3. 低置信度降级：max_score < 0.5 或前两名分差 < 0.15 → '其他' + 保留候选列表
- **输出**：`category`, `category_candidates: [[cat, score], ...]`, `evidence`

### 6. ✅ 来源/银行识别 — `common/entity_resolver.py`（已完成）
- **优先级链**：显式 bank 参数 > 公众号名映射 > 标题 > 正文 > '未知'
- **支持**：17 家银行简称→全称映射 + 15 个公众号→银行对应表
- **输出**：`bank`, `issuer_bank`, `publisher_name`, `source_name`, `evidence`

### 7. ✅ normalizer 集成 — structured/classify/resolve 一体化（已完成）
- `normalize_item()` 按顺序调用：classifier → entity_resolver → structured → display_fields → review_flags
- `_build_structured_for_category` / `_build_image_structured` 从 `_agent.py` 迁入
- `skip_auto_classify` 参数：已有分类的来源跳过自动分类

### 8. ✅ 展示字段生成 — `common/display_fields.py`（已完成）
- **标题策略**：含分类动作关键词 → 保留；缺关键词 → 按模板生成
- **摘要策略**：按分类取 structured 主字段
- **输出**：`title`, `normalized_title`, `display_title`, `highlight_summary`, `title_source`

### 9. ✅ `_agent.py` 瘦身 — `step3_merge()` 改用标准化入口（已完成）
- `step3_merge` 重写：WeChat 走 `normalize_item(source="wechat")`，官网走 `normalize_item(source="website", skip_auto_classify=True)`
- 5 个旧函数保留为薄适配器
- 删除 150+ 行手动 CreditCardItem 构造代码

### 测试验证
- 138 passed ✅
- E2E 新模块链全链路验证通过 ✅

---

## 第 3 批：重构微信/OCR 和官网清洗策略（已完成）

### Task 7. ✅ 微信 content_blocks 块输出
- **文件**：`wechat-article-extractor/scripts/fetch_wechat_article.py`
- **改动**：`process_single()` 将 OCR/LLM 提取结果分为 4 种 block 类型：
  - `article_text` — 文章正文（置信度 0.95）
  - `ocr_fact` — OCR 提取的关键事实（置信度 0.7）
  - `ocr_noise` — 噪音/图片描述（置信度 0.3，不进展示字段）
  - `image_cta` — 行动号召文字（置信度 0.3，不进展示字段）
- **新函数**：`_classify_text_block()` — 启发式分类（CTA 关键词/噪音模式/长度阈值）
- **兼容性**：`full_text` 重建为仅含 article_text + ocr_fact；旧字段 `ocr_text`/`llm_text` 保留

### Task 8. ✅ 官网 DOM 级噪音剥离
- **文件**：`news-analyzer/scripts/website_scraper.py`
- **BankConfig 新增 3 个配置字段**：
  - `detail_remove_selectors` — DOM 选择器列表，提取正文前删除匹配节点
  - `detail_start_markers` — 正文开头标记，文本层从此截取
  - `detail_end_markers` — 正文结束标记，文本层截取到此为止
- **fetch_detail_page 双层过滤**：
  1. DOM 层：先按 `detail_remove_selectors` 删除噪音节点
  2. 文本层：按 `detail_start_markers` / `detail_end_markers` 精确截取
- **零成本采用**：新字段默认为空 list，现有 BankConfig 不受影响

### Task 9/10 收尾. ✅ normalizer 消费 content_blocks
- **文件**：`common/normalizer.py`
- `normalize_item()` 优先从 `content_blocks` 构建清洁文本（只含 article_text + ocr_fact）
- OCR 噪音、CTA 文字 → `noise_flags`，绝不进入 structured 或展示字段
- `CreditCardItem` 构造时传入 `content_blocks` 和 `noise_flags`

### 测试验证
- 138 passed ✅
- 所有新模块可正常导入 ✅

---

## P2 候选（待排期）

### 3. 银行配置中心
- **问题**：银行列表硬编码在 `website_scraper.py`
- **方案**：抽取到 `data/bank_config.json`
- **工作量**：中
- **产出**：`data/bank_config.json`

### 4. merge_docs.py 图片增强
- **问题**：当前图片插入未考虑排版，可能溢出页面
- **方案**：添加图片尺寸限制和居中对齐
- **工作量**：小
- **产出**：`merge_docs.py` 图片处理优化

### 5. LLM 整体分析降级优化
- **问题**：LLM 调用失败时降级为简单关键词匹配，信息量不足
- **方案**：增强关键词降级逻辑，提供更多结构化建议
- **工作量**：中
- **产出**：`merge_docs.py` 降级逻辑增强

### 6. ✅ 死代码清理（已完成）
- **wechat_monitor.py**：移除 `fetch_article()` / `add_urls()` / `generate_report()` / `main()`，精简 182 行为纯去重组件
- **rsshub_fetcher.py**：添加 DEPRECATED 废弃标记注释
- **export_document.py**：标题逻辑 + 图片大小统一（实际已修复，代码审查确认）
- **fetch_wechat_article.py**：`USE_PLAYWRIGHT` 冗余 flag 删除（实际已删除）

### 7. ✅ 结构化字段数据链路修复（已完成）
- **问题**：银行官网 `structured` 字段在 `step3_merge` 中被丢弃，Word 报告只显示标题+链接无结构化内容
- **根因**：`step3_merge()` 中 `CreditCardItem(bank_announcement)` 未传入 `structured`/`images`/`author`；`step2_fetch_bank_news` 兜底转换遗漏相同字段
- **修复**：
  - `_agent.py` `step3_merge()` — 补充 `structured`、`images`、`author` 传递
  - `_agent.py` `step2_fetch_bank_news()` — 兜底转换补齐遗漏字段
  - `website_scraper.py` — "活动"分类 `活动内容` 由标题改为正文内容

### 8. ✅ 微信纯图片文章分类 & 结构化提取优化（已完成）
- **问题**：纯图片文章分类不准（OCR 中"卡种名称"误判为新卡、"核心权益"误判为权益变更）；结构化字段为 OCR 原始文本堆砌
- **修复**：
  - `_agent.py` `_guess_category_from_wechat()` — 标题优先+文本/OCR 兜底；移除"卡种"、"权益"宽泛关键词
  - `_agent.py` `_build_image_article_structured()` — 从 OCR 分析中提取卡种、权益、价格、适用条件等结构化字段
  - `_agent.py` `_format_article_structured()` — 纯图片走 OCR 解析路径，非图片文章保持原有逻辑
- **效果**：OCR 原始文本 → `活动内容: 无价惊喜；在40多家高端酒店享受游泳健身礼遇；55元起（优惠体验价）`

---

## P2 优先级（长期优化）

### 6. ~~wechat-article-extractor 集成到 pipeline~~ ✅
- **已完成**：`_agent.py` Step 1 已改用 `wechat-article-extractor`
- **方案**：requests 优先 + Playwright 兜底，搭配 URL 去重
- **工作量**：中

### 7. 定时任务调度
- **方案**：集成 schedule 或 crontab
- **工作量**：中

### 8. Web 管理端
- **方案**：简单 Flask/FastAPI 界面
- **工作量**：大

### 9. 增量抓取
- **方案**：记录上次抓取时间，只抓新内容
- **工作量**：中

---

## Skill 模块使用现状

| Skill | Pipeline 步骤 | 状态 | 说明 |
|-------|--------------|------|------|
| `common/` | Steps 3, 7 | ✅ 完全使用 | schema, archive, config |
| `wechat-article-extractor/` | Step 1 | ✅ 主力抓取 | requests + Playwright，替代 wechat-rss-monitor |
| `wechat-rss-monitor/` | Step 1 | ✅ 去重模块 | 仅使用 history.json URL 去重 |
| `news-analyzer/` | Step 2 | ✅ 使用 | scrape_bank + BANK_CONFIGS（18家银行） |
| `card-holding-suggestion/` | Step 5 | ✅ 使用 | build_context + scorer |
| `word-merger/` | Step 4 | ✅ 使用 | docx_utils.safe_generate_report |
| `merge_docs.py` | Mode B | ✅ 完全使用 | 多文档整合 + LLM 整体分析 |
| `scripts/` | 未接入 | ❌ 未使用 | convert_articles_to_rag.py 独立工具 |

---

## 项目清理记录（2026-05-30）

已清理内容：
- `unpacked_0530/` - docx 解压临时目录（57文件）
- `wechat-article-extractor/images/` - 独立抓取图片（152文件）
- `wechat_imgs/` - 测试图片（9文件）
- `data/` 测试版本、中间转换文件、缓存
- 根目录重复脚本（convert_rag.py, convert_rag_batch.py, fix_docx_encoding.py, wechat_monitor_integration.py）
- 所有 `__pycache__/` 目录
