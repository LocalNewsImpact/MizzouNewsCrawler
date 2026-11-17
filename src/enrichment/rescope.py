"""Answer a story's scope again, and re-place it only where that requires.

A scope prompt change is a change to ONE question. Re-enriching the record
answers every question again -- places, focus, topic, subject, people --
and the model does not give the same answer twice: asked the same question
with the same prompt over 279 articles on 2026-09-16, it moved 34 of 167
points. A full re-run would bury the effect of the new prompt in that
churn, and nothing could say afterwards which changes the prompt made.

So this asks the scope question and nothing else that it does not have to:

  a story that already has its   the answer is recorded; geography
  kind of geography             untouched -- a point story staying a point
                                story, a regional one staying regional
  a story that now needs a      the focus step runs -- the stored record
  point and was never given one never asked it -- and the point is placed
  anything else                 re-placed from the stored places: the point
                                cleared, a place set or a state code written

"Never given one" is judged by the rules of the prompt version that
answered the stored record. Before v4 only a neighborhood or city story got
a point; a crossing scope (`elsewhere_to_local`, `local_to_elsewhere`) did
not, so a pre-v4 one of those is placed now even when its scope does not
change. From v4 every point scope was placed.

The extracted places are read back from `article_places` rather than asked
for again, so the place set a story is coded with changes only because its
scope did. Placement goes through `repository.story_point` and
`repository.write_story_geoids`, the functions enrichment itself uses, so a
rescoped story is placed by the rules that place a new one.

Every article read gets a row in `enrichment_rescope_log`, written in the
same transaction as the change it describes.

Selection is by the recorded prompt version: a record rescoped under the
current prompt is not selected again, so an interrupted run resumes where it
stopped and a finished one is a no-op.
"""

from __future__ import annotations

import json
import logging
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.enrichment import adapter
from src.enrichment.grounding import support_for
from src.enrichment.profiles import POINT_SCOPES
from src.enrichment.repository import (
    _as_dict,
    _confidence,
    _rows_to_articles,
    institution_places,
    story_point,
    write_story_geoids,
)
from src.enrichment.resolve import norm
from src.enrichment.types import ArticleInput, StepResult

logger = logging.getLogger(__name__)

#: The categories the scope prompt offers. An answer outside them is a
#: failed call, not a new scope.
SCOPES = frozenset(
    {
        "neighborhood_community",
        "city_municipality",
        "regional",
        "statewide",
        "national",
        "international",
        "elsewhere_to_local",
        "local_to_elsewhere",
        "other",
    }
)

#: The scopes that were given a point before geographic_scope-v4.
PLACED_BEFORE_V4 = frozenset({"neighborhood_community", "city_municipality"})


def placed_scopes(version: str | None) -> frozenset[str]:
    """The scopes the prompt version that answered a record gave a point."""
    prefix = "geographic_scope-v"
    if version and version.startswith(prefix) and version[len(prefix) :].isdigit():
        if int(version[len(prefix) :]) >= 4:
            return POINT_SCOPES
    return PLACED_BEFORE_V4


#: Measured on the v4 validation run: $0.0994 for 109 stories. Used only by
#: --dry-run.
PROJECTED_SCOPE_COST = Decimal("0.00091")

_CANDIDATES = text("""
    SELECT a.id, a.title, a.text, a.raw, a.metadata,
           d.slug AS dataset_slug, s.city AS publication_city,
           coalesce(nullif(s.metadata::json->>'state',''),
                    d.metadata::json->>'default_state') AS publication_state,
           e.scope AS old_scope,
           CAST(e.prompt_versions AS jsonb)->>'scope' AS old_version
      FROM article_enrichment e
      JOIN articles a          ON a.id = e.article_id
      JOIN candidate_links cl  ON cl.id = a.candidate_link_id
      JOIN dataset_sources ds  ON ds.source_id = cl.source_id
      JOIN datasets d          ON d.id = ds.dataset_id
      LEFT JOIN sources s      ON s.id = cl.source_id
     WHERE d.slug = :dataset
       AND a.status = 'enriched'
       AND e.scope IS NOT NULL
       AND coalesce(a.text, '') <> ''
       AND coalesce(CAST(e.prompt_versions AS jsonb)->>'scope', '') <> :version
     ORDER BY a.id
""")

_BEFORE = text("""
    SELECT scope, scope_confidence, rationales, point_place, point_method,
           point_geoid, geoids, geo_skip_reason
      FROM article_enrichment
     WHERE article_id = :id
""")

_PLACES = text("""
    SELECT id, full_name, place_type, city, county, state, address,
           description, mention_text
      FROM article_places
     WHERE article_id = :id
     ORDER BY id
""")

#: The scope answer and its provenance. Shared by every outcome.
_SCOPE_SET = """
    scope = :scope,
    scope_confidence = :confidence,
    rationales = CAST(
        coalesce(CAST(rationales AS jsonb), '{}'::jsonb)
        || jsonb_build_object('scope', CAST(:rationale AS text)) AS json),
    prompt_versions = CAST(
        coalesce(CAST(prompt_versions AS jsonb), '{}'::jsonb)
        || jsonb_build_object('scope', CAST(:version AS text)) AS json),
    cost_usd = coalesce(cost_usd, 0) + :cost
"""

_UPDATE_SCOPE = text(
    f"UPDATE article_enrichment SET {_SCOPE_SET} WHERE article_id = :id"
)

#: Point columns written outright, NULL included. The enrichment upsert
#: COALESCEs them, which keeps a point a story no longer has.
_UPDATE_PLACED = text(f"""
    UPDATE article_enrichment SET {_SCOPE_SET},
           steps_applied = CASE
               WHEN :focus_ran AND NOT ('focus' = ANY(steps_applied))
               THEN array_append(steps_applied, 'focus')
               ELSE steps_applied END,
           point_place = :point_place,
           point_method = :point_method,
           point_support = :point_support,
           point_geoid = :point_geoid,
           point_geoid_level = :point_geoid_level,
           point_lat = :point_lat,
           point_lon = :point_lon,
           point_zcta = :point_zcta
     WHERE article_id = :id
""")

_LOG = text("""
    INSERT INTO enrichment_rescope_log (
      run_id, article_id, dataset_slug, prompt_version, model, change,
      old_scope, new_scope, old_confidence, new_confidence,
      old_rationale, new_rationale,
      old_point_place, new_point_place, old_point_method, new_point_method,
      old_point_geoid, new_point_geoid, old_geoids, new_geoids,
      old_geo_skip_reason, new_geo_skip_reason, focus_run, cost_usd, error
    ) VALUES (
      :run_id, :article_id, :dataset_slug, :prompt_version, :model, :change,
      :old_scope, :new_scope, :old_confidence, :new_confidence,
      :old_rationale, :new_rationale,
      :old_point_place, :new_point_place, :old_point_method, :new_point_method,
      :old_point_geoid, :new_point_geoid, CAST(:old_geoids AS json),
      CAST(:new_geoids AS json),
      :old_geo_skip_reason, :new_geo_skip_reason, :focus_run, :cost, :error
    )
""")


@dataclass(frozen=True)
class Candidate:
    article: ArticleInput
    old_scope: str | None
    #: Whether its stored scope was given a point by the version that
    #: answered it.
    placed: bool


@dataclass(frozen=True)
class Answer:
    """What the model said for one article. Built on a worker thread."""

    article: ArticleInput
    old_scope: str | None
    #: Whether the stored record's scope was given a point when answered.
    placed: bool
    scope: StepResult
    focus: StepResult | None

    @property
    def cost(self) -> Decimal:
        total = self.scope.cost_usd or Decimal("0")
        if self.focus is not None:
            total += self.focus.cost_usd or Decimal("0")
        return total


def select(session: Session, dataset: str, limit: int | None = None):
    rows = session.execute(
        _CANDIDATES, {"dataset": dataset, "version": adapter.SCOPE_PROMPT_VERSION}
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    articles = _rows_to_articles(rows)
    return [
        Candidate(a, r.old_scope, r.old_scope in placed_scopes(r.old_version))
        for a, r in zip(articles, rows, strict=True)
    ]


def scope_meta(result: StepResult) -> dict | None:
    """The scope answer, or None when the call did not give a usable one."""
    if not result.ok or not result.payload:
        return None
    meta = result.payload.get("article_metadata") or {}
    if meta.get("category") not in SCOPES:
        return None
    return meta


def ask(candidate: Candidate, model: str) -> Answer:
    """The model calls for one article: scope, and focus when it is needed.

    Focus is asked only for a story that now needs a point and was never
    given one. A story already placed at a point scope keeps its point;
    asking focus again would only re-roll it.
    """
    article = candidate.article
    scope = adapter.run_scope(article, model)
    meta = scope_meta(scope)
    focus = None
    if meta is not None and needs_point(meta["category"], candidate.placed):
        focus = adapter.run_focus(article, model)
    return Answer(
        article=article,
        old_scope=candidate.old_scope,
        placed=candidate.placed,
        scope=scope,
        focus=focus,
    )


def needs_point(new_scope: str, placed: bool) -> bool:
    return new_scope in POINT_SCOPES and not placed


def needs_placing(new_scope: str, old_scope: str | None, placed: bool) -> bool:
    """Whether the stored geography is wrong for the new scope."""
    if new_scope in POINT_SCOPES:
        return needs_point(new_scope, placed)
    return new_scope != old_scope


def places_payload(session: Session, article_id: str) -> tuple[dict, list]:
    """The stored places, in the shape the places step returns them."""
    rows = list(session.execute(_PLACES, {"id": article_id}).fetchall())
    locations = [
        {
            "location": {
                "full": r.full_name,
                "type": r.place_type,
                "components": {
                    "city": r.city,
                    "county": r.county,
                    "state": r.state,
                    "address": r.address,
                },
            },
            "description": r.description,
            "original_text": r.mention_text,
        }
        for r in rows
    ]
    return {"locations": locations}, rows


def _geoids(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return list(value) if isinstance(value, list) else []


def classify(before: dict, after: dict) -> str:
    """Which part of the record moved. Read off the record, not the plan.

    Geography first: a crossing-scope story keeps its scope and gains a
    point, and that is a change.
    """
    had, has = before["point_geoid"], after["point_geoid"]
    if had is None and has is not None:
        return "point_added"
    if had is not None and has is None:
        return "point_removed"
    if had != has:
        return "point_moved"
    if sorted(_geoids(before["geoids"])) != sorted(_geoids(after["geoids"])):
        return "place_set_changed"
    if before["scope"] != after["scope"]:
        return "scope_only"
    return "unchanged"


def _state(session: Session, article_id: str) -> dict:
    row = session.execute(_BEFORE, {"id": article_id}).mappings().first()
    if row is None:
        raise LookupError(f"no enrichment record for {article_id}")
    state = dict(row)
    rationales = _as_dict(state.pop("rationales"))
    state["rationale"] = rationales.get("scope")
    return state


def apply(session: Session, answer: Answer, *, run_id: str, model: str) -> str:
    """Write one article's new scope, re-place it if needed, log it, commit."""
    article = answer.article
    before = _state(session, article.id)
    meta = scope_meta(answer.scope)
    log = {
        "run_id": run_id,
        "article_id": article.id,
        "dataset_slug": article.dataset_slug,
        "prompt_version": adapter.SCOPE_PROMPT_VERSION,
        "model": model,
        "old_scope": before["scope"],
        "old_confidence": before["scope_confidence"],
        "old_rationale": before["rationale"],
        "old_point_place": before["point_place"],
        "old_point_method": before["point_method"],
        "old_point_geoid": before["point_geoid"],
        "old_geoids": json.dumps(_geoids(before["geoids"])),
        "old_geo_skip_reason": before["geo_skip_reason"],
        "focus_run": answer.focus is not None,
        "cost": answer.cost,
    }

    if meta is None:
        # Nothing about the record changes; the spend and the failure are
        # still on record, and the article is selected again next run.
        session.execute(
            _LOG,
            {
                **log,
                **_unchanged_after(before),
                "change": "error",
                "new_scope": None,
                "new_confidence": None,
                "new_rationale": None,
                "error": answer.scope.error or "no usable scope answer",
            },
        )
        session.commit()
        return "error"

    new_scope = meta["category"]
    scope_params = {
        "id": article.id,
        "scope": new_scope,
        "confidence": _confidence(meta),
        "rationale": meta.get("rationale"),
        "version": adapter.SCOPE_PROMPT_VERSION,
        "cost": answer.cost,
    }
    if needs_placing(new_scope, answer.old_scope, answer.placed):
        _replace(session, article, new_scope, answer, scope_params)
    else:
        session.execute(_UPDATE_SCOPE, scope_params)

    after = _state(session, article.id)
    change = classify(before, after)
    session.execute(
        _LOG,
        {
            **log,
            "change": change,
            "new_scope": after["scope"],
            "new_confidence": after["scope_confidence"],
            "new_rationale": after["rationale"],
            "new_point_place": after["point_place"],
            "new_point_method": after["point_method"],
            "new_point_geoid": after["point_geoid"],
            "new_geoids": json.dumps(_geoids(after["geoids"])),
            "new_geo_skip_reason": after["geo_skip_reason"],
            "error": None,
        },
    )
    session.commit()
    return change


def _unchanged_after(before: dict) -> dict:
    return {
        "new_point_place": before["point_place"],
        "new_point_method": before["point_method"],
        "new_point_geoid": before["point_geoid"],
        "new_geoids": json.dumps(_geoids(before["geoids"])),
        "new_geo_skip_reason": before["geo_skip_reason"],
    }


def _replace(
    session: Session,
    article: ArticleInput,
    new_scope: str,
    answer: Answer,
    scope_params: dict,
) -> None:
    """Place the story again under its new scope, from its stored places."""
    payload, place_rows = places_payload(session, article.id)
    named = institution_places(session, article.id)
    focus_ok = answer.focus is not None and answer.focus.ok
    point, geoid, skip_reason = story_point(
        session,
        article,
        new_scope,
        payload,
        answer.focus.payload if focus_ok else None,
        named,
    )
    session.execute(
        _UPDATE_PLACED,
        {
            **scope_params,
            "focus_ran": focus_ok,
            "point_place": point[0] if point else None,
            "point_method": point[1] if point else None,
            "point_support": (
                support_for(
                    point[0],
                    content=article.content,
                    title=article.title,
                    publication_city=article.publication_city,
                    institution_places=named,
                )
                if point
                else None
            ),
            "point_geoid": geoid.geoid if geoid else None,
            "point_geoid_level": geoid.level if geoid else None,
            "point_lat": geoid.lat if geoid else None,
            "point_lon": geoid.lon if geoid else None,
            "point_zcta": getattr(geoid, "zcta", None) if geoid else None,
        },
    )
    write_story_geoids(
        session,
        article,
        geoid=geoid,
        point=point,
        scope_category=new_scope,
        places_payload=payload,
        named_places=named,
        geo_skip_reason=skip_reason,
    )
    point_norm = norm(point[0]) if point else None
    for row in place_rows:
        session.execute(
            text("UPDATE article_places SET is_point = :p WHERE id = :id"),
            {
                "p": bool(point_norm and row.city and norm(row.city) == point_norm),
                "id": row.id,
            },
        )


def run(
    session_factory,
    candidates,
    *,
    model: str,
    concurrency: int,
    ceiling: Decimal | None = None,
) -> dict:
    """Ask in parallel, write on this thread as each article finishes.

    The same shape as `enrich run`: an article is durable the moment its
    answer is written, and the ceiling is checked between articles.
    """
    run_id = uuid.uuid4().hex[:12]
    counts: dict[str, int] = {}
    spent = Decimal("0")
    halted = False
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        submitted = {}
        for position, candidate in enumerate(candidates):
            submitted[pool.submit(ask, candidate, model)] = position
        pending = set(submitted)
        try:
            with session_factory() as session:
                while pending and not halted:
                    finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in sorted(finished, key=submitted.__getitem__):
                        answer = future.result()
                        change = apply(session, answer, run_id=run_id, model=model)
                        counts[change] = counts.get(change, 0) + 1
                        spent += answer.cost
                        if ceiling is not None and spent >= ceiling:
                            logger.error(
                                "spend ceiling reached: $%s >= $%s -- halting; "
                                "committed work is kept",
                                spent,
                                ceiling,
                            )
                            halted = True
                            break
        finally:
            for future in pending:
                future.cancel()
    return {"run_id": run_id, "counts": counts, "spent": str(spent), "halted": halted}
