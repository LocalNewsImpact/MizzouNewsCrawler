"""Entity extraction helpers for aligning articles with the OSM gazetteer."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import (
    cast,
)

import spacy
from rapidfuzz import fuzz
from spacy import about as spacy_about
from spacy.pipeline import EntityRuler
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Gazetteer
from src.pipeline.text_cleaning import decode_rot47_segments

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

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        self.model_name = model_name
        self.nlp = _load_spacy_model(model_name)
        self.extractor_version = f"spacy-{model_name}-{spacy_about.__version__}"

    def extract(
        self,
        text: str | None,
        *,
        gazetteer_rows: Sequence[Gazetteer] | None = None,
    ) -> list[dict[str, object]]:
        if not text:
            return []
        text = decode_rot47_segments(text) or text

        category_overrides: dict[str, tuple[str, str | None]] = {}
        pattern_entries: list[tuple[str, str]] = []
        if gazetteer_rows:
            seen_patterns: set[tuple[str, str]] = set()
            for row in gazetteer_rows:
                name = cast(str | None, getattr(row, "name", None))
                if not name:
                    continue
                category_key = (getattr(row, "category", None) or "").lower()
                mapping = GAZETTEER_CATEGORY_MAPPINGS.get(
                    category_key,
                    DEFAULT_GAZETTEER_MAPPING,
                )
                osm_category, osm_subcategory, label_override = mapping
                norm_name = _normalize_text(name)
                if norm_name:
                    category_overrides.setdefault(
                        norm_name,
                        (osm_category, osm_subcategory),
                    )
                key = (label_override, name.lower())
                if key not in seen_patterns:
                    pattern_entries.append((label_override, name))
                    seen_patterns.add(key)

                name_norm = cast(
                    str | None,
                    getattr(row, "name_norm", None),
                )
                if name_norm and name_norm.strip():
                    norm_norm = _normalize_text(name_norm)
                    if norm_norm:
                        category_overrides.setdefault(
                            norm_norm,
                            (osm_category, osm_subcategory),
                        )
                    key_norm = (label_override, name_norm.lower())
                    if key_norm not in seen_patterns:
                        pattern_entries.append((label_override, name_norm))
                        seen_patterns.add(key_norm)

        doc = self.nlp(text)
        if pattern_entries:
            make_doc = self.nlp.make_doc
            pattern_docs = [
                (label, make_doc(pattern_text))
                for label, pattern_text in pattern_entries
            ]
            pattern_docs = [
                (label, pattern_doc)
                for label, pattern_doc in pattern_docs
                if len(pattern_doc)
            ]
            if not pattern_docs:
                logger.debug(
                    "EntityRuler skipped: %d gazetteer entries filtered to"
                    " zero-length patterns",
                    len(pattern_entries),
                )
            else:
                pattern_payloads: Sequence[dict[str, object]] = [
                    {
                        "label": label,
                        "pattern": [
                            {"LOWER": token.lower_}
                            for token in pattern_doc
                            if not token.is_space
                        ],
                    }
                    for label, pattern_doc in pattern_docs
                ]
                pattern_payloads = [
                    payload for payload in pattern_payloads if payload["pattern"]
                ]
                sample_label, sample_doc = pattern_docs[0]
                logger.debug(
                    "EntityRuler sample payload label=%s text=%s",
                    sample_label,
                    sample_doc.text,
                )
                logger.debug(
                    "EntityRuler applying %d patterns for gazetteer rows",
                    len(pattern_payloads),
                )
                ruler = EntityRuler(
                    self.nlp,
                    validate=True,
                    phrase_matcher_attr="LOWER",
                )
                ruler.add_patterns(pattern_payloads)  # type: ignore[arg-type]
                logger.debug(
                    "EntityRuler stored %d patterns",
                    len(ruler.patterns),
                )
                ruler(doc)
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
        name_norm = cast(str | None, getattr(entry, "name_norm", None))
        entry_norm = name_norm or _normalize_text(cast(str, entry.name or ""))
        if not entry_norm:
            continue
        if entry_norm == norm_entity:
            # Exact match - return immediately
            if entity_text and len(candidates) > 100:
                logger.debug(f"✅ Exact match: '{entity_text}' → '{entry.name}'")
            return GazetteerMatch(
                cast(str, entry.id),
                1.0,
                cast(str, entry.name),
            )
        # Use rapidfuzz for fuzzy matching (10-100x faster than SequenceMatcher)
        score = fuzz.ratio(norm_entity, entry_norm) / 100.0
        if score >= 0.85 and (best_match is None or score > best_match.score):
            best_match = GazetteerMatch(
                cast(str, entry.id),
                score,
                cast(str, entry.name),
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
    # Use OR when multiple filters (get gazetteer entries for source OR dataset)
    from sqlalchemy import or_
    if len(filters) > 1:
        stmt = stmt.where(or_(*filters))
    else:
        stmt = stmt.where(filters[0])

    return list(session.execute(stmt).scalars().all())


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
        name_norm = cast(str | None, getattr(row, "name_norm", None))
        key = name_norm or _normalize_text(cast(str, row.name or ""))
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
