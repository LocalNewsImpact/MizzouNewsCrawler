"""Centralized configuration for MizzouNewsCrawler.

This module reads environment variables (optionally from a .env file) and
exposes simple constants and a small helper to access configuration values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote_plus, urlencode

try:
    # Optional dependency for local .env files
    from dotenv import load_dotenv  # pragma: no cover

    _HAVE_DOTENV = True  # pragma: no cover
except Exception:  # pragma: no cover - optional dependency missing
    _HAVE_DOTENV = False  # pragma: no cover

    def load_dotenv(*args, **kwargs) -> bool:  # pragma: no cover
        return False

# If a .env file is present and python-dotenv is installed, load it.
_env_path = Path(".") / ".env"
if _HAVE_DOTENV and _env_path.exists():
    load_dotenv(dotenv_path=str(_env_path))

_TRUTHY = {"1", "true", "t", "yes", "y", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUTHY


def _normalize_scheme(value: Optional[str], *, default: str = "http") -> str:
    """Normalize a URL scheme while tolerating partial or noisy values.

    Accepts inputs such as ``"HTTP"``, ``"https://"`` or ``" GrPc+1 "`` and
    returns a lowercase scheme token without trailing punctuation. If the
    provided value is empty the ``default`` is returned instead.
    """

    if value is None:
        return default

    cleaned = value.strip().lower()
    if not cleaned:
        return default

    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[0]

    cleaned = cleaned.rstrip(":/")

    return cleaned or default


# Runtime / deployment context
APP_ENV: str = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "local"))
IN_KUBERNETES: bool = bool(os.getenv("KUBERNETES_SERVICE_HOST"))
KUBERNETES_NAMESPACE: Optional[str] = os.getenv("KUBERNETES_NAMESPACE")


# Database configuration with Kubernetes-friendly fallbacks
DATABASE_ENGINE: str = os.getenv("DATABASE_ENGINE", "postgresql+psycopg2")
DATABASE_HOST: Optional[str] = os.getenv("DATABASE_HOST")
DATABASE_PORT: Optional[str] = os.getenv("DATABASE_PORT", "5432")
DATABASE_NAME: Optional[str] = os.getenv("DATABASE_NAME")
DATABASE_USER: Optional[str] = os.getenv("DATABASE_USER")
DATABASE_PASSWORD: Optional[str] = os.getenv("DATABASE_PASSWORD")
DATABASE_SSLMODE: Optional[str] = os.getenv("DATABASE_SSLMODE")
DATABASE_REQUIRE_SSL: bool = _env_bool("DATABASE_REQUIRE_SSL", False)

_database_url = os.getenv("DATABASE_URL")

if not _database_url and all([DATABASE_HOST, DATABASE_NAME, DATABASE_USER]):
    user = quote_plus(DATABASE_USER or "")
    auth_segment = user
    if DATABASE_PASSWORD:
        auth_segment += f":{quote_plus(DATABASE_PASSWORD)}"
    auth_segment = f"{auth_segment}@" if auth_segment else ""
    port_segment = f":{DATABASE_PORT}" if DATABASE_PORT else ""

    sslmode = DATABASE_SSLMODE or ("require" if DATABASE_REQUIRE_SSL else None)
    query = f"?{urlencode({'sslmode': sslmode})}" if sslmode else ""

    _database_url = (
        f"{DATABASE_ENGINE}://{auth_segment}{DATABASE_HOST}{port_segment}/"
        f"{DATABASE_NAME}{query}"
    )

DATABASE_URL: str = _database_url or "sqlite:///data/mizzou.db"


# Core configuration values
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
TELEMETRY_URL: Optional[str] = os.getenv("TELEMETRY_URL")
TELEMETRY_HOST: Optional[str] = os.getenv("TELEMETRY_HOST")
TELEMETRY_PORT: Optional[str] = os.getenv("TELEMETRY_PORT", "")
_telemetry_default_scheme = (
    "https" if _env_bool("TELEMETRY_USE_TLS", False) else "http"
)
TELEMETRY_SCHEME: str = _normalize_scheme(
    os.getenv("TELEMETRY_SCHEME"), default=_telemetry_default_scheme
)
TELEMETRY_BASE_PATH: str = os.getenv("TELEMETRY_BASE_PATH", "").strip()

if TELEMETRY_BASE_PATH and not TELEMETRY_BASE_PATH.startswith("/"):
    TELEMETRY_BASE_PATH = f"/{TELEMETRY_BASE_PATH}"

if not TELEMETRY_URL and TELEMETRY_HOST:
    port_fragment = f":{TELEMETRY_PORT}" if TELEMETRY_PORT else ""
    TELEMETRY_URL = (
        f"{TELEMETRY_SCHEME}://{TELEMETRY_HOST}{port_fragment}"
        f"{TELEMETRY_BASE_PATH}"
    )

# OAuth / Auth configuration (optional - used by future work)
OAUTH_PROVIDER: Optional[str] = os.getenv("OAUTH_PROVIDER")
OAUTH_CLIENT_ID: Optional[str] = os.getenv("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET: Optional[str] = os.getenv("OAUTH_CLIENT_SECRET")
OAUTH_REDIRECT_URI: Optional[str] = os.getenv("OAUTH_REDIRECT_URI")

# App behaviour toggles
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "20"))
REQUEST_DELAY: float = float(os.getenv("REQUEST_DELAY", "1.0"))

# LLM / Generative AI integration
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
OPENAI_ORGANIZATION: Optional[str] = os.getenv("OPENAI_ORGANIZATION")
ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY")
LLM_PROVIDER_SEQUENCE: Optional[str] = os.getenv("LLM_PROVIDER_SEQUENCE")
LLM_REQUEST_TIMEOUT: int = int(os.getenv("LLM_REQUEST_TIMEOUT", "30"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))
LLM_DEFAULT_MAX_OUTPUT_TOKENS: int = int(
    os.getenv("LLM_DEFAULT_MAX_OUTPUT_TOKENS", "1024")
)
LLM_DEFAULT_TEMPERATURE: float = float(
    os.getenv("LLM_DEFAULT_TEMPERATURE", "0.2")
)

# Optional vector store configuration
VECTOR_STORE_PROVIDER: Optional[str] = os.getenv("VECTOR_STORE_PROVIDER")
VECTOR_STORE_NAMESPACE: Optional[str] = os.getenv("VECTOR_STORE_NAMESPACE")
PINECONE_API_KEY: Optional[str] = os.getenv("PINECONE_API_KEY")
PINECONE_ENVIRONMENT: Optional[str] = os.getenv("PINECONE_ENVIRONMENT")
PINECONE_INDEX: Optional[str] = os.getenv("PINECONE_INDEX")
WEAVIATE_URL: Optional[str] = os.getenv("WEAVIATE_URL")
WEAVIATE_API_KEY: Optional[str] = os.getenv("WEAVIATE_API_KEY")
WEAVIATE_SCOPE: Optional[str] = os.getenv("WEAVIATE_SCOPE")
WEAVIATE_INDEX: Optional[str] = os.getenv("WEAVIATE_INDEX")


def get_config() -> Dict[str, Any]:
    """Return a dict of the most important configuration values.

    Useful for injecting into job records, telemetry events, or tests.
    """
    effective_sslmode = DATABASE_SSLMODE or (
        "require" if DATABASE_REQUIRE_SSL else None
    )

    return {
        "runtime": {
            "environment": APP_ENV,
            "in_kubernetes": IN_KUBERNETES,
            "namespace": KUBERNETES_NAMESPACE,
        },
        "database_url": DATABASE_URL,
        "log_level": LOG_LEVEL,
        "telemetry_url": TELEMETRY_URL,
        "oauth_provider": OAUTH_PROVIDER,
        "database": {
            "engine": DATABASE_ENGINE,
            "host": DATABASE_HOST,
            "port": DATABASE_PORT,
            "name": DATABASE_NAME,
            "user": DATABASE_USER,
            "sslmode": effective_sslmode,
        },
        "llm": {
            "provider_sequence": LLM_PROVIDER_SEQUENCE,
            "request_timeout": LLM_REQUEST_TIMEOUT,
            "max_retries": LLM_MAX_RETRIES,
            "default_max_output_tokens": LLM_DEFAULT_MAX_OUTPUT_TOKENS,
            "default_temperature": LLM_DEFAULT_TEMPERATURE,
            "api_keys": {
                "openai": bool(OPENAI_API_KEY),
                "anthropic": bool(ANTHROPIC_API_KEY),
                "google": bool(GOOGLE_API_KEY),
            },
        },
        "vector_store": {
            "provider": VECTOR_STORE_PROVIDER,
            "namespace": VECTOR_STORE_NAMESPACE,
            "pinecone_configured": bool(
                PINECONE_API_KEY and PINECONE_INDEX
            ),
            "weaviate_configured": bool(WEAVIATE_URL),
        },
        "services": {
            "telemetry": {
                "host": TELEMETRY_HOST,
                "port": TELEMETRY_PORT,
                "scheme": TELEMETRY_SCHEME,
                "base_path": TELEMETRY_BASE_PATH or None,
                "url": TELEMETRY_URL,
            }
        },
    }
