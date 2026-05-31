#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docx 工具函数
提供编码修复、打包等功能
"""
import os
import sys
import tempfile
import shutil
import zipfile
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def fix_xml_encoding(xml_file: Path) -> bool:
    """
    修复单个 XML 文件的编码问题

    Args:
        xml_file: XML 文件路径

    Returns:
        是否修复成功
    """
    try:
        # 尝试用 UTF-8 读取
        content = xml_file.read_text(encoding='utf-8')

        # 确保文件以 UTF-8 编码保存
        xml_file.write_text(content, encoding='utf-8')
        return True

    except Exception as e:
        logger.error(f"修复失败 {xml_file.name}: {e}")
        return False


def fix_docx_encoding(input_docx: str, output_docx: str = None) -> bool:
    """
    修复 docx 文件的编码问题

    Args:
        input_docx: 输入 docx 文件路径
        output_docx: 输出 docx 文件路径，None 则覆盖原文件

    Returns:
        是否修复成功
    """
    input_path = Path(input_docx)
    if not input_path.exists():
        logger.error(f"文件不存在: {input_docx}")
        return False

    if output_docx is None:
        output_docx = str(input_path.with_stem(input_path.stem + '_fixed'))

    output_path = Path(output_docx)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # 解压 docx
        try:
            with zipfile.ZipFile(input_path, 'r') as zf:
                zf.extractall(temp_path)
        except Exception as e:
            logger.error(f"解压失败: {e}")
            return False

        # 修复所有 XML 文件
        fixed_count = 0
        for xml_file in temp_path.rglob('*.xml'):
            if fix_xml_encoding(xml_file):
                fixed_count += 1

        for rels_file in temp_path.rglob('*.rels'):
            if fix_xml_encoding(rels_file):
                fixed_count += 1

        logger.debug(f"修复了 {fixed_count} 个文件")

        # 重新打包
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in temp_path.rglob('*'):
                    if f.is_file():
                        zf.write(f, f.relative_to(temp_path))
        except Exception as e:
            logger.error(f"打包失败: {e}")
            return False

    return True


def safe_generate_report(input_path: str, output_path: str, **kwargs) -> dict:
    """
    安全生成报告（带编码修复）

    Args:
        input_path: 输入 JSON 文件路径
        output_path: 输出 docx 文件路径
        **kwargs: 传递给 generate_report 的参数

    Returns:
        生成结果字典
    """
    # 导入生成函数
    sys.path.insert(0, str(Path(__file__).parent))
    from generate_report import generate_report

    # 生成报告
    result = generate_report(input_path, output_path, **kwargs)

    # 如果生成成功，尝试修复编码
    if result.get('success') and os.path.exists(output_path):
        try:
            # 创建临时文件
            temp_output = output_path + '.tmp'
            if fix_docx_encoding(output_path, temp_output):
                # 替换原文件
                os.replace(temp_output, output_path)
                logger.debug(f"编码修复完成: {output_path}")
        except Exception as e:
            logger.warning(f"编码修复失败（不影响使用）: {e}")

    return result


if __name__ == "__main__":
    # 测试用法
    if len(sys.argv) < 2:
        print("用法: python docx_utils.py <输入docx> [输出docx]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    logging.basicConfig(level=logging.INFO)

    if fix_docx_encoding(input_file, output_file):
        print(f"修复完成: {output_file or input_file}")
    else:
        print("修复失败")
        sys.exit(1)
