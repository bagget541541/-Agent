#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片内容提取工具
支持 OCR 文字提取和图片内容分析
"""
import os
import sys
from pathlib import Path
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class ImageContentExtractor:
    """图片内容提取器"""

    def __init__(self, tesseract_cmd: Optional[str] = None):
        """
        初始化图片内容提取器

        Args:
            tesseract_cmd: Tesseract OCR 路径，None 则自动查找
        """
        self._ocr_available = False
        self._pytesseract = None
        self._PIL = None

        # 尝试加载依赖
        self._load_dependencies(tesseract_cmd)

    def _load_dependencies(self, tesseract_cmd: Optional[str] = None):
        """加载 OCR 依赖"""
        try:
            import pytesseract
            from PIL import Image

            self._pytesseract = pytesseract
            self._PIL = Image

            # 配置 Tesseract 路径
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

            # 检查 Tesseract 是否可用
            try:
                pytesseract.get_tesseract_version()
                self._ocr_available = True
                logger.info("Tesseract OCR 已就绪")
            except Exception as e:
                logger.warning(f"Tesseract OCR 不可用: {e}")

        except ImportError as e:
            logger.warning(f"OCR 依赖未安装: {e}")
            logger.info("安装命令: pip install pytesseract Pillow")

    @property
    def is_available(self) -> bool:
        """OCR 是否可用"""
        return self._ocr_available

    def extract_text_from_image(self, image_path: str, lang: str = "chi_sim+eng") -> str:
        """
        从图片中提取文字

        Args:
            image_path: 图片路径
            lang: OCR 语言，默认中文简体+英文

        Returns:
            提取的文字内容
        """
        if not self._ocr_available:
            logger.warning("OCR 不可用，无法提取图片文字")
            return ""

        try:
            img = self._PIL.Image.open(image_path)
            text = self._pytesseract.image_to_string(img, lang=lang)
            return text.strip()
        except Exception as e:
            logger.error(f"OCR 提取失败: {e}")
            return ""

    def extract_text_from_images(self, image_paths: List[str], lang: str = "chi_sim+eng") -> Dict[str, str]:
        """
        批量从图片中提取文字

        Args:
            image_paths: 图片路径列表
            lang: OCR 语言

        Returns:
            {图片路径: 提取的文字} 字典
        """
        results = {}
        for path in image_paths:
            if os.path.exists(path):
                results[path] = self.extract_text_from_image(path, lang)
            else:
                logger.warning(f"图片不存在: {path}")
                results[path] = ""
        return results

    def get_image_info(self, image_path: str) -> Dict:
        """
        获取图片基本信息

        Args:
            image_path: 图片路径

        Returns:
            图片信息字典
        """
        if not self._PIL:
            return {"error": "Pillow 未安装"}

        try:
            img = self._PIL.Image.open(image_path)
            return {
                "path": image_path,
                "format": img.format,
                "mode": img.mode,
                "size": img.size,
                "width": img.width,
                "height": img.height,
            }
        except Exception as e:
            return {"error": str(e)}


def extract_text_from_directory(dir_path: str, extensions: tuple = (".png", ".jpg", ".jpeg", ".gif", ".bmp")) -> Dict[str, str]:
    """
    从目录中所有图片提取文字

    Args:
        dir_path: 目录路径
        extensions: 图片扩展名

    Returns:
        {文件路径: 提取的文字} 字典
    """
    extractor = ImageContentExtractor()
    if not extractor.is_available:
        logger.warning("OCR 不可用")
        return {}

    results = {}
    path = Path(dir_path)

    for ext in extensions:
        for img_path in path.glob(f"*{ext}"):
            results[str(img_path)] = extractor.extract_text_from_image(str(img_path))

    return results


if __name__ == "__main__":
    # 测试用法
    if len(sys.argv) < 2:
        print("用法: python image_content_extractor.py <图片路径或目录>")
        sys.exit(1)

    target = sys.argv[1]
    extractor = ImageContentExtractor()

    if not extractor.is_available:
        print("OCR 不可用，请安装 Tesseract OCR")
        print("安装方式:")
        print("  1. 下载: https://github.com/UB-Mannheim/tesseract/wiki")
        print("  2. 或使用: choco install tesseract")
        sys.exit(1)

    if os.path.isfile(target):
        # 单个图片
        print(f"提取文字: {target}")
        text = extractor.extract_text_from_image(target)
        print(text if text else "(无文字内容)")
    elif os.path.isdir(target):
        # 目录
        print(f"批量提取: {target}")
        results = extract_text_from_directory(target)
        for path, text in results.items():
            print(f"\n--- {path} ---")
            print(text if text else "(无文字内容)")
    else:
        print(f"路径不存在: {target}")
        sys.exit(1)
