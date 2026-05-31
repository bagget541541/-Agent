# 流程复盘与优化建议

> 基于 2026-05-30 实际操作（提取微信文章内容并更新 docx）的复盘分析

---

## 一、操作流程回顾

### 任务目标
从两个微信公众号链接提取信用卡资讯内容，补充到《用户上传_信用卡资讯汇总_0530.docx》中。

### 执行步骤
1. 读取现有 docx 文件内容
2. 使用 `wechat-article-extractor` 抓取微信文章
3. 解析文章内容（标题、正文、图片）
4. 编辑 docx XML 添加/更新章节
5. 重新打包 docx 文件

---

## 二、遇到的问题

### 问题 1：微信文章正文提取失败

**现象**：
- `requests` 方法返回空内容（仅标题，无正文）
- 文章内容以图片形式呈现，文本极少

**原因分析**：
- 微信公众号文章依赖 JavaScript 动态渲染
- `requests` 仅获取静态 HTML，无法执行 JS
- 文章设计为图片+SVG 动画，正文内容嵌入图片中

**尝试的解决方案**：
| 方案 | 结果 | 说明 |
|------|------|------|
| requests 抓取 | ❌ 失败 | 仅获取标题，正文为空 |
| Playwright (未安装浏览器) | ❌ 失败 | 需要 `playwright install` |
| Playwright + Chrome | ⚠️ 部分成功 | 能获取标题，但正文仍为空（图片内容） |
| 下载图片分析 | ✅ 成功 | 下载图片后可查看实际内容 |

### 问题 2：Playwright 浏览器未安装

**现象**：
```
Executable doesn't exist at ...chrome-headless-shell.exe
Looks like Playwright was just installed or updated.
Please run: playwright install
```

**影响**：
- 无法使用 Playwright 渲染 JS 页面
- 只能使用 requests 方法（功能受限）

### 问题 3：docx 编辑依赖缺失

**现象**：
```
ModuleNotFoundError: No module named 'defusedxml'
```

**影响**：
- 无法使用 `unpack.py` 解包 docx
- 需要手动安装依赖

### 问题 4：docx 打包验证失败

**现象**：
```
FAILED - Found 1 content type declaration errors
FAILED - Found NEW validation errors: 'gbk' codec can't decode byte
```

**原因分析**：
- XML 中包含中文字符，编码处理有问题
- 缺少图片内容类型声明

**解决方案**：
- 使用 `--validate false` 跳过验证（临时方案）
- 需要修复编码问题（根本方案）

### 问题 5：图片内容无法自动解析

**现象**：
- 微信文章内容以图片形式呈现
- 下载的图片需要人工查看才能理解内容
- 无法自动提取图片中的文字信息

**影响**：
- 需要人工介入解读图片内容
- 无法实现全自动化

---

## 三、各 Skill 优化建议

### 1. wechat-article-extractor（微信文章抓取）

#### 当前问题
- requests 方法无法获取 JS 渲染内容
- 图片内容无法自动解析
- 缺少 OCR 能力

#### 优化建议

| 优先级 | 优化项 | 说明 | 预期效果 |
|--------|--------|------|----------|
| P0 | 集成 Playwright 浏览器安装脚本 | 在 `requirements.txt` 或安装脚本中自动安装浏览器 | 解决 JS 渲染问题 |
| P0 | 增加 OCR 能力 | 集成 Tesseract/PaddleOCR 提取图片文字 | 自动解析图片内容 |
| P1 | 增加 fallback 策略 | requests → Playwright → 图片下载 → 人工标记 | 提高成功率 |
| P1 | 内容类型识别 | 自动判断文章是文本型还是图片型 | 选择最优提取策略 |
| P2 | 广告图片过滤 | 过滤二维码、关注引导等无关图片 | 减少噪声 |
| P2 | 图片内容摘要 | 使用多模态 LLM 生成图片内容摘要 | 自动理解图片 |

#### 具体实现建议

```python
# 新增：图片内容提取模块
class ImageContentExtractor:
    def __init__(self):
        self.ocr = None  # 延迟加载 OCR
    
    def extract_text_from_image(self, image_path: str) -> str:
        """使用 OCR 提取图片中的文字"""
        # 方案1：Tesseract OCR
        # 方案2：PaddleOCR（中文效果更好）
        # 方案3：多模态 LLM（如 GPT-4V）
        pass
    
    def summarize_image(self, image_path: str) -> str:
        """使用多模态 LLM 生成图片内容摘要"""
        pass
```

### 2. news-analyzer（银行公告抓取）

#### 当前问题
- 仅支持官网公告，不支持微信公众号
- 需要手动配置银行列表
- 缺少增量抓取能力

#### 优化建议

| 优先级 | 优化项 | 说明 | 预期效果 |
|--------|--------|------|----------|
| P1 | 支持微信公众号抓取 | 集成 wechat-article-extractor | 统一数据源 |
| P1 | 配置化银行列表 | 从 JSON/YAML 加载银行配置 | 易于维护 |
| P2 | 增量抓取 | 记录上次抓取时间，只抓新内容 | 减少重复工作 |
| P2 | 抓取状态监控 | 记录抓取成功率、失败原因 | 便于排查问题 |

### 3. word-merger（Word 周报生成）

#### 当前问题
- XML 编码处理有问题
- 依赖 `defusedxml` 但未在 requirements.txt 中声明
- 图片插入功能有限

#### 优化建议

| 优先级 | 优化项 | 说明 | 预期效果 |
|--------|--------|------|----------|
| P0 | 修复编码问题 | 使用 UTF-8 编码处理中文字符 | 避免 GBK 错误 |
| P0 | 完善依赖声明 | 在 requirements.txt 中添加 defusedxml | 避免安装失败 |
| P1 | 图片自动插入 | 从文章中提取图片并插入 docx | 丰富报告内容 |
| P1 | 模板化生成 | 支持自定义报告模板 | 灵活调整格式 |
| P2 | 增量更新 | 支持向现有 docx 追加内容 | 避免重复生成 |

#### 具体实现建议

```python
# 修复编码问题
def fix_encoding(content: str) -> str:
    """确保内容使用 UTF-8 编码"""
    if isinstance(content, bytes):
        return content.decode('utf-8')
    return content

# 在 pack.py 中修复
import sys
sys.stdout.reconfigure(encoding='utf-8')
```

### 4. card-holding-suggestion（持卡分析）

#### 当前问题
- 关键词评分规则固定
- LLM 评分依赖外部 API
- 缺少历史数据对比

#### 优化建议

| 优先级 | 优化项 | 说明 | 预期效果 |
|--------|--------|------|----------|
| P1 | 评分规则可配置 | 从配置文件加载评分规则 | 灵活调整 |
| P1 | 历史数据对比 | 结合 RAG 知识库进行趋势分析 | 提供更准确建议 |
| P2 | 评分结果可视化 | 生成评分图表 | 更直观展示 |

### 5. common/（公共层）

#### 当前问题
- 工具函数分散
- 配置管理不统一
- 错误处理不完善

#### 优化建议

| 优先级 | 优化项 | 说明 | 预期效果 |
|--------|--------|------|----------|
| P1 | 统一错误处理 | 定义标准错误类型和处理机制 | 提高稳定性 |
| P1 | 配置中心 | 统一管理所有配置项 | 易于维护 |
| P2 | 日志系统 | 统一日志格式和级别 | 便于调试 |
| P2 | 监控指标 | 记录关键操作的性能指标 | 便于优化 |

---

## 四、项目整体优化建议

### 1. 自动化程度提升

| 当前状态 | 目标状态 | 实现路径 |
|----------|----------|----------|
| 手动提供微信链接 | 自动监控公众号更新 | 接入微信公众号 API 或爬虫 |
| 人工解读图片内容 | 自动提取图片文字 | 集成 OCR + 多模态 LLM |
| 手动编辑 docx | 自动生成完整报告 | 完善 word-merger skill |

### 2. 错误处理增强

```python
# 建议：统一的错误处理框架
class PipelineError(Exception):
    """流水线错误基类"""
    pass

class FetchError(PipelineError):
    """抓取错误"""
    pass

class ParseError(PipelineError):
    """解析错误"""
    pass

class GenerateError(PipelineError):
    """生成错误"""
    pass
```

### 3. 依赖管理优化

```txt
# requirements.txt 需要补充
defusedxml>=0.7.1
playwright>=1.58.0
pytesseract>=0.3.10  # OCR 支持
Pillow>=10.0.0       # 图片处理
```

### 4. 测试覆盖提升

| 测试类型 | 当前覆盖 | 建议覆盖 |
|----------|----------|----------|
| 单元测试 | 低 | 每个 skill 核心函数 |
| 集成测试 | 无 | 端到端流程测试 |
| 性能测试 | 无 | 抓取速度、内存占用 |

---

## 五、工作内容梳理

### 已完成工作
1. ✅ 项目架构设计和文档编写
2. ✅ 微信文章抓取 skill 开发
3. ✅ 银行公告抓取 skill 开发
4. ✅ Word 周报生成 skill 开发
5. ✅ 持卡分析 skill 开发
6. ✅ RAG 知识库系统
7. ✅ 全流程 Agent 编排

### 待优化工作
1. 🔧 Playwright 浏览器自动安装
2. 🔧 OCR 图片文字提取
3. 🔧 docx 编码问题修复
4. 🔧 依赖管理完善
5. 🔧 错误处理增强

### 后续规划
1. 📋 配置中心开发
2. 📋 Web 管理端
3. 📋 定时任务调度
4. 📋 增量抓取机制

---

## 六、总结

本次操作暴露了项目在以下方面的不足：

1. **微信文章抓取**：过度依赖 requests，缺少对 JS 渲染页面的处理能力
2. **图片内容理解**：缺乏 OCR 和多模态能力，无法自动解析图片内容
3. **docx 处理**：编码和依赖管理需要完善
4. **错误处理**：缺少统一的错误处理和降级策略

**核心教训**：
- 微信公众号文章的特殊性（JS 渲染 + 图片为主）需要专门的处理策略
- 自动化流程需要完善的错误处理和降级机制
- 依赖管理需要在项目初期就规范化

**下一步行动**：
1. 优先解决 Playwright 浏览器安装问题
2. 集成 OCR 能力
3. 完善 docx 处理的编码问题
4. 建立统一的错误处理框架
