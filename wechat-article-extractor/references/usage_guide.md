# 批量提取与Word导出使用指南

## 完整流程

### 步骤 1：批量获取文章内容（包含图片）

```bash
python3 scripts/fetch_wechat_article.py \
  --batch \
  --download-images \
  --images-dir ./images \
  https://mp.weixin.qq.com/s/url1 \
  https://mp.weixin.qq.com/s/url2 \
  https://mp.weixin.qq.com/s/url3
```

**返回格式**（JSON）：
```json
{
  "https://mp.weixin.qq.com/s/url1": {
    "text": "文章1的文本内容...",
    "images": ["/workspace/projects/images/abc123.jpg"]
  },
  "https://mp.weixin.qq.com/s/url2": {
    "text": "文章2的文本内容...",
    "images": ["/workspace/projects/images/def456.jpg", "/workspace/projects/images/ghi789.jpg"]
  }
}
```

**关键点**：
- `images` 数组中的路径是**绝对路径**（由 `os.path.join` 生成）
- 如果下载失败，图片数组可能为空 `[]`

---

### 步骤 2：处理每篇文章（分类 + 格式化）

对每篇文章进行：
1. **类别识别**：根据 content 判断属于哪种类型
2. **标题提取**：从文本中提取或生成简洁标题
3. **关键信息提取**：按类别格式提取字段

**生成内容格式**（Markdown）：
```markdown
# 文章1标题

![图片1](/workspace/projects/images/abc123.jpg)

消息时间：2025.01.15
影响范围：所有持卡人
变更内容：具体变更内容...

---

# 文章2标题

![图片2](/workspace/projects/images/def456.jpg)
![图片3](/workspace/projects/images/ghi789.jpg)

活动时间：2025.01.10 - 2025.03.31
适用人群：新开卡用户

---
```

**关键点**：
- 图片路径必须**直接使用 `fetch_wechat_article.py` 返回的绝对路径**
- 图片使用 Markdown 语法：`
![描述](路径)
`
- 多个图片按顺序排列

---

### 步骤 3：导出Word文档

```bash
python3 scripts/export_document.py \
  --format word \
  --output ./output.docx \
  --content "# 文章1标题

![图片1](/workspace/projects/images/abc123.jpg)

消息时间：2025.01.15

---
"
```

**关键点**：
- `--content` 参数包含完整的 Markdown 内容（包含图片语法）
- 图片路径必须是**绝对路径**或相对于输出文件的路径

---

## 常见问题排查

### 问题 1：Word文档中有文字但没有图片

**可能原因**：

1. **图片路径错误**
   - 检查：图片路径是否为绝对路径
   - 验证：`ls -l /workspace/projects/images/abc123.jpg`

2. **图片文件不存在**
   - 检查：图片下载是否成功
   - 验证：查看 `fetch_wechat_article.py` 的 stderr 输出
   - 解决：重新运行提取命令

3. **图片格式不支持**
   - 支持格式：jpg, jpeg, png, gif
   - 验证：使用 `file` 命令检查图片格式

4. **Markdown语法错误**
   - 错误：`![图片](路径)` 后面缺少空格或换行
   - 正确：`![图片](/path/to/img.jpg)\n\n`

**调试方法**：
```bash
# 查看 export_document.py 的警告信息
python3 scripts/export_document.py --format word --output output.docx --content "..." 2>&1 | grep "警告"
```

---

### 问题 2：图片路径显示为 "[图片不存在]"

**原因**：`export_document.py` 无法找到图片文件

**排查步骤**：
1. 检查图片路径是否正确
2. 确认图片文件存在
3. 尝试使用绝对路径

**示例**：
```bash
# 错误（相对路径）
![图片](./images/abc123.jpg)

# 正确（绝对路径）
![图片](/workspace/projects/images/abc123.jpg)
```

---

### 问题 3：图片下载失败

**可能原因**：
1. 网络连接问题
2. 图片URL防盗链
3. 磁盘空间不足

**解决方案**：
1. 检查网络连接
2. 使用 `--download-images` 参数下载到本地
3. 查看下载失败信息（stderr）

---

## 完整示例

### 示例代码

```bash
# 1. 批量获取文章
python3 scripts/fetch_wechat_article.py \
  --batch \
  --download-images \
  --images-dir ./article_images \
  https://mp.weixin.qq.com/s/example1 \
  https://mp.weixin.qq.com/s/example2 \
  > batch_result.json

# 2. 查看结果
cat batch_result.json | jq

# 3. 手动处理（或由智能体自动处理）
# 假设生成的内容保存在 content.md 中

# 4. 导出Word
python3 scripts/export_document.py \
  --format word \
  --output final.docx \
  --content "$(cat content.md)"
```

---

## 验证检查清单

- [ ] 图片下载成功（`ls ./article_images/` 有文件）
- [ ] 图片路径为绝对路径（以 `/` 开头）
- [ ] Markdown语法正确（`
![描述](路径)
`）
- [ ] 图片文件存在（`file /path/to/img.jpg`）
- [ ] Word文档大小合理（包含图片的文档应 > 100KB）
- [ ] Word文档中图片居中显示
