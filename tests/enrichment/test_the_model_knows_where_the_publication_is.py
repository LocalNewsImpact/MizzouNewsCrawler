"""The model is told where the publication is, to tell namesakes apart.

March 2026, two Webster County, Missouri weeklies. The Webster County
Citizen (Seymour) had local stories filed under Seymour, Tennessee; Seymour,
Indiana; and Seymour, Wisconsin. The Marshfield Mail had one filed under
Marshfield, Wisconsin. The places and focus steps were given the headline and
body only, so a bare town name was a guess among every town of that name.
The gazetteer validates what the model identifies; it does not relocate it.
The model needs the context to identify it correctly in the first place.

And a Seymour story headlined "Gentry Cemetery meeting set April 18" was
filed under Gentry County: "Gentry" was read out of a cemetery's name.
"""

from __future__ import annotations

from src.enrichment import adapter
from src.enrichment.grounding import grounded
from src.enrichment.types import ArticleInput

STORY = "Parents are invited to Donuts With Grownups at Seymour Elementary."


def article(city="Seymour", state="MO"):
    return ArticleInput(
        "a1", "Donuts With Grownups set Friday", STORY, "ds", city, state
    )


class TestWhereThePublicationIs:
    def test_the_place_is_spelled_out(self):
        assert adapter.publication_place(article()) == "Seymour, Missouri"
        assert adapter.publication_place(article(state="Washington")) == (
            "Seymour, Washington"
        )

    def test_unknown_is_none(self):
        assert adapter.publication_place(article(city=None, state=None)) is None


class TestThePlacesStepIsGivenIt:
    def test_the_context_follows_the_article(self):
        """After the article, so the node's dateline anchor -- the first
        line -- is untouched, and in "City, State" form so the node's own
        state inference reads it."""
        text = adapter._places_text(article())
        assert text.startswith("Headline: Donuts With Grownups set Friday")
        assert text.index(STORY) < text.index("Seymour, Missouri")
        assert "not part of the article" in text

    def test_no_place_no_context(self):
        assert adapter._places_text(article(city=None, state=None)) == (
            adapter._article_text(article(city=None, state=None))
        )

    def test_grounding_never_reads_it(self):
        """A place named only in the context line is not the story's: the
        grounding gate reads the article's own text."""
        assert not grounded("Seymour", content="A fish fry is set for Friday.")


class TestTheFocusStepIsGivenIt:
    def test_the_prompt_carries_the_place_and_the_rule(self):
        text = (adapter.PROMPTS_DIR / "focus.md").read_text()
        assert "{publication}" in text
        assert "Buffalo Bills" in text and "Washington Capitals" in text
        assert adapter.FOCUS_PROMPT_VERSION == "focus-v4"


class TestANameHeadingAFeaturesNameIsNotTheTown:
    def test_the_cemetery_is_not_the_town(self):
        assert not grounded(
            "Gentry",
            content="The annual meeting of the Gentry Cemetery association is "
            "set for April 18 at the cemetery south of Seymour.",
            title="Gentry Cemetery meeting set April 18",
        )

    def test_roads_creeks_and_families_are_not_towns_either(self):
        for phrase in ("Ozark Road", "Finley Creek", "the Gentry family", "Ava Street"):
            name = phrase.split()[-2]
            assert not grounded(name, content=f"Crews worked on {phrase} on Monday.")

    def test_the_bare_name_still_grounds(self):
        assert grounded(
            "Gentry",
            content="Residents of Gentry gathered at the Gentry Cemetery on Saturday.",
        )
