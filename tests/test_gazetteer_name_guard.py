"""Names that are not names must not become text patterns.

48.3% of gazetteer entity matches in the corpus -- 68,676 of 142,282,
across 27,360 articles and 60 publishers -- were on OSM names of two
characters or fewer: lettered bus stops, numbered ball fields, building
numbers. The matcher compiles every gazetteer name into an EntityRuler
pattern, so a POI called "A" fired on every "a" in every article.
"""

import pytest

from src.utils.gazetteer_names import is_matchable_gazetteer_name


def _spacy_model_available() -> bool:
    try:
        import spacy

        spacy.load("en_core_web_sm")
    except Exception:
        return False
    return True


HAS_SPACY_MODEL = _spacy_model_available()


@pytest.mark.parametrize("name", ["A", "I", "O", "#4", "10", "BP", "QT", "S2"])
def test_two_characters_or_fewer_is_not_matchable(name):
    assert is_matchable_gazetteer_name(name) is False


@pytest.mark.parametrize("name", ["1327", "1501", "1984", "99+", "2"])
def test_a_name_with_no_letter_is_not_matchable(name):
    """These survive the length rule and are still not names."""
    assert is_matchable_gazetteer_name(name) is False


@pytest.mark.parametrize("name", ["CVS", "AMC", "IRS", "Kia", "Cox", "C-3"])
def test_three_characters_with_a_letter_is_kept(name):
    """265 matches over 26 names, nearly all real businesses."""
    assert is_matchable_gazetteer_name(name) is True


def test_real_names_are_untouched():
    assert is_matchable_gazetteer_name("First Baptist Church of Mission")
    assert is_matchable_gazetteer_name("RJ's Bob-be-que Shack")


@pytest.mark.parametrize("name", ["", "   ", None, 4, b"AAA"])
def test_absent_or_non_string_names_are_not_matchable(name):
    assert is_matchable_gazetteer_name(name) is False


def test_whitespace_does_not_buy_length():
    assert is_matchable_gazetteer_name("  A  ") is False


class _Row:
    def __init__(self, name, category="businesses"):
        self.name = name
        self.name_norm = name.lower() if isinstance(name, str) else None
        self.category = category


@pytest.mark.skipif(not HAS_SPACY_MODEL, reason="en_core_web_sm not installed")
def test_the_matcher_builds_no_pattern_for_a_single_letter():
    """The end of the bug: "A" reaching the EntityRuler as a pattern.

    Without the guard the gazetteer row named "A" compiles into a
    pattern that promotes the article's opening "A" into an ORG entity.
    Confirmed by bypassing the guard: the entity appears, labelled ORG,
    at start_char 0.

    "1327" is deliberately not asserted on. It is extracted either way,
    by spaCy's own DATE recogniser rather than from the gazetteer, so it
    would pass with or without the fix and prove nothing.
    """
    from src.pipeline.entity_extraction import ArticleEntityExtractor

    rows = [_Row("A"), _Row("#4"), _Row("1327"), _Row("Sushi Karma Asian Bistro")]
    text = "A car drove past Sushi Karma Asian Bistro at 1327 on a warm day."

    found = {
        entity["entity_text"]
        for entity in ArticleEntityExtractor().extract(text, gazetteer_rows=rows)
    }

    assert "A" not in found
    assert "#4" not in found
    assert "Sushi Karma Asian Bistro" in found


@pytest.mark.skipif(not HAS_SPACY_MODEL, reason="en_core_web_sm not installed")
def test_without_the_guard_a_single_letter_becomes_an_entity(monkeypatch):
    """A test that cannot fail is not a test.

    This pins the defect itself, so the guard above is known to be what
    removes it rather than something incidental about the fixture.
    """
    import src.pipeline.entity_extraction as entity_extraction

    monkeypatch.setattr(
        entity_extraction, "is_matchable_gazetteer_name", lambda name: True
    )

    rows = [_Row("A"), _Row("Sushi Karma Asian Bistro")]
    text = "A car drove past Sushi Karma Asian Bistro at 1327 on a warm day."

    found = {
        entity["entity_text"]
        for entity in entity_extraction.ArticleEntityExtractor().extract(
            text, gazetteer_rows=rows
        )
    }

    assert "A" in found


def test_the_fuzzy_scorer_rejects_an_unmatchable_candidate():
    from src.pipeline.entity_extraction import _score_match

    assert _score_match("a", [_Row("A")]) is None
