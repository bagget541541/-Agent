---
AIGC:
    Label: "1"
    ContentProducer: 001191110102MACQD9K64018705
    ProduceID: 7627489099708006675-data_volume/files/基础设定/TOOLS.md
    ReservedCode1: ""
    ContentPropagator: 001191110102MACQD9K64028705
    PropagateID: 582070170304003#1780318456280
    ReservedCode2: ""
---
记录各种工具的使用技巧和注意事项
- **常用工具注意事项：**
  1. extract_content.py：若遇JS渲染、SSL错误或空内容，改用fetch_web
  2. generate_docx.py：从项目根目录运行，避免路径解析失败
  3. wechat-article-extractor：
     - 批量用--batch，--download-images防防盗链；自动降级策略（playwright→requests→图片OCR）
     - 转Word若含图片须用脚本直接生成docx，严禁Markdown中转丢图
     - 微信内嵌页面无法提取时标注说明；非微信URL用fetch_web+download_image
- **交行公告SPA处理：** POST https://creditcard.bankcomm.com/content/api/notice.json获取JSON，参数含tab、pageSize、currentPageNo
- **特殊场景：** 网页为图片且无法提取时，若为广告则搜索第三方文本版
- **sessions_spawn**：明确任务要求，子代理完成后整理结果，路径用computer://
- **search_web**：关键词具体；多查询一次提交；找不到信息建议联系官方
- **word-merger：** 批量读取按类别整合去重；从项目根目录运行；**生成带图片Word必须用`generate_merged_docx.py`**，命令示例：`python3 .skills/skill_word-merger/scripts/generate_merged_docx.py --input merged.json --output 输出.docx`
- **python-docx：** 复杂格式生成（目录/标题/图片/样式）
  - ⚠️ **核心教训：Markdown转Word必丢图片，严禁走Markdown中转！** 必须用脚本直接生成.docx
  - 图片嵌入：用 `run.add_picture(path, width=Inches(4.5))` 插入，居中用 `paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER`
  - 已改造技能：word-merger 新增 `generate_merged_docx.py`（位于 `word-merger/scripts/`），news-analyzer 的 `generate_docx.py` 已支持 images 字段、LLM 点评和中文字体完整设置
  - 技巧：doc.part.rels找"image"；图片宽度4.5英寸
  - ⚠️ **eastAsia 中文字体双设教训：** python-docx 中仅设 `run.font.name = '宋体'` 对中文无效，必须额外通过底层 XML 设置 `w:eastAsia`：
    ```python
    from docx.oxml.ns import qn
    run.font.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    ```
    所有包含中文的 Word 生成脚本都必须做此操作。修复过的文件：`export_document.py`、`generate_report.py`、`merge_docs.py`、`generate_docx.py`
  - ⚠️ **Pillow 不可注释：** `requirements.txt` 中注释掉 Pillow → `from PIL import Image` 抛出 ImportError，报错不直观。Pillow 是图片处理的底层依赖，必须常驻
- **news-analyzer：** 流程：提取内容→提炼要点+点评→生成JSON→生成文档；提取失败改用fetch_web；从项目根目录运行
- **搜索知识库存档查询（rag_query）：** 支持 BM25 / LLM 两种检索模式；在 `merge_docs.py` 中持卡建议环节自动调用补充上下文
  - ⚠️ **路径配置 DRY 教训：** 新模块应优先从 `common.config` 导入已定义的常量（如 `DATA_DIR`、`DEFAULT_IMAGES_DIR`），不应本地重算 `os.path.dirname(__file__)` + `os.path.join`。修复：`src/rag_query.py` 改用 `from common.config import DATA_DIR`
- **硬编码常量去重：** 常量和白名单列表（如银行名、公众号名）应检查有无重复项。`common/llm_review.py` 的 BANKS 列表存在交行、浦发各出现两次的 bug，导致 LLM 审核输出中对同一银行给出重复分析。修复：Python `set()` 去重或人工检查
- **website-monitor：** 监控网站变化，配合fetch_web提取整理
- **docx-js：** JS生成Word，注意中文引号用单引号；目录用TableOfContents，标题用HeadingLevel
- **card-holding-suggestion：** 新卡评估→销卡建议→活动三档；需联网补充竞品信息
- **news-analyzer注意：** JSON字段需为title/url/message/comment（images可选），否则生成内容为空
- **飞书注意事项：**
- **微信图片型文章处理：**
  - 若文章正文为图片无法提取文字，使用`read_image`工具分析图片内容
  - 结合文章标题、公众号信息，通过`search_web`搜索官方渠道或第三方文本版补充信息
  - 若为银行信用卡文章，优先搜索银行官网产品页获取权益详情
- **微信验证拦截处理：**
  - 若微信链接触发"环境异常"验证无法抓取，尝试NO_PROXY参数绕过代理
  - 若仍无法抓取，建议用户提供截图、文字内容或其他可访问链接

---

> 本内容由 Coze AI 生成，请遵循相关法律法规及《人工智能生成合成内容标识办法》使用与传播。
