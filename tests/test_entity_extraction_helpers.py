from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from src.pipeline import entity_extraction as extraction


def test_normalize_text_lowers_and_strips_noise():
    value = " St. Louis—County! "
    assert extraction._normalize_text(value) == "st louis-county"


@pytest.mark.parametrize(
    "entity_text,label,expected",
    [
        ("Jane Doe", "PERSON", ("person", None)),
        ("Downtown Park", "LOC", ("place", None)),
        ("Springfield Clinic", "ORG", ("institution", "healthcare")),
        ("Local Bank", "ORG", ("business", None)),
        ("Election Day", "EVENT", ("event", None)),
        ("Unknown", "PRODUCT", (None, None)),
    ],
)
def test_map_to_category_keyword_overrides(entity_text, label, expected):
    extractor = extraction.ArticleEntityExtractor.__new__(
        extraction.ArticleEntityExtractor
    )
    assert extractor._map_to_category(entity_text, label) == expected


def test_score_match_prefers_exact_over_fuzzy():
    exact = SimpleNamespace(
        id="1",
        name="Springfield High School",
        name_norm="springfield high school",
    )
    near = SimpleNamespace(
        id="2",
        name="Springfield School",
        name_norm="springfield school",
    )
    candidates = cast(list[extraction.Gazetteer], [near, exact])
    result = extraction._score_match("springfield high school", candidates)
    assert result is not None
    assert result.gazetteer_id == "1"
    assert pytest.approx(result.score) == 1.0


def test_attach_gazetteer_matches_applies_best_candidate():
    rows = [
        SimpleNamespace(
            id="1",
            name="Springfield Clinic",
            name_norm="springfield clinic",
            category="healthcare",
        ),
        SimpleNamespace(
            id="2",
            name="Springfield High School",
            name_norm="springfield high school",
            category="schools",
        ),
    ]
    typed_rows = cast(list[extraction.Gazetteer], rows)

    entities: list[dict[str, object]] = [
        {
            "entity_text": "Springfield High School",
            "entity_label": "ORG",
        },
        {
            "entity_text": "Springfield Clinic",
            "entity_label": "ORG",
        },
    ]

    session_stub = cast(Session, None)

    updated = extraction.attach_gazetteer_matches(
        session=session_stub,
        source_id=None,
        dataset_id=None,
        entities=entities,
        gazetteer_rows=typed_rows,
    )

    schools = {entity["entity_text"]: entity for entity in updated}
    assert schools["Springfield High School"]["matched_gazetteer_id"] == "2"
    assert schools["Springfield Clinic"]["matched_gazetteer_id"] == "1"
    clinic_score = cast(float, schools["Springfield Clinic"]["match_score"])
    assert clinic_score >= 0.85
