"""
L2 OCR 模块 — 微信公众号正文图片文字识别

依据 doc/mode_c_公众号文章解析改进规范.md 第 7.5 / 7.8 节实现：
- OCR 引擎封装（rapidocr_onnxruntime，CPU/Windows 兼容，首次初始化策略）；
- 图片安全下载（协议/大小/重定向限制）；
- 断点续跑：进度状态持久化，进程中断后可幂等恢复；
- 图片哈希去重：同图不重复识别；
- 置信度聚合：词级 → 行级 → 图片级；
- 预处理（放大/灰度）为可选项，默认关闭，须回归验证后启用；
- 并发数、批大小、超时均为可配置项；
- 二维码/头像/尾图可执行过滤规则，支持人工强制纳入。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

import requests
from PIL import Image

from common.extraction import build_content_block
from common.wechat_fetch import REQUEST_HEADERS, ALLOWED_SCHEMES

# ── 默认配置（全部可覆盖，不写死） ───────────────────────
DEFAULT_CONFIG = {
    "engine": "rapidocr_onnxruntime",
    "model_cache_dir": "",            # 空 = 使用引擎默认模型目录
    "preprocess": "none",             # "none" | "gray" | "scale2x" | "gray_scale2x"
    "max_image_bytes": 10 * 1024 * 1024,   # 单图最大下载字节
    "image_timeout": 30,              # 单图下载超时（秒）
    "download_retries": 1,            # 下载失败重试次数
    "ocr_retries": 1,                 # OCR 失败重试次数
    "ocr_timeout": 120,               # 单图 OCR 预算（秒，超过则跳过标记）
    "batch_size": 20,                 # 每批图片数
    "max_workers": 1,                 # 并发数（rapidocr 单实例线程不安全，默认 1）
    "min_confidence": 0.5,            # 低于此置信度的行丢弃
    "filter_qt_code": True,           # 过滤二维码图片
    "filter_small_images": True,      # 过滤过小图片（头像等）
    "small_image_min_side": 120,      # 小于该短边视为装饰图
    "skip_leading": 1,                # 跳过正文开头 N 张（头图/引导图）
    "skip_trailing": 1,               # 跳过正文结尾 N 张（尾图/二维码）
    "manual_include_images": [],      # 人工强制纳入识别的图片标识（覆盖过滤）
}

# 二维码/装饰图启发式规则（可执行过滤）
_QR_TAGS = ("qrcode", "二维码")
_QR_TEXT_RE = re.compile(r"长按|扫一扫|扫码|识别二维码|关注", re.IGNORECASE)


class OCRModule:
    """OCR 引擎封装 + 断点续跑 + 批处理。

    线程安全声明：同一 OCRModule 实例的进度读写受内部锁保护，
    但单个实例并发调用 ocr_images() 仍不推荐（进度文件原子替换可保证
    不损坏，但语义上以串行为准）。如需并行请使用不同 workdir 的实例。
    """

    def __init__(self, workdir: str | Path = "", config: Optional[dict] = None):
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.workdir = Path(workdir) if workdir else Path("ocr_work")
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.progress_path = self.workdir / "ocr_progress.json"
        self._engine = None
        self._lock = threading.Lock()          # 保护引擎实际识别调用（串行）
        self._init_lock = threading.Lock()     # 风险项：保护引擎首次初始化
        self._progress_lock = threading.Lock() # 风险项：保护进度读写
        self._engine_stalled = False           # P1-4：引擎失速标志（超时后置位）
        self._load_progress()

    # ── 进度持久化（断点续跑） ──────────────────────────

    def _load_progress(self) -> None:
        with self._progress_lock:
            if self.progress_path.exists():
                try:
                    self.progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self.progress = {}
            else:
                self.progress = {}

    def _save_progress(self) -> None:
        with self._progress_lock:
            # 风险项：唯一临时文件名，避免并发覆盖同一 .tmp
            tmp = self.progress_path.with_suffix(
                f".tmp.{time.time_ns()}.{os.getpid()}"
            )
            tmp.write_text(
                json.dumps(self.progress, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            os.replace(tmp, self.progress_path)

    def _mark(self, image_key: str, status: str, text: str = "", confidence: float = 0.0) -> None:
        self.progress[image_key] = {
            "status": status,           # "done" | "failed" | "skipped"
            "text": text,
            "confidence": round(float(confidence), 3),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._save_progress()

    # ── 引擎初始化（首次初始化策略） ─────────────────────

    def _get_engine(self):
        # 风险项：初始化锁，max_workers>1 时防止重复初始化
        if self._engine is None:
            with self._init_lock:
                if self._engine is None:
                    from rapidocr_onnxruntime import RapidOCR
                    kwargs = {}
                    if self.cfg["model_cache_dir"]:
                        kwargs["model_dir"] = self.cfg["model_cache_dir"]
                    self._engine = RapidOCR(**kwargs)
        return self._engine

    def reset_engine(self) -> None:
        """P1-4：引擎失速后显式重置。丢弃旧引擎引用并清空失速标志。"""
        with self._init_lock:
            self._engine = None
            self._engine_stalled = False

    # ── 图片安全下载 ─────────────────────────────────────

    def download_image(self, url: str, save_path: str | Path) -> Optional[str]:
        """下载图片到本地（协议/大小限制 + 重试）。返回本地路径或 None。"""
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        if parts.scheme not in ALLOWED_SCHEMES:
            return None
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(self.cfg["download_retries"] + 1):
            try:
                resp = requests.get(
                    url, headers=REQUEST_HEADERS,
                    timeout=self.cfg["image_timeout"], stream=True,
                    allow_redirects=True,
                )
                from common.wechat_fetch import is_safe_redirect
                if resp.url and not is_safe_redirect(resp.url):
                    return None
                resp.raise_for_status()
                total = 0
                chunks = []
                for chunk in resp.iter_content(chunk_size=65536):
                    total += len(chunk)
                    if total > self.cfg["max_image_bytes"]:
                        return None
                    chunks.append(chunk)
                save_path.write_bytes(b"".join(chunks))
                return str(save_path)
            except Exception:
                if attempt >= self.cfg["download_retries"]:
                    return None
        return None

    # ── 图片哈希去重 ─────────────────────────────────────

    @staticmethod
    def image_hash(path: str | Path) -> str:
        """文件内容 md5（前 12 位），用于同图去重。"""
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:12]

    # ── 预处理（可选，默认关闭） ─────────────────────────

    def _preprocess(self, path: str | Path) -> Optional[str]:
        """按配置对图片做预处理，返回新路径或原路径。"""
        mode = self.cfg["preprocess"]
        if mode == "none":
            return str(path)
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
                if "gray" in mode:
                    img = img.convert("L")
                if "scale2x" in mode:
                    w, h = img.size
                    img = img.resize((w * 2, h * 2), Image.LANCZOS)
                out = Path(path).with_suffix(".pre.png")
                img.save(out, "PNG")
                return str(out)
        except Exception:
            return str(path)

    # ── 单图 OCR（超时预算 + 重试 + 失败跳过） ──────────

    def _ocr_single(self, image_path: str | Path) -> dict:
        """识别单张图片。返回 {texts: [...], confidence: float, ok: bool}。

        P1-4 修复：RapidOCR 同步调用无法硬中断，因此不再声称“硬超时”。
        超时后置位 _engine_stalled，后续图片直接跳过识别（不向同一引擎
        提交新任务），由调用方决定 reset_engine() 重建或放弃本批。
        """
        if self._engine_stalled:
            return {"ok": False, "texts": [], "confidence": 0.0,
                    "error": "engine_stalled"}
        engine = self._get_engine()
        target = self._preprocess(image_path)
        for attempt in range(self.cfg["ocr_retries"] + 1):
            try:
                # rapidocr 同步调用，无法硬中断；用线程+超时预算近似
                result_box = {}
                def _run():
                    with self._lock:  # 单引擎实例串行
                        result_box["r"] = engine(target)
                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join(timeout=self.cfg["ocr_timeout"])
                if t.is_alive():
                    # P1-4：引擎疑似卡死。置位失速标志，本图记为失败，
                    # 且后续图片不再向该引擎提交新任务（避免线程积压）。
                    self._engine_stalled = True
                    return {"ok": False, "texts": [], "confidence": 0.0,
                            "error": "ocr_timeout_engine_stalled"}
                result = result_box.get("r", (None, None))[0] or []
                lines = []
                confs = []
                for item in result:
                    text = str(item[1]).strip()
                    conf = float(item[2]) if len(item) > 2 else 0.0
                    if not text:
                        continue
                    if conf < self.cfg["min_confidence"]:
                        continue
                    lines.append(text)
                    confs.append(conf)
                avg_conf = (sum(confs) / len(confs)) if confs else 0.0
                return {"ok": True, "texts": lines, "confidence": round(avg_conf, 3)}
            except Exception as e:
                if attempt >= self.cfg["ocr_retries"]:
                    return {"ok": False, "texts": [], "confidence": 0.0, "error": str(e)[:120]}
        return {"ok": False, "texts": [], "confidence": 0.0, "error": "unknown"}

    # ── 二维码/装饰图过滤 ───────────────────────────────

    def _is_filtered(self, image_path: str | Path, idx: int, total: int) -> tuple[bool, str]:
        """返回 (是否过滤, 原因)。支持人工强制纳入。"""
        name = Path(image_path).name
        if name in self.cfg["manual_include_images"]:
            return False, ""
        n = self.cfg["skip_leading"]
        if idx < n:
            return True, f"leading_image:{idx}"
        if idx >= total - self.cfg["skip_trailing"]:
            return True, f"trailing_image:{idx}"
        try:
            with Image.open(image_path) as im:
                w, h = im.size
            if self.cfg["filter_small_images"] and min(w, h) < self.cfg["small_image_min_side"]:
                return True, f"small_image:{w}x{h}"
            if self.cfg["filter_qt_code"]:
                # 二维码启发式：近似正方形 + 尺寸较小
                if max(w, h) < 500 and abs(w - h) / max(w, h) < 0.2 and w < 400:
                    return True, f"qr_like:{w}x{h}"
        except Exception:
            pass
        # 文件名含二维码/关注等提示
        if self.cfg["filter_qt_code"] and _QR_TEXT_RE.search(name):
            return True, "qr_name"
        return False, ""

    # ── 批处理入口（断点续跑 + 去重 + 过滤） ─────────────

    def ocr_images(
        self,
        image_items: list[dict],
        *,
        force: bool = False,
    ) -> list[dict]:
        """识别一组图片。

        Args:
            image_items: [{"url":..., "local_path":..., "image_id":...}, ...]
                其中 local_path 可选（没有则自动下载）。
            force: True 时忽略已完成的断点记录重新识别。

        Returns:
            [{"image_id":..., "ok":..., "texts":[...], "confidence":...,
              "status":"done|failed|skipped", "skip_reason":...}, ...]
        """
        # 1) 确保本地图片存在
        prepared = []
        for i, item in enumerate(image_items):
            img = dict(item)
            local = img.get("local_path", "")
            if not local or not Path(local).exists():
                if not img.get("url"):
                    continue
                local = self.download_image(
                    img["url"],
                    self.workdir / f"img_{img.get('image_id', i)}_{i:03d}.img",
                )
                if not local:
                    img["status"] = "failed"
                    img["skip_reason"] = "download_failed"
                    prepared.append(img)
                    continue
                img["local_path"] = local
            prepared.append(img)

        # 2) 哈希去重
        seen_hashes: dict[str, str] = {}
        unique = []
        for img in prepared:
            if img.get("status") == "failed":
                continue
            h = self.image_hash(img["local_path"])
            if h in seen_hashes:
                img["status"] = "skipped"
                img["skip_reason"] = f"duplicate_of:{seen_hashes[h]}"
                continue
            seen_hashes[h] = img.get("image_id", img["local_path"])
            unique.append(img)

        # 3) 过滤 + 断点跳过
        todo = []
        total = len(unique)
        for idx, img in enumerate(unique):
            key = img.get("image_id") or img["local_path"]
            if not force and key in self.progress and self.progress[key]["status"] == "done":
                img["status"] = "done"
                img["texts"] = [self.progress[key]["text"]] if self.progress[key]["text"] else []
                img["confidence"] = self.progress[key]["confidence"]
                img["from_cache"] = True
                continue
            filtered, reason = self._is_filtered(img["local_path"], idx, total)
            if filtered:
                img["status"] = "skipped"
                img["skip_reason"] = reason
                self._mark(key, "skipped", "", 0.0)
                continue
            img["status"] = "pending"
            todo.append(img)

        # 4) 分批并发识别
        results: list[dict] = []
        for start in range(0, len(todo), self.cfg["batch_size"]):
            batch = todo[start:start + self.cfg["batch_size"]]
            with ThreadPoolExecutor(max_workers=self.cfg["max_workers"]) as pool:
                futures = {pool.submit(self._ocr_single, img["local_path"]): img for img in batch}
                for fut in as_completed(futures):
                    img = futures[fut]
                    key = img.get("image_id") or img["local_path"]
                    ocr = fut.result()
                    if ocr["ok"]:
                        img["status"] = "done"
                        img["texts"] = ocr["texts"]
                        img["confidence"] = ocr["confidence"]
                        self._mark(key, "done", " | ".join(ocr["texts"]), ocr["confidence"])
                    else:
                        img["status"] = "failed"
                        img["skip_reason"] = ocr.get("error", "ocr_failed")
                        self._mark(key, "failed", "", 0.0)

        # 5) 合并结果（保持输入顺序）
        merged = []
        for img in prepared:
            if img.get("status") == "failed":
                merged.append(img)
                continue
            merged.append(img)
        return merged


# ── 便捷函数：OCR 结果 → content_blocks / 字段级证据 ────

def ocr_results_to_blocks(ocr_results: list[dict]) -> tuple[list[dict], list[str]]:
    """将 OCR 结果转换为 content_blocks（ocr_fact / ocr_noise）与噪音标记。

    返回 (blocks, noise_flags)。
    """
    blocks: list[dict] = []
    noise_flags: list[str] = []
    for r in ocr_results:
        if r.get("status") != "done" or not r.get("texts"):
            continue
        image_id = r.get("image_id", "")
        for line in r["texts"]:
            btype = _classify_ocr_line(line)
            blocks.append(
                build_content_block(
                    btype,
                    text=line,
                    image_id=image_id,
                    confidence=r.get("confidence", 0.0),
                )
            )
            if btype == "ocr_noise":
                noise_flags.append("ocr_noise")
            elif btype == "image_cta":
                noise_flags.append("image_cta")
    return blocks, noise_flags


def _classify_ocr_line(text: str) -> str:
    """行级 OCR 文本分类：事实内容 / 引导文案 / 噪音。"""
    stripped = text.strip()
    if not stripped:
        return "ocr_noise"
    if len(stripped) < 4:
        return "ocr_noise"
    # CTA 引导文案
    if re.search(r"点击|立即|查看详情|马上|参与|报名|申卡|办卡|申请|GO$|扫码", stripped):
        return "image_cta"
    # 页脚/版权/导航噪音
    if re.search(r"广告|版权|客服热线|公众号|长按|关注|置顶|阅读原文|预览时", stripped):
        return "ocr_noise"
    return "ocr_fact"


def aggregate_confidence(blocks: list[dict]) -> float:
    """字段级置信度聚合：ocr_fact 块置信度均值。"""
    confs = [
        float(b.get("confidence", 0.0))
        for b in blocks
        if b.get("type") == "ocr_fact" and b.get("confidence")
    ]
    return round(sum(confs) / len(confs), 3) if confs else 0.0
