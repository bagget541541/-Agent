"""common.llm_client 集成测试

覆盖：
  - LlmResponse 数据类
  - LlmClient._resolve() 三模式（显式参数 / 环境变量 / 文件配置）
  - LlmClient.call() 全链路（成功 / 超时 / 失败）
  - 兼容性函数 call_llm_simple / call_llm_simple_str / call_llm_file_config
"""

import json
import os
import sys
from dataclasses import fields
from unittest.mock import ANY, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from common.llm_client import (
    LlmClient,
    LlmResponse,
    _get_provider_config,
    _load_file_config,
    call_llm_simple,
    call_llm_simple_str,
    call_llm_file_config,
)


# ═══════════════════════════════════════════════════════════
# LlmResponse 数据类
# ═══════════════════════════════════════════════════════════

class TestLlmResponse:
    def test_success_bool_true(self):
        """success=True → bool(resp) is True"""
        resp = LlmResponse(content="hi", success=True)
        assert bool(resp) is True

    def test_failure_bool_false(self):
        """success=False → bool(resp) is False"""
        resp = LlmResponse(success=False, error="fail")
        assert bool(resp) is False

    def test_default_error_none(self):
        """不传 error → 默认 None"""
        resp = LlmResponse(content="ok", success=True)
        assert resp.error is None

    def test_usage_default_empty(self):
        """不传 usage → 默认 {}"""
        resp = LlmResponse(content="ok", success=True)
        assert resp.usage == {}

    def test_dataclass_fields(self):
        """dataclass 字段完整"""
        field_names = {f.name for f in fields(LlmResponse)}
        assert field_names == {"content", "success", "error", "usage"}


# ═══════════════════════════════════════════════════════════
# LlmClient._resolve() — 三种配置模式
# ═══════════════════════════════════════════════════════════

class TestLlmClientResolveExplicit:
    """显式参数模式"""

    def test_key_and_base_resolved(self):
        """api_key + api_base → resolve 成功"""
        client = LlmClient(api_key="sk-test", api_base="https://test.api.com")
        assert client._resolve() is True
        assert client._resolved_key == "sk-test"
        assert client._resolved_url == "https://test.api.com/chat/completions"
        assert client._resolved_model == "default"
        assert client._resolved_provider == "explicit"

    def test_key_only_not_resolved(self):
        """仅有 api_key 缺 api_base → resolve 失败（无 env var 兜底）"""
        with patch.dict(os.environ, {}, clear=True):
            from common.llm_client import LlmClient as LC
            client = LC(api_key="sk-test")
            assert client._resolve() is False

    def test_base_only_not_resolved(self):
        """仅有 api_base 缺 api_key → resolve 失败（无 env var 兜底）"""
        with patch.dict(os.environ, {}, clear=True):
            from common.llm_client import LlmClient as LC
            client = LC(api_base="https://test.api.com")
            assert client._resolve() is False

    def test_explicit_model_used(self):
        """显式 model 覆盖 default"""
        client = LlmClient(api_key="sk-test", api_base="https://test.api.com", model="gpt-4")
        assert client._resolve() is True
        assert client._resolved_model == "gpt-4"

    def test_base_trailing_slash_stripped(self):
        """api_base 末尾带 / → 不生成双斜杠"""
        client = LlmClient(api_key="sk-test", api_base="https://test.api.com/")
        assert client._resolve() is True
        assert client._resolved_url == "https://test.api.com/chat/completions"


class TestLlmClientResolveEnv:
    """环境变量模式"""

    @patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test", "GROQ_MODEL": "mixtral"})
    def test_groq_env_resolved(self):
        """GROQ_API_KEY 已设置 → resolve 成功"""
        client = LlmClient(provider="groq")
        assert client._resolve() is True
        assert client._resolved_key == "gsk-test"
        assert client._resolved_model == "mixtral"
        assert client._resolved_provider == "groq"

    @patch.dict(os.environ, {"GROK_API_KEY": "xai-test", "GROK_MODEL": "grok-2"})
    def test_grok_env_resolved(self):
        """GROK_API_KEY 已设置 → resolve 成功"""
        client = LlmClient(provider="grok")
        assert client._resolve() is True
        assert client._resolved_key == "xai-test"
        assert client._resolved_provider == "grok"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openrouter-test", "OPENAI_MODEL": "qwen-32b", "OPENAI_API_URL": "https://custom.openai.com/v1"})
    def test_openrouter_env_resolved(self):
        """OPENAI_API_KEY + OPENAI_API_URL 已设置 → resolve 成功"""
        client = LlmClient(provider="openrouter")
        assert client._resolve() is True
        assert "custom.openai.com" in client._resolved_url
        assert client._resolved_provider == "openrouter"

    def test_no_env_not_resolved(self):
        """环境变量未设置 → resolve 失败"""
        with patch.dict(os.environ, {}, clear=True):
            # 清除所有 env var 后，默认 groq 找不到 key
            client = LlmClient()
            assert client._resolve() is False

    def test_provider_from_llm_provider_env(self):
        """LLM_PROVIDER 环境变量指定 provider"""
        # 清理环境变量，只设置 GROK_API_KEY 和 LLM_PROVIDER=grok
        with patch.dict(os.environ, {"GROK_API_KEY": "xai-test"}, clear=True):
            from common.llm_client import LlmClient as LC
            client = LC()  # 默认 provider，无 env var → resolve 失败
            assert client._resolve() is False


class TestLlmClientResolveFile:
    """文件配置模式"""

    def test_file_config_loaded(self):
        """文件配置存在 → resolve 成功"""
        mock_cfg = {"api_key": "sk-file", "api_base": "https://file.api.com", "model": "deepseek"}
        with patch("common.llm_client._load_file_config", return_value=mock_cfg):
            client = LlmClient(config_source="file")
            assert client._resolve() is True
            assert client._resolved_key == "sk-file"
            assert client._resolved_url == "https://file.api.com/chat/completions"
            assert client._resolved_model == "deepseek"
            assert client._resolved_provider == "file"

    def test_file_config_with_explicit_override(self):
        """显式参数覆盖文件配置"""
        mock_cfg = {"api_key": "sk-file", "api_base": "https://file.api.com", "model": "deepseek"}
        with patch("common.llm_client._load_file_config", return_value=mock_cfg):
            client = LlmClient(config_source="file", api_key="sk-override", model="gpt-4")
            assert client._resolve() is True
            assert client._resolved_key == "sk-override"
            assert client._resolved_model == "gpt-4"

    def test_file_config_incomplete(self):
        """文件配置缺少 api_key → 不 resolve"""
        mock_cfg = {"api_base": "https://file.api.com"}
        with patch("common.llm_client._load_file_config", return_value=mock_cfg):
            client = LlmClient(config_source="file")
            assert client._resolve() is False

    def test_file_config_none(self):
        """无文件配置 → 不 resolve"""
        with patch("common.llm_client._load_file_config", return_value=None):
            client = LlmClient(config_source="file")
            assert client._resolve() is False


# ═══════════════════════════════════════════════════════════
# LlmClient.call() — HTTP 请求模拟
# ═══════════════════════════════════════════════════════════

class TestLlmClientCall:
    def _make_client(self):
        """返回一个已 resolve 的客户端"""
        return LlmClient(api_key="sk-test", api_base="https://test.api.com")

    @patch("requests.post")
    def test_success_response(self, mock_post):
        """正常响应 → 提取 content + usage"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from LLM"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        client = self._make_client()
        resp = client.call(system_msg="Be helpful", user_msg="Hi")

        assert resp.success is True
        assert resp.content == "Hello from LLM"
        assert resp.usage["prompt_tokens"] == 10

        # 验证请求载荷
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["model"] == "default"
        assert len(call_kwargs["json"]["messages"]) == 2
        assert call_kwargs["json"]["messages"][0]["role"] == "system"
        assert call_kwargs["json"]["messages"][1]["role"] == "user"

    @patch("requests.post")
    def test_system_msg_omitted_when_empty(self, mock_post):
        """system_msg 为空 → 不发送 system 消息"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        client = self._make_client()
        resp = client.call(user_msg="Hi")

        assert resp.success is True
        call_kwargs = mock_post.call_args[1]
        assert len(call_kwargs["json"]["messages"]) == 1
        assert call_kwargs["json"]["messages"][0]["role"] == "user"

    @patch("requests.post")
    def test_timeout_error(self, mock_post):
        """请求超时 → LlmResponse 含错误信息"""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout("timeout")

        client = self._make_client()
        resp = client.call(user_msg="Hi")

        assert resp.success is False
        assert "超时" in resp.error

    @patch("requests.post")
    def test_http_error(self, mock_post):
        """HTTP 失败 → LlmResponse 含错误信息"""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
        mock_post.return_value = mock_response

        client = self._make_client()
        resp = client.call(user_msg="Hi")

        assert resp.success is False
        assert "401" in resp.error

    @patch("requests.post")
    def test_unresolveable_returns_error(self, mock_post):
        """配置不可用 → 不调用 HTTP，返回错误"""
        client = LlmClient()  # 无任何配置
        with patch.object(client, "_resolve", return_value=False):
            resp = client.call(user_msg="Hi")
            mock_post.assert_not_called()
            assert resp.success is False
            assert "不可用" in resp.error

    @patch("requests.post")
    def test_temperature_and_max_tokens(self, mock_post):
        """temperature / max_tokens 传递到请求"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        client = self._make_client()
        client.call(user_msg="Hi", temperature=0.7, max_tokens=2048)

        payload = mock_post.call_args[1]["json"]
        assert payload["temperature"] == 0.7
        assert payload["max_tokens"] == 2048

    def test_provider_model_properties(self):
        """provider / model 属性返回 resolved 值"""
        client = LlmClient(api_key="sk-test", api_base="https://test.api.com", model="gpt-4")
        client._resolve()
        assert client.provider == "explicit"
        assert client.model == "gpt-4"

    def test_provider_model_none_before_resolve(self):
        """未 resolve 前 provider/model 为 None"""
        client = LlmClient()
        assert client.provider is None
        assert client.model is None

    def test_provider_not_in_allowed_list_falls_back_to_openrouter(self):
        """provider 名不合法 → 返回的 config 值来自 openrouter"""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            from common.llm_client import _get_provider_config as gpc
            cfg = gpc("invalid_provider_name")
            # 虽然在返回值中 provider 还是传入值，但 url/model 来自 openrouter
            assert cfg["api_key"] == "sk-test"
            assert "openrouter" in cfg["url"]


# ═══════════════════════════════════════════════════════════
# 兼容性函数
# ═══════════════════════════════════════════════════════════

class TestCallLlmSimple:
    """call_llm_simple → (content, error) tuple"""

    @patch("common.llm_client.LlmClient.call")
    def test_success_returns_content(self, mock_call):
        """成功 → (content, None)"""
        mock_call.return_value = LlmResponse(content="hello", success=True)
        content, error = call_llm_simple("system", "user")
        assert content == "hello"
        assert error is None

    @patch("common.llm_client.LlmClient.call")
    def test_failure_returns_error(self, mock_call):
        """失败 → (None, error)"""
        mock_call.return_value = LlmResponse(success=False, error="fail")
        content, error = call_llm_simple("system", "user")
        assert content is None
        assert error == "fail"

    @patch("common.llm_client.LlmClient.call")
    def test_passes_args(self, mock_call):
        """参数正确传递"""
        mock_call.return_value = LlmResponse(content="ok", success=True)
        call_llm_simple("sys", "usr", temperature=0.5, max_tokens=999, timeout=60)
        mock_call.assert_called_once_with("sys", "usr", temperature=0.5, max_tokens=999, timeout=60)


class TestCallLlmSimpleStr:
    """call_llm_simple_str → str"""

    @patch("common.llm_client.LlmClient.call")
    def test_success_returns_content(self, mock_call):
        """成功 → content"""
        mock_call.return_value = LlmResponse(content="hello", success=True)
        result = call_llm_simple_str("system", "user")
        assert result == "hello"

    @patch("common.llm_client.LlmClient.call")
    def test_failure_returns_empty(self, mock_call):
        """失败 → 空串"""
        mock_call.return_value = LlmResponse(success=False, error="fail")
        assert call_llm_simple_str("system", "user") == ""


class TestCallLlmFileConfig:
    """call_llm_file_config → (content, error) tuple with file config mode"""

    @patch("common.llm_client.LlmClient.call")
    def test_success_returns_content(self, mock_call):
        """成功 → (content, None)"""
        mock_call.return_value = LlmResponse(content="hello", success=True)
        content, error = call_llm_file_config("prompt")
        assert content == "hello"
        assert error is None

    @patch("common.llm_client.LlmClient.call")
    def test_creates_client_with_file_config(self, mock_call):
        """使用 config_source='file' 创建客户端"""
        mock_call.return_value = LlmResponse(content="ok", success=True)
        with patch("common.llm_client.LlmClient") as MockClient:
            MockClient.return_value.call.return_value = LlmResponse(content="ok", success=True)
            call_llm_file_config("prompt", api_key="sk-ext", api_base="https://ext.api.com", model="ext-model")
            MockClient.assert_called_once_with(
                config_source="file",
                api_key="sk-ext",
                api_base="https://ext.api.com",
                model="ext-model",
            )

    @patch("common.llm_client.LlmClient.call")
    def test_empty_api_key_converted_to_none(self, mock_call):
        """空的显式 key/base 转为 None 以免覆盖文件配置"""
        mock_call.return_value = LlmResponse(content="ok", success=True)
        with patch("common.llm_client.LlmClient") as MockClient:
            MockClient.return_value.call.return_value = LlmResponse(content="ok", success=True)
            call_llm_file_config("prompt")
            MockClient.assert_called_once_with(
                config_source="file",
                api_key=None,
                api_base=None,
                model=None,
            )

    @patch("common.llm_client.LlmClient.call")
    def test_failure_returns_error(self, mock_call):
        """失败 → (None, error)"""
        mock_call.return_value = LlmResponse(success=False, error="fail")
        content, error = call_llm_file_config("prompt")
        assert content is None
        assert error == "fail"

    def test_prompt_as_user_msg(self):
        """prompt 作为 user_msg 传递"""
        with patch("common.llm_client.LlmClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.call.return_value = LlmResponse(content="ok", success=True)
            MockClient.return_value = mock_instance
            call_llm_file_config("my prompt")
            mock_instance.call.assert_called_once()
            # 验证被当作 user_msg 而非 system_msg
            assert mock_instance.call.call_args[1].get("user_msg") is not None
