"""
项目路径和全局配置

所有 skill 都应通过本模块获取路径，而非硬编码路径字符串。
"""

import os
from pathlib import Path

# ── 项目根目录（自动检测，支持 Windows / Linux / macOS） ───
# common/ 目录所在位置即为项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 常用子目录 ──────────────────────────────────────────
SKILLS_DIR = PROJECT_ROOT                     # skills 目录
DATA_DIR = PROJECT_ROOT / "data"              # 统一数据输出目录
ARCHIVE_DIR = DATA_DIR / "archive"            # 知识库归档目录
TEMP_DIR = DATA_DIR / "temp"                  # 临时文件

# ── 各 skill 路径 ──────────────────────────────────────
NEWS_ANALYZER_DIR = SKILLS_DIR / "news-analyzer"
WECHAT_DIR = SKILLS_DIR / "wechat-article-extractor"
WORD_MERGER_DIR = SKILLS_DIR / "word-merger"
CARD_HOLDING_DIR = SKILLS_DIR / "card-holding-suggestion"

# ── 默认图片存储目录 ────────────────────────────────────
DEFAULT_IMAGES_DIR = DATA_DIR / "images"


def ensure_dirs() -> None:
    """确保所有常用目录存在。首次运行调用一次即可。"""
    for d in [DATA_DIR, ARCHIVE_DIR, TEMP_DIR, DEFAULT_IMAGES_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def short_path(p: str | Path) -> str:
    """返回相对于 PROJECT_ROOT 的短路径，用于日志显示。"""
    return str(Path(p).relative_to(PROJECT_ROOT)) if PROJECT_ROOT in Path(p).parents else str(p)
