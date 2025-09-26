"""Centralized configuration for MizzouNewsCrawler.

This module reads environment variables (optionally from a .env file) and
exposes simple constants and a small helper to access configuration values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

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

# Core configuration values
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/mizzou.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
TELEMETRY_URL: Optional[str] = os.getenv("TELEMETRY_URL")

# OAuth / Auth configuration (optional - used by future work)
OAUTH_PROVIDER: Optional[str] = os.getenv("OAUTH_PROVIDER")
OAUTH_CLIENT_ID: Optional[str] = os.getenv("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET: Optional[str] = os.getenv("OAUTH_CLIENT_SECRET")
OAUTH_REDIRECT_URI: Optional[str] = os.getenv("OAUTH_REDIRECT_URI")

# App behaviour toggles
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "20"))
REQUEST_DELAY: float = float(os.getenv("REQUEST_DELAY", "1.0"))


def get_config() -> dict:
    """Return a dict of the most important configuration values.

    Useful for injecting into job records, telemetry events, or tests.
    """
    return {
        "database_url": DATABASE_URL,
        "log_level": LOG_LEVEL,
        "telemetry_url": TELEMETRY_URL,
        "oauth_provider": OAUTH_PROVIDER,
    }
