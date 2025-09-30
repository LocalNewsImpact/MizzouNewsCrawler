"""Sequential orchestration across LLM providers with graceful fallbacks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, TYPE_CHECKING

from .providers import (
    LLMConfigurationError,
    LLMProvider,
    LLMProviderError,
    LLMProviderResponse,
    LLMRateLimitError,
    ProviderRegistry,
)
from .settings import LLMSettings, load_llm_settings

if TYPE_CHECKING:  # pragma: no cover - typing helper only
    from .vectorstores import VectorStore


@dataclass(slots=True)
class ProviderFailure:
    """Record of a provider failure during orchestration."""

    provider: str
    reason: str
    error_type: str


@dataclass(slots=True)
class OrchestrationResult:
    """Aggregated result of orchestrating a single LLM task."""

    response: Optional[LLMProviderResponse] = None
    failures: List[ProviderFailure] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.response is not None

    @property
    def provider(self) -> Optional[str]:
        if self.response is None:
            return None
        return self.response.provider

    @property
    def content(self) -> Optional[str]:
        if self.response is None:
            return None
        return self.response.content


@dataclass(slots=True)
class LLMTaskConfig:
    """Runtime overrides for a single LLM request."""

    max_output_tokens: Optional[int] = None
    temperature: Optional[float] = None
    metadata: Optional[Dict[str, object]] = None


class LLMOrchestrator:
    """Sequential orchestration of multiple LLM providers with fallback."""

    def __init__(
        self,
        settings: LLMSettings,
        providers: Sequence[LLMProvider],
        vector_store: Optional["VectorStore"] = None,
    ) -> None:
        self._settings = settings
        self._providers = list(providers)
        self._vector_store = vector_store

    @classmethod
    def from_settings(
        cls,
        settings: Optional[LLMSettings] = None,
        *,
        vector_store: Optional["VectorStore"] = None,
    ) -> "LLMOrchestrator":
        resolved = settings or load_llm_settings()
        providers = [
            ProviderRegistry.create(name, resolved)
            for name in resolved.provider_names()
        ]
        return cls(resolved, providers, vector_store)

    def list_providers(self) -> List[str]:
        return [provider.name for provider in self._providers]

    def generate(
        self,
        prompt: str,
        config: Optional[LLMTaskConfig] = None,
    ) -> OrchestrationResult:
        config = config or LLMTaskConfig()
        result = OrchestrationResult()

        for provider in self._providers:
            if not provider.is_available():
                result.failures.append(
                    ProviderFailure(
                        provider=provider.name,
                        reason="provider not configured",
                        error_type="configuration",
                    )
                )
                continue

            try:
                response = provider.generate(
                    prompt,
                    max_output_tokens=config.max_output_tokens,
                    temperature=config.temperature,
                    metadata=config.metadata,
                )
            except LLMRateLimitError as exc:
                result.failures.append(
                    ProviderFailure(
                        provider=provider.name,
                        reason=str(exc),
                        error_type="rate_limit",
                    )
                )
                continue
            except LLMConfigurationError as exc:
                result.failures.append(
                    ProviderFailure(
                        provider=provider.name,
                        reason=str(exc),
                        error_type="configuration",
                    )
                )
                continue
            except LLMProviderError as exc:
                result.failures.append(
                    ProviderFailure(
                        provider=provider.name,
                        reason=str(exc),
                        error_type="provider",
                    )
                )
                continue

            result.response = response
            self._store_vector_if_enabled(prompt, response)
            return result

        # Exhausted providers without success
        return result

    def _store_vector_if_enabled(
        self,
        prompt: str,
        response: LLMProviderResponse,
    ) -> None:
        if not self._vector_store:
            return

        try:
            self._vector_store.store(
                prompt=prompt,
                response=response.content,
                metadata=response.metadata,
            )
        except Exception as exc:  # pragma: no cover - best effort only
            logging.getLogger(__name__).debug(
                "Vector store store() failed for provider %s: %s",
                response.provider,
                exc,
            )


__all__ = [
    "LLMOrchestrator",
    "LLMTaskConfig",
    "OrchestrationResult",
    "ProviderFailure",
]
