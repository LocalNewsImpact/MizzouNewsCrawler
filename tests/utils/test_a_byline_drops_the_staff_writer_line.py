"""The newsroom-and-title line under a reporter's name is not part of it.

TownNews writes Wenatchee World's author field as `Reneé Dìaz<br>World staff
writer`. Its meta tag keeps the `<br>` as a double space, or as nothing, and
escapes the accents. Of 171 Wenatchee World articles, 115 were stored as
`Reneé Dìaz World`, `Reneé Dìaz Word` or `Renee DiazWorld`, and 30 with no
author at all.
"""

from __future__ import annotations

import pytest

from src.mcmetadata.structured_data import _extract_from_meta_tags
from src.utils.byline_cleaner import BylineCleaner

SOURCE = "Wenatchee World"


@pytest.fixture(scope="module")
def cleaner():
    return BylineCleaner(enable_telemetry=False)


@pytest.mark.parametrize(
    "raw",
    [
        "Reneé Dìaz<br>World staff writer",
        "Reneé Dìaz <br> World staff writer",
        "Reneé Dìaz  World staff writer",
        "Rene&eacute; D&igrave;az  World staff writer",
        "Reneé Dìaz  Word staff writer",  # the page's own typo
        "Reneé DìazWorld staff writer",
        "Rene&eacute; D&igrave;azWorld staff writer",
    ],
)
def test_the_reporter_is_left(cleaner, raw):
    assert cleaner.clean_byline(raw, source_name=SOURCE) == ["Reneé Dìaz"]


def test_an_unaccented_spelling_too(cleaner):
    assert cleaner.clean_byline("Renee DiazWorld staff writer", source_name=SOURCE) == [
        "Renee Diaz"
    ]


def test_the_masthead_word_without_a_line_break(cleaner):
    assert cleaner.clean_byline(
        "Kalie Worthen World staff writer", source_name=SOURCE
    ) == ["Kalie Worthen"]


def test_co_authors_keep_both_names(cleaner):
    assert cleaner.clean_byline(
        "Jenni Rodas and Reneé Dìaz  World staff writers", source_name=SOURCE
    ) == ["Jenni Rodas", "Reneé Dìaz"]
    assert cleaner.clean_byline(
        "Jenni Rodas, Reneé DìazWorld staff writer", source_name=SOURCE
    ) == ["Jenni Rodas", "Reneé Dìaz"]


@pytest.mark.parametrize(
    "raw, want",
    [
        # A two-word name beside a title was emptied whole.
        ("John Smith staff writer", ["John Smith"]),
        ("Jane McDonald staff writer", ["Jane McDonald"]),
        # No boundary and no masthead word: every name word stays.
        ("Mary Ann Smith staff writer", ["Mary Ann Smith"]),
        ("Jane McDonald, staff writer", ["Jane McDonald"]),
    ],
)
def test_a_title_never_costs_a_name(cleaner, raw, want):
    assert cleaner.clean_byline(raw, source_name=SOURCE) == want


def test_another_sources_word_is_not_a_masthead(cleaner):
    """`World` is only the masthead on the World's own pages."""
    assert cleaner.clean_byline(
        "Kalie Worthen World staff writer", source_name="Yakima Herald-Republic"
    ) == ["Kalie Worthen World"]


def test_a_title_alone_is_no_byline(cleaner):
    assert cleaner.clean_byline("Staff writer", source_name=SOURCE) == []


def test_the_meta_author_is_unescaped():
    html = (
        '<meta name="author" content="Rene&eacute; D&igrave;az  World staff writer" />'
    )
    assert _extract_from_meta_tags(html)["author"] == "Reneé Dìaz  World staff writer"
