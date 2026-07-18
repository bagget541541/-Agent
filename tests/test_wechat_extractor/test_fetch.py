"""wechat-article-extractor / fetch_wechat_article.py 单元测试"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

# ── 路径设置 ──────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
_EXTRACTOR_SCRIPTS = os.path.join(_PROJECT_ROOT, "wechat-article-extractor", "scripts")
for p in (_PROJECT_ROOT, _EXTRACTOR_SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)

import fetch_wechat_article as fwa


# ═══════════════════════════════════════════════════════════════
# extract_article — 核心 HTML 解析
# ═══════════════════════════════════════════════════════════════

class TestExtractArticle:
    """extract_article 的 title / content / images 选择器回退逻辑。"""

    def _make_html(self, title_html="", content_html="", extra=""):
        return (
            "<html><head></head><body>"
            f"{title_html}"
            f'{content_html}'
            f"{extra}"
            "</body></html>"
        )

    # ── title 选择器优先级 ────────────────────────────────

    def test_title_rich_media_title(self):
        html = self._make_html(
            '<h1 class="rich_media_title">测试标题A</h1>',
            '<div id="js_content">正文</div>',
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["title"] == "测试标题A"

    def test_title_fallback_activity_name(self):
        html = self._make_html(
            '<h1 id="activity-name">测试标题B</h1>',
            '<div id="js_content">正文</div>',
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["title"] == "测试标题B"

    def test_title_fallback_og_title(self):
        html = self._make_html(
            '<meta property="og:title" content="测试标题C">',
            '<div id="js_content">正文</div>',
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["title"] == "测试标题C"

    def test_title_not_found(self):
        html = self._make_html("", '<div id="js_content">正文</div>')
        result = fwa.extract_article(html, "http://test.com")
        assert result["title"] == ""

    # ── content div 选择器优先级 ──────────────────────────

    def test_content_js_content(self):
        html = self._make_html(
            '<h1 class="rich_media_title">T</h1>',
            '<div id="js_content">核心正文内容</div>',
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["content_text"] == "核心正文内容"
        assert "<div" in result["content_html"]

    def test_content_fallback_rich_media(self):
        html = self._make_html(
            '<h1 class="rich_media_title">T</h1>',
            '<div class="rich_media_content">备用正文</div>',
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["content_text"] == "备用正文"

    def test_content_fallback_page_content(self):
        html = self._make_html(
            '<h1 class="rich_media_title">T</h1>',
            '<div id="page_content">第三级正文</div>',
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["content_text"] == "第三级正文"

    def test_content_not_found(self):
        html = self._make_html('<h1 class="rich_media_title">T</h1>', "")
        result = fwa.extract_article(html, "http://test.com")
        assert result["content_text"] == ""
        assert result["content_html"] == ""

    # ── 图片提取 ─────────────────────────────────────────

    def test_images_data_src_preferred(self):
        html = (
            '<html><body>'
            '<div id="js_content">'
            '<img data-src="https://img1.example.com/a.jpg" src="">'
            '<img src="https://img2.example.com/b.png">'
            '</div></body></html>'
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["images"] == [
            "https://img1.example.com/a.jpg",
            "https://img2.example.com/b.png",
        ]

    def test_images_excludes_data_uri(self):
        html = (
            '<html><body>'
            '<div id="js_content">'
            '<img src="data:image/png;base64,abc123">'
            '<img data-src="https://real.example.com/pic.jpg">'
            '</div></body></html>'
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["images"] == ["https://real.example.com/pic.jpg"]

    def test_images_no_src(self):
        html = (
            '<html><body>'
            '<div id="js_content">'
            '<img alt="no source">'
            '</div></body></html>'
        )
        result = fwa.extract_article(html, "http://test.com")
        assert result["images"] == []

    # ── url 原样返回 ─────────────────────────────────────

    def test_url_passthrough(self):
        url = "https://mp.weixin.qq.com/s/ABC123"
        result = fwa.extract_article("<html></html>", url)
        assert result["url"] == url

    # ── text 空白折叠 ────────────────────────────────────

    def test_text_whitespace_collapsed(self):
        html = (
            '<div id="js_content">'
            '<p>第一段</p>\n\n\n'
            '<p>  第二段  </p>'
            '</div>'
        )
        result = fwa.extract_article(html, "http://test.com")
        assert "\n\n" not in result["content_text"]
        assert "第一段" in result["content_text"]
        assert "第二段" in result["content_text"]


# ═══════════════════════════════════════════════════════════════
# download_image — 文件名格式 & extension 检测
# ═══════════════════════════════════════════════════════════════

class TestDownloadImage:

    def test_filename_format_index_zero_padded(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "image/png"}
        mock_resp.content = b"\x89PNG"

        with tempfile.TemporaryDirectory() as tmp:
            with patch("fetch_wechat_article.requests.get", return_value=mock_resp) as mock_get:
                result = fwa.download_image("http://img.test.com/a.png", Path(tmp), 5)
                mock_get.assert_called_once()
                # index=5 → img_0005.ext
                assert os.path.basename(result) == "img_0005.png"
                assert os.path.exists(result)

    def test_content_type_png(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "image/png"}
        mock_resp.content = b"\x89PNG"

        with tempfile.TemporaryDirectory() as tmp:
            with patch("fetch_wechat_article.requests.get", return_value=mock_resp):
                result = fwa.download_image("http://img.test.com/a", Path(tmp), 0)
                assert os.path.basename(result) == "img_0000.png"

    def test_content_type_gif(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "image/gif"}
        mock_resp.content = b"GIF89"

        with tempfile.TemporaryDirectory() as tmp:
            with patch("fetch_wechat_article.requests.get", return_value=mock_resp):
                result = fwa.download_image("http://img.test.com/a", Path(tmp), 0)
                assert os.path.basename(result) == "img_0000.gif"

    def test_content_type_webp(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "image/webp"}
        mock_resp.content = b"RIFF"

        with tempfile.TemporaryDirectory() as tmp:
            with patch("fetch_wechat_article.requests.get", return_value=mock_resp):
                result = fwa.download_image("http://img.test.com/a", Path(tmp), 0)
                assert os.path.basename(result) == "img_0000.webp"

    def test_content_type_unknown_defaults_jpg(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/octet-stream"}
        mock_resp.content = b"\xff\xd8\xff"

        with tempfile.TemporaryDirectory() as tmp:
            with patch("fetch_wechat_article.requests.get", return_value=mock_resp):
                result = fwa.download_image("http://img.test.com/a", Path(tmp), 0)
                assert os.path.basename(result) == "img_0000.jpg"

    def test_download_failure_returns_none(self):
        with patch("fetch_wechat_article.requests.get", side_effect=Exception("network error")):
            result = fwa.download_image("http://img.test.com/fail.jpg", Path("/tmp"), 0)
            assert result is None


# ═══════════════════════════════════════════════════════════════
# find_chrome — 路径探测
# ═══════════════════════════════════════════════════════════════

class TestFindChrome:

    def test_found_in_program_files(self):
        fake_path = os.path.join("C:", os.sep, "Program Files",
                                 "Google", "Chrome", "Application", "chrome.exe")
        with patch("os.path.isfile", return_value=True):
            result = fwa.find_chrome()
            assert result == fake_path

    def test_found_via_env_var(self):
        with patch.dict(os.environ, {"CHROME_PATH": "/opt/chrome/chrome"}):
            with patch("os.path.isfile", lambda p: p == "/opt/chrome/chrome"):
                result = fwa.find_chrome()
                assert result == "/opt/chrome/chrome"

    def test_not_found(self):
        with patch("os.path.isfile", return_value=False):
            with patch.dict(os.environ, {}, clear=True):
                result = fwa.find_chrome()
                assert result is None


# ═══════════════════════════════════════════════════════════════
# _load_llm_config — 配置加载
# ═══════════════════════════════════════════════════════════════

class TestLoadLLMConfig:

    def test_config_file_present(self):
        """显式 file config 优先（mock _load_file_config 直接返回该 cfg）。"""
        fake_cfg = '{"api_key": "sk-123", "api_base": "https://custom.api/v1"}'
        m = mock_open(read_data=fake_cfg)
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", m), \
             patch("common.llm_client._load_file_config",
                   return_value={"api_key": "sk-123", "api_base": "https://custom.api/v1"}):
            result = fwa._load_llm_config()
        assert result["api_key"] == "sk-123"
        assert result["api_base"] == "https://custom.api/v1"

    def test_config_file_absent_env_fallback(self):
        """file config 不存在 + env 已设置 → 用 env 值。"""
        with patch("os.path.exists", return_value=False), \
             patch("common.llm_client._load_file_config", return_value=None), \
             patch.dict(os.environ, {"LLM_API_KEY": "env-key", "LLM_API_BASE": "https://env.api"}):
            result = fwa._load_llm_config()
        assert result["api_key"] == "env-key"
        assert result["api_base"] == "https://env.api"

    def test_apikey_txt_fallback(self):
        """共享配置缺失时回退项目根 apikey.txt。"""
        with patch.object(fwa, "LLM_CONFIG_FILE", "missing.json"), \
             patch("common.llm_client._load_file_config", return_value={"api_key": "sk-local", "api_base": "https://local.api/v1"}):
            result = fwa._load_llm_config()
        assert result["api_key"] == "sk-local"
        assert result["api_base"] == "https://local.api/v1"

    def test_defaults_when_nothing_configured(self):
        with patch("os.path.exists", return_value=False), \
             patch("common.llm_client._load_file_config", return_value=None), \
             patch.dict(os.environ, {}, clear=True):
            result = fwa._load_llm_config()
        assert result["api_key"] == ""
        assert result["api_base"] == fwa.DEFAULT_API_BASE
        assert result["vision_model"] == fwa.DEFAULT_VISION_MODEL

    def test_vision_model_precedence(self):
        """file config 中的 vision_model 优先于环境变量。"""
        with patch("os.path.exists", return_value=True), \
             patch("common.llm_client._load_file_config",
                   return_value={"vision_model": "gpt-4o"}), \
             patch.dict(os.environ, {"LLM_VISION_MODEL": "env-model"}):
            result = fwa._load_llm_config()
        assert result["vision_model"] == "gpt-4o"


# ═══════════════════════════════════════════════════════════════
# fetch_with_requests / fetch_with_playwright
# ═══════════════════════════════════════════════════════════════

class TestFetchWithRequests:

    def test_success(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "<html><body>OK</body></html>"
        with patch("fetch_wechat_article.requests.get", return_value=mock_resp) as mock_get:
            result = fwa.fetch_with_requests("http://test.com")
            assert result == "<html><body>OK</body></html>"
            _, kwargs = mock_get.call_args
            assert kwargs["timeout"] == 30
            assert "User-Agent" in kwargs["headers"]

    def test_failure_returns_none(self):
        with patch("fetch_wechat_article.requests.get", side_effect=Exception("timeout")):
            result = fwa.fetch_with_requests("http://test.com")
            assert result is None


class TestFetchWithPlaywright:

    def test_playwright_not_installed(self):
        with patch.object(fwa, "PLAYWRIGHT_IMPORT_OK", False):
            result = fwa.fetch_with_playwright("http://test.com")
            assert result is None

    def test_chrome_not_found(self):
        with patch.object(fwa, "PLAYWRIGHT_IMPORT_OK", True), \
             patch.object(fwa, "find_chrome", return_value=None):
            result = fwa.fetch_with_playwright("http://test.com")
            assert result is None

    def test_success(self):
        fake_page = MagicMock()
        fake_page.content.return_value = "<html>rendered</html>"
        fake_browser = MagicMock()
        fake_browser.new_page.return_value = fake_page
        fake_pw = MagicMock()
        fake_pw.chromium.launch.return_value = fake_browser

        with patch.object(fwa, "PLAYWRIGHT_IMPORT_OK", True), \
             patch.object(fwa, "find_chrome", return_value="/fake/chrome"), \
             patch.object(fwa, "sync_playwright") as mock_sync:
            mock_sync.return_value.__enter__ = MagicMock(return_value=fake_pw)
            mock_sync.return_value.__exit__ = MagicMock(return_value=False)
            result = fwa.fetch_with_playwright("http://test.com")
            assert result == "<html>rendered</html>"
            fake_page.wait_for_selector.assert_called_once_with("#js_content", timeout=10000)


# ═══════════════════════════════════════════════════════════════
# process_single — 端到端（mock 网络）
# ═══════════════════════════════════════════════════════════════

class TestProcessSingle:

    @pytest.fixture(autouse=True)
    def _mock_fetch(self):
        """统一 mock fetch_with_requests，返回含图片的 HTML。"""
        self.fake_html = (
            '<html><body>'
            '<h1 class="rich_media_title">测试文章</h1>'
            '<div id="js_content">'
            '<p>测试正文内容，包含关键信息。</p>'
            '<img data-src="https://img.example.com/1.jpg">'
            '<img data-src="https://img.example.com/2.jpg">'
            '<img data-src="https://img.example.com/3.jpg">'
            '</div></body></html>'
        )
        with patch.object(fwa, "fetch_with_requests", return_value=self.fake_html):
            yield

    def test_basic_extraction(self):
        result = fwa.process_single("http://test.com")
        assert result["title"] == "测试文章"
        assert "测试正文内容" in result["content_text"]
        assert len(result["images"]) == 3
        assert result["source"] == "requests"

    def test_fetch_fails_returns_error(self):
        with patch.object(fwa, "fetch_with_requests", return_value=None), \
             patch.object(fwa, "fetch_with_playwright", return_value=None):
            result = fwa.process_single("http://test.com")
            assert result.get("error") == "Cannot fetch page"

    def test_max_images_truncates(self):
        result = fwa.process_single("http://test.com", max_images=2)
        assert len(result["images"]) == 2

    def test_max_images_zero_means_all(self):
        result = fwa.process_single("http://test.com", max_images=0)
        assert len(result["images"]) == 3

    def test_playwright_fallback(self):
        with patch.object(fwa, "fetch_with_requests", return_value=None), \
             patch.object(fwa, "fetch_with_playwright", return_value=self.fake_html):
            result = fwa.process_single("http://test.com")
            assert result["source"] == "playwright"
            assert result["title"] == "测试文章"
