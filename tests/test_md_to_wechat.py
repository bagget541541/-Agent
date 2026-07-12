from pathlib import Path

from md_to_wechat import render_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_render_mode_d_sample():
    md = (ROOT / "data" / "mode_d_merged.md").read_text(encoding="utf-8")
    html = render_markdown(md)
    assert "<h1" in html
    assert "中国银行福气值上线" in html
    assert "<table" in html
    assert "公众号编辑器上传原图" in html


def test_render_escapes_raw_html():
    html = render_markdown("# 标题\n\n<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
