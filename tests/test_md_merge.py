from pathlib import Path

from md_merge import build_editorial, merge_items, parse_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_parse_sample_markdown():
    doc = parse_markdown(ROOT / "data" / "公众号文章整理_20260711.md")
    assert len(doc["items"]) == 4
    assert doc["items"][0]["title"] == "一、中国银行福气值上线"
    assert "明升暗降" in doc["items"][0]["comment"]


def test_merge_deduplicates_same_title():
    a = {"file": "a", "items": [{"title": "测试活动", "key": "测试活动", "category": "活动", "body": "a", "comment": "点评"}]}
    b = {"file": "b", "items": [{"title": "测试活动", "key": "测试活动", "category": "活动", "body": "b", "comment": ""}]}
    result = merge_items([a, b])
    assert len(result) == 1
    assert result[0]["duplicate_count"] == 2


def test_editorial_output_keeps_source_content():
    docs = [
        parse_markdown(ROOT / "data" / "公众号文章整理_20260708.md"),
        parse_markdown(ROOT / "data" / "公众号文章整理_20260711.md"),
    ]
    items = merge_items(docs)
    output = build_editorial(items, docs)
    assert len(items) == 6
    assert "兴业银行小白金卡年费政策更新" in output
    assert "中国银行福气值上线" in output
    assert "行动建议" in output
