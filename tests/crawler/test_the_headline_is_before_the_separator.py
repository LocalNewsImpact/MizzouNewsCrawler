"""The headline is the part before the publication, and sometimes only the h1 has it.

The Port Townsend Leader serves `<title>` as "- Port Townsend & Jefferson County
Leader" on a good article page, with the headline only in the `<h1>`. Preferring
a non-empty `<title>` there returns the masthead as the story's name and never
reaches the h1. That overwrote 26 clean headlines from the WSU tracker with 4
titles that were only the publication and 20 carrying it as a suffix.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from src.crawler import ContentExtractor
from src.crawler.headline import (
    MAX_PUBLICATION_CHARS,
    _looks_like_a_masthead,
    headline_from_title,
    split_publication,
)

#: The real title tag from ptleader.com/stories/pt-adopts-68-million-budget,189328
PTLEADER_EMPTY_TITLE = "- Port Townsend & Jefferson County Leader"
PTLEADER_H1 = "PT adopts $68 million budget"


class TestSplittingOffThePublication:
    @pytest.mark.parametrize(
        "given,headline",
        [
            (
                "City approves ARPA fund reallocation - Port Townsend & Jefferson County Leader",
                "City approves ARPA fund reallocation",
            ),
            ("Port adopts 2025 budget | The Leader", "Port adopts 2025 budget"),
            ("Orcas return to Penn Cove — The Leader", "Orcas return to Penn Cove"),
            ("Council hikes property tax :: PT Leader", "Council hikes property tax"),
        ],
    )
    def test_the_masthead_comes_off(self, given, headline):
        assert split_publication(given)[0] == headline

    def test_a_title_with_no_separator_is_left_alone(self):
        assert split_publication("Council hikes property tax by 1%") == (
            "Council hikes property tax by 1%",
            None,
        )

    def test_an_unspaced_hyphen_belongs_to_the_headline(self):
        """ "Dec-1" and "Chetzemoka-area" are not mastheads."""
        given = "County to stop taking glass recycling Dec-1"
        assert split_publication(given) == (given, None)

    def test_a_long_tail_is_a_clause_not_a_masthead(self):
        """A headline split on a spaced dash must keep its second half. Length
        is what separates a masthead from a clause."""
        given = "Glass is trash - and Jefferson County is done hauling it to the coast"
        assert split_publication(given) == (given, None)

    def test_the_rightmost_qualifying_separator_wins(self):
        """So a headline containing a dash keeps it and only the masthead goes."""
        given = "Glass is trash - the county's view - PT Leader"
        headline, pub = split_publication(given)
        assert headline == "Glass is trash - the county's view"
        assert pub == "PT Leader"

    def test_the_boundary_is_stated_not_guessed(self):
        assert MAX_PUBLICATION_CHARS >= len("Port Townsend & Jefferson County Leader")

    def test_a_masthead_reads_as_a_name_and_a_clause_does_not(self):
        """Length cannot settle it: the clause below is 52 characters and the
        masthead is 38. A masthead is a proper noun."""
        assert _looks_like_a_masthead("Port Townsend & Jefferson County Leader")
        assert not _looks_like_a_masthead(
            "and Jefferson County is done hauling it to the coast"
        )
        assert not _looks_like_a_masthead("the county's view")


class TestATitleThatCarriesNoHeadline:
    def test_the_real_ptleader_title_yields_nothing(self):
        """The whole point: this is a good article page, and its title tag says
        only who published it."""
        assert headline_from_title(PTLEADER_EMPTY_TITLE) == ""

    @pytest.mark.parametrize(
        "given", ["- The Leader", ": The Leader", " | The Leader", "", "   ", "-"]
    )
    def test_punctuation_residue_is_not_a_headline(self, given):
        assert headline_from_title(given) == ""

    def test_a_real_headline_survives(self):
        assert headline_from_title("Port adopts 2025 budget | The Leader") == (
            "Port adopts 2025 budget"
        )


class TestWhatTheExtractorReturns:
    def _title(self, html: str):
        obj = ContentExtractor.__new__(ContentExtractor)
        return obj._extract_title(BeautifulSoup(html, "html.parser"))

    def test_it_falls_through_to_the_h1_when_the_title_is_only_a_masthead(self):
        """The ptleader case, end to end."""
        html = (
            f"<html><head><title>{PTLEADER_EMPTY_TITLE}</title></head>"
            f"<body><h1>{PTLEADER_H1}</h1></body></html>"
        )
        assert self._title(html) == PTLEADER_H1

    def test_og_title_still_wins_when_it_has_a_headline(self):
        html = (
            '<html><head><meta property="og:title" content="The og headline">'
            "<title>A different headline - The Leader</title></head>"
            "<body><h1>An h1 headline</h1></body></html>"
        )
        assert self._title(html) == "The og headline"

    def test_an_og_title_that_is_only_a_masthead_is_skipped(self):
        """Publishers get this wrong in og:title too, and it is checked first."""
        html = (
            f'<html><head><meta property="og:title" content="{PTLEADER_EMPTY_TITLE}">'
            f"<title>{PTLEADER_EMPTY_TITLE}</title></head>"
            f"<body><h1>{PTLEADER_H1}</h1></body></html>"
        )
        assert self._title(html) == PTLEADER_H1

    def test_the_masthead_is_stripped_from_the_title_tag(self):
        html = (
            "<html><head><title>City moves ahead with downtown sewer fix - "
            "Port Townsend & Jefferson County Leader</title></head></html>"
        )
        assert self._title(html) == "City moves ahead with downtown sewer fix"

    def test_a_page_with_nothing_usable_returns_none(self):
        assert self._title("<html><head></head><body></body></html>") is None

    def test_an_h1_that_is_only_a_masthead_is_not_a_headline_either(self):
        html = f"<html><head></head><body><h1>{PTLEADER_EMPTY_TITLE}</h1></body></html>"
        assert self._title(html) is None
