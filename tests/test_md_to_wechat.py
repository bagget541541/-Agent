from pathlib import Path

from md_to_wechat import build_publish_markdown, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_weekly_activity_is_compact_and_actionable():
    md = """# 周报\n\n## 🏷️ 活动\n\n### 农行活动：满200元随机减99元\n\n**亮点：** 农行信用卡持卡人；2026.10.10；满200元随机减1~99元优惠\n\n**结构化信息：**\n\n- **活动内容**：2026年10月10日至2026年10月31日，在去哪儿旅行APP收银台支付。\n\n[原文链接](https://example.com/a)\n"""
    publish_md, _ = build_publish_markdown(md)
    assert "活动要点" not in publish_md
    assert "亮点：" not in publish_md
    assert "结构化信息" not in publish_md
    assert "去哪儿APP" in publish_md
    assert "农行信用卡" in publish_md
    assert "满200元随机减99元" in publish_md


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


def test_render_markdown_link_keeps_raw_url_for_wechat():
    html = render_markdown("[活动规则](https://example.com/rules)")
    assert "https://example.com/rules" in html
    assert "<a " not in html


def test_render_weekly_report_markdown_without_numbered_items():
    md = (ROOT / "data" / "Weekly_Report_2026年7月第4周.md").read_text(encoding="utf-8")
    publish_md, title = build_publish_markdown(md)
    html = render_markdown(publish_md)
    assert "本期共 **9 条**资讯" in publish_md
    assert "超然商务卡消费达标抢" in html
    assert "华夏银行信用卡" in html
    assert "本期共 <strong>0 条</strong>" not in html
    assert "原文摘要" not in publish_md
    assert "原文摘要" not in html
    assert "**活动内容**" not in publish_md
    assert "**消息内容**" not in publish_md
    assert "**点评**：" not in publish_md
    assert "**活动时间**" in publish_md
    assert publish_md.count("https://") == 9
    assert "https://www.abchina.com" in html
    assert "href=\"https://www.abchina.com" not in html
    assert "text-align:left;word-break:break-all" in html
    assert "超然商务卡消费达标抢“两票”（7-9月）<br>https://www.abchina.com" in html
    assert title.startswith("信用卡资讯精选｜")
