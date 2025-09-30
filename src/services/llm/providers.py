"""LLM provider implementations and registration utilities."""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple, Type

from .settings import LLMSettings

logger = logging.getLogger(__name__)

ErrorType = Optional[Type[BaseException]]
ClientTuple = Tuple[Any, ErrorType, ErrorType]


def _import_module(module_name: str) -> Optional[Any]:
    """Import a module lazily, returning None when it cannot be loaded."""

    try:  # pragma: no cover - import side effects only when available
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
        logger.debug("Module %s not available: %s", module_name, exc)
        return None


class LLMProviderError(RuntimeError):
    """Base exception raised when a provider fails to produce an output."""


class LLMRateLimitError(LLMProviderError):
    """Raised when a provider reports a rate limit condition."""


class LLMConfigurationError(LLMProviderError):
    """Raised when required configuration for a provider is missing."""


@dataclass(slots=True)
class LLMProviderResponse:
    """Normalized response payload returned by providers."""

    provider: str
    model: str
    content: str
    metadata: Dict[str, object]


class LLMProvider(ABC):
    """Abstract base class implemented by concrete LLM providers."""

    provider_name: str
    model_name: str
    max_context_tokens: int

    def __init__(self, settings: LLMSettings):
        self._settings = settings
        self._client: Optional[Any] = None

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def model(self) -> str:
        return self.model_name

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the provider can be invoked safely."""

    @abstractmethod
    def _client_tuple(self) -> ClientTuple:
        """Return the cached client and error types."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> LLMProviderResponse:
        """Produce a response for the supplied prompt."""

    def _default_temperature(self, override: Optional[float]) -> float:
        if override is not None:
            return override
        return self._settings.default_temperature

    def _default_output_tokens(self, override: Optional[int]) -> int:
        if override is not None:
            return override
        return self._settings.default_max_output_tokens

    def _decorate_metadata(
        self, metadata: Optional[Dict[str, object]]
    ) -> Dict[str, object]:
        payload = metadata.copy() if metadata else {}
        payload.setdefault("provider", self.provider_name)
        payload.setdefault("model", self.model_name)
        payload.setdefault("timestamp", datetime.utcnow().isoformat())
        return payload


class GPT41Provider(LLMProvider):
    provider_name = "openai-gpt4.1"
    model_name = "gpt-4.1"
    max_context_tokens = 128_000

    def is_available(self) -> bool:
        return bool(self._settings.openai_api_key)

    def _client_tuple(self) -> ClientTuple:
        module = _import_module("openai")
        if module is None:
            return (None, None, None)

        openai_cls = getattr(module, "OpenAI", None)
        error_cls = getattr(module, "OpenAIError", None)
        rate_cls = getattr(module, "RateLimitError", None)

        if openai_cls is None:
            logger.debug("OpenAI class missing in openai module")
            return (None, error_cls, rate_cls)

        if self._client is None:
            self._client = openai_cls(
                api_key=self._settings.openai_api_key,
                organization=self._settings.openai_organization,
                timeout=self._settings.request_timeout,
            )
        return (self._client, error_cls, rate_cls)

    def generate(
        self,
        prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> LLMProviderResponse:
        client, error_cls, rate_cls = self._client_tuple()
        if client is None:
            raise LLMConfigurationError("OpenAI client is unavailable")
        if not self._settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not configured")

        output_tokens = self._default_output_tokens(max_output_tokens)
        temp = self._default_temperature(temperature)

        try:
            response = client.responses.create(  # type: ignore[call-arg]
                model=self.model_name,
                input=prompt,
                max_output_tokens=output_tokens,
                temperature=temp,
            )
        except Exception as exc:  # pragma: no cover - client specific
            if rate_cls and isinstance(exc, rate_cls):
                raise LLMRateLimitError(str(exc)) from exc
            if error_cls and isinstance(exc, error_cls):
                raise LLMProviderError(str(exc)) from exc
            raise

        text = _coalesce_response_text(response)
        return LLMProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            content=text,
            metadata=self._decorate_metadata(metadata),
        )


class GPT4MiniProvider(GPT41Provider):
    provider_name = "openai-gpt4.1-mini"
    model_name = "gpt-4.1-mini"


class Claude35SonnetProvider(LLMProvider):
    provider_name = "claude-3.5-sonnet"
    model_name = "claude-3-5-sonnet-latest"
    max_context_tokens = 200_000

    def is_available(self) -> bool:
        return bool(self._settings.anthropic_api_key)

    def _client_tuple(self) -> ClientTuple:
        module = _import_module("anthropic")
        if module is None:
            return (None, None, None)

        client_cls = getattr(module, "Anthropic", None)
        error_cls = getattr(module, "AnthropicError", None)
        rate_cls = getattr(module, "RateLimitError", None)

        if client_cls is None:
            logger.debug("Anthropic client class missing")
            return (None, error_cls, rate_cls)

        if self._client is None:
            self._client = client_cls(
                api_key=self._settings.anthropic_api_key,
                timeout=self._settings.request_timeout,
            )
        return (self._client, error_cls, rate_cls)

    def generate(
        self,
        prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> LLMProviderResponse:
        client, error_cls, rate_cls = self._client_tuple()
        if client is None:
            raise LLMConfigurationError("Anthropic client is unavailable")
        if not self._settings.anthropic_api_key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY is not configured")

        output_tokens = self._default_output_tokens(max_output_tokens)
        temp = self._default_temperature(temperature)

        try:
            result = client.messages.create(  # type: ignore[call-arg]
                model=self.model_name,
                max_output_tokens=output_tokens,
                temperature=temp,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # pragma: no cover - client specific
            if rate_cls and isinstance(exc, rate_cls):
                raise LLMRateLimitError(str(exc)) from exc
            if error_cls and isinstance(exc, error_cls):
                raise LLMProviderError(str(exc)) from exc
            raise

        text = _coalesce_claude_text(result)
        return LLMProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            content=text,
            metadata=self._decorate_metadata(metadata),
        )


class Gemini15FlashProvider(LLMProvider):
    provider_name = "gemini-1.5-flash"
    model_name = "gemini-1.5-flash"
    max_context_tokens = 1_000_000

    def is_available(self) -> bool:
        return bool(self._settings.google_api_key)

    def _client_tuple(self) -> ClientTuple:
        module = _import_module("google.generativeai")
        if module is None:
            return (None, None, None)

        configure = getattr(module, "configure", None)
        model_cls = getattr(module, "GenerativeModel", None)
        types_mod = getattr(module, "types", None)
        generation_types = getattr(types_mod, "generation_types", None)
        error_cls = getattr(generation_types, "GenerationException", None)

        if configure is None or model_cls is None:
            logger.debug("google-generativeai client helpers missing")
            return (None, error_cls, None)

        if self._client is None:
            configure(
                api_key=self._settings.google_api_key,
                client_options={"timeout": self._settings.request_timeout},
            )
            self._client = model_cls(self.model_name)
        return (self._client, error_cls, None)

    def generate(
        self,
        prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> LLMProviderResponse:
        client, error_cls, rate_cls = self._client_tuple()
        if client is None:
            raise LLMConfigurationError("Gemini client is unavailable")
        if not self._settings.google_api_key:
            raise LLMConfigurationError("GOOGLE_API_KEY is not configured")

        output_tokens = self._default_output_tokens(max_output_tokens)
        temp = self._default_temperature(temperature)

        try:
            result = client.generate_content(  # type: ignore[call-arg]
                prompt,
                generation_config={
                    "temperature": temp,
                    "max_output_tokens": output_tokens,
                },
            )
        except Exception as exc:  # pragma: no cover - client specific
            if rate_cls and isinstance(exc, rate_cls):
                raise LLMRateLimitError(str(exc)) from exc
            if error_cls and isinstance(exc, error_cls):
                raise LLMProviderError(str(exc)) from exc
            raise

        text = _coalesce_gemini_text(result)
        return LLMProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            content=text,
            metadata=self._decorate_metadata(metadata),
        )


class ProviderRegistry:
    """Registry for mapping provider slugs to implementations."""

    _registry: Dict[str, Type[LLMProvider]] = {
        GPT41Provider.provider_name: GPT41Provider,
        GPT4MiniProvider.provider_name: GPT4MiniProvider,
        Claude35SonnetProvider.provider_name: Claude35SonnetProvider,
        Gemini15FlashProvider.provider_name: Gemini15FlashProvider,
    }

    @classmethod
    def register(cls, slug: str, provider_cls: Type[LLMProvider]) -> None:
        cls._registry[slug] = provider_cls

    @classmethod
    def create(cls, slug: str, settings: LLMSettings) -> LLMProvider:
        provider_cls = cls._registry.get(slug)
        if not provider_cls:
            raise KeyError(f"Unknown provider '{slug}'")
        return provider_cls(settings)

    @classmethod
    def names(cls) -> Iterable[str]:
        return sorted(cls._registry)


def _coalesce_response_text(response: Any) -> str:
    try:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return str(output_text)
        output = getattr(response, "output", None)
        if isinstance(output, list):
            return "\n".join(str(item) for item in output if item)
        if output:
            return str(output)
        choices = getattr(response, "choices", None)
        if choices:
            first = choices[0]
            message = getattr(first, "message", {})
            content = None
            if isinstance(message, dict):
                content = message.get("content")
            if content:
                return str(content)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("Failed to coalesce OpenAI response text: %s", exc)
    return ""


def _coalesce_claude_text(response: Any) -> str:
    try:
        content = getattr(response, "content", None)
        if isinstance(content, list):
            parts = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
            if parts:
                return "\n".join(parts)
        text_value = getattr(response, "text", None)
        if text_value:
            return str(text_value)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("Failed to coalesce Claude response text: %s", exc)
    return ""


def _coalesce_gemini_text(response: Any) -> str:
    try:
        text_value = getattr(response, "text", None)
        if text_value:
            return str(text_value)
        candidates = getattr(response, "candidates", None)
        if candidates:
            parts: list[str] = []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if content is None:
                    continue
                for part in getattr(content, "parts", []) or []:
                    text = getattr(part, "text", None)
                    if text:
                        parts.append(str(text))
            if parts:
                return "\n".join(parts)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("Failed to coalesce Gemini response text: %s", exc)
    return ""
