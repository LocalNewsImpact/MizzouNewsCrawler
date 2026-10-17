"""Dataclasses crossing enrichment module boundaries.

Frozen by docs/BACKFIELD_IMPLEMENTATION.md §2. Changing a field here is a spec
change, not a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ArticleInput:
    id: str
    title: str
    content: str
    dataset_slug: str
    publication_city: str | None
    publication_state: str | None = None
    #: Enrichment-stage claims a person has already answered on this
    #: article. The gate reads them before refusing: a refusal a reviewer
    #: overruled is not made again, or the record would be held, released,
    #: and held again by the next run -- a loop with a person in it.
    answered: frozenset = frozenset()
    #: The unprocessed capture (`articles.raw`), read only by the free paywall
    #: pre-check: its wall phrases and story-length threshold were measured
    #: against the capture, and cleaning removes the very furniture it looks
    #: for. Everything the model reads is `content`, the processed `text`.
    #: None where no capture was loaded; the pre-check then reads `content`.
    capture: str | None = None


@dataclass(frozen=True)
class StepResult:
    step: str  # 'content_gate' | 'scope' | 'places' | 'people' | 'organizations' | preset name
    ok: bool
    payload: dict | None
    error: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class EnrichmentOutcome:
    article_id: str
    status: str  # enriched | enrichment_skipped | not_article | paywall | labeled
    skip_reason: str | None
    steps_applied: list[str]
    results: list[StepResult] = field(default_factory=list)
    total_cost_usd: Decimal = Decimal("0")
