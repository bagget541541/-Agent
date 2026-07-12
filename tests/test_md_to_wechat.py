from pathlib import Path

from md_to_wechat import build_publish_markdown, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_render_mode_d_sample():
    md = (ROOT / "data" / "mode_d_merged.md").read_text(encoding="utf-8")
    publish_md, title = build_publish_markdown(md)
    html = render_markdown(publish_md)
    assert "<h1" in html
    assert "中国银行福气值上线" in html
    assert "<table" in html
    assert "公众号编辑器上传原图" in html
    assert "来源清单" not in publish_md
    assert "行动建议" not in publish_md
    assert "## 原文链接" in publish_md
    assert publish_md.count("https://mp.weixin.qq.com") == 4
    assert title.startswith("信用卡资讯精选｜")
    assert len([line for line in publish_md.splitlines() if line.startswith("### ") and line[4:5].isdigit()]) == 6


def test_render_escapes_raw_html():
    html = render_markdown("# 标题\n\n<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
