from typing import Dict, List, Optional, Type

import pytest

from src.services.llm.orchestrator import LLMOrchestrator, LLMTaskConfig
from src.services.llm.providers import (
    LLMConfigurationError,
    LLMProvider,
    LLMProviderError,
    LLMProviderResponse,
    LLMRateLimitError,
    ProviderRegistry,
)
from src.services.llm.settings import LLMSettings
from src.services.llm.vectorstores import VectorStore


class FakeProvider(LLMProvider):
    provider_name = "fake"
    model_name = "model"
    max_context_tokens = 1000

    def __init__(
        self,
        settings: LLMSettings,
        *,
        name: Optional[str] = None,
        available: bool = True,
        error: Optional[Exception] = None,
        response: Optional[LLMProviderResponse] = None,
    ) -> None:
        super().__init__(settings)
        if name:
            self.provider_name = name
        self._available = available
        self._error = error
        self._response = response
        self.calls: List[Dict[str, object]] = []

    def is_available(self) -> bool:
        return self._available

    def _client_tuple(self):  # pragma: no cover - interface stub
        return (None, None, None)

    def generate(
        self,
        prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> LLMProviderResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "metadata": metadata,
            }
        )
        if self._error:
            raise self._error
        return self._response or LLMProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            content=f"{prompt}-{self.provider_name}",
            metadata=(metadata or {}).copy(),
        )


class RecordingVectorStore(VectorStore):
    def __init__(self) -> None:
        self.calls: List[Dict[str, object]] = []

    def store(
        self,
        *,
        prompt: str,
        response: str,
        metadata: Dict[str, object],
    ) -> None:
        self.calls.append(
            {
                "prompt": prompt,
                "response": response,
                "metadata": metadata,
            }
        )


class ExplodingVectorStore(RecordingVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self.exc = RuntimeError("store failed")

    def store(
        self,
        *,
        prompt: str,
        response: str,
        metadata: Dict[str, object],
    ) -> None:
        super().store(prompt=prompt, response=response, metadata=metadata)
        raise self.exc


def _settings(**overrides) -> LLMSettings:
    return LLMSettings(
        provider_order=overrides.get("provider_order", ["p1", "p2"]),
        openai_api_key=overrides.get("openai_api_key", "key"),
        openai_organization=overrides.get("openai_organization"),
        anthropic_api_key=overrides.get("anthropic_api_key", "anthropic"),
        google_api_key=overrides.get("google_api_key", "google"),
        request_timeout=overrides.get("request_timeout", 30),
        max_retries=overrides.get("max_retries", 2),
        default_max_output_tokens=overrides.get(
            "default_max_output_tokens",
            200,
        ),
        default_temperature=overrides.get("default_temperature", 0.5),
        vector_store=overrides.get("vector_store"),
    )


def _provider(name: str, **kwargs) -> FakeProvider:
    return FakeProvider(_settings(), name=name, **kwargs)


class _RegistryPatch:
    def __init__(self, registry: Dict[str, Type[LLMProvider]]) -> None:
        self.registry = registry

    def __enter__(self) -> None:
        self.original = dict(ProviderRegistry._registry)
        ProviderRegistry._registry.update(self.registry)

    def __exit__(self, exc_type, exc, tb) -> None:
        ProviderRegistry._registry = self.original


def test_from_settings_builds_providers_in_order():
    settings = _settings(provider_order=["first", "second"])
    with _RegistryPatch(
        {
            "first": type(
                "ProviderFirst",
                (FakeProvider,),
                {"provider_name": "first"},
            ),
            "second": type(
                "ProviderSecond",
                (FakeProvider,),
                {"provider_name": "second"},
            ),
        }
    ):
        orchestrator = LLMOrchestrator.from_settings(settings)
        assert orchestrator.list_providers() == ["first", "second"]


@pytest.mark.parametrize(
    "error, expected_type",
    [
        (LLMRateLimitError("boom"), "rate_limit"),
        (LLMConfigurationError("missing"), "configuration"),
        (LLMProviderError("nope"), "provider"),
    ],
)
def test_generate_collects_failures_and_falls_back(error, expected_type):
    providers = [
        _provider("unavailable", available=False),
        _provider("failing", error=error),
        _provider("success"),
    ]
    orchestrator = LLMOrchestrator(_settings(), providers)

    result = orchestrator.generate(
        "PROMPT",
        LLMTaskConfig(metadata={"base": True}),
    )

    assert result.succeeded is True
    assert result.provider == "success"
    assert result.content == "PROMPT-success"
    assert [
        (failure.provider, failure.error_type)
        for failure in result.failures
    ] == [
        ("unavailable", "configuration"),
        ("failing", expected_type),
    ]


def test_generate_returns_failures_when_all_providers_fail():
    providers = [
        _provider("unavailable", available=False),
        _provider("misconfigured", error=LLMConfigurationError("missing")),
    ]
    orchestrator = LLMOrchestrator(_settings(), providers)

    result = orchestrator.generate("PROMPT")

    assert result.succeeded is False
    assert result.response is None
    assert [failure.provider for failure in result.failures] == [
        "unavailable",
        "misconfigured",
    ]


def test_generate_uses_task_config_values():
    provider = _provider("configured")
    orchestrator = LLMOrchestrator(_settings(), [provider])

    config = LLMTaskConfig(
        max_output_tokens=512,
        temperature=0.7,
        metadata={"topic": "news"},
    )

    orchestrator.generate("PROMPT", config)

    assert provider.calls == [
        {
            "prompt": "PROMPT",
            "max_output_tokens": 512,
            "temperature": 0.7,
            "metadata": {"topic": "news"},
        }
    ]


def test_vector_store_records_success():
    vector_store = RecordingVectorStore()
    response = LLMProviderResponse(
        provider="vec",
        model="model",
        content="RESPONSE",
        metadata={"provider": "vec"},
    )
    providers = [_provider("vec", response=response)]
    orchestrator = LLMOrchestrator(
        _settings(),
        providers,
        vector_store=vector_store,
    )

    result = orchestrator.generate(
        "PROMPT",
        LLMTaskConfig(metadata={"foo": "bar"}),
    )

    assert result.succeeded
    assert vector_store.calls == [
        {
            "prompt": "PROMPT",
            "response": "RESPONSE",
            "metadata": {"provider": "vec"},
        }
    ]


def test_vector_store_failure_is_swallowed(caplog):
    caplog.set_level("DEBUG")
    vector_store = ExplodingVectorStore()
    providers = [_provider("vec")]
    orchestrator = LLMOrchestrator(
        _settings(),
        providers,
        vector_store=vector_store,
    )

    result = orchestrator.generate("PROMPT")

    assert result.succeeded
    assert len(vector_store.calls) == 1
    assert any(
        "Vector store store() failed" in message
        for message in caplog.messages
    )
