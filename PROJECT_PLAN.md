# 信用卡周报自动化项目计划

## 项目愿景
将信用卡周报的「抓取→分类→合并→出报告→持卡建议→归档」全流程 agent 化，用户只需一句话即可触发完整流水线，归档数据沉淀为可检索的知识库。

## 技能体系

| Skill | 职责 | 现状 |
|-------|------|------|
| `wechat-article-extractor` | 抓取微信公众号文章 | ✅ 基础可用，图片已集中存储 |
| `news-analyzer` | 抓取银行官网公告/活动 | ✅ 多银行支持(15+银行) |
| `word-merger` | 合并且生成 Word 周报 | ✅ 已验证可用 |
| `card-holding-suggestion` | 持卡用卡 AI 评分建议 | ✅ LLM评分已验证可用（mimo-v2-pro），关键词评分保留为降级方案 |
| 公共层 `common/` | 数据契约、配置、工具、归档 | ✅ 基础完备 |

## 里程碑

### M1 — 基础设施与归档 ✅
- [x] 统一数据契约 `CreditCardItem` / `CreditCardBatch`
- [x] 图片集中存储（Route B）
- [x] 项目文档（本计划 + CHANGELOG）
- [x] 知识库归档机制 `common/archive.py`
- [x] 全流程编排 `_agent.py`

### M2 — skill 升级 ✅
- [x] `card-holding-suggestion`: LLM 语义评分 + 加权 ROI 模型（mimo-v2-pro，scorer_used 可审计）
- [x] `news-analyzer`: 多银行官网支持（迁入 banks_parser_v2.py 模式）
- [x] `wechat-article-extractor`: 图片质量/去重优化（广告图过滤，写入 Word 前自动跳过）

### M3 — 最小闭环场景 ✅
- [x] 交互式入口 `run.bat` + `run_pipeline.py`
- [x] 多文档整合 `merge_docs.py`（Mode B）
- [x] LLM 整体分析替代逐条评分
- [x] 层级结构保留 + 图片保留
- [x] RAG 知识库问答系统（BM25 + LLM）
- [x] 知识库清洗（405 条/59 篇，覆盖 26 家银行）
- [x] 项目文件清理

### M4 — Agent 编排完善 ✅
- [x] 代码审查（6 大模块，问题分级 P1/P2/P3）
- [x] 补充核心单元测试（59 个用例，schema + scorer + highlight 全覆盖）
- [x] 修复 step6 标题重复 bug + 补齐综合持卡策略输出
- [x] 持卡建议输出规范化（notes / activity_value / _generate_notes()）

### M5 — 持续优化（部分完成）
- [ ] 配置中心（银行列表、公众号列表可配置化）
- [x] 统一错误处理框架（common/errors.py）
- [x] 错误恢复 / 降级策略
- [x] LLM 自动分类 → 替代为 rule-based 三层分类器（common/classifier.py）
- [ ] Web 管理端 / 定时任务
- [ ] 增量抓取（只抓上次归档后的新公告）
- [ ] merge_docs.py 图片尺寸优化
- [x] wechat-monitor 功能去重（fetch_article 死代码移除）
- [x] 来源/银行自动识别（common/entity_resolver.py，17 家银行 + 15 公众号映射）

### M6 — 代码质量重构 ✅
- [x] Schema 扩字段：CreditCardItem 新增 16 个审核/质量字段（issuer_bank、publisher_name、source_name、content_blocks、noise_flags 等）
- [x] 标准化 Normalizer 入口：normalize_item() 统一处理分类/识别/结构化/展示/审核
- [x] 审核队列输出：data/review/review_queue.md，自动标记待复核条目
- [x] 统一分类器：common/classifier.py（强规则 + 弱规则打分 + 低置信度降级）
- [x] 银行/公众号自动识别：common/entity_resolver.py
- [x] 展示字段生成器：common/display_fields.py
- [x] 微信 content_blocks：4 种 block 类型分类（article_text / ocr_fact / ocr_noise / image_cta）
- [x] 官网 DOM 级噪音剥离：BankConfig.detail_remove_selectors + detail_start/end_markers 双层过滤
- [x] _agent.py 瘦身：step3_merge 改标准化入口，删除 150+ 行手动构造代码
- [x] 138 测试全通过

### M7 — 公众号多主题拆分 ✅
- [x] 文章信封构建器（common/article_envelope.py）：统一 URL/标题/时间/正文块/图片封装，自动 article_id
- [x] 主题拆分引擎（common/topic_splitter.py）：6 种信号检测 + 置信度打分 + 切点分割 + 过拆修正
- [x] 单主题安全回退：无信号/低置信度自动 fallback 到原文
- [x] 桥接函数 normalize_topic()：TopicDict → CreditCardItem 字段映射
- [x] Schema 扩 4 字段：is_multi_topic_split / topic_id / topic_split_confidence / topic_split_signals
- [x] step3_merge 集成：content_blocks 存在 → 检测 → 拆分 → 逐 topic 入 batch
- [x] 27 个测试用例覆盖（信号检测/拆分算法/合并/桥接/边界）
- [x] 全量 165 passed，无回归

### M8 — 验收修复与标准化收口 ✅
- [x] 来源字段净化：entity_resolver 过滤"未知公众号"等垃圾 author 值，fallthrough 到银行名
- [x] 分类逻辑统一：删除 news-analyzer/website_scraper 3 处本地分类函数，全部委派 common/classifier
- [x] 结构化内容清洁：_trim_marketing_intro() / _safe_truncate() / structured_clean 填充
- [x] display_fields 重构：移除方法级 self 传递，参数化调用
- [x] 全量 165 passed，无回归

## 架构图

```
用户输入（链接 / 自动抓取）

```
用户输入（链接 / 自动抓取）
    │
    ├── wechat-article-extractor ──→ data/wechat_utf8.json
    │       (requests(主力)+playwright(备选) 抓取公众号文章)
    │
    ├── news-analyzer ──→ data/announcements_YYYYMMDD.json
    │       (requests + BS4 抓银行官网)
    │
    └── _agent.py (or _pipeline.py) ────────────────────────
        │
        ├── 1. 分类/银行识别 ──→ common/utils.py
        ├── 2. 转换为标准格式 ──→ common/schema.py
        ├── 3. 合并批次 ──→ batch_merged.json
        ├── 4. 生成 Word ──→ word-merger/generate_report.py
        ├── 5. 持卡分析 ──→ card-holding-suggestion/analyze_batch.py
        └── 6. 归档 ──→ data/archive/{YYYY}/{MM}/{label}/
```
