"""common.images 集成测试

覆盖：
  - 目录管理：ensure_dir / get_central_image_dir
  - 下载/复制：download_image_from_url / copy_to_central_image_dir / centralize_images
  - 内容哈希：image_hash / deduplicate_images
  - 图片过滤：filter_meaningful_images（用真实 PIL 图片）
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from common.images import (
    ensure_dir,
    get_central_image_dir,
    download_image_from_url,
    copy_to_central_image_dir,
    centralize_images,
    image_hash,
    deduplicate_images,
    filter_meaningful_images,
)
from common.config import DEFAULT_IMAGES_DIR


# ═══════════════════════════════════════════════════════════
# 目录管理
# ═══════════════════════════════════════════════════════════

class TestEnsureDir:
    def test_creates_directory(self):
        """ensure_dir 创建目录并返回绝对路径"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = os.path.join(tmpdir, "nested", "dir")
            result = ensure_dir(test_dir)
            assert os.path.isdir(test_dir)
            assert os.path.isabs(result)
            assert result == os.path.abspath(test_dir)

    def test_existing_directory_returns(self):
        """已存在目录 → 直接返回"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ensure_dir(tmpdir)
            assert result == os.path.abspath(tmpdir)


class TestGetCentralImageDir:
    def test_returns_under_default_images_dir(self):
        """get_central_image_dir 返回 DEFAULT_IMAGES_DIR/item_id"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("common.images.DEFAULT_IMAGES_DIR", tmpdir):
                path = get_central_image_dir("item_001")
                assert "item_001" in path
                assert tmpdir in path
                assert os.path.isabs(path)

    def test_different_item_ids_different_dirs(self):
        """不同 item_id 返回不同路径"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("common.images.DEFAULT_IMAGES_DIR", tmpdir):
                path_a = get_central_image_dir("item_a")
                path_b = get_central_image_dir("item_b")
                assert path_a != path_b


# ═══════════════════════════════════════════════════════════
# 下载 & 复制
# ═══════════════════════════════════════════════════════════

class TestDownloadImageFromUrl:
    @patch("common.images.requests.get")
    def test_success_download(self, mock_get):
        """下载成功 → 返回本地文件绝对路径"""
        mock_response = MagicMock()
        mock_response.content = b"fake_image_bytes"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("common.images.get_central_image_dir", return_value=tmpdir):
                result = download_image_from_url("https://example.com/img/photo.png", "item_001")
                assert result is not None
                assert os.path.isfile(result)
                assert result.endswith(".png")
                with open(result, "rb") as f:
                    assert f.read() == b"fake_image_bytes"

    @patch("common.images.requests.get")
    def test_url_without_ext_uses_jpg(self, mock_get):
        """URL 无扩展名 → 默认 .jpg"""
        mock_response = MagicMock()
        mock_response.content = b"data"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("common.images.get_central_image_dir", return_value=tmpdir):
                result = download_image_from_url("https://example.com/image", "item_001")
                assert result.endswith(".jpg")

    @patch("common.images.requests.get")
    def test_failure_returns_none(self, mock_get):
        """下载失败 → 返回 None"""
        mock_get.side_effect = Exception("Connection error")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("common.images.get_central_image_dir", return_value=tmpdir):
                result = download_image_from_url("https://example.com/bad.jpg", "item_001")
                assert result is None


class TestCopyToCentralImageDir:
    def test_copy_success(self):
        """复制成功 → 返回新路径"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建源文件
            src = os.path.join(tmpdir, "source.jpg")
            with open(src, "wb") as f:
                f.write(b"image_data")

            # 预先创建 dest 目录（确保拷贝目标存在）
            dest_dir = os.path.join(tmpdir, "dest")
            os.makedirs(dest_dir, exist_ok=True)
            with patch("common.images.get_central_image_dir", return_value=dest_dir):
                result = copy_to_central_image_dir(src, "item_001")
                assert result is not None
                assert os.path.isfile(result)
                assert "source.jpg" in result

    def test_source_not_found(self):
        """源文件不存在 → 返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = copy_to_central_image_dir("/nonexistent/file.jpg", "item_001")
            assert result is None

    def test_dest_already_exists_adds_suffix(self):
        """目标已存在 → 自动添加后缀避免覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "photo.png")
            with open(src, "wb") as f:
                f.write(b"original_data")

            dest_dir = os.path.join(tmpdir, "dest")
            os.makedirs(dest_dir, exist_ok=True)
            # 在目标目录创建同名文件
            dest_file = os.path.join(dest_dir, "photo.png")
            with open(dest_file, "wb") as f:
                f.write(b"different_data")

            with patch("common.images.get_central_image_dir", return_value=dest_dir):
                result = copy_to_central_image_dir(src, "item_001")
                assert result is not None
                assert "photo" in result
                assert "item_001" in result  # 携带 item_id 前缀


class TestCentralizeImages:
    @patch("common.images.download_image_from_url")
    def test_url_images_downloaded(self, mock_download):
        """URL 路径 → 下载"""
        mock_download.return_value = "/local/img.jpg"
        result = centralize_images(["https://example.com/img.jpg"], "item_001")
        mock_download.assert_called_once_with("https://example.com/img.jpg", "item_001")
        assert result == ["/local/img.jpg"]

    @patch("common.images.copy_to_central_image_dir")
    def test_local_images_copied(self, mock_copy):
        """本地路径 → 复制"""
        mock_copy.return_value = "/local/dest.jpg"
        result = centralize_images(["/local/src.jpg"], "item_001")
        mock_copy.assert_called_once_with("/local/src.jpg", "item_001")
        assert result == ["/local/dest.jpg"]

    @patch("common.images.download_image_from_url")
    @patch("common.images.copy_to_central_image_dir")
    def test_mixed_input(self, mock_copy, mock_download):
        """混合 URL 和本地路径 → 各自正确处理"""
        mock_download.return_value = "/local/dl.jpg"
        mock_copy.return_value = "/local/cp.jpg"
        result = centralize_images(
            ["https://example.com/a.jpg", "/local/b.jpg"],
            "item_001",
        )
        mock_download.assert_called_once()
        mock_copy.assert_called_once()
        assert len(result) == 2

    @patch("common.images.download_image_from_url")
    def test_empty_url_skipped(self, mock_download):
        """空字符串 → 跳过"""
        result = centralize_images(["", None], "item_001")
        assert result == []
        mock_download.assert_not_called()

    @patch("common.images.download_image_from_url")
    def test_all_failures_return_empty(self, mock_download):
        """全部失败 → 返回空列表"""
        mock_download.return_value = None
        result = centralize_images(["https://example.com/img.jpg"], "item_001")
        assert result == []


# ═══════════════════════════════════════════════════════════
# 内容哈希 — 用 > 68KB 的文件确保 SHA-256 能正常计算
# ═══════════════════════════════════════════════════════════

def _make_large_file(dirpath: str, name: str, content: bytes) -> str:
    """创建 > 68KB 的文件以确保 image_hash 能正常 seek"""
    path = os.path.join(dirpath, name)
    data = content * (70000 // len(content) + 1)  # 至少 70KB
    with open(path, "wb") as f:
        f.write(data[:70000])
    return path


class TestImageHash:
    def test_file_not_found_returns_none(self):
        """不存在的文件 → None"""
        assert image_hash("/nonexistent/file.jpg") is None

    def test_same_content_same_hash(self):
        """相同内容的文件 → 相同哈希"""
        with tempfile.TemporaryDirectory() as tmpdir:
            a = _make_large_file(tmpdir, "a.png", b"same_content")
            b = _make_large_file(tmpdir, "b.png", b"same_content")
            ha = image_hash(a)
            hb = image_hash(b)
            assert ha is not None
            assert hb is not None
            assert ha == hb

    def test_diff_content_diff_hash(self):
        """不同内容的文件 → 不同哈希"""
        with tempfile.TemporaryDirectory() as tmpdir:
            a = _make_large_file(tmpdir, "a.png", b"content_a")
            b = _make_large_file(tmpdir, "b.png", b"content_b")
            ha = image_hash(a)
            hb = image_hash(b)
            assert ha is not None, "hash(a) should not be None"
            assert hb is not None, "hash(b) should not be None"
            assert ha != hb


class TestDeduplicateImages:
    def test_no_duplicates(self):
        """无重复 → 全部保留"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = [_make_large_file(tmpdir, f"img_{i}.png", f"content_{i}".encode()) for i in range(3)]
            result = deduplicate_images(files)
            assert len(result) == 3

    def test_duplicates_removed(self):
        """有重复 → 只保留一个"""
        with tempfile.TemporaryDirectory() as tmpdir:
            a = _make_large_file(tmpdir, "a.png", b"same_data")
            b = _make_large_file(tmpdir, "b.png", b"same_data")
            c = _make_large_file(tmpdir, "c.png", b"diff_data")
            result = deduplicate_images([a, b, c])
            assert len(result) == 2
            # 相同内容的只保留第一个
            assert result[0] == a
            assert result[1] == c

    def test_unreadable_files_kept(self):
        """无法读取的文件保守保留"""
        result = deduplicate_images(["/nonexistent/file.png"])
        assert result == ["/nonexistent/file.png"]

    def test_empty_input(self):
        """空列表 → []"""
        assert deduplicate_images([]) == []


# ═══════════════════════════════════════════════════════════
# 图片过滤 — 用 PNG 格式避免 JPEG 压缩引入像素噪声
# ═══════════════════════════════════════════════════════════

class TestFilterMeaningfulImages:
    def _make_png(self, tmpdir: str, name: str, size_px: tuple = (200, 200),
                  color: tuple = (128, 128, 128), file_size_kb: int = 50) -> str:
        """创建一张 PNG 测试图片（PNG 无损，纯色无噪声）"""
        from PIL import Image
        path = os.path.join(tmpdir, name)
        img = Image.new("RGB", size_px, color)
        img.save(path, "PNG")
        # 文件如果太小则填充到指定 KB（填充后 PIL 仍能读取 PNG 头部信息）
        actual = os.path.getsize(path)
        if file_size_kb * 1024 > actual:
            with open(path, "ab") as f:
                f.write(b"\x00" * (file_size_kb * 1024 - actual))
        return path

    def _make_varied_png(self, tmpdir: str, name: str, file_size_kb: int = 10) -> str:
        """创建一张有像素变化的图片（PNG 无损），并填充到指定大小"""
        from PIL import Image
        path = os.path.join(tmpdir, name)
        img = Image.new("RGB", (200, 200))
        pixels = img.load()
        for x in range(200):
            for y in range(200):
                pixels[x, y] = (x * 255 // 200, y * 255 // 200, 128)
        img.save(path, "PNG")
        # 填充到 >5KB 以免被文件大小过滤
        actual = os.path.getsize(path)
        target = file_size_kb * 1024
        if target > actual:
            with open(path, "ab") as f:
                f.write(b"\x00" * (target - actual))
        return path

    def test_small_file_size_filtered(self):
        """文件 < 5KB → 过滤（混入有效图避免兜底）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = self._make_png(tmpdir, "small.png", file_size_kb=3)
            good = self._make_varied_png(tmpdir, "good.png")
            result = filter_meaningful_images([bad, good])
            assert bad not in result
            assert good in result

    def test_tiny_dimensions_filtered(self):
        """宽高都 < 50px → 过滤"""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = self._make_png(tmpdir, "tiny.png", size_px=(40, 40), file_size_kb=10)
            good = self._make_varied_png(tmpdir, "good.png")
            result = filter_meaningful_images([bad, good])
            assert bad not in result
            assert good in result

    def test_extreme_narrow_filtered(self):
        """任一方 < 30px → 过滤"""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = self._make_png(tmpdir, "bar.png", size_px=(20, 200), file_size_kb=10)
            good = self._make_varied_png(tmpdir, "good.png")
            result = filter_meaningful_images([bad, good])
            assert bad not in result
            assert good in result

    def test_pure_color_filtered(self):
        """纯色图片 → 过滤"""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = self._make_png(tmpdir, "pure.png", color=(200, 200, 200), size_px=(100, 100), file_size_kb=10)
            good = self._make_varied_png(tmpdir, "good.png")
            result = filter_meaningful_images([bad, good])
            assert bad not in result
            assert good in result

    def test_varied_image_kept(self):
        """有变化的图片 → 保留"""
        with tempfile.TemporaryDirectory() as tmpdir:
            img = self._make_varied_png(tmpdir, "varied.png")
            result = filter_meaningful_images([img])
            assert img in result

    def test_mixed_input(self):
        """混合过滤 → 仅保留有意义的"""
        with tempfile.TemporaryDirectory() as tmpdir:
            good = self._make_varied_png(tmpdir, "good.png")
            bad = self._make_png(tmpdir, "bad.png", file_size_kb=3)
            result = filter_meaningful_images([good, bad])
            assert good in result
            assert bad not in result

    def test_empty_input(self):
        """空列表 → []"""
        assert filter_meaningful_images([]) == []

    def test_urls_passed_through(self):
        """HTTP URL → 不过滤直接保留"""
        result = filter_meaningful_images(["https://example.com/img.jpg"])
        assert result == ["https://example.com/img.jpg"]

    def test_all_filtered_keeps_first(self):
        """全被过滤 → 至少保留第一张"""
        with tempfile.TemporaryDirectory() as tmpdir:
            img = self._make_png(tmpdir, "tiny.png", size_px=(10, 10), file_size_kb=3)
            result = filter_meaningful_images([img])
            # 虽然被过滤但至少保留一张
            assert len(result) == 1

    def test_non_existent_file_skipped(self):
        """文件不存在 → 跳过（混入有效图）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            valid = self._make_varied_png(tmpdir, "good.png")
            result = filter_meaningful_images(["/nonexistent/file.png", valid])
            assert valid in result
            assert "/nonexistent/file.png" not in result
