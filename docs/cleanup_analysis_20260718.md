# 工程文件清理分析

> 日期：2026-07-18  
> 说明：扫描项目根目录，识别无关/临时/敏感文件，给出清理建议。

---

## 一、敏感文件（应立即处理）

### 1. `apikey.txt`

| 属性 | 值 |
|---|---|
| 大小 | 83 字节 |
| 跟踪状态 | **未跟踪**（untracked） |
| .gitignore | **未覆盖** |
| 风险 | ⚠️ 含 API key，若意外 `git add .` 后会进入仓库 |

**建议**：立即删除，或加入 `.gitignore`。

---

## 二、已跟踪的噪声文件（应取消跟踪 + 加 .gitignore）

### 2. `pipeline_log.txt`

| 属性 | 值 |
|---|---|
| 大小 | 17832 字节 |
| 跟踪状态 | **已跟踪**（git ls-files 确认） |
| .gitignore | 未覆盖 |
| 来源 | 运行日志，每次运行都会产生 |

**建议**：`git rm --cached pipeline_log.txt` 取消跟踪，加入 `.gitignore`。

---

## 三、未跟踪的临时/陈旧文件（应清理或忽略）

### 3. `run_outside_sandbox.py`

| 属性 | 值 |
|---|---|
| 大小 | 344 字节 |
| 跟踪状态 | 未跟踪 |
| 说明 | 看起来是调试用的 sandbox 垫片 |

**建议**：确认无用后删除，或加入 `.gitignore`。

### 4. `weekly_to_wechat.py`

| 属性 | 值 |
|---|---|
| 大小 | 18336 字节 |
| 跟踪状态 | 未跟踪 |
| 说明 | 文件名暗示是 `weekly_report_to_wechat.py` 的前身或旧版 |

**建议**：与 `weekly_report_to_wechat.py` 对比确认功能重叠后删除。

### 5. `信用卡周报自动化 AgentReadme.md` 和 `信用卡周报自动化 AgentReadme_v2.md`

| 属性 | 值 |
|---|---|
| 大小 | 26330 + 28447 字节 |
| 跟踪状态 | 未跟踪 |
| 说明 | 两个版本的 README，v2 覆盖 v1；中文文件名在 Git 中易乱码 |

**建议**：保留 v2，删除 v1。

### 6. `pytest-cache-files-*` 目录（3 个）

| 目录 | 大小 |
|---|---|
| `pytest-cache-files-0apmkesb/` | — |
| `pytest-cache-files-w7uvpk0a/` | — |
| `pytest-cache-files-woa2cfn1/` | — |

| 跟踪状态 | 未跟踪 |
| .gitignore | **未覆盖** |
| 说明 | pytest 运行产生的临时缓存目录 |

**建议**：加入 `.gitignore`（如 `pytest-cache-files-*/`）。

### 7. `doc-qa-reviewer/`

| 属性 | 值 |
|---|---|
| 跟踪状态 | 未跟踪 |
| 说明 | 含 `SKILL.md` 和 `qa_report_0606_sample.md`，看似是旧的 skill 或评估工具 |

**建议**：确认是否还在使用，若已废弃则删除。

---

## 四、输出产物（应加入 .gitignore 或移入 data/）

### 8. `公众号文章整合点评_0714+0717.md_公众号粘贴版.html`

| 属性 | 值 |
|---|---|
| 位置 | 根目录 |
| 跟踪状态 | 未跟踪（但类似文件已被 commit） |
| 说明 | `docx_to_wechat.py` 的输出产物，根目录应保持干净 |

**建议**：输出产物应放入 `data/` 目录，或加入 `.gitignore`。

### 9. `data/公众号文章整合点评_0714+0717.md_公众号粘贴版.html`

已被 commit（上轮提交）。`data/Weekly_Report_2026年7月第3周_公众号粘贴版.html` 同样被 commit。

**建议**：在 `.gitignore` 中加入 `data/*_公众号粘贴版.html`，并在后续 commit 中取消跟踪。

---

## 五、目录结构健康度

| 目录 | 状态 |
|---|---|
| `__pycache__/` | ✅ 已 .gitignore |
| `node_modules/` | ✅ 已 .gitignore |
| `.env` | ✅ 已 .gitignore |
| `.atomcode/` / `.claude/` | ✅ 已 .gitignore |
| `.agents/` | ⚠️ 未在 .gitignore，但可能为 Agent 配置目录 |
| `data/*.json` / `data/*.md` | ✅ 已 .gitignore |
| `data/Weekly_Report_*.docx` | ✅ 已 .gitignore |
| `data/archive/` / `data/review/` / `data/images/` | ✅ 已 .gitignore |
| `data/bm25_cache.pkl` / `data/vector_cache.pkl` | ✅ 已 .gitignore |

---

## 六、清理建议优先级

| 优先级 | 操作 | 文件 |
|---|---|---|
| 🔴 高 | 加 .gitignore + 删除或移动 | `apikey.txt` |
| 🔴 高 | 取消跟踪 + 加 .gitignore | `pipeline_log.txt` |
| 🟡 中 | 删除或加 .gitignore | `pytest-cache-files-*/`（3 个目录） |
| 🟡 中 | 确认后删除 | `weekly_to_wechat.py`、`run_outside_sandbox.py` |
| 🟡 中 | 取消跟踪 + 加 .gitignore | `data/*_公众号粘贴版.html` |
| 🟢 低 | 删除 v1 | `信用卡周报自动化 AgentReadme.md` |
| 🟢 低 | 确认后删除 | `doc-qa-reviewer/` |
| 🟢 低 | 删除根目录产物 | `公众号文章整合点评_0714+0717.md_公众号粘贴版.html` |

---

## 七、.gitignore 补充条目

```gitignore
# Sensitive files
apikey.txt

# Runtime logs
pipeline_log.txt

# pytest temp dirs
pytest-cache-files-*/

# Sandbox / debug launchers
run_outside_sandbox.py

# Old/obsolete scripts
weekly_to_wechat.py

# Output HTML for WeChat
data/*_公众号粘贴版.html
*_公众号粘贴版.html
```