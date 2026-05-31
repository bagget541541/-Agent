---
name: wechat-article-extractor
description: 智能提取微信公众号文章内容并分类整理为结构化文档；当用户需要分析信用卡活动、权益变更、新卡发行或公告类文章时使用
dependency:
  python:
    - requests==2.31.0
    - beautifulsoup4==4.12.2
    - python-docx==1.1.0
    - playwright==1.58.0
    - html2text==2020.1.16
---

# 微信公众号文章智能提取器

## 任务目标
- 本 Skill 用于：从微信公众号文章链接获取内容，智能分析类别并提取关键信息，输出结构化文档
- 能力包含：文章内容获取、类别识别、关键信息提取、Word/Markdown 文档生成
- 触发条件：用户提供微信公众号文章链接，要求提取、整理或转换文档格式

## 前置准备
- 依赖说明：脚本运行所需依赖包
  ```
  requests==2.31.0
  beautifulsoup4==4.12.2
  python-docx==1.1.0
  playwright==1.58.0
  ```
- 首次使用需要安装 playwright 浏览器：
  ```bash
  playwright install chromium
  ```

## 操作步骤

### 标准流程（单篇文章）

1. **获取文章内容**
   - 调用 `scripts/fetch_wechat_article.py` 获取文章纯文本内容和图片
   - 传入参数：公众号文章 URL、`--download-images`（下载图片到本地避免防盗链）、`--images-dir`（图片保存目录）
   - 获取返回的 JSON 格式结果，包含 `text`（文本内容）和 `images`（本地图片路径列表）
   - **重要**：必须使用 `--download-images` 参数下载图片，否则图片会因防盗链无法显示

2. **分析文章类别（务必使用标准分类名）**
   - 阅读 [references/category_guide.md](references/category_guide.md) 了解各类别识别特征
   - 根据文章标题、正文内容判断类别，**使用以下标准化分类名**：
     - **活动**（原"信用卡活动"）
     - **权益变更**
     - **新卡**（原"新发行信用卡"）
     - **公告**（原"公告或其他"）
   - ⚠️ 分类名称必须唯一对应上述标准，否则下游 word-merger 无法识别

3. **提取关键信息并格式化**
   - 提取文章标题：从文章文本中提取或生成简洁标题（10-15字）
   - 根据识别的类别，按对应格式提取信息：
     - **活动**：活动内容、活动时间、适用人群
     - **权益变更**：消息时间、影响范围、变更内容、变更分析
     - **新卡**：卡种、卡亮点、适用人群、来源、详情
     - **公告**：消息内容、点评
   - **表达规范（严格遵循）**：
     - ✅ **精简干练**：每句话不超过20字，能用一句话说清的事情绝不说两句
     - ✅ **短句断句**：多用句号分段，少用"以及""并且""同时"等连词堆砌长句
     - ✅ **直接内容**：直接从文章原文提取，不额外搜索、不补充背景知识
     - ✅ **关键信息优先**：省略修饰性描述，只看数字、时间、产品名、规则等核心事实
     - ✅ 例：~~"本次活动从2026年6月1日开始到2026年12月31日结束，在此期间所有持有农行信用卡的用户都可以享受消费满100元返10元的优惠活动"~~ →
       "满100返10。6.1-12.31。农行信用卡持卡人"
   - **图片处理**：将文章中的核心图片放在相关文字后面，使用 Markdown 格式 `
![图片](本地路径)
` 或 Word 图片格式
   - **重要**：必须使用 `--download-images` 参数下载图片，否则图片会因防盗链显示"未经允许不可引用"
   - **输出格式**：
     ```markdown
     # [简洁标题]

     [类别字段内容]
     ```

4. **输出文档**
   - 调用 `scripts/export_document.py` 生成文档
   - 传入参数：
     - `--content`：格式化内容（包含本地图片路径的Markdown格式）
     - `--format`：输出格式（word 或 md）
     - `--output`：输出文件名（建议使用绝对路径或明确的相对路径）
   - **重要**：输出文件路径必须明确指定，例如 `./output.docx` 或 `/tmp/output.docx`
   - 生成结构化文档供用户下载

### 批量处理流程（多篇文章）

1. **批量获取文章内容**
   - 调用 `scripts/fetch_wechat_article.py` 批量获取多篇文章内容和图片
   - 传入参数：多个公众号文章 URL、`--batch`、`--download-images`（下载图片到本地）
   - 获取返回的 JSON 格式结果，包含每篇文章的 URL、文本内容和本地图片路径列表

2. **逐篇分析类别**
   - 对每篇文章内容分别进行类别判断
   - 根据 [references/category_guide.md](references/category_guide.md) 识别每篇文章的类别

3. **逐篇提取并合并内容**
   - 为每篇文章提取或生成简洁标题（10-15字）
   - 对每篇文章按对应类别格式提取关键信息
   - 将文章中的核心图片放在相关文字后面（Markdown 格式）
   - 将多篇文章内容按顺序合并，每篇文章之间添加分隔线（`---`）
   - 合并格式：
     ```markdown
     # [文章1标题]

     [文章1内容，包含图片]

     ---

     # [文章2标题]

     [文章2内容，包含图片]

     ---

     # [文章3标题]

     [文章3内容，包含图片]
     ```

4. **输出合并文档**
   - 调用 `scripts/export_document.py` 生成单个文档
   - 传入参数：合并后的完整内容（包含Markdown图片语法）、输出格式（word/md）、输出文件名
   - 生成包含所有文章的结构化文档
   - **关键**：图片路径处理
     - `fetch_wechat_article.py` 返回的图片路径是**绝对路径**
     - 在内容中直接使用返回的路径，无需额外转换
     - 示例：`![图片描述](/workspace/projects/images/abc123.jpg)`
   - **Word导出时，图片必须使用Markdown语法 `
![图片描述](绝对路径)
`，否则图片不会插入**

5. **转换为统一标准格式（供下游 skill 消费）**
   - 调用 `scripts/convert_to_standard.py` 将 batch_result.json 转为 CreditCardBatch 标准格式
   - 标准格式包含完整的分类、结构化字段和元数据，供 word-merger 等下游 skill 直接使用
   - 命令示例：
     ```bash
     python scripts/convert_to_standard.py --input batch_result.json --output 标准格式.json --batch-label "2026年5月第2周"
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
           "source": "wechat",
           "category": "活动",
           "bank": "中信银行",
           "title": "中信消费返现活动",
           "url": "https://mp.weixin.qq.com/s/xxx",
           "raw_text": "提取的原文内容...",
           "images": ["D:\\path\\img.jpg"],
           "structured": {
             "活动内容": "15%返现",
             "活动时间": "2027.01.31",
             "适用人群": "持卡人"
           },
           "author": "老胡",
           "publish_time": "2026.05.08",
           "extracted_at": "2025-06-16T12:00:00"
         }
       ]
     }
     ```
   - 将标准格式JSON归档到 `data/archive/` 目录（用于后续知识库积累）

## 资源索引

- 必要脚本：
  - [scripts/fetch_wechat_article.py](scripts/fetch_wechat_article.py) - 获取公众号文章内容和下载图片
  - [scripts/export_document.py](scripts/export_document.py) - 导出 Word/Markdown 文档
- 领域参考：
  - [references/category_guide.md](references/category_guide.md) - 类别识别特征与提取要点

## 注意事项

- ** playwright 安装**：首次使用需要执行 `playwright install chromium` 安装浏览器（约需 200MB 空间）
- **动态页面支持**：脚本支持微信公众号的动态加载页面，会自动选择最佳的提取方法
- **降级机制**：如果 playwright 不可用或失败，脚本会自动降级到 requests 方法（可能无法获取动态内容）
- 仅在需要时读取参考文档，保持上下文简洁
- 提取内容必须精简干练，使用短句，避免大段长句
- 严格按文章原文提取，不进行外部搜索或信息补充
- 输出格式必须符合各类别的固定字段要求
- **图片防盗链处理**：必须使用 `--download-images` 参数下载图片到本地，否则图片会显示"未经允许不可引用"
- **Word图片插入**：Word文档中的图片必须使用Markdown语法 `
![描述](图片路径)
`，脚本会自动识别并插入
- 图片路径建议使用绝对路径以确保正确引用
- 文档命名建议：`{类别}_{日期}` 格式，如 `活动_20250115.md

## 与全流程集成

`_agent.py` Step 1 使用本模块抓取微信文章：

```python
# _agent.py Step 1 调用方式
sys.path.insert(0, "wechat-article-extractor/scripts")
from fetch_wechat_article import process_single

# 抓取单篇文章（requests + Playwright 兜底）
article = process_single(url, download_images=False)

# 转换为标准格式
standard_article = {
    "title": article.get("title", ""),
    "url": url,
    "content_text": article.get("content_text", ""),
    "images": article.get("images", []),
    "source": article.get("source", "unknown"),  # requests 或 playwright
}
```

**优势**：
- requests 优先，Playwright 兜底，兼容动态/静态页面
- 自动降级，无需人工干预
- 搭配 `wechat-rss-monitor` 的 `history.json` 实现去重

## 使用示例

### 示例 1：信用卡活动文章（单篇）
- **功能说明**：提取信用卡优惠活动信息
- **执行方式**：获取文章 → 识别为"活动"类别 → 提取活动内容/时间/人群 → 输出文档
- **输出格式**：
  ```
  # 招商银行消费返现活动

  活动内容：消费满额返现

![活动海报](./images/xxx.jpg)

  活动时间：2025.01.01-2025.03.31
  适用人群：招商银行信用卡持卡人
  ```

### 示例 2：权益变更文章（单篇）
- **功能说明**：提取信用卡权益变更信息
- **执行方式**：获取文章 → 识别为"权益变更"类别 → 提取变更详情和分析 → 输出文档
- **输出格式**：
  ```
  消息时间：2025.01.10
  影响范围：金卡及以上等级用户
  变更内容：机场贵宾厅服务次数调整
  变更分析：权益缩减，成本优化
  ```

### 示例 3：批量处理多篇文章
- **功能说明**：一次处理多篇文章，输出合并文档
- **执行方式**：批量获取多篇文章 → 逐篇分类和提取 → 合并所有内容 → 输出单个文档
- **输出格式**：
  ```
  # 招商银行消费返现活动

  活动内容：消费满额返现
  活动时间：2025.01.01-2025.03.31
  适用人群：招商银行信用卡持卡人

  ---

  # 星座信用卡首发上市

  卡种：招商银行星座信用卡
  卡亮点：首年免年费，生日双倍积分
  适用人群：年轻消费群体
  来源：招商银行
  详情：年刷满6次免次年年费

  ---

  # 系统维护通知

  消息内容：系统将于2025.01.20凌晨进行升级维护，届时部分服务暂停
  点评：常规维护，影响较小，建议提前完成业务办理
  ```

### 示例 4：公告类文章
- **功能说明**：提取公告通知信息
- **执行方式**：获取文章 → 识别为"公告"类别 → 提取消息内容和点评 → 输出文档
- **输出格式**：
  ```
  消息内容：系统将于2025.01.20 02:00-06:00进行升级维护
  点评：常规维护，影响较小，建议提前完成业务办理
  ```
