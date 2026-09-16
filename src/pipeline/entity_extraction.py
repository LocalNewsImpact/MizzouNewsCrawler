"""Entity extraction helpers for aligning articles with the OSM gazetteer."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import spacy
from spacy import about as spacy_about
from spacy.pipeline import EntityRuler
from sqlalchemy import bindparam as bindparam_sql
from sqlalchemy import select
from sqlalchemy import text as text_sql
from sqlalchemy.orm import Session

from src.models import Gazetteer
from src.models.database import safe_session_execute
from src.pipeline.text_cleaning import decode_rot47_segments
from src.utils.gazetteer_names import (
    is_matchable_gazetteer_name,
    lookup_keys,
    normalize_name,
)

logger = logging.getLogger(__name__)


GAZETTEER_CATEGORY_MAPPINGS: dict[str, tuple[str, str | None, str]] = {
    "businesses": ("business", None, "ORG"),
    "economic": ("business", None, "ORG"),
    "entertainment": ("institution", "entertainment", "ORG"),
    "government": ("institution", "government", "ORG"),
    "healthcare": ("institution", "healthcare", "ORG"),
    "religious": ("institution", "religious", "ORG"),
    "schools": ("school", None, "ORG"),
    "sports": ("institution", "sports", "ORG"),
    "transportation": ("landmark", "transportation", "FAC"),
    "emergency": ("institution", "emergency", "ORG"),
    "landmarks": ("landmark", None, "FAC"),
}

DEFAULT_GAZETTEER_MAPPING: tuple[str, str | None, str] = (
    "institution",
    None,
    "ORG",
)


@dataclass
class GazetteerMatch:
    """Represents a best-effort gazetteer match for an entity."""

    gazetteer_id: str
    score: float
    name: str


def _normalize_text(value: str) -> str:
    value = value.lower()
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = re.sub(r"[^a-z0-9\s'-]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


@lru_cache(maxsize=1)
def _load_spacy_model(model_name: str):
    logger.info("Loading spaCy model %s", model_name)
    return spacy.load(model_name)


class ArticleEntityExtractor:
    """Extract named entities and align them with gazetteer categories."""

    SCHOOL_KEYWORDS = (
        "school",
        "university",
        "college",
        "academy",
        "elementary",
        "middle school",
        "high school",
    )
    HEALTHCARE_KEYWORDS = (
        "hospital",
        "clinic",
        "medical",
        "health",
        "dental",
        "pharmacy",
        "care center",
    )
    BUSINESS_KEYWORDS = (
        "bank",
        "grill",
        "restaurant",
        "bar",
        "hotel",
        "store",
        "market",
        "company",
        "inc",
        "llc",
    )

    #: Compiled rulers held at once. One per state in practice.
    RULER_CACHE = 4

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        self.model_name = model_name
        self.nlp = _load_spacy_model(model_name)
        self.extractor_version = f"spacy-{model_name}-{spacy_about.__version__}"
        self._rulers: dict[str, tuple[object, dict]] = {}

    def _build(self, gazetteer_rows):
        """(EntityRuler or None, category overrides) for a set of rows."""
        category_overrides: dict[str, tuple[str, str | None]] = {}
        pattern_entries: list[tuple[str, str]] = []
        seen_patterns: set[tuple[str, str]] = set()
        for row in gazetteer_rows or ():
            name = getattr(row, "name", None)
            if not name:
                continue
            category_key = (getattr(row, "category", None) or "").lower()
            mapping = GAZETTEER_CATEGORY_MAPPINGS.get(
                category_key, DEFAULT_GAZETTEER_MAPPING
            )
            osm_category, osm_subcategory, label_override = mapping
            for candidate in (name, getattr(row, "name_norm", None)):
                if not candidate or not str(candidate).strip():
                    continue
                normalised = _normalize_text(str(candidate))
                if normalised:
                    category_overrides.setdefault(
                        normalised, (osm_category, osm_subcategory)
                    )
                if not is_matchable_gazetteer_name(candidate):
                    # A POI called "A" becomes a pattern that fires on
                    # every "a" in the article. See src/utils/gazetteer_names.
                    continue
                key = (label_override, str(candidate).lower())
                if key not in seen_patterns:
                    pattern_entries.append((label_override, str(candidate)))
                    seen_patterns.add(key)

        if not pattern_entries:
            return None, category_overrides

        make_doc = self.nlp.make_doc
        payloads: list[dict[str, object]] = []
        for label, pattern_text in pattern_entries:
            pattern_doc = make_doc(pattern_text)
            tokens: list[dict[str, object]] = [
                {"LOWER": token.lower_} for token in pattern_doc if not token.is_space
            ]
            if not tokens:
                continue
            if len(tokens) == 1:
                # A ONE-WORD NAME MUST BE CAPITALISED TO COUNT.
                #
                # Matching case-insensitively, a POI called "Mobile"
                # fires on the word "mobile" in prose -- measured on a
                # Kansas City policing story. A proper noun is
                # capitalised where it names something; the common noun
                # that shares its spelling is not. Multi-word names do
                # not need this: "kansas city police department" is not
                # a phrase that occurs by accident.
                tokens[0]["IS_LOWER"] = False
            payloads.append({"label": label, "pattern": tokens})
        if not payloads:
            logger.debug(
                "EntityRuler skipped: %d entries filtered to zero-length patterns",
                len(pattern_entries),
            )
            return None, category_overrides

        # THE CURATED NAME WINS (2026-09-16).
        #
        # `overwrite_ents` defaults to False, so a span the statistical
        # model had already claimed stayed claimed and the gazetteer
        # pattern was dropped. "The team plays at Mizzou Arena" came back
        # as `Arena`/PERSON -- en_core_web_sm's guess -- while "Mizzou
        # Arena", a name we curated and geocoded to Columbia, was thrown
        # away. The same model files `Columbia` as ORG 3,047 times,
        # `story` as ORG 2,999 and `REWRITTEN` as ORG 1,726, so its
        # claims are not the ones to defer to.
        ruler = EntityRuler(
            self.nlp,
            validate=True,
            phrase_matcher_attr="LOWER",
            overwrite_ents=True,
        )
        ruler.add_patterns(payloads)  # type: ignore[arg-type]
        logger.debug("EntityRuler compiled %d patterns", len(ruler.patterns))
        return ruler, category_overrides

    def _compiled(self, gazetteer_rows, cache_key):
        """The built ruler, reused when the caller names its gazetteer.

        Keyed by the caller rather than by the rows themselves: the rows
        are ORM objects with no cheap identity, and the caller already
        knows which gazetteer it loaded.
        """
        if not gazetteer_rows:
            return None, {}
        if cache_key is None:
            return self._build(gazetteer_rows)
        if cache_key not in self._rulers:
            # Few keys -- one per state -- but a compiled ruler is large,
            # so an unbounded cache in a long-running worker is a leak.
            if len(self._rulers) >= self.RULER_CACHE:
                self._rulers.pop(next(iter(self._rulers)))
            self._rulers[cache_key] = self._build(gazetteer_rows)
        return self._rulers[cache_key]

    def extract(
        self,
        text: str | None,
        *,
        gazetteer_rows: Sequence[Gazetteer] | None = None,
        cache_key: str | None = None,
    ) -> list[dict[str, object]]:
        """Entities in one article.

        `cache_key` identifies the gazetteer the rows came from -- the
        state, now that the gazetteer is statewide. Without it the ruler
        is compiled from scratch for every article, which tokenises every
        gazetteer name and adds every pattern again: tolerable at a
        publisher's couple of thousand names, ruinous at Washington's
        49,650. With it, one compile serves every article in that state.
        """
        if not text:
            return []
        text = decode_rot47_segments(text) or text

        patterns, category_overrides = self._compiled(gazetteer_rows, cache_key)
        doc = self.nlp(text)
        if patterns is not None:
            patterns(doc)
        results: list[dict[str, object]] = []
        seen_spans: set[tuple[int, int, str]] = set()
        seen_norms: set[tuple[str, str]] = set()

        for ent in doc.ents:
            entity_text = ent.text.strip()
            if not entity_text:
                continue

            label = ent.label_
            span_key = (ent.start_char, ent.end_char, label)
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)
            norm_value = _normalize_text(entity_text)
            norm_key = (norm_value, label)
            if norm_key in seen_norms:
                continue
            override = category_overrides.get(norm_value)
            category: str | None
            subcategory: str | None
            if override:
                category, subcategory = override
            else:
                category, subcategory = self._map_to_category(
                    entity_text,
                    label,
                )
            if category is None:
                continue

            seen_norms.add(norm_key)
            results.append(
                {
                    "entity_text": entity_text,
                    "entity_norm": norm_value,
                    "entity_label": label,
                    "osm_category": category,
                    "osm_subcategory": subcategory,
                    "confidence": None,
                    "extractor_version": self.extractor_version,
                    "meta": {
                        "start_char": ent.start_char,
                        "end_char": ent.end_char,
                        "label": label,
                    },
                }
            )

        return results

    def _map_to_category(
        self, entity_text: str, entity_label: str
    ) -> tuple[str | None, str | None]:
        normalized = _normalize_text(entity_text)
        label = entity_label.upper()

        if label == "PERSON":
            return "person", None

        if label in {"GPE", "LOC"}:
            return "place", None

        if label == "FAC":
            return "landmark", None

        if label == "ORG":
            if any(keyword in normalized for keyword in self.SCHOOL_KEYWORDS):
                return "school", "education"
            if any(keyword in normalized for keyword in self.HEALTHCARE_KEYWORDS):
                return "institution", "healthcare"
            if any(keyword in normalized for keyword in self.BUSINESS_KEYWORDS):
                return "business", None
            return "institution", None

        if label == "NORP":
            return "institution", "demographic"

        if label == "EVENT":
            return "event", None

        return None, None


def _score_match(
    norm_entity: str, candidates: Sequence[Gazetteer], entity_text: str = ""
) -> GazetteerMatch | None:
    """The candidate whose name IS this entity's name, or None.

    NO SIMILARITY THRESHOLD. It accepted `fuzz.ratio >= 0.85`, which
    matched "St. Louis City" to St. Louis COUNTY 206 times, "the Kansas
    City Police Department" to NORTH Kansas City's 286 times,
    "Cardinals" to "Cardinal" 802 and "Marshall" to "Marshalls" 257 --
    different jurisdictions and unrelated places. The 640 legitimate
    matches it also made, "Kansas City's" against "Kansas City" among
    them, are possessives that `normalize_name` resolves before anything
    is compared. Nothing is left for a threshold to do that is not an
    error, and it is a hazard to leave one live on a second path.

    See docs/STATEWIDE_GAZETTEER.md §8.1.
    """
    if not candidates:
        return None
    for entry in candidates:
        if not is_matchable_gazetteer_name(getattr(entry, "name", None)):
            continue
        name_norm = getattr(entry, "name_norm", None)
        entry_norm = name_norm or normalize_name(entry.name or "")
        if entry_norm and entry_norm == norm_entity:
            return GazetteerMatch(
                str(getattr(entry, "id", "")),
                1.0,
                str(getattr(entry, "name", "")) or "",
            )
    return None


def get_gazetteer_rows(
    session: Session,
    source_id: str | None,
    dataset_id: str | None,
) -> list[Gazetteer]:
    filters = []
    if source_id:
        filters.append(Gazetteer.source_id == source_id)
    if dataset_id:
        filters.append(Gazetteer.dataset_id == dataset_id)
    if not filters:
        return []

    stmt = select(Gazetteer)
    # Use AND when multiple filters (get gazetteer entries for BOTH source AND dataset)
    if len(filters) > 1:
        stmt = stmt.where(*filters)
    else:
        stmt = stmt.where(filters[0])

    rows = list(safe_session_execute(session, stmt).scalars().all())
    # Unmatchable names are dropped here so both the EntityRuler and the
    # fuzzy scorer see the same corpus, however they were called.
    return [row for row in rows if is_matchable_gazetteer_name(row.name)]


def attach_gazetteer_matches(
    session: Session,
    source_id: str | None,
    dataset_id: str | None,
    entities: list[dict[str, object]],
    gazetteer_rows: list[Gazetteer] | None = None,
) -> list[dict[str, object]]:
    """Attach gazetteer matches to extracted entities using fuzzy matching.

    Args:
        session: Database session
        source_id: Source ID filter for gazetteer
        dataset_id: Dataset ID filter for gazetteer
        entities: List of extracted entities to match
        gazetteer_rows: Optional pre-loaded gazetteer entries

    Returns:
        Entities with matched_gazetteer_id, match_score, and match_name added
    """
    if not entities:
        return entities

    if gazetteer_rows is None:
        gazetteer_rows = get_gazetteer_rows(session, source_id, dataset_id)
    if not gazetteer_rows:
        return entities

    logger.debug(
        f"🗺️  Matching {len(entities)} entities against "
        f"{len(gazetteer_rows)} gazetteer entries"
    )

    # Build normalized name index for fast direct lookups
    index: dict[str, list[Gazetteer]] = {}
    for row in gazetteer_rows:
        name_norm = getattr(row, "name_norm", None)
        key = name_norm or _normalize_text(row.name or "")
        if not key:
            continue
        index.setdefault(key, []).append(row)

    matched_count = 0
    fallback_count = 0

    for i, entity in enumerate(entities):
        entity_text = str(entity.get("entity_text", ""))

        # Log progress for large batches
        if len(entities) > 20 and (i + 1) % 10 == 0:
            logger.debug(f"   Entity matching progress: {i + 1}/{len(entities)}")

        norm = entity.get("entity_norm")
        if not isinstance(norm, str) or not norm:
            norm = _normalize_text(entity_text)
            entity["entity_norm"] = norm

        # Try direct match first (fast O(1) lookup)
        direct_matches = index.get(norm, [])
        match = _score_match(norm, direct_matches, entity_text)

        # Fallback: fuzzy match against all candidates
        # With rapidfuzz, this is now 50-100x faster (seconds instead of hours)
        if not match and index and len(gazetteer_rows) < 50000:
            # Only do fallback for reasonable-sized gazetteers
            # This prevents extreme cases but allows normal operation
            fallback_count += 1
            all_candidates: Iterable[Gazetteer] = (
                candidate for candidates in index.values() for candidate in candidates
            )
            match = _score_match(norm, list(all_candidates), entity_text)

        if match:
            entity["matched_gazetteer_id"] = match.gazetteer_id
            entity["match_score"] = match.score
            entity["match_name"] = match.name
            matched_count += 1

    logger.debug(
        f"✅ Matched {matched_count}/{len(entities)} entities "
        f"({fallback_count} required fallback fuzzy matching)"
    )

    return entities


__all__ = [
    "ArticleEntityExtractor",
    "Feature",
    "attach_gazetteer_matches",
    "attach_state_matches",
    "get_gazetteer_rows",
    "get_state_features",
]


@dataclass(frozen=True)
class Feature:
    """One statewide gazetteer feature, as the matcher needs it."""

    id: str
    name: str
    name_norm: str
    category: str | None


_STATE_FEATURES = text_sql("""
    SELECT id, name, name_norm, category
      FROM gazetteer_features
     WHERE state IN :states
""")


def get_state_features(session: Session, states: Sequence[str]) -> list[Feature]:
    """This source's states' features, and nothing else.

    An empty `states` returns nothing rather than everything: a source
    whose state could not be resolved -- the 901 national student papers
    -- is scoped to no gazetteer at all, which is the safe reading.
    """
    if not states:
        return []
    rows = session.execute(
        _STATE_FEATURES.bindparams(bindparam_sql("states", expanding=True)),
        {"states": list(states)},
    )
    return [
        Feature(id=row[0], name=row[1], name_norm=row[2], category=row[3])
        for row in rows
        if is_matchable_gazetteer_name(row[1])
    ]


def attach_state_matches(
    entities: list[dict[str, object]], features: Sequence[Feature]
) -> list[dict[str, object]]:
    """Match entities to features by name. EXACTLY, and only by name.

    THE THRESHOLD IS GONE. `_score_match` accepted `fuzz.ratio >= 0.85`,
    which was 26.3% of the corpus's 73,330 matches and held "St. Louis
    City" matched to St. Louis COUNTY (206 times), "the Kansas City
    Police Department" matched to NORTH Kansas City's (286) and
    "Cardinals" matched to "Cardinal" (802). Those are different
    jurisdictions and unrelated places, and a similarity score cannot
    tell them from the possessives it was also papering over -- "Kansas
    City's" against "Kansas City", 463 times. `normalize_name` handles
    the possessives, so the score has nothing left to do that is not
    wrong, and the statewide pool would have made every one of those
    errors likelier.

    Ambiguity is not resolved here. A name occurring in several places
    still matches a feature; whether it can serve as EVIDENCE is
    `gazetteer_name_places`' question, and it is asked where the answer
    is used.
    """
    if not entities or not features:
        return entities
    index: dict[str, Feature] = {}
    for feature in features:
        key = feature.name_norm or normalize_name(feature.name)
        if key:
            index.setdefault(key, feature)

    for entity in entities:
        keys = lookup_keys(str(entity.get("entity_text", "")))
        if not keys:
            continue
        entity["entity_norm"] = keys[0]
        text_value = str(entity.get("entity_text", ""))
        # Same rule as the ruler's: a one-word name that appears
        # lowercase in the article is the common noun, not the place.
        if " " not in text_value.strip() and text_value.strip().islower():
            continue
        hit = None
        for key in keys:
            hit = index.get(key)
            if hit is not None:
                # Store the form that MATCHED: the gate joins the name
                # index on `entity_norm`, so "Kansas City's" has to be
                # recorded as "kansas city" once that is what it hit.
                entity["entity_norm"] = key
                break
        if hit is None:
            continue
        # The STATEWIDE feature. `matched_gazetteer_id` keeps its
        # foreign key to the per-source `gazetteer` table and is left
        # alone; this is the id that means something under §8.
        entity["matched_feature_id"] = hit.id
        entity["match_score"] = 1.0
        entity["match_name"] = hit.name
        # The gazetteer's own category, not the model's label. Across
        # 2.9M rows en_core_web_sm files `Columbia` as ORG 3,047 times,
        # `story` as ORG 2,999 and `REWRITTEN` as ORG 1,726.
        entity["osm_category"] = hit.category
    return entities


#: One source's stored entities, oldest id first, for keyset paging.
#: EXISTS rather than a join to `source_gazetteer_scope`: that table has
#: a row per state, so joining it multiplies a two-state source's
#: entities -- 3,619,730 rows against the 2,966,298 that exist.
#: The articles this source owns, paged. EXISTS rather than a join to
#: `source_gazetteer_scope`: that table has a row per state, so joining
#: it multiplies a two-state source's rows -- 3,619,730 against the
#: 2,966,298 that exist.
_SOURCE_ARTICLES = text_sql("""
    SELECT DISTINCT a.id
      FROM articles a
      JOIN candidate_links cl ON cl.id = a.candidate_link_id
     WHERE cl.source_id = :source_id
       AND a.id > :after
     ORDER BY a.id
     LIMIT :batch
""")

#: EVERY entity of those articles, together.
#:
#: The unique key is (article_id, entity_norm, entity_label,
#: extractor_version), so a collision is always WITHIN one article --
#: and can only be resolved if every row of that article is in hand.
#: Paging by entity id instead split articles across batches, and an
#: update then collided with a row in a later page that still held the
#: target norm and was never going to be rewritten because it was
#: already correct.
_ARTICLE_ENTITIES = text_sql("""
    SELECT ae.id, ae.entity_text, ae.entity_norm,
           COALESCE(ae.matched_feature_id, ae.matched_gazetteer_id),
           ae.article_id, ae.entity_label, ae.extractor_version
      FROM article_entities ae
     WHERE ae.article_id IN :ids
     ORDER BY ae.article_id, ae.id
""").bindparams(bindparam_sql("ids", expanding=True))

_REMATCH_DELETE = text_sql("DELETE FROM article_entities WHERE id IN :ids").bindparams(
    bindparam_sql("ids", expanding=True)
)

#: PHASE ONE OF THE WRITE, and it is not optional.
#:
#: The unique key is (article_id, entity_norm, entity_label,
#: extractor_version). Row A's new norm is frequently a norm row B still
#: holds -- "the Missouri Department of Transportation" and "Missouri
#: Department of Transportation" both resolve to the latter -- and if B
#: is on a later page it has not been rewritten yet, so the update
#: collides with a value that is about to disappear.
#:
#: Parking every row being changed on its own id first makes the
#: intermediate state unique by construction, so phase two can write the
#: real values in any order.
_REMATCH_PARK = text_sql(
    "UPDATE article_entities SET entity_norm = id WHERE id IN :ids"
).bindparams(bindparam_sql("ids", expanding=True))

#: `matched_gazetteer_id` is CLEARED rather than rewritten: its foreign
#: key points at the per-source table, and every value in it was made by
#: the rules this replaces -- fuzzy, at 0.85, inside one publisher's 22
#: miles. `matched_feature_id` carries the statewide answer.
_REMATCH_UPDATE = text_sql("""
    UPDATE article_entities
       SET entity_norm = :entity_norm,
           matched_gazetteer_id = NULL,
           matched_feature_id = :matched_feature_id,
           match_score = :match_score,
           match_name = :match_name,
           osm_category = :osm_category
     WHERE id = :id
""")


def rematch_source(
    session: Session,
    source_id: str,
    features: Sequence[Feature],
    *,
    batch: int = 5000,
    dry_run: bool = False,
) -> dict[str, int]:
    """Re-match one source's stored entities against its states.

    spaCy is not re-run: `entity_text` is already stored, and what
    changed is the normalisation, the scope and the threshold. So this
    re-asks the matching question over 2.97M existing rows rather than
    re-reading 20,521 articles.

    A row that no longer matches is CLEARED, not left alone. The old
    matches were made at `fuzz.ratio >= 0.85` against one publisher's
    22-mile slice; leaving them would keep exactly the errors this
    replaces -- "St. Louis City" filed under St. Louis County, 206 times.
    """
    index: dict[str, Feature] = {}
    for feature in features:
        key = feature.name_norm or normalize_name(feature.name)
        if key:
            index.setdefault(key, feature)

    counts = {"read": 0, "matched": 0, "cleared": 0, "unchanged": 0, "deduped": 0}
    # `article_entities` is unique on (article_id, entity_norm,
    # entity_label, extractor_version). Rewriting the norm COLLAPSES rows
    # that used to differ -- "Tesla" and "Tesla's" both become "tesla" --
    # so two rows land on one key and the update fails on the constraint.
    #
    # They are the same entity under the new rule, so the surplus row is
    # deleted rather than kept with a stale norm. Tracked across pages
    # because one article's entities can straddle a batch boundary.
    seen: set[tuple] = set()
    after = ""
    while True:
        articles = [
            row[0]
            for row in session.execute(
                _SOURCE_ARTICLES,
                {"source_id": source_id, "after": after, "batch": 200},
            )
        ]
        if not articles:
            break
        after = articles[-1]
        rows = session.execute(_ARTICLE_ENTITIES, {"ids": articles}).all()

        updates: list[dict] = []
        surplus: list[str] = []
        # Scoped to this batch because the unique key is scoped to the
        # article, and every row of these articles is in hand.
        seen: set[tuple] = set()
        for (
            row_id,
            entity_text,
            old_norm,
            old_match,
            article_id,
            label,
            extractor,
        ) in rows:
            counts["read"] += 1
            keys = lookup_keys(str(entity_text or ""))
            norm = keys[0] if keys else ""
            hit = None
            for key in keys:
                hit = index.get(key)
                if hit is not None:
                    norm = key
                    break
            unique_key = (article_id, norm, label, extractor)
            if unique_key in seen:
                # The same entity twice under the new normalisation.
                surplus.append(row_id)
                counts["deduped"] += 1
                continue
            seen.add(unique_key)
            if hit is None and old_match is None and norm == (old_norm or ""):
                counts["unchanged"] += 1
                continue
            if hit is not None:
                counts["matched"] += 1
            elif old_match is not None:
                counts["cleared"] += 1
            else:
                counts["unchanged"] += 1
            updates.append(
                {
                    "id": row_id,
                    "entity_norm": norm,
                    "matched_feature_id": hit.id if hit else None,
                    "match_score": 1.0 if hit else None,
                    "match_name": hit.name if hit else None,
                    "osm_category": hit.category if hit else None,
                }
            )
        if not dry_run:
            if surplus:
                session.execute(_REMATCH_DELETE, {"ids": surplus})
            if updates:
                # Park first: a row's new norm is often a norm another
                # row of the same article still holds.
                session.execute(_REMATCH_PARK, {"ids": [row["id"] for row in updates]})
                session.execute(_REMATCH_UPDATE, updates)
            if surplus or updates:
                session.commit()
    return counts
