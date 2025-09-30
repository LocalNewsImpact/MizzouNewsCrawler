"""Configuration helpers for the LLM orchestration layer."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DEFAULT_PROVIDER_ORDER: List[str] = [
    "openai-gpt4.1",
    "openai-gpt4.1-mini",
    "claude-3.5-sonnet",
    "gemini-1.5-flash",
]


@dataclass(slots=True)
class VectorStoreSettings:
    """Runtime configuration for optional vector store integrations."""

    provider: str
    options: Dict[str, str] = field(default_factory=dict)

    def is_enabled(self) -> bool:
        return bool(self.provider)


@dataclass(slots=True)
class LLMSettings:
    """Aggregated configuration for the LLM orchestration stack."""

    provider_order: List[str] = field(default_factory=list)
    openai_api_key: Optional[str] = None
    openai_organization: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    request_timeout: int = 30
    max_retries: int = 2
    default_max_output_tokens: int = 1024
    default_temperature: float = 0.2
    vector_store: Optional[VectorStoreSettings] = None

    def provider_names(self) -> List[str]:
        return list(self.provider_order)

    def has_api_key(self, provider: str) -> bool:
        provider = provider.lower()
        if provider.startswith("openai"):
            return bool(self.openai_api_key)
        if provider.startswith("claude") or provider.startswith("anthropic"):
            return bool(self.anthropic_api_key)
        if provider.startswith("gemini") or provider.startswith("google"):
            return bool(self.google_api_key)
        return False


def _parse_provider_order(raw: Optional[str]) -> List[str]:
    if not raw:
        return list(DEFAULT_PROVIDER_ORDER)
    parts = [segment.strip() for segment in raw.split(",") if segment.strip()]
    if not parts:
        return list(DEFAULT_PROVIDER_ORDER)
    return parts


def _vector_store_settings() -> Optional[VectorStoreSettings]:
    provider = os.getenv("VECTOR_STORE_PROVIDER", "").strip().lower()
    if not provider:
        return None

    options: Dict[str, str] = {}
    if provider == "pinecone":
        pinecone_keys = (
            "PINECONE_API_KEY",
            "PINECONE_ENVIRONMENT",
            "PINECONE_INDEX",
        )
        for key in pinecone_keys:
            value = os.getenv(key)
            if value:
                options[key.lower()] = value
    elif provider == "weaviate":
        weaviate_keys = (
            "WEAVIATE_URL",
            "WEAVIATE_API_KEY",
            "WEAVIATE_SCOPE",
            "WEAVIATE_INDEX",
        )
        for key in weaviate_keys:
            value = os.getenv(key)
            if value:
                options[key.lower()] = value
    else:
        # Preserve arbitrary providers for future extensions
        for key, value in os.environ.items():
            if key.startswith(f"{provider.upper()}_"):
                options[key.lower()] = value

    namespace = os.getenv("VECTOR_STORE_NAMESPACE")
    if namespace:
        options["namespace"] = namespace

    if not options:
        # Keep provider disabled when no options supplied to avoid
        # runtime failures
        return None

    return VectorStoreSettings(provider=provider, options=options)


def load_llm_settings() -> LLMSettings:
    """Load LLM settings from the environment (dotenv already applied)."""

    provider_order = _parse_provider_order(os.getenv("LLM_PROVIDER_SEQUENCE"))

    settings = LLMSettings(
        provider_order=provider_order,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_organization=os.getenv("OPENAI_ORGANIZATION"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        request_timeout=int(os.getenv("LLM_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        default_max_output_tokens=int(
            os.getenv("LLM_DEFAULT_MAX_OUTPUT_TOKENS", "1024")
        ),
        default_temperature=float(os.getenv("LLM_DEFAULT_TEMPERATURE", "0.2")),
        vector_store=_vector_store_settings(),
    )

    return settings
