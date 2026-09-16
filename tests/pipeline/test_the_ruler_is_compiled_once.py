"""A statewide gazetteer cannot be recompiled per article.

`extract` built its EntityRuler from scratch on every call: it tokenised
every gazetteer name into a pattern doc, constructed a ruler and added
every pattern, for each article in turn. Against one publisher's couple
of thousand names that was wasteful. Against Washington's 49,650 it is
the difference between a job that finishes and one that does not.

The caller already knows which gazetteer it loaded -- the extraction loop
groups articles so the rows are fetched once -- so it names it, and the
compiled ruler is reused for every article in that group.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.pipeline.entity_extraction import ArticleEntityExtractor


@dataclass
class _Row:
    name: str
    name_norm: str | None = None
    category: str | None = "schools"


@pytest.fixture(scope="module")
def extractor():
    return ArticleEntityExtractor()


ROWS = [_Row("Mizzou Arena"), _Row("Westminster College"), _Row("Houck Stadium")]


class TestTheCache:
    def test_a_named_gazetteer_is_compiled_once(self, extractor, monkeypatch):
        extractor._rulers.clear()
        builds = []
        original = extractor._build
        monkeypatch.setattr(
            extractor, "_build", lambda rows: (builds.append(1), original(rows))[1]
        )
        for _ in range(5):
            extractor.extract(
                "A game at Mizzou Arena.", gazetteer_rows=ROWS, cache_key="MO"
            )
        assert len(builds) == 1

    def test_an_unnamed_gazetteer_is_compiled_every_time(self, extractor, monkeypatch):
        """The old behaviour, kept for callers that have not grouped."""
        extractor._rulers.clear()
        builds = []
        original = extractor._build
        monkeypatch.setattr(
            extractor, "_build", lambda rows: (builds.append(1), original(rows))[1]
        )
        for _ in range(3):
            extractor.extract("A game at Mizzou Arena.", gazetteer_rows=ROWS)
        assert len(builds) == 3

    def test_different_states_get_different_rulers(self, extractor):
        extractor._rulers.clear()
        extractor.extract("x", gazetteer_rows=ROWS, cache_key="MO")
        extractor.extract(
            "x", gazetteer_rows=[_Row("Church Street Marketplace")], cache_key="VT"
        )
        assert set(extractor._rulers) == {"MO", "VT"}

    def test_the_cache_is_bounded(self, extractor):
        """A compiled ruler is large and a worker is long-running."""
        extractor._rulers.clear()
        for index in range(ArticleEntityExtractor.RULER_CACHE + 3):
            extractor.extract("x", gazetteer_rows=ROWS, cache_key=f"S{index}")
        assert len(extractor._rulers) <= ArticleEntityExtractor.RULER_CACHE


class TestBehaviourIsUnchanged:
    def test_a_gazetteer_name_is_still_found(self, extractor):
        found = extractor.extract(
            "The team plays at Mizzou Arena tonight.",
            gazetteer_rows=ROWS,
            cache_key="MO",
        )
        assert any("mizzou arena" in str(e.get("entity_norm", "")) for e in found)

    def test_an_unmatchable_name_still_never_becomes_a_pattern(self, extractor):
        """A POI called "A" would fire on every "a" in the article."""
        extractor._rulers.clear()
        ruler, _ = extractor._build([_Row("A"), _Row("1327")])
        assert ruler is None

    def test_no_rows_means_no_ruler(self, extractor):
        assert extractor._compiled(None, "MO") == (None, {})
        assert extractor._compiled([], "MO") == (None, {})


class TestTheCuratedNameBeatsTheGuess:
    """`EntityRuler` defaults to `overwrite_ents=False`, so a span the
    statistical model had already claimed stayed claimed and the
    gazetteer pattern was dropped on the floor.

    Measured directly: "The team plays at Mizzou Arena tonight." gives
    `Arena`/PERSON from en_core_web_sm alone, and gave exactly that with
    the ruler attached. Mizzou Arena is a name we curated, geocoded to
    Columbia, and then discarded in favour of a guess -- from a model
    that files `Columbia` as ORG 3,047 times, `story` as ORG 2,999 and
    `REWRITTEN` as ORG 1,726 across the corpus.
    """

    def test_the_gazetteer_name_replaces_the_models_guess(self, extractor):
        found = extractor.extract(
            "The team plays at Mizzou Arena tonight.",
            gazetteer_rows=ROWS,
            cache_key="MO-overwrite",
        )
        texts = {str(entity.get("entity_text")) for entity in found}
        assert "Mizzou Arena" in texts
        assert "Arena" not in texts

    def test_the_ruler_is_constructed_to_overwrite(self):
        """Asserted on the source too: the default is the defect, and a
        refactor that drops the argument restores it silently."""
        from pathlib import Path

        source = Path("src/pipeline/entity_extraction.py").read_text()
        assert "overwrite_ents=True" in source
