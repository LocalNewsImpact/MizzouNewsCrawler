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

from src.enrichment.fips import county_geoid, place_geoid, resolve_geoid, state_geoid
from src.enrichment.profiles import Profile, parse_profile
from src.enrichment.resolve import norm, resolve_point
from src.enrichment.types import ArticleInput, EnrichmentOutcome

TERMINAL_STATUSES = ("enriched", "enrichment_skipped", "out_of_scope")
EXPORTABLE_STATUSES = ("enriched", "enrichment_skipped")

_CANDIDATE_SQL = text("""
    SELECT a.id, a.title, a.content, d.slug AS dataset_slug, s.city AS publication_city,
           coalesce(nullif(s.metadata::json->>'state',''), d.metadata::json->>'default_state') AS publication_state
    FROM articles a
    JOIN candidate_links cl ON cl.id = a.candidate_link_id
    JOIN dataset_sources ds ON ds.source_id = cl.source_id
    JOIN datasets d          ON d.id = ds.dataset_id
    LEFT JOIN sources s      ON s.id = cl.source_id
    WHERE d.slug = :dataset
      AND a.status = 'labeled'
      AND a.wire_check_status IN ('complete', 'local')
      AND a.enrichment_attempts < :max_attempts
      AND (CAST(:since AS date) IS NULL OR a.created_at >= CAST(:since AS date))
    ORDER BY a.created_at
    LIMIT :batch
    FOR UPDATE OF a SKIP LOCKED
    """)

_REPROCESS_SQL = text("""
    SELECT a.id, a.title, a.content, d.slug AS dataset_slug, s.city AS publication_city,
           coalesce(nullif(s.metadata::json->>'state',''), d.metadata::json->>'default_state') AS publication_state
    FROM articles a
    JOIN candidate_links cl ON cl.id = a.candidate_link_id
    JOIN dataset_sources ds ON ds.source_id = cl.source_id
    JOIN datasets d          ON d.id = ds.dataset_id
    LEFT JOIN sources s      ON s.id = cl.source_id
    LEFT JOIN article_enrichment e ON e.article_id = a.id
    WHERE d.slug = :dataset
      AND a.wire_check_status IN ('complete', 'local')
      AND (
        (a.status = 'labeled' AND a.enrichment_attempts < :max_attempts)
        OR (a.status IN ('enriched', 'enrichment_skipped', 'out_of_scope')
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
            publication_state=getattr(r, "publication_state", None),
        )
        for r in rows
    ]


def select_candidates(
    session: Session,
    dataset_slug: str,
    batch: int,
    max_attempts: int,
    since: str | None = None,
) -> list[ArticleInput]:
    rows = session.execute(
        _CANDIDATE_SQL,
        {
            "dataset": dataset_slug,
            "batch": batch,
            "max_attempts": max_attempts,
            "since": since,
        },
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
                   d.slug AS dataset_slug, s.city AS publication_city,
           coalesce(nullif(s.metadata::json->>'state',''), d.metadata::json->>'default_state') AS publication_state
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
        elif row.wire_check_status not in ("complete", "local"):
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
                    getattr(row, "publication_state", None),
                )
            )
    return ListReport(candidates=candidates, rejected=rejected)


# ---- writes -----------------------------------------------------------------


def _geoid_for(places_payload: dict, point):
    """Run the FIPS ladder from the extracted components (§ fips.py)."""
    point_norm = norm(point[0]) if point else None
    state = county = street = street_city = None
    states, counties = {}, {}
    for location in places_payload.get("locations") or []:
        components = (location.get("location") or {}).get("components") or {}
        loc_state = components.get("state")
        if isinstance(loc_state, dict):
            loc_state = loc_state.get("abbr") or loc_state.get("name")
        city = components.get("city")
        if loc_state:
            states[loc_state] = states.get(loc_state, 0) + 1
        if components.get("county"):
            counties[components["county"]] = counties.get(components["county"], 0) + 1
        matches_point = bool(point_norm and city and norm(city) == point_norm)
        if matches_point:
            if loc_state:
                state = loc_state
            if components.get("county"):
                county = components["county"]
        address = (components.get("address") or "").strip()
        if address and street is None and (matches_point or not point_norm):
            street, street_city = address, city
    if state is None and states:
        state = max(states, key=lambda k: states[k])
    if county is None and counties:
        county = max(counties, key=lambda k: counties[k])
    return resolve_geoid(
        point_city=point[0] if point else None,
        state=state,
        county=county,
        street_address=street,
        address_city=street_city,
        census_lookup=True,
    )


def build_story_geoids(
    point_geoid,  # GeoidResult | None
    place_rows: list[tuple[str | None, str | None]],  # (geoid, level) per mention
    scope_category: str | None,
    state_code: str | None,
    point_place_name: str | None = None,
    place_row_names: list[str | None] | None = None,
) -> list[tuple[str, str, bool, str]]:
    """The distinct story-to-FIPS set: (geoid, level, is_primary, source).

    News geography is one-to-many. The point (when resolved) is primary;
    every distinct mention GEOID joins the set; a statewide story contributes
    its state code. Order: primary first, then mentions by first appearance.

    One rung per location (decided 2026-08-21): the Census hierarchy is
    already declared by the codes themselves, so ancestors of a more specific
    code are dropped. Only genuine prefix relations apply — state prefixes
    everything, county prefixes tract/block. Place codes do NOT nest by
    prefix, so a place is dropped only when the point resolved below place
    level at that same named place.
    """
    out: list[tuple[str, str, bool, str]] = []
    seen: set[str] = set()
    names = place_row_names or [None] * len(place_rows)
    if point_geoid is not None:
        out.append((point_geoid.geoid, point_geoid.level, True, "point"))
        seen.add(point_geoid.geoid)
    for (geoid, level), name in zip(place_rows, names, strict=False):
        if not geoid or geoid in seen:
            continue
        lvl = level or "place"
        if (
            point_geoid is not None
            and point_geoid.level in ("tract", "block")
            and lvl == "place"
            and point_place_name
            and name
            and norm(name) == norm(point_place_name)
        ):
            continue  # same place, point already carries the lower rung
        out.append((geoid, lvl, False, "mention"))
        seen.add(geoid)
    if scope_category == "statewide" and state_code and state_code not in seen:
        out.append(
            (state_code, "state", point_geoid is None and not out, "scope_state")
        )
        seen.add(state_code)
    # Drop hierarchy ancestors: a state code when anything longer shares its
    # 2-digit prefix; a county code when a tract/block carries its 5 digits.
    specific = [g for g, _, _, _ in out]
    kept = []
    for g, lvl, primary, src in out:
        if lvl == "state" and any(o != g and o.startswith(g) for o in specific):
            continue
        if lvl == "county" and any(
            len(o) in (11, 15) and o.startswith(g) for o in specific
        ):
            continue
        kept.append((g, lvl, primary, src))
    return kept


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
    geoid = None
    places_payload = step_payloads.get("places")
    scope_meta = (step_payloads.get("scope") or {}).get("article_metadata") or {}
    scope_category = scope_meta.get("category")
    if places_payload:
        # A point is resolved only at point scope. Regional keeps its places
        # rows (each with a per-place GEOID) and no story-level point.
        if scope_category in ("city_municipality", "neighborhood_community"):
            point = resolve_point(places_payload, article.publication_city)
            geoid = _geoid_for(places_payload, point)
            # A point-scope story must never take the ladder's state rung —
            # that rung exists for statewide scope. A state-level result here
            # means the point city missed the gazetteer (e.g. "Webster" for
            # Webster Groves): treat as unresolved so the publication-place
            # fallback below applies instead of coding the whole state.
            if geoid is not None and geoid.level == "state":
                geoid = None
                point = None
    # Story-level fallbacks (decided 2026-08-21). regional gets NO story-level
    # code: its geography is the per-place GEOIDs on its mentions — a state
    # championship matters to the two teams' cities, not to the state.
    # statewide keeps the state code (legislation genuinely is statewide).
    # Unresolved city/neighborhood stories take the publication's own city as
    # an assumed place. national/international/other stay null.
    geo_skip_reason = None
    if geoid is None:
        category = scope_category
        if category == "statewide" and article.publication_state:
            geoid = state_geoid(article.publication_state)
        elif (
            category in ("city_municipality", "neighborhood_community")
            and article.publication_city
            and article.publication_state
        ):
            geoid = place_geoid(article.publication_city, article.publication_state)
            if geoid is not None and point is None:
                point = (article.publication_city, "publication_place_assumed")

    # An absent point code must carry its cause (decided 2026-08-21).
    if geoid is None:
        if scope_category == "regional":
            geo_skip_reason = "regional_uses_place_set"
        elif scope_category in ("national", "international", "other"):
            geo_skip_reason = "no_codeable_geography"
        elif scope_category is None:
            geo_skip_reason = "not_scoped"
        elif scope_category in ("city_municipality", "neighborhood_community"):
            if not article.publication_state:
                geo_skip_reason = "publication_state_unknown"
            elif point is not None:
                geo_skip_reason = "city_not_in_census_gazetteer"
            else:
                geo_skip_reason = "publication_city_not_in_census_gazetteer"
        elif scope_category == "statewide":
            geo_skip_reason = "publication_state_unknown"

    session.execute(
        text("""
            INSERT INTO article_enrichment (
              article_id, profile_version, steps_applied, skip_reason,
              backfield_commit, model, prompt_versions, cost_usd, enriched_at,
              is_news_content, content_gate_reason,
              scope, scope_confidence, subject, subject_confidence,
              topic, topic_confidence, format, format_confidence,
              timeframe, timeframe_confidence, user_need, user_need_confidence,
              rationales, point_place, point_method,
              point_geoid, point_geoid_level, point_lat, point_lon, geoids,
              geo_skip_reason
            ) VALUES (
              :article_id, :profile_version, :steps_applied, :skip_reason,
              :backfield_commit, :model, :prompt_versions, :cost_usd, :enriched_at,
              :is_news_content, :content_gate_reason,
              :scope, :scope_confidence, :subject, :subject_confidence,
              :topic, :topic_confidence, :format, :format_confidence,
              :timeframe, :timeframe_confidence, :user_need, :user_need_confidence,
              :rationales, :point_place, :point_method,
              :point_geoid, :point_geoid_level, :point_lat, :point_lon, :geoids,
              :geo_skip_reason
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
              point_method = COALESCE(EXCLUDED.point_method, article_enrichment.point_method),
              point_geoid = COALESCE(EXCLUDED.point_geoid, article_enrichment.point_geoid),
              point_geoid_level = COALESCE(EXCLUDED.point_geoid_level, article_enrichment.point_geoid_level),
              point_lat = COALESCE(EXCLUDED.point_lat, article_enrichment.point_lat),
              point_lon = COALESCE(EXCLUDED.point_lon, article_enrichment.point_lon),
              geoids = COALESCE(EXCLUDED.geoids, article_enrichment.geoids),
              geo_skip_reason = EXCLUDED.geo_skip_reason
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
            "point_geoid": geoid.geoid if geoid else None,
            "point_geoid_level": geoid.level if geoid else None,
            "point_lat": geoid.lat if geoid else None,
            "point_lon": geoid.lon if geoid else None,
            "geoids": None,  # filled below once the story set is built
            "geo_skip_reason": geo_skip_reason,
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
            row_state = state or article.publication_state
            row_geoid = None
            if city and row_state:
                row_geoid = place_geoid(city, row_state)
            if row_geoid is None and components.get("county") and row_state:
                row_geoid = county_geoid(components["county"], row_state)
            session.execute(
                text("""
                    INSERT INTO article_places
                      (article_id, full_name, place_type, city, county, state,
                       address, description, mention_text, is_point,
                       geoid, geoid_level)
                    VALUES
                      (:article_id, :full_name, :place_type, :city, :county, :state,
                       :address, :description, :mention_text, :is_point,
                       :geoid, :geoid_level)
                    """),
                {
                    "geoid": row_geoid.geoid if row_geoid else None,
                    "geoid_level": row_geoid.level if row_geoid else None,
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

    # The story-to-FIPS set (one row per distinct GEOID; news geography is
    # one-to-many). Rebuilt whole on every persist.
    mention_geoids: list[tuple[str | None, str | None]] = []
    mention_names: list[str | None] = []
    if places_payload:
        for location in places_payload.get("locations") or []:
            components = (location.get("location") or {}).get("components") or {}
            loc_state = components.get("state")
            if isinstance(loc_state, dict):
                loc_state = loc_state.get("abbr") or loc_state.get("name")
            loc_state = loc_state or article.publication_state
            city = components.get("city")
            g = place_geoid(city, loc_state) if (city and loc_state) else None
            if g is None and components.get("county") and loc_state:
                g = county_geoid(components["county"], loc_state)
            mention_geoids.append((g.geoid if g else None, g.level if g else None))
            mention_names.append(city)
    state_code = None
    if article.publication_state:
        sg = state_geoid(article.publication_state)
        state_code = sg.geoid if sg else None
    story_geoids = build_story_geoids(
        geoid,
        mention_geoids,
        scope_category,
        state_code,
        point_place_name=point[0] if point else None,
        place_row_names=mention_names,
    )
    geoids_json = json.dumps([g for g, *_ in story_geoids]) if story_geoids else None
    session.execute(
        text("DELETE FROM article_geoids WHERE article_id = :id"), {"id": article.id}
    )
    for g_code, g_level, g_primary, g_source in story_geoids:
        session.execute(
            text(
                "INSERT INTO article_geoids "
                "(article_id, geoid, geoid_level, is_primary, source) "
                "VALUES (:a, :g, :l, :p, :s) ON CONFLICT DO NOTHING"
            ),
            {"a": article.id, "g": g_code, "l": g_level, "p": g_primary, "s": g_source},
        )

    session.execute(
        text("UPDATE article_enrichment SET geoids = :g WHERE article_id = :id"),
        {"g": geoids_json, "id": article.id},
    )

    session.execute(
        text("UPDATE articles SET status = :status, enriched_at = :now WHERE id = :id"),
        {"status": outcome.status, "now": now, "id": article.id},
    )
    session.commit()
