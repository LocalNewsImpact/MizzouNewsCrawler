from __future__ import annotations

import types
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Tuple, cast

import pytest
from sqlalchemy.orm import Session

from src.services.llm.article_pipeline import ArticleLLMPipeline
from src.services.llm.orchestrator import (
    LLMOrchestrator,
    OrchestrationResult,
    ProviderFailure,
)
from src.services.llm.providers import LLMProviderResponse


def _make_article(**overrides: Any) -> Any:
    defaults: Dict[str, Any] = {
        "id": "article-1",
        "title": "Local council approves budget",
        "author": "Jamie Writer",
        "publish_date": datetime(2024, 1, 1, 12, 0),
        "content": "Vital update for the community.",
        "text": "",
        "url": "https://example.com/story",
        "meta": {},
        "created_at": datetime(2024, 1, 1, 11, 0),
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class _FakeResult:
    def __init__(self, articles: Iterable[Any]) -> None:
        self._articles = list(articles)

    def scalars(self) -> Iterator[Any]:
        return iter(self._articles)


class _FakeSession:
    def __init__(self, articles: Iterable[Any]) -> None:
        self._articles = list(articles)
        self.statements: List[Any] = []
        self.commit_calls = 0

    def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self._articles)

    def commit(self) -> None:
        self.commit_calls += 1


class _DummyOrchestrator:
    def __init__(self, responses: Iterable[OrchestrationResult]) -> None:
        self._responses = iter(responses)
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def generate(
        self,
        prompt: str,
        config: Any | None = None,
    ) -> OrchestrationResult:
        metadata = config.metadata if config else None
        self.calls.append((prompt, metadata or {}))
        try:
            return next(self._responses)
        except StopIteration:  # pragma: no cover - defensive guard
            pytest.fail("Unexpected orchestrator call")


def _make_success(
    provider: str = "openai",
    content: str = "Summary",
) -> OrchestrationResult:
    response = LLMProviderResponse(
        provider=provider,
        model="gpt-4",
        content=content,
        metadata={"tokens": 123},
    )
    return OrchestrationResult(response=response)


def _make_failure(
    provider: str = "openai",
    *,
    reason: str = "rate limit",
    error_type: str = "rate_limit",
) -> OrchestrationResult:
    failure = ProviderFailure(
        provider=provider,
        reason=reason,
        error_type=error_type,
    )
    result = OrchestrationResult()
    result.failures.append(failure)
    return result


def test_iter_articles_builds_select_with_filters() -> None:
    session = _FakeSession([])
    pipeline = ArticleLLMPipeline(
        cast(Session, session),
        cast(LLMOrchestrator, _DummyOrchestrator([])),
    )

    list(pipeline._iter_articles(statuses=("summarised",), limit=5))

    assert session.statements, "Expected a SELECT statement to be executed"
    compiled = str(session.statements[0])
    assert "ORDER BY" in compiled
    assert "created_at" in compiled
    assert "status" in compiled
    assert "LIMIT" in compiled


def test_render_prompt_formats_defaults_and_truncation() -> None:
    session = _FakeSession([])
    pipeline = ArticleLLMPipeline(
        cast(Session, session),
        cast(LLMOrchestrator, _DummyOrchestrator([])),
    )
    long_content = "A" * 4050
    article = _make_article(
        title=None,
        author=None,
        publish_date=datetime(2024, 6, 1, 9, 30),
        content=long_content,
        url="https://example.com/long",
    )

    prompt = pipeline._render_prompt(article)

    assert "Title: (untitled)" in prompt
    assert "Author: unknown" in prompt
    assert "Published: 2024-06-01T09:30:00" in prompt
    assert prompt.endswith("\n...\n")
    assert "Article Body:" in prompt
    assert len(prompt.splitlines()[-2]) == 4000


def test_render_prompt_falls_back_to_text_and_unknown_date() -> None:
    session = _FakeSession([])
    pipeline = ArticleLLMPipeline(
        cast(Session, session),
        cast(LLMOrchestrator, _DummyOrchestrator([])),
    )
    article = _make_article(
        content="",
        text=" Replacement body ",
        publish_date="2024-01-02",
    )

    prompt = pipeline._render_prompt(article)

    assert "Published: unknown" in prompt
    assert "Replacement body" in prompt


def test_run_dry_run_collects_results_without_commit() -> None:
    article = _make_article()
    session = _FakeSession([article])
    orchestrator = _DummyOrchestrator([_make_success(content="Civic summary")])
    pipeline = ArticleLLMPipeline(
        cast(Session, session),
        cast(LLMOrchestrator, orchestrator),
    )

    results = pipeline.run(dry_run=True)

    assert session.commit_calls == 0
    assert len(results) == 1
    result = results[0]
    assert result.article_id == article.id
    assert result.success is True
    assert result.provider == "openai"
    assert result.content == "Civic summary"
    assert result.failures == []
    assert orchestrator.calls and orchestrator.calls[0][1] == {
        "article_id": article.id,
        "url": article.url,
    }
    assert article.meta == {}


def test_run_persists_success_and_failure() -> None:
    first = _make_article(id="a-1", meta={})
    second = _make_article(
        id="a-2",
        meta={},
        created_at=datetime(2024, 1, 1, 10, 0),
    )
    session = _FakeSession([first, second])
    orchestrator = _DummyOrchestrator(
        [
            _make_success(provider="anthropic", content="Summary A"),
            _make_failure(
                provider="openai",
                reason="timeout",
                error_type="provider",
            ),
        ]
    )
    pipeline = ArticleLLMPipeline(
        cast(Session, session),
        cast(LLMOrchestrator, orchestrator),
    )

    results = pipeline.run(dry_run=False)

    assert session.commit_calls == 1
    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is False
    llm_meta_first = first.meta["llm"]
    assert llm_meta_first["summary"] == "Summary A"
    assert llm_meta_first["provider"] == "anthropic"
    assert isinstance(llm_meta_first["timestamp"], str)
    assert llm_meta_first["failures"] == []

    llm_meta_second = second.meta["llm"]
    assert llm_meta_second["summary"] is None
    assert llm_meta_second["provider"] is None
    assert llm_meta_second["failures"] == [
        {
            "provider": "openai",
            "reason": "timeout",
            "error_type": "provider",
        }
    ]


def test_load_prompt_template_reads_file(tmp_path: Path) -> None:
    template = tmp_path / "prompt.txt"
    template.write_text("Prompt here", encoding="utf-8")

    content = ArticleLLMPipeline.load_prompt_template(str(template))

    assert content == "Prompt here"


def test_load_prompt_template_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        ArticleLLMPipeline.load_prompt_template("~/does-not-exist.txt")
