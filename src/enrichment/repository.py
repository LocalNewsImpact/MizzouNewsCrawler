"""All enrichment reads and writes. No backfield imports; plain SQLAlchemy.

Candidate selection follows §5.1: FOR UPDATE SKIP LOCKED so concurrent runs are
safe, following the direct extraction path's pattern. Writes follow §9's tables
and §7's rules: an outcome is committed per article, never per run, and a
'labeled' outcome (transient failure) increments attempts and writes nothing
else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.enrichment.profiles import Profile, parse_profile
from src.enrichment.resolve import norm, resolve_point
from src.enrichment.types import ArticleInput, EnrichmentOutcome

TERMINAL_STATUSES = ("enriched", "enrichment_skipped")

_CANDIDATE_SQL = text("""
    SELECT a.id, a.title, a.content, d.slug AS dataset_slug, s.city AS publication_city
    FROM articles a
    JOIN candidate_links cl ON cl.id = a.candidate_link_id
    JOIN dataset_sources ds ON ds.source_id = cl.source_id
    JOIN datasets d          ON d.id = ds.dataset_id
    LEFT JOIN sources s      ON s.id = cl.source_id
    WHERE d.slug = :dataset
      AND a.status = 'labeled'
      AND a.wire_check_status = 'complete'
      AND a.enrichment_attempts < :max_attempts
    ORDER BY a.created_at
    LIMIT :batch
    FOR UPDATE OF a SKIP LOCKED
    """)

_REPROCESS_SQL = text("""
    SELECT a.id, a.title, a.content, d.slug AS dataset_slug, s.city AS publication_city
    FROM articles a
    JOIN candidate_links cl ON cl.id = a.candidate_link_id
    JOIN dataset_sources ds ON ds.source_id = cl.source_id
    JOIN datasets d          ON d.id = ds.dataset_id
    LEFT JOIN sources s      ON s.id = cl.source_id
    LEFT JOIN article_enrichment e ON e.article_id = a.id
    WHERE d.slug = :dataset
      AND a.wire_check_status = 'complete'
      AND (
        (a.status = 'labeled' AND a.enrichment_attempts < :max_attempts)
        OR (a.status IN ('enriched', 'enrichment_skipped')
            AND e.profile_version < :profile_version)
      )
    ORDER BY a.created_at
    LIMIT :batch
    FOR UPDATE OF a SKIP LOCKED
    """)


@dataclass(frozen=True)
class ListReport:
    """Backfill accounting (§5.1): every supplied id is accounted for."""

    candidates: list[ArticleInput]
    rejected: dict[str, str]  # id -> reason


def dataset_profile(session: Session, dataset_slug: str) -> Profile:
    row = session.execute(
        text("SELECT metadata FROM datasets WHERE slug = :slug"),
        {"slug": dataset_slug},
    ).first()
    if row is None:
        from src.enrichment.profiles import ConfigurationError

        raise ConfigurationError(f"unknown dataset: {dataset_slug}")
    meta = row[0]
    if isinstance(meta, str):
        meta = json.loads(meta) if meta else {}
    raw = (meta or {}).get("enrichment_profile")
    return parse_profile(raw)


def _rows_to_articles(rows) -> list[ArticleInput]:
    return [
        ArticleInput(
            id=r.id,
            title=r.title or "",
            content=r.content or "",
            dataset_slug=r.dataset_slug,
            publication_city=r.publication_city,
        )
        for r in rows
    ]


def select_candidates(
    session: Session, dataset_slug: str, batch: int, max_attempts: int
) -> list[ArticleInput]:
    rows = session.execute(
        _CANDIDATE_SQL,
        {"dataset": dataset_slug, "batch": batch, "max_attempts": max_attempts},
    ).fetchall()
    return _rows_to_articles(rows)


def select_reprocess_candidates(
    session: Session,
    dataset_slug: str,
    profile_version: int,
    batch: int,
    max_attempts: int,
) -> list[ArticleInput]:
    rows = session.execute(
        _REPROCESS_SQL,
        {
            "dataset": dataset_slug,
            "profile_version": profile_version,
            "batch": batch,
            "max_attempts": max_attempts,
        },
    ).fetchall()
    return _rows_to_articles(rows)


def select_by_ids(session: Session, ids: list[str], max_attempts: int) -> ListReport:
    """Backfill selection. Ids that are not candidates are reported with the
    predicate that excluded them, never silently dropped."""
    rejected: dict[str, str] = {}
    found = session.execute(
        text("""
            SELECT a.id, a.title, a.content, a.status, a.wire_check_status,
                   a.enrichment_attempts,
                   d.slug AS dataset_slug, s.city AS publication_city
            FROM articles a
            LEFT JOIN candidate_links cl ON cl.id = a.candidate_link_id
            LEFT JOIN dataset_sources ds ON ds.source_id = cl.source_id
            LEFT JOIN datasets d          ON d.id = ds.dataset_id
            LEFT JOIN sources s           ON s.id = cl.source_id
            WHERE a.id = ANY(:ids)
            """),
        {"ids": ids},
    ).fetchall()
    by_id = {r.id: r for r in found}

    candidates = []
    for article_id in ids:
        row = by_id.get(article_id)
        if row is None:
            rejected[article_id] = "not found"
        elif row.status != "labeled":
            rejected[article_id] = f"status is {row.status!r}, not 'labeled'"
        elif row.wire_check_status != "complete":
            rejected[article_id] = f"wire_check_status is {row.wire_check_status!r}"
        elif row.enrichment_attempts >= max_attempts:
            rejected[article_id] = f"attempts exhausted ({row.enrichment_attempts})"
        elif row.dataset_slug is None:
            rejected[article_id] = "no dataset"
        else:
            candidates.append(
                ArticleInput(
                    row.id,
                    row.title or "",
                    row.content or "",
                    row.dataset_slug,
                    row.publication_city,
                )
            )
    return ListReport(candidates=candidates, rejected=rejected)


# ---- writes -----------------------------------------------------------------


def _confidence(meta: dict) -> float | None:
    value = meta.get("confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def persist_outcome(
    session: Session,
    article: ArticleInput,
    outcome: EnrichmentOutcome,
    *,
    profile: Profile,
    model: str,
    backfield_commit: str,
    prompt_versions: dict[str, str],
) -> None:
    """Write one article's outcome and commit. §5.2: a 'labeled' outcome writes
    nothing but the attempt counter; partial results are discarded."""
    now = datetime.now(timezone.utc)

    if outcome.status == "labeled":
        session.execute(
            text(
                "UPDATE articles SET enrichment_attempts = enrichment_attempts + 1 "
                "WHERE id = :id"
            ),
            {"id": article.id},
        )
        session.commit()
        return

    step_payloads = {r.step: r.payload for r in outcome.results if r.ok and r.payload}
    presets = {
        "scope": step_payloads.get("scope"),
        "subject": step_payloads.get("subject"),
        "topic": step_payloads.get("topic"),
        "format": step_payloads.get("format"),
        "timeframe": step_payloads.get("temporal_orientation"),
        "user_need": step_payloads.get("user_need"),
    }
    columns: dict[str, object] = {}
    rationales: dict[str, str] = {}
    for column, payload in presets.items():
        meta = (payload or {}).get("article_metadata") or {}
        columns[column] = meta.get("category")
        columns[f"{column}_confidence"] = _confidence(meta)
        if meta.get("rationale"):
            rationales[column] = meta["rationale"]

    gate = step_payloads.get("content_gate") or {}
    point = None
    places_payload = step_payloads.get("places")
    if places_payload:
        point = resolve_point(places_payload, article.publication_city)

    session.execute(
        text("""
            INSERT INTO article_enrichment (
              article_id, profile_version, steps_applied, skip_reason,
              backfield_commit, model, prompt_versions, cost_usd, enriched_at,
              is_news_content, content_gate_reason,
              scope, scope_confidence, subject, subject_confidence,
              topic, topic_confidence, format, format_confidence,
              timeframe, timeframe_confidence, user_need, user_need_confidence,
              rationales, point_place, point_method
            ) VALUES (
              :article_id, :profile_version, :steps_applied, :skip_reason,
              :backfield_commit, :model, :prompt_versions, :cost_usd, :enriched_at,
              :is_news_content, :content_gate_reason,
              :scope, :scope_confidence, :subject, :subject_confidence,
              :topic, :topic_confidence, :format, :format_confidence,
              :timeframe, :timeframe_confidence, :user_need, :user_need_confidence,
              :rationales, :point_place, :point_method
            )
            ON CONFLICT (article_id) DO UPDATE SET
              profile_version = EXCLUDED.profile_version,
              steps_applied = EXCLUDED.steps_applied,
              skip_reason = EXCLUDED.skip_reason,
              backfield_commit = EXCLUDED.backfield_commit,
              model = EXCLUDED.model,
              prompt_versions = EXCLUDED.prompt_versions,
              cost_usd = EXCLUDED.cost_usd,
              enriched_at = EXCLUDED.enriched_at,
              is_news_content = EXCLUDED.is_news_content,
              content_gate_reason = EXCLUDED.content_gate_reason,
              scope = COALESCE(EXCLUDED.scope, article_enrichment.scope),
              scope_confidence = COALESCE(EXCLUDED.scope_confidence, article_enrichment.scope_confidence),
              subject = COALESCE(EXCLUDED.subject, article_enrichment.subject),
              subject_confidence = COALESCE(EXCLUDED.subject_confidence, article_enrichment.subject_confidence),
              topic = COALESCE(EXCLUDED.topic, article_enrichment.topic),
              topic_confidence = COALESCE(EXCLUDED.topic_confidence, article_enrichment.topic_confidence),
              format = COALESCE(EXCLUDED.format, article_enrichment.format),
              format_confidence = COALESCE(EXCLUDED.format_confidence, article_enrichment.format_confidence),
              timeframe = COALESCE(EXCLUDED.timeframe, article_enrichment.timeframe),
              timeframe_confidence = COALESCE(EXCLUDED.timeframe_confidence, article_enrichment.timeframe_confidence),
              user_need = COALESCE(EXCLUDED.user_need, article_enrichment.user_need),
              user_need_confidence = COALESCE(EXCLUDED.user_need_confidence, article_enrichment.user_need_confidence),
              rationales = COALESCE(EXCLUDED.rationales, article_enrichment.rationales),
              point_place = COALESCE(EXCLUDED.point_place, article_enrichment.point_place),
              point_method = COALESCE(EXCLUDED.point_method, article_enrichment.point_method)
            """),
        {
            "article_id": article.id,
            "profile_version": profile.version,
            "steps_applied": outcome.steps_applied,
            "skip_reason": outcome.skip_reason,
            "backfield_commit": backfield_commit,
            "model": model,
            "prompt_versions": json.dumps(prompt_versions),
            "cost_usd": outcome.total_cost_usd,
            "enriched_at": now,
            "is_news_content": outcome.status == "enriched" or None,
            "content_gate_reason": gate.get("reason"),
            "rationales": json.dumps(rationales) if rationales else None,
            "point_place": point[0] if point else None,
            "point_method": point[1] if point else None,
            **columns,
        },
    )

    if places_payload:
        point_norm = norm(point[0]) if point else None
        session.execute(
            text("DELETE FROM article_places WHERE article_id = :id"),
            {"id": article.id},
        )
        for location in places_payload.get("locations") or []:
            loc = location.get("location") or {}
            components = loc.get("components") or {}
            state = components.get("state")
            if isinstance(state, dict):
                state = state.get("abbr") or state.get("name")
            city = components.get("city")
            session.execute(
                text("""
                    INSERT INTO article_places
                      (article_id, full_name, place_type, city, county, state,
                       address, description, mention_text, is_point)
                    VALUES
                      (:article_id, :full_name, :place_type, :city, :county, :state,
                       :address, :description, :mention_text, :is_point)
                    """),
                {
                    "article_id": article.id,
                    "full_name": loc.get("full"),
                    "place_type": loc.get("type"),
                    "city": city,
                    "county": components.get("county"),
                    "state": state,
                    "address": components.get("address"),
                    "description": location.get("description"),
                    "mention_text": location.get("original_text"),
                    "is_point": bool(point and city and norm(city) == point_norm),
                },
            )

    people_payload = step_payloads.get("people")
    if people_payload:
        session.execute(
            text("DELETE FROM article_people WHERE article_id = :id"),
            {"id": article.id},
        )
        for person in people_payload.get("people") or []:
            mentions = person.get("mentions") or []
            quotes = [m.get("text") for m in mentions if m.get("quote")]
            session.execute(
                text("""
                    INSERT INTO article_people
                      (article_id, name, sort_key, title, affiliation, person_type,
                       role_in_story, nature, public_figure, mention_count, quotes)
                    VALUES
                      (:article_id, :name, :sort_key, :title, :affiliation, :person_type,
                       :role_in_story, :nature, :public_figure, :mention_count, :quotes)
                    """),
                {
                    "article_id": article.id,
                    "name": person.get("name"),
                    "sort_key": person.get("sort_key"),
                    "title": person.get("title"),
                    "affiliation": person.get("affiliation"),
                    "person_type": person.get("type"),
                    "role_in_story": person.get("role_in_story"),
                    "nature": person.get("nature"),
                    "public_figure": person.get("public_figure"),
                    "mention_count": len(mentions),
                    "quotes": json.dumps(quotes) if quotes else None,
                },
            )

    organizations_payload = step_payloads.get("organizations")
    if organizations_payload:
        session.execute(
            text("DELETE FROM article_organizations WHERE article_id = :id"),
            {"id": article.id},
        )
        for organization in organizations_payload.get("organizations") or []:
            session.execute(
                text("""
                    INSERT INTO article_organizations
                      (article_id, name, org_type, boundary, role_in_story,
                       nature, mention_count)
                    VALUES
                      (:article_id, :name, :org_type, :boundary, :role_in_story,
                       :nature, :mention_count)
                    """),
                {
                    "article_id": article.id,
                    "name": organization.get("name"),
                    "org_type": organization.get("type"),
                    "boundary": organization.get("organization_boundary"),
                    "role_in_story": organization.get("role_in_story"),
                    "nature": organization.get("nature"),
                    "mention_count": len(organization.get("mentions") or []),
                },
            )

    session.execute(
        text("UPDATE articles SET status = :status, enriched_at = :now WHERE id = :id"),
        {"status": outcome.status, "now": now, "id": article.id},
    )
    session.commit()
