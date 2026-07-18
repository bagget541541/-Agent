# 根目录 py 脚本重构分析：移入 src/

> 日期：2026-07-18

---

## 当前根目录 py 脚本一览

| 文件 | 行数 | 角色 | 是否已有 src/ 对应 |
|---|---|---|---|
| `_agent.py` | 18 | stub → `src/agent.main()` | ✅ 已有 |
| `rag_query.py` | 18 | stub → `src/rag_query` | ✅ 已有 |
| `run_pipeline.py` | 18 | stub → `src/agent.main()` | ✅ 已有 |
| `docx_to_wechat.py` | 413 | 独立工具脚本 | ❌ |
| `weekly_report_to_wechat.py` | 644 | 独立工具脚本 | ❌ |
| `md_to_wechat.py` | 245 | 独立工具脚本 | ❌ |
| `md_merge.py` | 188 | 独立工具脚本 | ❌ |
| `merge_docs.py` | 1174 | 独立工具脚本 | ❌ |

---

## 三类脚本分析

### 第一类：已是 stub（保持不动）

`_agent.py`、`rag_query.py`、`run_pipeline.py` 已经是根级垫片，3 行导入 + 1 行调用，委派到 `src/` 下的同名模块。**保持不动**。

### 第二类：可移入 src/，无外部依赖冲突

`docx_to_wechat.py`、`weekly_report_to_wechat.py`、`md_to_wechat.py`、`md_merge.py`、`merge_docs.py`

**共同特征**：
- 不引用 `src/` 下的任何模块（纯标准库 + 第三方 pip 包）
- 自包含 `if __name__ == "__main__": main()` 入口
- 被 `run.bat` 按文件名直接调用（`python -X utf8 xxx.py`）

**移入 src/ 后的好处**：
- 统一项目入口，根目录只留 `_agent.py` 等 3 个 stub
- 模块间依赖路径明确（`src/docx_to_wechat.py` → `from src.xxx import xxx`）
- 便于 `pytest` 测试发现（`tests/test_src/`）

### 第三类：需注意的依赖问题

`weekly_report_to_wechat.py` 第 28 行：
```python
from docx_to_wechat import parse_docx, _read_rels, esc, inline, color_for
```
移入 `src/` 后需改为：
```python
from src.docx_to_wechat import parse_docx, _read_rels, esc, inline, color_for
```

---

## 重构方案

### 方案 A：移入 + 新建根级 stub（推荐）

为每个移入 `src/` 的脚本在根目录创建 stub（同 `_agent.py` 模式）：

```
src/
  docx_to_wechat.py
  weekly_report_to_wechat.py
  md_to_wechat.py
  md_merge.py
  merge_docs.py
  agent.py
  rag_query.py
```

根目录新建 stub 文件：

```python
# docx_to_wechat.py（根目录 stub）
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from src.docx_to_wechat import main

if __name__ == "__main__":
    main()
```

### 方案 B：直接移入，run.bat 改路径

`run.bat` 所有调用改为 `python -X utf8 src\xxx.py`，根目录不留 stub。

**缺点**：`run.bat` 修改量大，且直接暴露 `src/` 内部路径给用户。

### 方案 C：保持现状，不动

**缺点**：根目录继续膨胀，模块间依赖路径不统一。

---

## 推荐方案 A 的原因

1. **向后兼容**：`run.bat` 无需修改，现有调用路径不变
2. **统一模式**：与 `_agent.py` / `rag_query.py` / `run_pipeline.py` 的 stub 模式一致
3. **渐进迁移**：可以在不影响现有使用的前提下逐个移入
4. **测试友好**：`pytest` run 时自动发现 `src/` 下的模块

---

## 操作步骤

1. 将 5 个脚本 `cp` 到 `src/` 下
2. 修改 `weekly_report_to_wechat.py` 的 import：`from docx_to_wechat` → `from src.docx_to_wechat`
3. 根目录原文件替换为 stub（同 `_agent.py` 模板）
4. 验证：`python -X utf8 docx_to_wechat.py "..."` 仍能正常调用
5. 提交 git

---

## 暂不处理

- `scripts/` 下的辅助脚本（`show_last_run.py`、`validate_batch.py` 等）——与 `src/` 职责不同，保持原位
- `run.bat` / `run_grok.bat` / `run_groq.bat` / `run_openrouter.bat` —— 非 py 脚本，保持原位