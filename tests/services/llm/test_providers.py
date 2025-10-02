"""Tests for LLM provider implementations and registry utilities."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.services.llm.providers import (
    Claude35SonnetProvider,
    Gemini15FlashProvider,
    GPT4MiniProvider,
    GPT41Provider,
    LLMConfigurationError,
    LLMProviderError,
    LLMProviderResponse,
    LLMRateLimitError,
    ProviderRegistry,
    _coalesce_claude_text,
    _coalesce_gemini_text,
    _coalesce_response_text,
    _import_module,
)
from src.services.llm.settings import LLMSettings


@pytest.fixture
def mock_settings():
    """Create mock LLM settings for testing."""
    settings = Mock(spec=LLMSettings)
    settings.openai_api_key = "test-openai-key"
    settings.openai_organization = "test-org"
    settings.anthropic_api_key = "test-anthropic-key"
    settings.google_api_key = "test-google-key"
    settings.request_timeout = 30.0
    settings.default_temperature = 0.7
    settings.default_max_output_tokens = 1000
    return settings


class TestImportModule:
    """Tests for the _import_module utility function."""

    def test_imports_existing_module(self):
        """Should successfully import standard library modules."""
        json_module = _import_module("json")
        assert json_module is not None
        assert hasattr(json_module, "loads")

    def test_returns_none_for_missing_module(self):
        """Should return None for non-existent modules."""
        result = _import_module("nonexistent_module_12345")
        assert result is None


class TestGPT41Provider:
    """Tests for OpenAI GPT-4.1 provider implementation."""

    def test_provider_attributes(self, mock_settings):
        """Should have correct provider metadata."""
        provider = GPT41Provider(mock_settings)
        assert provider.provider_name == "openai-gpt4.1"
        assert provider.model_name == "gpt-4.1"
        assert provider.max_context_tokens == 128_000
        assert provider.name == "openai-gpt4.1"
        assert provider.model == "gpt-4.1"

    def test_is_available_with_api_key(self, mock_settings):
        """Should be available when API key is configured."""
        provider = GPT41Provider(mock_settings)
        assert provider.is_available() is True

    def test_is_available_without_api_key(self, mock_settings):
        """Should not be available when API key is missing."""
        mock_settings.openai_api_key = None
        provider = GPT41Provider(mock_settings)
        assert provider.is_available() is False

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_with_missing_module(self, mock_import, mock_settings):
        """Should handle missing openai module gracefully."""
        mock_import.return_value = None
        provider = GPT41Provider(mock_settings)
        client, error_cls, rate_cls = provider._client_tuple()
        assert client is None
        assert error_cls is None
        assert rate_cls is None

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_with_module(self, mock_import, mock_settings):
        """Should create client when openai module is available."""
        mock_module = Mock()
        mock_openai_cls = Mock()
        mock_module.OpenAI = mock_openai_cls
        mock_module.OpenAIError = Exception
        mock_module.RateLimitError = Exception
        mock_import.return_value = mock_module

        provider = GPT41Provider(mock_settings)
        client, error_cls, rate_cls = provider._client_tuple()

        mock_openai_cls.assert_called_once_with(
            api_key="test-openai-key",
            organization="test-org",
            timeout=30.0,
        )
        assert client == mock_openai_cls.return_value
        assert error_cls is Exception
        assert rate_cls is Exception

    @patch("src.services.llm.providers._import_module")
    def test_generate_raises_config_error_no_client(self, mock_import, mock_settings):
        """Should raise configuration error when client is unavailable."""
        mock_import.return_value = None
        provider = GPT41Provider(mock_settings)

        with pytest.raises(LLMConfigurationError, match="OpenAI client is unavailable"):
            provider.generate("test prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_raises_config_error_no_key(self, mock_import, mock_settings):
        """Should raise configuration error when API key is missing."""
        mock_module = Mock()
        mock_module.OpenAI = Mock()
        mock_import.return_value = mock_module
        mock_settings.openai_api_key = None

        provider = GPT41Provider(mock_settings)

        with pytest.raises(
            LLMConfigurationError, match="OPENAI_API_KEY is not configured"
        ):
            provider.generate("test prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_success(self, mock_import, mock_settings):
        """Should generate response successfully."""
        mock_module = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_response.output_text = "Generated response"
        mock_client.responses.create.return_value = mock_response
        mock_module.OpenAI.return_value = mock_client
        mock_module.OpenAIError = Exception
        mock_module.RateLimitError = Exception
        mock_import.return_value = mock_module

        provider = GPT41Provider(mock_settings)
        result = provider.generate(
            "test prompt", max_output_tokens=500, temperature=0.5
        )

        assert isinstance(result, LLMProviderResponse)
        assert result.provider == "openai-gpt4.1"
        assert result.model == "gpt-4.1"
        assert result.content == "Generated response"
        assert "provider" in result.metadata
        assert "model" in result.metadata
        assert "timestamp" in result.metadata

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_missing_openai_class(self, mock_import, mock_settings):
        """Should fall back when OpenAI class is unavailable."""
        mock_module = Mock()
        mock_module.OpenAI = None
        mock_module.OpenAIError = ValueError
        mock_module.RateLimitError = TimeoutError
        mock_import.return_value = mock_module

        provider = GPT41Provider(mock_settings)
        client, error_cls, rate_cls = provider._client_tuple()

        assert client is None
        assert error_cls is ValueError
        assert rate_cls is TimeoutError

    @patch("src.services.llm.providers._import_module")
    def test_generate_converts_rate_limit_error(self, mock_import, mock_settings):
        """Should translate client rate limit errors into LLMRateLimitError."""

        class FakeRateLimitError(Exception):
            pass

        mock_module = Mock()
        mock_client = Mock()
        mock_client.responses.create.side_effect = FakeRateLimitError("rate limited")
        mock_module.OpenAI.return_value = mock_client
        mock_module.OpenAIError = Exception
        mock_module.RateLimitError = FakeRateLimitError
        mock_import.return_value = mock_module

        provider = GPT41Provider(mock_settings)

        with pytest.raises(LLMRateLimitError, match="rate limited"):
            provider.generate("rate limited prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_converts_provider_error(self, mock_import, mock_settings):
        """Should translate client errors into LLMProviderError."""

        class FakeProviderError(Exception):
            pass

        mock_module = Mock()
        mock_client = Mock()
        mock_client.responses.create.side_effect = FakeProviderError("boom")
        mock_module.OpenAI.return_value = mock_client
        mock_module.OpenAIFineTuneError = None
        mock_module.OpenAIError = FakeProviderError
        mock_module.RateLimitError = None
        mock_import.return_value = mock_module

        provider = GPT41Provider(mock_settings)

        with pytest.raises(LLMProviderError, match="boom"):
            provider.generate("cause error")


class TestGPT4MiniProvider:
    """Tests for OpenAI GPT-4.1-mini provider implementation."""

    def test_provider_attributes(self, mock_settings):
        """Should have correct provider metadata."""
        provider = GPT4MiniProvider(mock_settings)
        assert provider.provider_name == "openai-gpt4.1-mini"
        assert provider.model_name == "gpt-4.1-mini"


class TestClaude35SonnetProvider:
    """Tests for Anthropic Claude 3.5 Sonnet provider implementation."""

    def test_provider_attributes(self, mock_settings):
        """Should have correct provider metadata."""
        provider = Claude35SonnetProvider(mock_settings)
        assert provider.provider_name == "claude-3.5-sonnet"
        assert provider.model_name == "claude-3-5-sonnet-latest"
        assert provider.max_context_tokens == 200_000

    def test_is_available_with_api_key(self, mock_settings):
        """Should be available when API key is configured."""
        provider = Claude35SonnetProvider(mock_settings)
        assert provider.is_available() is True

    def test_is_available_without_api_key(self, mock_settings):
        """Should not be available when API key is missing."""
        mock_settings.anthropic_api_key = None
        provider = Claude35SonnetProvider(mock_settings)
        assert provider.is_available() is False

    @patch("src.services.llm.providers._import_module")
    def test_generate_success(self, mock_import, mock_settings):
        """Should generate response successfully."""
        mock_module = Mock()
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="Claude response")]
        mock_client.messages.create.return_value = mock_response
        mock_module.Anthropic.return_value = mock_client
        mock_module.AnthropicError = Exception
        mock_module.RateLimitError = Exception
        mock_import.return_value = mock_module

        provider = Claude35SonnetProvider(mock_settings)
        result = provider.generate("test prompt")

        assert isinstance(result, LLMProviderResponse)
        assert result.provider == "claude-3.5-sonnet"
        assert result.model == "claude-3-5-sonnet-latest"
        assert result.content == "Claude response"

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_handles_missing_module(self, mock_import, mock_settings):
        """Should return empty tuple when anthropic module is missing."""
        mock_import.return_value = None
        provider = Claude35SonnetProvider(mock_settings)

        client, error_cls, rate_cls = provider._client_tuple()

        assert client is None
        assert error_cls is None
        assert rate_cls is None

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_handles_missing_class(self, mock_import, mock_settings):
        """Should surface error classes even when client class is missing."""
        mock_module = Mock()
        mock_module.Anthropic = None
        mock_module.AnthropicError = RuntimeError
        mock_module.RateLimitError = TimeoutError
        mock_import.return_value = mock_module

        provider = Claude35SonnetProvider(mock_settings)
        client, error_cls, rate_cls = provider._client_tuple()

        assert client is None
        assert error_cls is RuntimeError
        assert rate_cls is TimeoutError

    @patch("src.services.llm.providers._import_module")
    def test_generate_missing_client_raises_configuration(
        self, mock_import, mock_settings
    ):
        """Should raise configuration errors when client cannot be created."""
        mock_import.return_value = None
        provider = Claude35SonnetProvider(mock_settings)

        with pytest.raises(
            LLMConfigurationError,
            match="Anthropic client is unavailable",
        ):
            provider.generate("prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_missing_api_key(self, mock_import, mock_settings):
        """Should raise configuration error when API key missing."""
        mock_module = Mock()
        mock_client = Mock()
        mock_client.messages.create.return_value = Mock(content=[])
        mock_module.Anthropic.return_value = mock_client
        mock_module.AnthropicError = Exception
        mock_module.RateLimitError = Exception
        mock_import.return_value = mock_module
        mock_settings.anthropic_api_key = None

        provider = Claude35SonnetProvider(mock_settings)

        with pytest.raises(LLMConfigurationError, match="ANTHROPIC_API_KEY"):
            provider.generate("prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_translates_rate_limit(self, mock_import, mock_settings):
        """Should translate anthropic rate limit errors."""

        class FakeRateLimitError(Exception):
            pass

        mock_module = Mock()
        mock_client = Mock()
        mock_client.messages.create.side_effect = FakeRateLimitError("too fast")
        mock_module.Anthropic.return_value = mock_client
        mock_module.AnthropicError = Exception
        mock_module.RateLimitError = FakeRateLimitError
        mock_import.return_value = mock_module

        provider = Claude35SonnetProvider(mock_settings)

        with pytest.raises(LLMRateLimitError, match="too fast"):
            provider.generate("prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_translates_client_error(self, mock_import, mock_settings):
        """Should translate anthropic client errors."""

        class FakeClientError(Exception):
            pass

        mock_module = Mock()
        mock_client = Mock()
        mock_client.messages.create.side_effect = FakeClientError("broken")
        mock_module.Anthropic.return_value = mock_client
        mock_module.AnthropicError = FakeClientError
        mock_module.RateLimitError = None
        mock_import.return_value = mock_module

        provider = Claude35SonnetProvider(mock_settings)

        with pytest.raises(LLMProviderError, match="broken"):
            provider.generate("prompt")


class TestGemini15FlashProvider:
    """Tests for Google Gemini 1.5 Flash provider implementation."""

    def test_provider_attributes(self, mock_settings):
        """Should have correct provider metadata."""
        provider = Gemini15FlashProvider(mock_settings)
        assert provider.provider_name == "gemini-1.5-flash"
        assert provider.model_name == "gemini-1.5-flash"
        assert provider.max_context_tokens == 1_000_000

    def test_is_available_with_api_key(self, mock_settings):
        """Should be available when API key is configured."""
        provider = Gemini15FlashProvider(mock_settings)
        assert provider.is_available() is True

    def test_is_available_without_api_key(self, mock_settings):
        """Should not be available when API key is missing."""
        mock_settings.google_api_key = None
        provider = Gemini15FlashProvider(mock_settings)
        assert provider.is_available() is False

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_missing_module(self, mock_import, mock_settings):
        """Should return empty tuple when google generative module missing."""
        mock_import.return_value = None
        provider = Gemini15FlashProvider(mock_settings)

        client, error_cls, rate_cls = provider._client_tuple()

        assert client is None
        assert error_cls is None
        assert rate_cls is None

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_missing_helpers(self, mock_import, mock_settings):
        """Should expose error class even when helpers missing."""
        error_cls = type("GenerationException", (Exception,), {})
        module = SimpleNamespace(
            configure=None,
            GenerativeModel=None,
            types=SimpleNamespace(
                generation_types=SimpleNamespace(GenerationException=error_cls)
            ),
        )
        mock_import.return_value = module

        provider = Gemini15FlashProvider(mock_settings)
        client, error_cls_out, rate_cls = provider._client_tuple()

        assert client is None
        assert error_cls_out is error_cls
        assert rate_cls is None

    @patch("src.services.llm.providers._import_module")
    def test_client_tuple_success_configures_client(self, mock_import, mock_settings):
        """Should configure and cache generative AI client."""
        error_cls = type("GenerationException", (Exception,), {})
        configure_calls: list[dict[str, object]] = []

        def fake_configure(**kwargs):
            configure_calls.append(kwargs)

        class FakeModel:
            def __init__(self, model_name: str):
                self.model_name = model_name
                self.generate_content = Mock()

        module = SimpleNamespace(
            configure=fake_configure,
            GenerativeModel=FakeModel,
            types=SimpleNamespace(
                generation_types=SimpleNamespace(GenerationException=error_cls)
            ),
        )
        mock_import.return_value = module

        provider = Gemini15FlashProvider(mock_settings)
        client, error_cls_out, rate_cls = provider._client_tuple()

        assert isinstance(client, FakeModel)
        assert client.model_name == "gemini-1.5-flash"
        assert error_cls_out is error_cls
        assert rate_cls is None
        assert configure_calls
        call_kwargs = configure_calls[0]
        assert call_kwargs["api_key"] == "test-google-key"
        client_options = call_kwargs["client_options"]
        assert isinstance(client_options, dict)
        assert client_options["timeout"] == 30.0

        # Ensure cached client is reused without reconfiguring
        configure_calls.clear()
        cached_client, _, _ = provider._client_tuple()
        assert cached_client is client
        assert configure_calls == []

    @patch("src.services.llm.providers._import_module")
    def test_generate_missing_client_raises_configuration(
        self, mock_import, mock_settings
    ):
        """Should raise configuration error when client unavailable."""
        mock_import.return_value = None
        provider = Gemini15FlashProvider(mock_settings)

        with pytest.raises(LLMConfigurationError, match="Gemini client is unavailable"):
            provider.generate("prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_missing_api_key(self, mock_import, mock_settings):
        """Should raise configuration error when API key missing."""
        error_cls = type("GenerationException", (Exception,), {})

        class FakeModel:
            def __init__(self, model_name: str):
                self.generate_content = Mock()

        module = SimpleNamespace(
            configure=lambda **kwargs: None,
            GenerativeModel=FakeModel,
            types=SimpleNamespace(
                generation_types=SimpleNamespace(GenerationException=error_cls)
            ),
        )
        mock_import.return_value = module
        mock_settings.google_api_key = None

        provider = Gemini15FlashProvider(mock_settings)

        with pytest.raises(LLMConfigurationError, match="GOOGLE_API_KEY"):
            provider.generate("prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_translates_client_error(self, mock_import, mock_settings):
        """Should translate generation exceptions into provider errors."""
        error_cls = type("GenerationException", (Exception,), {})

        class FakeModel:
            def __init__(self, model_name: str):
                def _raise(prompt, generation_config):
                    raise error_cls("failed")

                self.generate_content = Mock(side_effect=_raise)

        module = SimpleNamespace(
            configure=lambda **kwargs: None,
            GenerativeModel=FakeModel,
            types=SimpleNamespace(
                generation_types=SimpleNamespace(GenerationException=error_cls)
            ),
        )
        mock_import.return_value = module

        provider = Gemini15FlashProvider(mock_settings)

        with pytest.raises(LLMProviderError, match="failed"):
            provider.generate("prompt")

    @patch("src.services.llm.providers._import_module")
    def test_generate_success(self, mock_import, mock_settings):
        """Should generate responses successfully."""
        error_cls = type("GenerationException", (Exception,), {})

        class FakeResponse:
            text = "Gemini success"

        class FakeModel:
            def __init__(self, model_name: str):
                self.generate_content = Mock(return_value=FakeResponse())

        module = SimpleNamespace(
            configure=lambda **kwargs: None,
            GenerativeModel=FakeModel,
            types=SimpleNamespace(
                generation_types=SimpleNamespace(GenerationException=error_cls)
            ),
        )
        mock_import.return_value = module

        provider = Gemini15FlashProvider(mock_settings)
        response = provider.generate("prompt", metadata={"foo": "bar"})

        assert isinstance(response, LLMProviderResponse)
        assert response.provider == "gemini-1.5-flash"
        assert response.model == "gemini-1.5-flash"
        assert response.content == "Gemini success"
        assert response.metadata["foo"] == "bar"
        assert response.metadata["provider"] == "gemini-1.5-flash"


class TestProviderRegistry:
    """Tests for the provider registry functionality."""

    def test_registry_contains_default_providers(self):
        """Should contain all default provider implementations."""
        names = list(ProviderRegistry.names())
        assert "openai-gpt4.1" in names
        assert "openai-gpt4.1-mini" in names
        assert "claude-3.5-sonnet" in names
        assert "gemini-1.5-flash" in names

    def test_create_provider_success(self, mock_settings):
        """Should create provider instances successfully."""
        provider = ProviderRegistry.create("openai-gpt4.1", mock_settings)
        assert isinstance(provider, GPT41Provider)

    def test_create_provider_unknown(self, mock_settings):
        """Should raise KeyError for unknown provider slugs."""
        with pytest.raises(KeyError, match="Unknown provider 'unknown-provider'"):
            ProviderRegistry.create("unknown-provider", mock_settings)

    def test_register_custom_provider(self, mock_settings):
        """Should allow registration of custom providers."""

        class CustomProvider(GPT41Provider):
            provider_name = "custom-test"

        ProviderRegistry.register("custom-test", CustomProvider)
        provider = ProviderRegistry.create("custom-test", mock_settings)
        assert isinstance(provider, CustomProvider)


class TestResponseCoalescing:
    """Tests for response text extraction utilities."""

    def test_coalesce_response_text_output_text(self):
        """Should extract text from output_text attribute."""
        response = Mock()
        response.output_text = "Test output"
        result = _coalesce_response_text(response)
        assert result == "Test output"

    def test_coalesce_response_text_choices(self):
        """Should extract text from choices structure."""
        response = Mock()
        response.output_text = None
        response.output = None
        choice = Mock()
        choice.message = {"content": "Choice content"}
        response.choices = [choice]

        result = _coalesce_response_text(response)
        assert result == "Choice content"

    def test_coalesce_response_text_output_list(self):
        """Should join list outputs when present."""
        response = Mock()
        response.output_text = None
        response.output = ["first", "second", ""]
        response.choices = None

        result = _coalesce_response_text(response)
        assert result == "first\nsecond"

    def test_coalesce_response_text_output_scalar(self):
        """Should coerce scalar output to string."""
        response = Mock()
        response.output_text = None
        response.output = 123
        response.choices = None

        result = _coalesce_response_text(response)
        assert result == "123"

    def test_coalesce_response_text_empty(self):
        """Should return empty string when no text found."""
        response = Mock()
        response.output_text = None
        response.output = None
        response.choices = None

        result = _coalesce_response_text(response)
        assert result == ""

    def test_coalesce_claude_text_content_list(self):
        """Should extract text from Claude content list."""
        response = Mock()
        text_item = Mock()
        text_item.text = "Claude text"
        response.content = [text_item]

        result = _coalesce_claude_text(response)
        assert result == "Claude text"

    def test_coalesce_claude_text_direct_text(self):
        """Should extract text from direct text attribute."""
        response = Mock()
        response.content = None
        response.text = "Direct text"

        result = _coalesce_claude_text(response)
        assert result == "Direct text"

    def test_coalesce_gemini_text_candidates(self):
        """Should extract text from Gemini candidates structure."""
        response = Mock()
        response.text = None

        part = Mock()
        part.text = "Gemini text"
        content = Mock()
        content.parts = [part]
        candidate = Mock()
        candidate.content = content
        response.candidates = [candidate]

        result = _coalesce_gemini_text(response)
        assert result == "Gemini text"

    def test_coalesce_gemini_text_direct_text(self):
        """Should extract text from direct text attribute."""
        response = Mock()
        response.text = "Direct Gemini text"

        result = _coalesce_gemini_text(response)
        assert result == "Direct Gemini text"
