"""
文档输出验收模块 — doc-qa-reviewer

对 pipeline 生成的 Word 周报做五类质量检查，输出 Markdown 验收报告。
集成位置：Step 6（追加建议）之后、Step 7（归档）之前。

检查维度：
  A — 标题与格式一致性
  B — 图文匹配
  C — 逻辑一致性
  D — 废话识别
  E — 读者视角（仅对外/混合型文档）
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from common.config import DATA_DIR

_EXTERNAL_KEYWORDS = [
    "公众号", "产品说明", "用户手册", "销售", "客户",
    "对外", "宣传", "推广",
]
_INTERNAL_KEYWORDS = [
    "详设", "接口", "架构", "标书", "测试报告", "技术方案",
]


def _detect_doc_type(filename: str, full_text: str) -> tuple[str, str]:
    """判断文档类型，返回 (类型名, 判断依据)。"""
    combined = f"{filename}\n{full_text[:2000]}"
    ext_hits = sum(1 for kw in _EXTERNAL_KEYWORDS if kw in combined)
    int_hits = sum(1 for kw in _INTERNAL_KEYWORDS if kw in combined)
    if ext_hits >= 2:
        return "对外文档", "包含对外传播关键词"
    if ext_hits >= 1 and int_hits == 0:
        return "混合型", "面向非技术干系人的写法，含对外关键词"
    if int_hits >= 2:
        return "纯内部技术文档", "包含技术文档关键词"
    return "混合型", "内部用但写法接近对外（信用卡资讯汇总）"


def _extract_docx_text(docx_path: str) -> str:
    """从 .docx 提取全文，保留标题层级标记。"""
    from docx import Document

    doc = Document(docx_path)
    lines: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue
        style_name = (para.style.name or "").lower()
        if "heading 1" in style_name:
            lines.append(f"# {text}")
        elif "heading 2" in style_name:
            lines.append(f"## {text}")
        elif "heading 3" in style_name:
            lines.append(f"### {text}")
        else:
            lines.append(text)

    img_count = 0
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            img_count += 1

    full_text = "\n".join(lines)
    if img_count > 0:
        full_text += f"\n\n<!-- 文档内嵌图片 {img_count} 张 -->"
    else:
        full_text += "\n\n<!-- 文档未含图片 -->"
    return full_text


_QA_SYSTEM_PROMPT = """\
你是一位专业的文档质量审查员。请对以下文档做五类质量检查，严格以 JSON 格式输出结果。

检查维度：
A — 标题与格式一致性：层级编号、字体加粗规律、标题末尾标点、平行结构、缺失标题
B — 图文匹配：引用与图位置、图题缺失/多余、图题与内容匹配、图编号连续性、文字描述与图矛盾
C — 逻辑一致性：术语统一、数字/参数前后矛盾、结论与正文脱节、章节间衔接、时态/状态矛盾
D — 废话识别：空洞背景铺垫、重复前文、过度解释、无实质过渡句、罗列不带结论的清单
E — 读者视角（仅对外/混合型）：主语错位、缺"对我有什么用"、术语未解释、行动指引模糊、负面信息回避、信息优先级失序

规则：
- 每条问题须包含 issue_id（如"A01"）、location（章节/段落关键词）、description、suggestion
- 找到几条写几条，不凑数，不遗漏显眼问题
- 修改建议具体可操作
- 若某类无问题，返回空列表
- 若文档无图，B 类返回空列表并在 notes 中说明
- 若文档类型为纯内部技术文档，E 类跳过并在 notes 中说明
- 只输出 JSON，不要其他文字"""


def _build_qa_user_prompt(full_text: str, doc_type: str) -> str:
    """构建 QA 审查的 user prompt。"""
    if len(full_text) > 60000:
        full_text = full_text[:60000] + "\n\n[... 文档内容过长，已截断 ...]"
    return (
        f"文档类型：{doc_type}\n\n"
        f"以下是待审查文档内容（Markdown 格式，标题用 # 标记）：\n\n"
        f"```\n{full_text}\n```\n\n"
        f"请输出 JSON，结构如下：\n"
        f'{{"A": [...], "B": [...], "C": [...], "D": [...], "E": [...], "notes": "..."}}\n'
        f"每个列表元素包含: issue_id, location, description, suggestion"
    )


def _call_llm_for_qa(system_prompt: str, user_prompt: str) -> str:
    """调用 LLM 进行 QA 审查。"""
    from common.llm_client import call_llm_simple_str
    return call_llm_simple_str(
        system_prompt, user_prompt, max_tokens=8192, timeout=180,
    )


def _parse_qa_response(raw: str) -> dict:
    """从 LLM 响应中提取 QA JSON 结果。"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


_CHECK_LABELS = {
    "A": "标题与格式一致性", "B": "图文匹配", "C": "逻辑一致性",
    "D": "废话", "E": "读者视角",
}
_CHECK_TAG = {
    "A": "格式", "B": "图文", "C": "逻辑", "D": "废话", "E": "视角",
}


def _generate_report_md(
    filename: str, doc_type: str, doc_type_reason: str, result: dict,
) -> str:
    """从 QA 结果生成 Markdown 验收报告。"""
    now = datetime.now().strftime("%Y-%m-%d")
    counts = {}
    for key in ("A", "B", "C", "D", "E"):
        issues = result.get(key) or []
        counts[key] = len(issues) if isinstance(issues, list) else 0
    total = sum(counts.values())

    sorted_keys = sorted(
        [k for k in ("A", "B", "C", "D", "E") if counts[k] > 0],
        key=lambda k: counts[k], reverse=True,
    )
    zero_keys = [k for k in ("A", "B", "C", "D", "E") if counts[k] == 0]
    e_note = "（跳过：纯内部技术文档）" if doc_type == "纯内部技术文档" else ""
    notes = result.get("notes", "")

    lines: list[str] = []
    lines.append("# 文档验收报告\n")
    lines.append(f"**文档**：{filename}  ")
    lines.append(f"**验收日期**：{now}  ")
    lines.append(f"**文档类型**：{doc_type}（{doc_type_reason}）  ")
    count_str = " | ".join(
        f"{k}类 {counts[k]} 条" if not (k == "E" and e_note) else f"E类 {e_note}"
        for k in ("A", "B", "C", "D", "E")
    )
    lines.append(f"**问题总数**：{count_str} | 合计 {total} 条\n")
    lines.append("---\n")

    lines.append("## 总体评估\n")
    if total == 0:
        lines.append("文档质量良好，未发现明显问题。\n")
    else:
        top_type = sorted_keys[0] if sorted_keys else "A"
        lines.append(
            f"共发现 {total} 条问题，"
            f"其中 {_CHECK_LABELS[top_type]}类最多（{counts[top_type]} 条）。"
        )
        if notes:
            lines.append(f"\n{notes}\n")
    lines.append("---\n")

    for key in sorted_keys + zero_keys:
        label = _CHECK_LABELS[key]
        count = counts[key]
        tag = _CHECK_TAG[key]
        if key == "E" and e_note:
            lines.append(f"## {key} {label}（{e_note}）\n")
            continue
        lines.append(f"## {key} {label}（{count} 条）\n")
        if count == 0:
            if key == "B":
                lines.append("文档未含图片，跳过图文检查。\n")
            else:
                lines.append("未发现问题。\n")
            continue
        issues = result.get(key) or []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_id = issue.get("issue_id", "??")
            location = issue.get("location", "未知位置")
            description = issue.get("description", "")
            suggestion = issue.get("suggestion", "")
            lines.append(f"### [{tag}-{issue_id}] {location}\n")
            lines.append(f"**问题**：{description}  ")
            lines.append(f"**建议**：{suggestion}\n")

    all_issues: list[tuple[str, dict]] = []
    for key in ("A", "B", "C", "D", "E"):
        issues = result.get(key) or []
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if isinstance(issue, dict):
                all_issues.append((key, issue))

    if all_issues:
        lines.append("---\n")
        lines.append("## 优先修改清单\n")
        lines.append("按修改价值排序，前 5 条最值得先改：\n")
        priority = {"C": 0, "A": 1, "D": 2, "E": 3, "B": 4}
        all_issues.sort(key=lambda x: priority.get(x[0], 5))
        for i, (key, issue) in enumerate(all_issues[:5], 1):
            issue_id = issue.get("issue_id", "??")
            desc = issue.get("description", "")[:60]
            lines.append(f"{i}. [{_CHECK_TAG[key]}-{issue_id}] {desc}")
        lines.append("")

    return "\n".join(lines)


def run_qa_review(docx_path: str) -> str:
    """对 Word 文档执行五类质量检查，生成验收报告。

    Args:
        docx_path: 待检查的 .docx 文件路径

    Returns:
        str: 验收报告文件路径（失败时返回空字符串）
    """
    print("\n" + "=" * 60)
    print("Step 6.5: 文档 QA 验收")
    print("=" * 60)

    if not docx_path or not os.path.isfile(docx_path):
        print("  [跳过] 报告文件不存在")
        return ""

    filename = os.path.basename(docx_path)
    print(f"  检查文档: {filename}")

    try:
        full_text = _extract_docx_text(docx_path)
        print(f"  提取文本: {len(full_text)} 字符")
    except Exception as e:
        print(f"  [错误] 文本提取失败: {e}")
        return ""

    if len(full_text.strip()) < 100:
        print("  [跳过] 文档内容过短，无法有效审查")
        return ""

    doc_type, doc_type_reason = _detect_doc_type(filename, full_text)
    print(f"  文档类型: {doc_type}")

    print("  LLM 审查中...")
    try:
        raw = _call_llm_for_qa(_QA_SYSTEM_PROMPT, _build_qa_user_prompt(full_text, doc_type))
    except Exception as e:
        print(f"  [错误] LLM 调用失败: {e}")
        return ""

    if not raw:
        print("  [错误] LLM 返回为空")
        return ""

    result = _parse_qa_response(raw)
    if not result:
        print("  [警告] 无法解析 LLM 响应为 JSON，保存原始输出")
        result = {"A": [], "B": [], "C": [], "D": [], "E": [], "notes": raw[:500]}

    report_md = _generate_report_md(filename, doc_type, doc_type_reason, result)

    review_dir = DATA_DIR / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    today_tag = datetime.now().strftime("%m%d")
    report_path = review_dir / f"qa_report_{today_tag}.md"
    if report_path.exists():
        for i in range(2, 10):
            candidate = review_dir / f"qa_report_{today_tag}_{i}.md"
            if not candidate.exists():
                report_path = candidate
                break

    report_path.write_text(report_md, encoding="utf-8")

    total = sum(
        len(result.get(k) or [])
        for k in ("A", "B", "C", "D", "E")
        if isinstance(result.get(k), list)
    )

    # Phase 4: 同时输出 qa_findings.json（结构化问题列表 + quality_score）
    findings_path = report_path.with_suffix(".json")
    findings = {
        "doc_name": filename,
        "review_date": datetime.now().isoformat(timespec="seconds"),
        "doc_type": doc_type,
        "total_issues": total,
        "categories": {k: len(v) for k, v in result.items() if isinstance(v, list)},
        "issues": result,
        "quality_score": max(0, 100 - total * 5),
    }
    findings_path.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"  报告已保存: {report_path}")
    print(f"  发现问题: {total} 条")
    print(f"  质量评分: {findings['quality_score']}/100")

    c_issues = result.get("C") or []
    if isinstance(c_issues, list) and c_issues:
        print(f"  [!] 逻辑一致性问题 {len(c_issues)} 条，建议优先处理")

    return str(report_path)