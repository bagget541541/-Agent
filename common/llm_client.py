"""
统一 LLM 客户端 — 集中管理 OpenAI 兼容 API 调用。

消除 llm_review.py / rag_query.py / scorer.py 三处重复的 HTTP 调用代码。

## 配置源

| 模式 | 来源 | 优先级 | 示例 |
|------|------|--------|------|
| 环境变量 | `LLM_PROVIDER` + 各 provider Key | 优先 | groq / openrouter / grok |
| 配置文件 | `~/.llm_config.json` | 降级 | `{"api_key":"sk-...","api_base":"...","model":"..."}` |
| 显式参数 | `LlmClient()` 构造函数 | 最高 | `LlmClient(api_key="...")` |

## 用法

```python
from common.llm_client import LlmClient

# 自动检测环境变量（groq / openrouter / grok）
client = LlmClient()
resp = client.call("system prompt", "user message", temperature=0.1)

# 指定 provider
client = LlmClient(provider="openrouter")
resp = client.call(sys_msg, user_msg, max_tokens=2048, timeout=60)

# 使用配置文件（deepseek 等）
client = LlmClient(config_source="file")
resp = client.call("", prompt, temperature=0.3, max_tokens=2048)
```
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ── 返回类型 ─────────────────────────────────────────────

@dataclass
class LlmResponse:
    """统一的 LLM 调用返回。"""
    content: str = ""
    success: bool = False
    error: Optional[str] = None
    usage: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success


# ── 多 Provider 配置（环境变量模式） ─────────────────

_ENV_PROVIDERS = {
    "groq": {
        "api_key_var": "GROQ_API_KEY",
        "model_var": "GROQ_MODEL",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "llama-3.3-70b-versatile",
        "key_error": "未设置 GROQ_API_KEY 环境变量",
    },
    "mimo": {
        "api_key_var": "MIMO_API_KEY",
        "model_var": "MIMO_MODEL",
        "url_var": "MIMO_API_URL",
        "default_url": "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
        "default_model": "mimo-v2-pro",
        "key_error": "未设置 MIMO_API_KEY 环境变量",
    },
    "grok": {
        "api_key_var": "GROK_API_KEY",
        "model_var": "GROK_MODEL",
        "url": "https://api.x.ai/v1/chat/completions",
        "default_model": "grok-2-latest",
        "key_error": "未设置 GROK_API_KEY 环境变量",
    },
    "openrouter": {
        "api_key_var": "OPENAI_API_KEY",
        "model_var": "OPENAI_MODEL",
        "url_var": "OPENAI_API_URL",
        "default_url": "https://openrouter.ai/api/v1/chat/completions",
        "default_model": "qwen/qwen3-32b",
        "key_error": "未设置 OPENAI_API_KEY 环境变量",
    },
}

_CONFIG_FILE_PATH = os.path.expanduser("~/.llm_config.json")
_CONFIG_PRINTED = False


# ── .env 加载（简化版，零外部依赖） ─────────────────

def _load_dotenv() -> None:
    """简易 .env 加载，无需 python-dotenv 依赖。

    只在项目根目录存在 .env 文件时加载，且不覆盖已有环境变量。
    与 llm_review.py 中的 _load_dotenv() 逻辑一致。
    """
    # 向上搜索项目根目录（通过 setup.py / .git / pyproject.toml 等标记）
    search = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        env_path = os.path.join(search, ".env")
        if os.path.exists(env_path):
            break
        parent = os.path.dirname(search)
        if parent == search:
            return
        search = parent
    else:
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


# 模块级加载一次
_load_dotenv()


# ── 统一配置加载 ─────────────────────────────────────

def _get_provider_config(provider: str = None) -> dict:
    """从环境变量解析 provider 配置，返回 {'api_key', 'model', 'url'}。

    环境变量未设时，回退读取 ~/.llm_config.json（兼容 mimo 等文件配置场景）。
    """
    provider = provider or os.environ.get("LLM_PROVIDER", "groq").lower()

    cfg = _ENV_PROVIDERS.get(provider, _ENV_PROVIDERS["openrouter"])
    api_key = os.environ.get(cfg["api_key_var"], "")

    if cfg.get("url_var"):
        url = os.environ.get(cfg["url_var"], cfg.get("default_url", ""))
    else:
        url = cfg["url"]

    model = os.environ.get(cfg["model_var"], cfg["default_model"])

    # 环境变量未设 → 回退读 ~/.llm_config.json
    if not api_key:
        file_cfg = _load_file_config()
        if file_cfg:
            api_key = file_cfg.get("api_key", "")
            if not url or url == cfg.get("default_url", ""):
                url = file_cfg.get("api_base", "")
                if url and not url.endswith("/chat/completions"):
                    url = url.rstrip("/") + "/chat/completions"
            if not model or model == cfg["default_model"]:
                model = file_cfg.get("model", "") or model

    return {
        "api_key": api_key,
        "model": model,
        "url": url,
        "key_error": cfg["key_error"],
        "provider": provider,
    }


def _load_file_config() -> Optional[dict]:
    """从 ~/.llm_config.json 读取 LLM 配置。

    兼容 scorer.py 的配置格式：
        {"api_key": "sk-...", "api_base": "https://api.deepseek.com", "model": "deepseek-chat"}
    """
    if os.path.isfile(_CONFIG_FILE_PATH):
        try:
            with open(_CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg
        except Exception:
            pass

    # 降级到环境变量
    api_key = os.environ.get("LLM_API_KEY", "")
    api_base = os.environ.get("LLM_API_BASE", "")
    model = os.environ.get("LLM_MODEL", "")
    if api_key and api_base:
        return {"api_key": api_key, "api_base": api_base, "model": model}

    return None


# ── 客户端类 ─────────────────────────────────────────

class LlmClient:
    """统一 LLM 客户端。

    Args:
        provider: 环境变量模式下的 provider 名称 ("groq" / "mimo" / "grok" / "openrouter")
        config_source: 配置源 "env"（环境变量）或 "file"（~/.llm_config.json）
        api_key: 显式指定 API Key（最高优先级）
        api_base: 显式指定 API Base URL
        model: 显式指定模型名
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        config_source: str = "env",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._provider = provider
        self._config_source = config_source
        self._explicit_key = api_key
        self._explicit_base = api_base
        self._explicit_model = model
        self._resolved_provider: Optional[str] = None
        self._resolved_model: Optional[str] = None
        self._resolved_url: Optional[str] = None
        self._resolved_key: Optional[str] = None

    def _resolve(self) -> bool:
        """解析最终的有效配置，返回是否可用。"""
        # 1. 显式参数优先
        if self._explicit_key and self._explicit_base:
            self._resolved_key = self._explicit_key
            self._resolved_url = f"{self._explicit_base.rstrip('/')}/chat/completions"
            self._resolved_model = self._explicit_model or "default"
            self._resolved_provider = "explicit"
            return True

        # 2. 环境变量模式
        if self._config_source == "env":
            cfg = _get_provider_config(self._provider)
            if cfg["api_key"] and cfg["url"]:
                self._resolved_key = cfg["api_key"]
                self._resolved_url = cfg["url"]
                self._resolved_model = cfg["model"]
                self._resolved_provider = cfg["provider"]
                return True
            self._print_warning(f"{cfg['key_error']}，LLM 不可用")
            return False

        # 3. 配置文件模式
        file_cfg = _load_file_config()
        if file_cfg:
            key = self._explicit_key or file_cfg.get("api_key", "")
            base = self._explicit_base or file_cfg.get("api_base", "")
            model = self._explicit_model or file_cfg.get("model", "")
            if key and base:
                self._resolved_key = key
                self._resolved_url = f"{base.rstrip('/')}/chat/completions"
                self._resolved_model = model or "default"
                self._resolved_provider = "file"
                return True
            self._print_warning("配置文件不完整（缺少 api_key 或 api_base）")
            return False

        self._print_warning(
            f"未找到 LLM 配置。环境变量未设置，{_CONFIG_FILE_PATH} 不存在。"
        )
        return False

    def _print_warning(self, msg: str) -> None:
        """打印警告（抑制重复）。"""
        print(f"  [LLM] {msg}", flush=True)

    def _print_config_once(self) -> None:
        """首次调用时打印配置摘要。"""
        global _CONFIG_PRINTED
        if _CONFIG_PRINTED:
            return
        _CONFIG_PRINTED = True
        key_hint = f"...{self._resolved_key[-4:]}" if self._resolved_key and len(self._resolved_key) >= 4 else "****"
        print(
            f"  [LLM配置] provider={self._resolved_provider}  "
            f"url={self._resolved_url}  model={self._resolved_model}  key={key_hint}",
            flush=True,
        )

    def call(
        self,
        system_msg: str = "",
        user_msg: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: int = 30,
    ) -> LlmResponse:
        """调用 LLM，返回统一响应。

        Args:
            system_msg: 系统提示词
            user_msg: 用户消息
            temperature: 温度参数 (0.0-1.0)
            max_tokens: 最大输出 token 数
            timeout: 请求超时秒数

        Returns:
            LlmResponse — 用 bool(response) 判断是否成功
        """
        import requests  # 延迟导入，降低模块加载副作用

        if not self._resolve():
            return LlmResponse(success=False, error="LLM 配置不可用")

        self._print_config_once()

        messages = []
        if system_msg:
            messages.append({"role": "system", "content": system_msg})
        messages.append({"role": "user", "content": user_msg})

        payload = {
            "model": self._resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self._resolved_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                self._resolved_url, headers=headers, json=payload, timeout=timeout
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            return LlmResponse(content=content, success=True, usage=usage)
        except requests.exceptions.Timeout:
            msg = f"LLM 请求超时（{timeout}s）"
            return LlmResponse(success=False, error=msg)
        except Exception as e:
            msg = f"LLM 调用失败：{e}"
            return LlmResponse(success=False, error=msg)

    @property
    def provider(self) -> Optional[str]:
        """当前使用的 provider 名称。"""
        return self._resolved_provider

    @property
    def model(self) -> Optional[str]:
        """当前使用的模型名。"""
        return self._resolved_model


# ── 兼容性函数（供 rag_query.py 等旧代码直接使用） ──

def call_llm_simple(
    system_msg: str,
    user_msg: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: int = 30,
) -> tuple[Optional[str], Optional[str]]:
    """简化版调用，兼容 rag_query.call_llm 的 (content, error) 签名。

    自动 fallback：主 provider 失败时尝试 mimo（从 ~/.llm_config.json 读取）。

    Returns:
        (content, None) 成功
        (None, error_msg) 失败
    """
    client = LlmClient()
    resp = client.call(system_msg, user_msg, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    if resp.success:
        return resp.content, None

    # 主 provider 失败 → 尝试 mimo fallback（仅在当前非 mimo 时）
    if client.provider != "mimo":
        fallback = LlmClient(provider="mimo")
        resp2 = fallback.call(system_msg, user_msg, temperature=temperature, max_tokens=max_tokens, timeout=max(timeout, 180))
        if resp2.success:
            return resp2.content, None

    return None, resp.error


def call_llm_simple_str(
    system_msg: str,
    user_msg: str,
    temperature: float = 0.1,
    max_tokens: int = 512,
    timeout: int = 30,
) -> str:
    """简化版调用，兼容 llm_review._call_llm 的 str 签名（失败返回空串）。

    Returns:
        str: LLM 响应文本，失败返回 ""
    """
    client = LlmClient()
    resp = client.call(system_msg, user_msg, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    return resp.content if resp.success else ""


def call_llm_file_config(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: int = 60,
    api_key: str = "",
    api_base: str = "",
    model: str = "",
) -> tuple[Optional[str], Optional[str]]:
    """使用文件配置模式调用 LLM，兼容 scorer.py 的调用方式。

    Returns:
        (content, None) 成功
        (None, error_msg) 失败
    """
    client = LlmClient(
        config_source="file",
        api_key=api_key or None,
        api_base=api_base or None,
        model=model or None,
    )
    # scorer 的 prompt 不含 system，直接作为 user_msg
    resp = client.call(user_msg=prompt, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    if resp.success:
        return resp.content, None
    return None, resp.error
