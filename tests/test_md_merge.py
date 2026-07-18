"""md_merge 单元测试。

设计原则：测试不依赖外部样本文件，全部使用 inline fixture，保证
在任何 CWD / 任何样本文件存在与否的情况下都能稳定运行。
"""
from pathlib import Path

from md_merge import build_editorial, merge_items, parse_markdown


ROOT = Path(__file__).resolve().parents[1]


# ── inline fixture：模拟 parse_markdown 的返回结构 ──────────────────
SAMPLE_DOC_A = {
    "file": "a.md",
    "title": "A 文档",
    "items": [
        {
            "title": "一、中国银行福气值上线",
            "display_title": "中国银行福气值上线",
            "key": "中国银行福气值上线",
            "category": "权益变更",
            "priority": "高",
            "source_url": "https://example.com/a",
            "source_file": "a.md",
            "comment": "明升暗降：积分获取更容易，但兑换门槛提高",
            "body": "## 一、中国银行福气值上线\n\n类别：权益变更\n优先级：高\n来源：https://example.com/a",
            "source_date": "2026.07.08",
            "images": [],
        },
        {
            "title": "二、招商银行 AI 联名卡",
            "display_title": "招商银行 AI 联名卡",
            "key": "招商银行ai联名卡",
            "category": "新卡",
            "priority": "中",
            "source_url": "https://example.com/a2",
            "source_file": "a.md",
            "comment": "AI 算力包装进权益，需核对真实使用价值",
            "body": "## 二、招商银行 AI 联名卡\n\n类别：新卡",
            "source_date": "2026.07.08",
            "images": [],
        },
    ],
}

SAMPLE_DOC_B = {
    "file": "b.md",
    "title": "B 文档",
    "items": [
        {
            "title": "一、中国银行福气值上线",
            "display_title": "中国银行福气值上线",
            "key": "中国银行福气值上线",
            "category": "权益变更",
            "priority": "高",
            "source_url": "https://example.com/b",
            "source_file": "b.md",
            "comment": "",
            "body": "## 一、中国银行福气值上线\n\n类别：权益变更",
            "source_date": "2026.07.11",
            "images": [],
        },
    ],
}


def test_merge_deduplicates_same_title():
    """同 key 条目合并，duplicate_count 正确累加。"""
    a = {
        "file": "a",
        "items": [{
            "title": "测试活动",
            "display_title": "测试活动",
            "key": "测试活动",
            "category": "活动",
            "body": "a",
            "comment": "点评",
            "source_file": "a.md",
            "source_url": "https://example.com/a",
        }],
    }
    b = {
        "file": "b",
        "items": [{
            "title": "测试活动",
            "display_title": "测试活动",
            "key": "测试活动",
            "category": "活动",
            "body": "b",
            "comment": "",
            "source_file": "b.md",
            "source_url": "https://example.com/b",
        }],
    }
    result = merge_items([a, b])
    assert len(result) == 1
    assert result[0]["duplicate_count"] == 2
    # sources 列表应含两份来源
    assert len(result[0]["sources"]) == 2


def test_merge_keeps_first_comment():
    """同 key 合并时，保留第一条非空 comment。"""
    result = merge_items([SAMPLE_DOC_A, SAMPLE_DOC_B])
    item = next(r for r in result if "福气值" in r["title"])
    assert "明升暗降" in item["comment"]


def test_editorial_output_keeps_source_content():
    """build_editorial 输出含逐条原文、来源清单、行动建议。"""
    docs = [SAMPLE_DOC_A, SAMPLE_DOC_B]
    items = merge_items(docs)
    output = build_editorial(items, docs)
    # 去重后 2 条（福气值合并 + AI 联名卡）
    assert len(items) == 2
    assert "中国银行福气值上线" in output
    assert "招商银行 AI 联名卡" in output
    assert "行动建议" in output
    assert "来源清单" in output


def test_parse_markdown_real_file_skipped_if_missing():
    """样本文件不存在时，parse_markdown 应抛 FileNotFoundError（不静默通过）。

    此测试断言当前 parse_markdown 的契约：缺文件直接报错。
    """
    missing = ROOT / "data" / "_nonexistent_sample_20260708.md"
    try:
        parse_markdown(missing)
        raise AssertionError("expected FileNotFoundError for missing sample")
    except FileNotFoundError:
        pass
