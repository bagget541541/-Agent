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
VECTOR_CACHE = DATA_DIR / "vector_cache.pkl"  # 向量索引缓存
EMBEDDING_MODEL = "D:/models/bge-small-zh-v1.5"   # 默认 embedding 模型（本地路径）

# ── 各 skill 路径 ──────────────────────────────────────
NEWS_ANALYZER_DIR = SKILLS_DIR / "news-analyzer"
WECHAT_DIR = SKILLS_DIR / "wechat-article-extractor"
WORD_MERGER_DIR = SKILLS_DIR / "word-merger"
CARD_HOLDING_DIR = SKILLS_DIR / "card-holding-suggestion"

# ── 默认图片存储目录 ────────────────────────────────────
DEFAULT_IMAGES_DIR = DATA_DIR / "images"

# ── 已知字段名集合（用于字段模式解析，冒号结尾时加粗但不作为顶级标题） ──
# 来自 merge_docs.py 和 export_document.py 的合并统一版本
KNOWN_FIELD_NAMES = {
    '活动内容', '活动时间', '适用人群',
    '卡种', '卡亮点', '详情', '来源',
    '消息时间', '影响范围', '变更内容', '变更分析',
    '消息内容', '点评',
    '卡组织', '发卡银行', '年费标准', '有效期限',
    '原文链接', '发布时间', '作者',
    '银行', '标题', '关键信息',
}

# ── 信用卡领域合法分类（用于 LLM 审核等校验场景） ─────────
VALID_CATEGORIES = {
    '新卡', '权益变更', '活动', '公告', '其他',
}


def ensure_dirs() -> None:
    """确保所有常用目录存在。首次运行调用一次即可。"""
    for d in [DATA_DIR, ARCHIVE_DIR, TEMP_DIR, DEFAULT_IMAGES_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def short_path(p: str | Path) -> str:
    """返回相对于 PROJECT_ROOT 的短路径，用于日志显示。"""
    return str(Path(p).relative_to(PROJECT_ROOT)) if PROJECT_ROOT in Path(p).parents else str(p)
