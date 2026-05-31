---
name: word-merger
description: 从标准JSON生成格式化信用卡周报Word文档(.docx)；当用户需要将上游标准数据转成可交付的Word周报或合并多篇资讯成报告时使用
dependency:
  python:
    - python-docx>=0.8.11
---

# Word文档合并器 — 信用卡周报生成

## 任务目标
- **核心价值**：将上游 skill 产出的**标准 JSON 批次数据**（CreditCardBatch 格式）转化为精美的 Word 文档 (.docx)，用于周报输出 / 交付物归档
- **能力范围**：
  - 读取标准 JSON → 自动排版生成 `.docx`
  - 按分类展示（新卡 / 权益变更 / 活动 / 公告），自动生成封面、亮点摘要、目录区
  - 嵌入集中存储的图片（`data/images/{item_id}/`）
  - 保留每条资讯的链接、结构化字段、全文摘要
- **触发条件**：用户需要"生成周报"、"导出Word"、"制作交付物"、"合并为报告"

## 数据流

```
上游 skill（news-analyzer / wechat-article-extractor）
  │  输出标准 JSON（含 data/images/ 图片路径）
  ▼
word-merger / scripts / generate_report.py
  │  读取标准 JSON → 格式化 Word 文档
  ▼
信用卡周报_{日期}.docx  ← 最终交付物
```

## 前置准备
```bash
pip install python-docx>=0.8.11
```

## 操作步骤

### 1. 调用脚本生成 Word 周报

从上游标准 JSON 直接生成：

```bash
python word-merger/scripts/generate_report.py \
  --input data/batch_标准格式.json \
  --output 信用卡周报_2026年5月第2周.docx
```

**脚本参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--input` | 是 | 上游输出的标准格式 JSON 文件路径 |
| `--output` | 否 | 输出 .docx 路径（默认自动生成 `信用卡周报_{日期}.docx`） |
| `--no-images` | 否 | 添加则跳过图片嵌入（文档体积更小） |
| `--title` | 否 | 自定义文档标题（默认"信用卡周报"） |

### 2. 周报结构说明

生成的 Word 文档包含以下章节：

| 章节 | 内容 |
|------|------|
| **封面区** | 标题 + 批次标签 + 生成时间 |
| **内容概览** | 各分类条目统计（新卡: N条 / 权益变更: N条 / 活动: N条 / 公告: N条） |
| **本期亮点** | 每条资讯的一句话亮点摘要（自动从结构化字段提取） |
| **正文** | 按「新卡→权益变更→活动→公告」顺序逐条展示，每类包括：银行标头、标题、原文链接、结构化信息表、全文摘要、嵌入式图片 |
| **尾页** | 自动生成脚注 |

### 3. 嵌入图片机制

- 从标准 JSON 的 `images` 字段读取绝对路径（`data/images/{item_id}/xxx.jpg`）
- 自动检测路径是否存在，存在则嵌入到对应条目下方
- 图片宽度统一为 13cm，保持文档整洁
- 图片加载失败时显示友好提示，不中断生成

### 4. 仍可用的旧版功能（独立于新流）

读取已有 Word 文档并提取结构化内容（用于兼容旧数据）：

```bash
python word-merger/scripts/read_word_docs.py \
  --input-files "旧周报.docx" \
  --output content.json
```

## 资源索引

| 脚本 | 路径 | 用途 |
|------|------|------|
| **generate_report.py** | `scripts/generate_report.py` | **主脚本** — 标准 JSON → Word `.docx` |
| read_word_docs.py | `scripts/read_word_docs.py` | 旧版 — Word → JSON（兼容旧数据） |

## 使用示例

### 标准流程（推荐）

```bash
# 1. 上游产生标准 JSON
# 2. 生成周报
python word-merger/scripts/generate_report.py \
  --input data/batch_20260516_标准格式.json \
  --output 周报_2026年5月第2周.docx \
  --title "2026年5月第2周信用卡周报"
```

### 带图片的周报

```bash
python word-merger/scripts/generate_report.py \
  --input data/batch_with_images.json \
  --output 周报_带图版.docx
# 图片自动从 data/images/{item_id}/ 嵌入
```

### 纯文字版（快速出稿）

```bash
python word-merger/scripts/generate_report.py \
  --input data/batch.json \
  --output 周报_纯文字版.docx \
  --no-images
```

## 注意事项
- **输入格式**：仅接受标准 CreditCardBatch JSON（`schema_version` + `items` 数组）
- **图片路径**：必须是本地绝对路径（由上游通过 `centralize_images()` 产生的路径）
- **依赖**：确保 `python-docx` 已安装（`pip install python-docx`）
- **大型周报**：超过 50 条资讯 + 大量图片时，生成时间可能较长（建议 `--no-images` 单独出图版）
- **字体**：默认使用 `Microsoft YaHei`，Linux/macOS 会回退系统字体
