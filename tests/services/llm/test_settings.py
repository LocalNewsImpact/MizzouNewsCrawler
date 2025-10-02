import pytest

from src.services.llm import settings as llm_settings


def test_parse_provider_order_variants():
    defaults = llm_settings.DEFAULT_PROVIDER_ORDER
    assert llm_settings._parse_provider_order(None) == defaults
    assert llm_settings._parse_provider_order(" , , ") == defaults

    custom = llm_settings._parse_provider_order(
        "openai-gpt4.1,gemini-1.5-flash"
    )
    assert custom == ["openai-gpt4.1", "gemini-1.5-flash"]


def test_vector_store_settings_known_providers(monkeypatch):
    monkeypatch.delenv("VECTOR_STORE_PROVIDER", raising=False)
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "pinecone")
    monkeypatch.setenv("PINECONE_API_KEY", "pc-key")
    monkeypatch.setenv("PINECONE_ENVIRONMENT", "pc-env")
    monkeypatch.setenv("PINECONE_INDEX", "pc-index")
    monkeypatch.setenv("VECTOR_STORE_NAMESPACE", "pc-namespace")

    vector_settings = llm_settings._vector_store_settings()
    assert vector_settings is not None
    assert vector_settings.provider == "pinecone"
    assert vector_settings.is_enabled() is True
    assert vector_settings.options["pinecone_api_key"] == "pc-key"
    assert vector_settings.options["namespace"] == "pc-namespace"


def test_vector_store_settings_generic_provider(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_API_KEY", "secret")
    monkeypatch.setenv("CUSTOM_ENDPOINT", "https://example.com")

    vector_settings = llm_settings._vector_store_settings()
    assert vector_settings is not None
    assert vector_settings.provider == "custom"
    assert vector_settings.options["custom_api_key"] == "secret"
    assert vector_settings.options["custom_endpoint"] == "https://example.com"


def test_vector_store_settings_missing_options_returns_none(monkeypatch):
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_ENDPOINT", raising=False)
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "custom")

    assert llm_settings._vector_store_settings() is None


def test_load_llm_settings_aggregates_environment(monkeypatch):
    monkeypatch.setenv(
        "LLM_PROVIDER_SEQUENCE", "openai-gpt4.1, claude-3.5-sonnet"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_ORGANIZATION", "openai-org")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "45")
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")
    monkeypatch.setenv("LLM_DEFAULT_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("LLM_DEFAULT_TEMPERATURE", "0.5")
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "weaviate")
    monkeypatch.setenv("WEAVIATE_URL", "https://weaviate")
    monkeypatch.setenv("WEAVIATE_API_KEY", "wave-key")
    monkeypatch.setenv("WEAVIATE_INDEX", "wave-index")
    monkeypatch.setenv("VECTOR_STORE_NAMESPACE", "wave-ns")

    settings = llm_settings.load_llm_settings()
    assert settings.provider_order == [
        "openai-gpt4.1",
        "claude-3.5-sonnet",
    ]
    assert settings.openai_api_key == "openai-key"
    assert settings.openai_organization == "openai-org"
    assert settings.anthropic_api_key == "anthropic-key"
    assert settings.google_api_key == "google-key"
    assert settings.request_timeout == 45
    assert settings.max_retries == 4
    assert settings.default_max_output_tokens == 2048
    assert settings.default_temperature == pytest.approx(0.5)

    assert settings.vector_store is not None
    assert settings.vector_store.provider == "weaviate"
    assert settings.vector_store.options["weaviate_url"] == "https://weaviate"
    assert settings.vector_store.options["namespace"] == "wave-ns"

    names = settings.provider_names()
    names.append("extra-provider")
    assert settings.provider_order == ["openai-gpt4.1", "claude-3.5-sonnet"]

    assert settings.has_api_key("openai-gpt4.1") is True
    assert settings.has_api_key("claude-3.5-sonnet") is True
    assert settings.has_api_key("gemini-1.5-flash") is True
    assert settings.has_api_key("unknown") is False
