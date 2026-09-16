"""Entity extraction helpers for aligning articles with the OSM gazetteer."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import spacy
from rapidfuzz import fuzz
from spacy import about as spacy_about
from spacy.pipeline import EntityRuler
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Gazetteer
from src.models.database import safe_session_execute
from src.pipeline.text_cleaning import decode_rot47_segments
from src.utils.gazetteer_names import is_matchable_gazetteer_name

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
            tokens = [
                {"LOWER": token.lower_} for token in pattern_doc if not token.is_space
            ]
            if tokens:
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
    """Score fuzzy matches between entity and gazetteer candidates.

    Args:
        norm_entity: Normalized entity text
        candidates: List of gazetteer entries to compare against
        entity_text: Original entity text (for logging)

    Returns:
        Best matching gazetteer entry with score >= 0.85, or None
    """
    if not candidates:
        return None

    # Log when doing expensive fuzzy matching on many candidates
    if len(candidates) > 100 and entity_text:
        logger.debug(
            f"🔍 Fuzzy matching '{entity_text}' against {len(candidates)} candidates"
        )

    best_match: GazetteerMatch | None = None
    for entry in candidates:
        if not is_matchable_gazetteer_name(getattr(entry, "name", None)):
            continue
        name_norm = getattr(entry, "name_norm", None)
        entry_norm = name_norm or _normalize_text(entry.name or "")
        if not entry_norm:
            continue

        # Exact match - return immediately
        if entry_norm == norm_entity:
            if entity_text and len(candidates) > 100:
                logger.debug(
                    "✅ Exact match: '%s' → '%s'",
                    entity_text,
                    str(getattr(entry, "name", "")),
                )
            return GazetteerMatch(
                str(getattr(entry, "id", "")),
                1.0,
                str(getattr(entry, "name", "")) or "",
            )

        # Use rapidfuzz for fuzzy matching (10-100x faster than SequenceMatcher)
        score = fuzz.ratio(norm_entity, entry_norm) / 100.0
        if score >= 0.85 and (best_match is None or score > best_match.score):
            best_match = GazetteerMatch(
                str(getattr(entry, "id", "")),
                score,
                str(getattr(entry, "name", "")) or "",
            )

    if best_match and entity_text and len(candidates) > 100:
        logger.debug(
            f"✅ Fuzzy match: '{entity_text}' → '{best_match.name}' "
            f"(score: {best_match.score:.2f})"
        )

    return best_match


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
    "get_gazetteer_rows",
    "attach_gazetteer_matches",
]
