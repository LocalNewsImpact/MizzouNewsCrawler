from __future__ import annotations

from dataclasses import dataclass
from typing import Generator, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models import Base, Gazetteer
from src.pipeline import entity_extraction as extraction


@pytest.fixture()
def in_memory_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    try:
        with SessionLocal() as session:
            yield session
            session.rollback()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


class FakeToken:
    def __init__(self, text: str):
        self.text = text
        self.lower_ = text.lower()
        self.is_space = not text.strip()


class FakePatternDoc:
    def __init__(self, text: str):
        tokens = [FakeToken(part) for part in text.split() if part]
        self._tokens = tokens
        self.text = text

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._tokens)

    def __iter__(self):
        return iter(self._tokens)


@dataclass
class FakeSpan:
    text: str
    label_: str
    start_char: int
    end_char: int


class FakeDoc:
    def __init__(self, text: str, spans: list[FakeSpan]):
        self.text = text
        self.ents = spans


class FakeNLP:
    def __init__(self):
        self.calls: list[str] = []
        self.ents_by_text: dict[str, list[FakeSpan]] = {}

    def __call__(self, text: str) -> FakeDoc:
        self.calls.append(text)
        spans = self.ents_by_text.get(text, [])
        return FakeDoc(
            text,
            [
                FakeSpan(
                    span.text,
                    span.label_,
                    span.start_char,
                    span.end_char,
                )
                for span in spans
            ],
        )

    def make_doc(self, text: str) -> FakePatternDoc:
        return FakePatternDoc(text)


@pytest.fixture()
def fake_entity_ruler(monkeypatch):
    class _FakeEntityRuler:
        instances: list[_FakeEntityRuler] = []

        def __init__(self, *args, **kwargs):
            self.patterns: list[dict[str, object]] = []
            self.called_with: Optional[FakeDoc] = None
            _FakeEntityRuler.instances.append(self)

        def add_patterns(self, patterns):
            self.patterns.extend(patterns)

        def __call__(self, doc: FakeDoc) -> None:
            self.called_with = doc

    monkeypatch.setattr(extraction, "EntityRuler", _FakeEntityRuler)
    yield _FakeEntityRuler
    _FakeEntityRuler.instances.clear()


@pytest.fixture()
def fake_nlp(monkeypatch):
    nlp = FakeNLP()
    monkeypatch.setattr(extraction, "_load_spacy_model", lambda model: nlp)
    return nlp


def test_normalize_text_removes_punctuation():
    raw = "New—York’s Finest!!"
    assert extraction._normalize_text(raw) == "new-york's finest"


@pytest.mark.parametrize(
    "label,text,expected",
    [
        ("PERSON", "Jane Doe", ("person", None)),
        ("GPE", "Columbia", ("place", None)),
        ("FAC", "Faurot Field", ("landmark", None)),
        ("ORG", "Boone County High School", ("school", "education")),
        ("ORG", "Boone County Hospital", ("institution", "healthcare")),
        ("ORG", "Downtown Grill", ("business", None)),
        ("NORP", "Missourians", ("institution", "demographic")),
        ("EVENT", "Homecoming", ("event", None)),
        ("LANGUAGE", "Latin", (None, None)),
    ],
)
def test_map_to_category_branches(label, text, expected, fake_nlp: FakeNLP):
    del fake_nlp  # ensure patched loader is used without configuring ents
    extractor = extraction.ArticleEntityExtractor(model_name="fake-model")
    result = extractor._map_to_category(text, label)
    assert result == expected


def test_score_match_prefers_exact_match():
    rows = [
        Gazetteer(
            id="1",
            name="Boone Library",
            name_norm="boone library",
        )
    ]
    match = extraction._score_match("boone library", rows)
    assert match and match.score == pytest.approx(1.0)
    assert match.gazetteer_id == "1"


def test_score_match_returns_best_fuzzy_match():
    rows = [
        Gazetteer(
            id="2",
            name="Boone County Library",
            name_norm="boone county library",
        )
    ]
    match = extraction._score_match("boone cnty library", rows)
    assert match and match.gazetteer_id == "2"
    assert match.score >= 0.85


def test_score_match_returns_none_when_no_candidates():
    rows = [Gazetteer(id="3", name=None, name_norm=None)]
    assert extraction._score_match("unknown", rows) is None


def test_get_gazetteer_rows_filters_by_source_or_dataset(
    in_memory_session: Session,
) -> None:
    """Test that get_gazetteer_rows uses AND logic for filters.

    When both source_id and dataset_id are provided, only entries matching
    BOTH should be returned (not OR). This was fixed in commit ba814da to
    prevent loading 326K entries instead of ~8.5K.
    """
    rows = [
        Gazetteer(
            id="1",
            source_id="source-1",
            dataset_id=None,
            name="A",
        ),
        Gazetteer(
            id="2",
            source_id=None,
            dataset_id="dataset-1",
            name="B",
        ),
        Gazetteer(
            id="3",
            source_id="source-1",
            dataset_id="dataset-1",
            name="C",  # Matches BOTH source AND dataset
        ),
        Gazetteer(
            id="4",
            source_id="source-other",
            dataset_id="dataset-other",
            name="D",
        ),
    ]
    in_memory_session.add_all(rows)
    in_memory_session.commit()

    # When both filters provided, should use AND logic (not OR)
    fetched = extraction.get_gazetteer_rows(
        in_memory_session,
        "source-1",
        "dataset-1",
    )
    fetched_ids = {row.id for row in fetched}
    # Should only return entry 3 which matches BOTH filters
    assert fetched_ids == {"3"}


def test_get_gazetteer_rows_returns_empty_when_no_filters(
    in_memory_session: Session,
) -> None:
    assert extraction.get_gazetteer_rows(in_memory_session, None, None) == []


def test_attach_gazetteer_matches_handles_direct_and_fuzzy(
    in_memory_session: Session,
) -> None:
    direct = Gazetteer(
        id="direct",
        source_id="source-1",
        dataset_id="dataset-1",
        name="Boone County Library",
        name_norm="boone county library",
    )
    fuzzy = Gazetteer(
        id="fuzzy",
        source_id="source-1",
        dataset_id="dataset-1",
        name="Boone General Hospital",
        name_norm="boone general hospital",
    )
    in_memory_session.add_all([direct, fuzzy])
    in_memory_session.commit()

    entities: list[dict[str, object]] = [
        {
            "entity_text": "Boone County Library",
            "entity_norm": "boone county library",
        },
        {"entity_text": "Boone Gen Hospital"},
    ]

    result = extraction.attach_gazetteer_matches(
        in_memory_session,
        "source-1",
        "dataset-1",
        entities,
    )
    by_id = {entity.get("matched_gazetteer_id") for entity in result}
    assert by_id == {"direct", "fuzzy"}
    fuzzy_entity = next(
        entity for entity in result if entity["matched_gazetteer_id"] == "fuzzy"
    )
    assert fuzzy_entity["entity_norm"] == "boone gen hospital"
    match_score = float(fuzzy_entity["match_score"])  # type: ignore[arg-type]
    assert match_score >= 0.85


def test_attach_gazetteer_matches_no_entities_returns_input(
    in_memory_session: Session,
) -> None:
    assert (
        extraction.attach_gazetteer_matches(
            in_memory_session,
            "src",
            "ds",
            [],
        )
        == []
    )


def test_article_entity_extractor_applies_overrides_and_deduplicates(
    fake_nlp: FakeNLP,
    fake_entity_ruler,
    monkeypatch,
) -> None:
    decoded_text = "Boone County Hospital welcomed alumni"
    spans = [
        FakeSpan("Boone County Hospital", "ORG", 0, 21),
        FakeSpan("Boone County Hospital", "ORG", 0, 21),
        FakeSpan("Jane Doe", "PERSON", 30, 38),
    ]
    fake_nlp.ents_by_text[decoded_text] = spans
    fake_nlp.ents_by_text.setdefault("encoded", [])

    monkeypatch.setattr(
        extraction,
        "decode_rot47_segments",
        lambda value: decoded_text,
    )

    extractor = extraction.ArticleEntityExtractor(model_name="fake-model")
    gazetteer_rows = [
        Gazetteer(
            id="g-hospital",
            name="Boone County Hospital",
            category="healthcare",
            source_id="src",
            dataset_id="ds",
            name_norm="boone county hospital",
        )
    ]

    results = extractor.extract("encoded", gazetteer_rows=gazetteer_rows)
    assert fake_nlp.calls == [decoded_text]
    assert len(results) == 2
    hospital = next(
        item for item in results if item["entity_text"] == "Boone County Hospital"
    )
    assert hospital["osm_category"] == "institution"
    assert hospital["osm_subcategory"] == "healthcare"
    assert hospital["entity_label"] == "ORG"
    person = next(item for item in results if item["entity_text"] == "Jane Doe")
    assert person["osm_category"] == "person"
    assert len(fake_entity_ruler.instances) == 1
    assert fake_entity_ruler.instances[0].patterns


def test_article_entity_extractor_skips_empty_pattern_payload(
    fake_nlp: FakeNLP,
    fake_entity_ruler,
    monkeypatch,
) -> None:
    decoded_text = "Plain sentence"
    fake_nlp.ents_by_text[decoded_text] = []
    monkeypatch.setattr(
        extraction,
        "decode_rot47_segments",
        lambda value: decoded_text,
    )

    extractor = extraction.ArticleEntityExtractor(model_name="fake-model")
    gazetteer_rows = [
        Gazetteer(
            id="g-empty",
            name="   ",
            category="businesses",
            source_id="src",
            dataset_id="ds",
        )
    ]

    extractor.extract("encoded", gazetteer_rows=gazetteer_rows)
    assert not fake_entity_ruler.instances  # EntityRuler never instantiated
