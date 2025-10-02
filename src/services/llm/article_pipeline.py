"""High-level helpers for applying LLM orchestration to article records."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Article

from .orchestrator import LLMOrchestrator, LLMTaskConfig, OrchestrationResult

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_TEMPLATE = (
    "You are assisting a newsroom by producing a concise summary of "
    "the following article. Provide a three sentence summary focusing on "
    "the who, what, where, and why. Include any key impacts on the "
    "community and note if the story highlights civic issues.\n\n"
    "Title: {title}\n"
    "Author: {author}\n"
    "Published: {published}\n"
    "URL: {url}\n\n"
    "Article Body:\n{content}\n"
)


@dataclass(slots=True)
class ArticleLLMResult:
    article_id: str
    success: bool
    provider: Optional[str]
    content: Optional[str]
    failures: List[dict]


class ArticleLLMPipeline:
    """Orchestrate LLM-driven summarisation for Article records."""

    def __init__(
        self,
        session: Session,
        orchestrator: LLMOrchestrator,
        *,
        prompt_template: Optional[str] = None,
    ) -> None:
        self._session = session
        self._orchestrator = orchestrator
        self._prompt_template = prompt_template or DEFAULT_PROMPT_TEMPLATE

    def run(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
    ) -> List[ArticleLLMResult]:
        articles = list(self._iter_articles(statuses, limit))
        results: List[ArticleLLMResult] = []

        for article in articles:
            prompt = self._render_prompt(article)
            config = LLMTaskConfig(
                metadata={
                    "article_id": article.id,
                    "url": article.url,
                }
            )
            orchestration = self._orchestrator.generate(prompt, config=config)
            result = ArticleLLMResult(
                article_id=str(article.id),
                success=orchestration.succeeded,
                provider=orchestration.provider,
                content=orchestration.content,
                failures=[
                    asdict(failure)
                    for failure in orchestration.failures
                ],
            )
            results.append(result)

            if not dry_run and orchestration.succeeded:
                self._persist_result(article, orchestration)
            elif not dry_run and not orchestration.succeeded:
                self._persist_failure(article, orchestration)

        if not dry_run:
            self._session.commit()
        return results

    def _iter_articles(
        self,
        statuses: Optional[Sequence[str]],
        limit: Optional[int],
    ) -> Iterable[Article]:
        stmt = select(Article).order_by(Article.created_at.desc())
        if statuses:
            stmt = stmt.where(Article.status.in_(list(statuses)))
        if limit:
            stmt = stmt.limit(limit)
        for article in self._session.execute(stmt).scalars():
            yield article

    def _render_prompt(self, article: Article) -> str:
        content = article.content or article.text or ""
        content = (content or "").strip()
        if len(content) > 4000:
            content = content[:4000] + "\n..."

        published_at = getattr(article, "publish_date", None)
        if isinstance(published_at, datetime):
            published = published_at.isoformat()
        else:
            published = "unknown"

        data = {
            "title": article.title or "(untitled)",
            "author": article.author or "unknown",
            "published": published,
            "url": article.url or "",
            "content": content,
        }
        return self._prompt_template.format(**data)

    def _persist_result(
        self,
        article: Article,
        orchestration: OrchestrationResult,
    ) -> None:
        meta = _coerce_meta(article.meta)
        llm_meta = cast(Dict[str, Any], meta.setdefault("llm", {}))
        llm_meta.update(
            {
                "summary": orchestration.content,
                "provider": orchestration.provider,
                "timestamp": datetime.utcnow().isoformat(),
                "failures": [
                    asdict(failure)
                    for failure in orchestration.failures
                ],
            }
        )
        setattr(article, "meta", meta)

    def _persist_failure(
        self,
        article: Article,
        orchestration: OrchestrationResult,
    ) -> None:
        meta = _coerce_meta(article.meta)
        llm_meta = cast(Dict[str, Any], meta.setdefault("llm", {}))
        llm_meta.update(
            {
                "summary": None,
                "provider": None,
                "timestamp": datetime.utcnow().isoformat(),
                "failures": [
                    asdict(failure)
                    for failure in orchestration.failures
                ],
            }
        )
        setattr(article, "meta", meta)

    @staticmethod
    def load_prompt_template(path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        file_path = Path(path).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return file_path.read_text(encoding="utf-8")


def _coerce_meta(meta: object) -> Dict[str, Any]:
    if isinstance(meta, dict):
        return dict(meta)
    return {}
