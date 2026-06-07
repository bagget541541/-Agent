# Phase 1-3 E2E 测试问题报告

## 测试环境
- 数据源：data/batch_merged.json（20 items，2026年6月第1周）
- 评分模式：keyword（无 LLM）
- 流程：Step5 → 富字段回写 → Step4 报告生成 → Step6 建议追加

## 测试结果
- ✅ 流程跑通，无异常
- ✅ 报告生成成功（85KB，2687 段落，23 个 H2 标题）
- ✅ 14/20 条目获得 priority_emoji（70%）
- ✅ 13/20 条目获得 key_benefits（65%）
- ✅ 综合建议段落完整（综合持卡策略 + 涉及银行）
- ✅ 14/23 个 H2 标题含 emoji

## 问题清单

### P0 — 严重问题

#### 问题 1：target_audience 覆盖率 0%
- **现象**：20 条条目无一提取到 target_audience
- **根因**：keyword fallback 的三个正则模式全部未命中
  - structured["适用人群"] 为空或默认值"信用卡持卡人"
  - raw_text 是银行公告正文（"尊敬的客户：为提升客户使用体验..."），不含定位描述
  - keyword fallback 不读 structured 作为 ta 来源
- **修复方向**：
  1. keyword fallback 增加从 structured["适用人群"] 读取（当值非"信用卡持卡人"时）
  2. 对新卡类，从 title 中提取银行名+卡名作为 fallback target_audience

#### 问题 2：highlight_summary 覆盖率 0%
- **现象**：enrichment 后 highlight_summary 仍为空
- **根因**：analysis 的 item_data 中不包含 highlight_summary 字段。enrichment 代码只从 evaluation 中读取富字段。generate_display_fields() 的增强逻辑依赖已有的 highlight_summary 作为基础，当基础为空时只用 key_benefits 生成。
- **影响**：目录条目的摘要显示为空
- **修复方向**：enrichment 循环中，当 highlight_summary 为空时，从 key_benefits 或 title 生成一个 fallback 摘要

#### 问题 3："其他"类 6 条垃圾数据未过滤
- **现象**：6 条"其他"类条目是网页导航文本（"银行卡\n贵宾\n加入收藏\n兴业银行信用卡..."）
- **根因**：Step 3 合并时未过滤 raw_text 含大量导航噪音的条目
- **影响**：报告中出现无意义条目，拉低整体质量
- **修复方向**：Step 3 合并时增加噪音过滤

### P1 — 中等问题

#### 问题 4：fee_assessment 覆盖率仅 10%
- **现象**：20 条中仅 2 条提取到 fee_assessment
- **根因**：10 条含"年费"关键词，但正则匹配条件过严
- **修复方向**：从 structured["详情"] 中提取年费信息；增加"按次刷免"/"消费满N次免"等模式

#### 问题 5：评分分布过于集中
- **现象**：high(>=7) 仅 1 条，mid(4-6) 19 条，low(<=3) 0 条
- **根因**：keyword scorer 基础分 5.0，正向关键词每个 +1.0，但 raw_text 中关键词密度低
- **修复方向**：调整 keyword scorer 的基础分和关键词权重，或对 structured 字段中的关键词也计分

#### 问题 6：worth_applying 始终为空
- **现象**：keyword 模式下 worth_applying 为空列表
- **根因**：按设计，worth_applying 需要 LLM 判断，keyword 模式不生成
- **修复方向**：对 keyword 模式，基于 score 和 category 生成简单的 worth_applying

### P2 — 轻微问题

#### 问题 7：同类卡对比未触发
- **现象**：报告中无"同类卡对比"段落
- **根因**：当前数据集不满足"同场景 >=2 张高分卡"的触发条件
- **影响**：逻辑正确，数据集不触发

#### 问题 8：跨期趋势分析依赖归档数据
- **现象**：趋势分析加载历史归档，但当前归档数据有限（4 期）

#### 问题 9：Step 6 "推荐申请"段落格式
- **现象**：当 all_recommended 为空时，不输出"当前最值得申请的卡"标题
- **影响**：当前数据集可以触发

## 修复优先级建议

| 优先级 | 问题 | 预计工作量 |
|--------|------|-----------|
| P0-1 | target_audience 从 structured 读取 | 小（5 行代码） |
| P0-2 | highlight_summary fallback 生成 | 小（10 行代码） |
| P0-3 | "其他"类噪音过滤 | 中（Step 3 增加过滤逻辑） |
| P1-4 | fee_assessment 增强 | 小（增加模式） |
| P1-5 | 评分区分度优化 | 中（调整 scorer 权重） |
| P1-6 | keyword worth_applying 生成 | 小（基于 score 生成） |