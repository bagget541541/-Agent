---
name: news-analyzer
description: 批量提取公告/新闻链接核心内容并生成分析报告；当用户需要分析多个公告、整理新闻要点或快速了解多个链接核心内容时使用
dependency:
  python:
    - requests>=2.28.0
    - beautifulsoup4>=4.12.0
    - readability-lxml>=0.8.1
    - python-docx>=1.1.0
---

# News Analyzer

## 任务目标
- 本 Skill 用于：批量从多个公告/新闻链接提取正文内容，智能提取核心要点，输出为Word文档 + 标准统一格式JSON
- 能力包含：网页内容提取、关键信息提炼、Word文档生成、统一数据格式输出
- 触发条件：用户需要分析多个公告、整理新闻要点或快速了解多个链接核心内容

## 前置准备
- 依赖说明：脚本所需的依赖包
  ```
  requests>=2.28.0
  beautifulsoup4>=4.12.0
  readability-lxml>=0.8.1
  python-docx>=1.1.0
  ```

## 操作步骤
- 标准流程：
  1. **提取网页内容**
     - 调用 `scripts/extract_content.py` 处理用户提供的多个链接
     - 脚本会提取每个网页的标题和正文内容，返回JSON格式数据
     - 命令示例：`python scripts/extract_content.py --urls "url1,url2,url3" --pretty`
     - 银行网站需加 `--insecure` 参数（支持 legacy TLS renegotiation）
     - 可选参数：`--concurrency 4`（并发数）、`--pretty`（美化输出）

  2. **提取核心要点**
     - 智能体分析每个公告/新闻的正文内容
     - 识别并提取关键信息：时间、事件、影响、数据等
     - 提炼出2-5条核心要点，每点控制在50字以内

  3. **生成Word文档**
    - 智能体将所有公告的分析结果整理为以下格式的JSON数据：
      ```json
      [
        {
          "title": "公告标题",
          "url": "公告URL",
          "message": "消息内容：核心要点列表"
        }
      ]
      ```
    - 将JSON数据保存为临时文件（如 `analysis_data.json`）
    - 调用 `scripts/generate_docx.py` 生成Word文档
    - 命令示例：`python scripts/generate_docx.py --input analysis_data.json --output 公告分析报告.docx`

  4. **转换为统一标准格式（供下游 skill 消费）**
    - 调用 `scripts/convert_to_standard.py` 将分析结果转为标准统一格式
    - 标准格式包含完整的分类、结构化字段和元数据，供 word-merger 等下游 skill 直接使用
    - 命令示例：
      ```bash
      python scripts/convert_to_standard.py --input analysis_data.json --output 标准格式.json --batch-label "2026年5月第2周"
      ```
    - 输出格式说明（CreditCardBatch）：
      ```json
      {
        "schema_version": "1.0",
        "generated_at": "2025-06-16T12:00:00",
        "batch_label": "2026年5月第2周",
        "total": 5,
        "items": [
          {
            "item_id": "a1b2c3d4e5f6",
            "source": "website",
            "category": "公告",
            "bank": "中信银行",
            "title": "公告标题",
            "url": "公告URL",
            "raw_text": "提取的原文内容...",
            "images": [],
            "structured": {
              "消息内容": "核心要点列表",
              "点评": "影响分析"
            },
            "author": "",
            "publish_time": "",
            "extracted_at": "2025-06-16T12:00:00"
          }
        ]
      }
      ```

  5. **交付结果**
    - 返回生成的Word文档给用户
    - 将标准格式JSON归档到 `data/archive/` 目录（用于后续知识库积累）
    - 提供简要总结：处理了X个公告，生成了包含X条分析的报告

## 资源索引
- 必要脚本：
  - [scripts/extract_content.py](scripts/extract_content.py)（用途：提取网页标题和正文内容，支持批量并发处理、银行SSL兼容）
  - [scripts/generate_docx.py](scripts/generate_docx.py)（用途：生成格式化的Word分析报告）
  - [scripts/convert_to_standard.py](scripts/convert_to_standard.py)（新增）用途：将分析结果转为 CreditCardBatch 标准统一格式，供 word-merger 等下游 skill 消费
- 公共模块：
  - [common/schema.py](../common/schema.py)（用途：统一数据契约 CreditCardItem / CreditCardBatch 定义）
  - [common/config.py](../common/config.py)（用途：项目路径配置）
  - [common/utils.py](../common/utils.py)（用途：工具函数如银行名提取）

## 注意事项
- 提取网页内容时，某些网站可能因反爬机制导致提取失败，智能体需跳过此类链接并提示用户
- 银行网站（建行、中信、交行等）需使用 `--insecure` 参数，否则可能因 TLS 问题抓取失败
- 核心要点应客观准确，每点不超过50字
- Word文档命名建议使用有意义的名称，如"公告分析报告-YYYYMMDD.docx"
- 如链接数量较多（超过10个），建议智能体询问用户是否需要分批处理
- 脚本输出到 stdout（JSON），日志/警告输出到 stderr，不影响数据解析

## 使用示例

### 示例1：分析多个公告链接并生成报告
**功能说明**：从多个公告链接提取核心内容，生成Word报告
**执行方式**：脚本提取 + 智能体分析 + Word生成
**关键参数**：多个URL（逗号分隔）

```bash
# 步骤1：提取网页内容（银行网站加 --insecure）
python scripts/extract_content.py --urls "https://creditcard.ecitic.com/xxx,https://ae2.ccb.com/xxx" --insecure --pretty

# 步骤2：智能体处理
# 智能体分析内容，提取要点，整理为JSON格式：
# [
#   {
#     "title": "公告标题",
#     "url": "https://creditcard.ecitic.com/xxx",
#     "message": "消息内容：1. 核心要点1；2. 核心要点2"
#   }
# ]
# 保存为 analysis_data.json

# 步骤3：生成Word文档
python scripts/generate_docx.py --input analysis_data.json --output 公告分析报告.docx

# 步骤4（可选）：转换为统一标准格式，供下游 skill 消费
python scripts/convert_to_standard.py --input analysis_data.json --output 标准格式.json --batch-label "2026年5月第2周"
```

### 示例2：行业新闻快讯整理
**功能说明**：快速整理行业内多条新闻的核心要点，生成Word报告
**执行方式**：脚本提取 + 智能体分析 + Word生成
**指导要点**：聚焦行业趋势和影响

```bash
python scripts/extract_content.py --urls "url1,url2,url3,url4" --pretty
# 智能体提取要点，关注行业整体趋势
# 将结果整理为JSON格式并保存为 analysis_data.json
python scripts/generate_docx.py --input analysis_data.json --output 行业快讯-20260517.docx
```
