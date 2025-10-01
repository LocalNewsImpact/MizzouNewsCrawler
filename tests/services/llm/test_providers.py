"""Tests for LLM provider implementations and registry utilities."""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch

from src.services.llm.providers import (
    GPT41Provider,
    GPT4MiniProvider,
    Claude35SonnetProvider,
    Gemini15FlashProvider,
    LLMConfigurationError,
    LLMProviderResponse,
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

    @patch('src.services.llm.providers._import_module')
    def test_client_tuple_with_missing_module(
        self, mock_import, mock_settings
    ):
        """Should handle missing openai module gracefully."""
        mock_import.return_value = None
        provider = GPT41Provider(mock_settings)
        client, error_cls, rate_cls = provider._client_tuple()
        assert client is None
        assert error_cls is None
        assert rate_cls is None

    @patch('src.services.llm.providers._import_module')
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
        assert error_cls == Exception
        assert rate_cls == Exception

    @patch('src.services.llm.providers._import_module')
    def test_generate_raises_config_error_no_client(
        self, mock_import, mock_settings
    ):
        """Should raise configuration error when client is unavailable."""
        mock_import.return_value = None
        provider = GPT41Provider(mock_settings)
        
        with pytest.raises(
            LLMConfigurationError, match="OpenAI client is unavailable"
        ):
            provider.generate("test prompt")

    @patch('src.services.llm.providers._import_module')
    def test_generate_raises_config_error_no_key(
        self, mock_import, mock_settings
    ):
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

    @patch('src.services.llm.providers._import_module')
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

    @patch('src.services.llm.providers._import_module')
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
        with pytest.raises(
            KeyError, match="Unknown provider 'unknown-provider'"
        ):
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
