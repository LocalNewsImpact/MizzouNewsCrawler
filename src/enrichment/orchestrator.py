"""Per-article step sequencing and status transitions.

Implements docs/BACKFIELD_IMPLEMENTATION.md §5.2 exactly. Pure given a stubbed
adapter: no database, no environment. Rules encoded here:

- Any transient failure aborts the article, not the batch; partial results are
  discarded and the article retries whole (steps cost $0.0008; partial-resume
  bookkeeping is not worth its bugs).
- Gate rejection is terminal and does not count as an attempt.
- places never runs without a point-level scope: the 54% exclusion is the cost
  model.
- Attempts exhaustion is decided here so the rule is testable: the caller
  passes the current attempt count.
"""

from __future__ import annotations

from decimal import Decimal

from src.enrichment import adapter
from src.enrichment.gate import HEURISTIC_REJECT, boilerplate_score
from src.enrichment.profiles import Profile
from src.enrichment.resolve import resolve_point
from src.enrichment.types import ArticleInput, EnrichmentOutcome, StepResult

POINT_SCOPES = frozenset({"city_municipality", "neighborhood_community"})

_GATE_VERDICT_STATUS = {"paywall": "paywall", "not_news": "not_article"}


def _metadata_payload_invalid(payload: dict) -> str | None:
    """§5.1's parsing rule: a bad classification fails the article rather than
    writing a bad row."""
    meta = payload.get("article_metadata")
    if not isinstance(meta, dict):
        return "article_metadata missing from node payload"
    category = meta.get("category")
    if not isinstance(category, str) or not category.strip():
        return f"category missing or empty: {category!r}"
    confidence = meta.get("confidence")
    if confidence is not None:
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return f"confidence not numeric: {confidence!r}"
        if not 0.0 <= value <= 1.0:
            return f"confidence out of range: {value}"
    return None


def enrich_article(
    article: ArticleInput,
    profile: Profile,
    *,
    model: str,
    attempts: int = 0,
    max_attempts: int = 3,
) -> EnrichmentOutcome:
    results: list[StepResult] = []
    steps: list[str] = []

    def outcome(status: str, skip_reason: str | None = None) -> EnrichmentOutcome:
        return EnrichmentOutcome(
            article_id=article.id,
            status=status,
            skip_reason=skip_reason,
            steps_applied=list(steps),
            results=list(results),
            total_cost_usd=sum((r.cost_usd for r in results), Decimal("0")),
        )

    def transient_failure() -> EnrichmentOutcome:
        # Partial results are discarded with the article; nothing is written.
        if attempts + 1 >= max_attempts:
            return outcome("enrichment_skipped", "failed_max_attempts")
        return outcome("labeled")

    # ---- step 0: content gate ------------------------------------------------
    if profile.content_gate:
        if boilerplate_score(article.content) >= HEURISTIC_REJECT:
            return outcome("not_article", None)
        gate = adapter.run_content_gate(article, model)
        results.append(gate)
        if not gate.ok or gate.payload is None:
            return transient_failure()
        verdict = gate.payload["verdict"]
        if verdict in _GATE_VERDICT_STATUS:
            return outcome(_GATE_VERDICT_STATUS[verdict], None)
        steps.append("content_gate")

    # ---- step 1: scope -------------------------------------------------------
    scope_category: str | None = None
    if profile.scope:
        scope = adapter.run_scope(article, model)
        results.append(scope)
        if not scope.ok or scope.payload is None:
            return transient_failure()
        if _metadata_payload_invalid(scope.payload):
            return transient_failure()
        scope_category = scope.payload["article_metadata"]["category"]
        steps.append("scope")

    # ---- steps 2–3: places and point resolution ------------------------------
    if profile.places and scope_category in POINT_SCOPES:
        places = adapter.run_places(article, model)
        results.append(places)
        if not places.ok or places.payload is None:
            return transient_failure()
        steps.append("places")
        resolve_point(places.payload, article.publication_city)
        # The resolved point rides in the places StepResult payload for the
        # repository to persist; geocode (step 4) is validated off in profiles.

    # ---- step 5: remaining metadata presets ----------------------------------
    for preset in profile.metadata_presets:
        result = adapter.run_preset(article, preset, model)
        results.append(result)
        if not result.ok or result.payload is None:
            return transient_failure()
        if _metadata_payload_invalid(result.payload):
            return transient_failure()
        steps.append(preset)

    # ---- step 6: people and organizations ------------------------------------
    if profile.people:
        people = adapter.run_people(article, model)
        results.append(people)
        if not people.ok:
            return transient_failure()
        steps.append("people")

    if profile.organizations:
        organizations = adapter.run_organizations(article, model)
        results.append(organizations)
        if not organizations.ok:
            return transient_failure()
        steps.append("organizations")

    if steps:
        return outcome("enriched")
    return outcome("enrichment_skipped", "profile_none")
