""" "Murrow Fellow" is a title, not a name.

The WSU Murrow College's student reporters carry it after their names. It was
not in the cleaner's title list, so it was kept as part of the name. From
production, 2026-09-21, WSU dataset:

    Kevin Teeter Local/WSU Murrow Fellow        17 articles
    Henry Brannan Murrow Fellow Sarah Wolf       1 article

With a comma in front of it the cleaner returned it as a second author.

Pinned here: the phrase is removed wherever it sits, and a byline that is only
the title yields no author at all. Two things it deliberately does NOT do, and
which stay open: a desk tag such as `Local/WSU` is still part of the name, and
two authors left adjacent by the removal are still one string.
"""

from __future__ import annotations

import pytest

from src.utils.byline_cleaner import BylineCleaner


@pytest.fixture(scope="module")
def cleaner():
    return BylineCleaner()


@pytest.mark.parametrize(
    "byline, expected",
    [
        ("Sarah Wolf Murrow Fellow", ["Sarah Wolf"]),
        ("By Kevin Teeter Murrow Fellow", ["Kevin Teeter"]),
        ("Kevin Teeter, Murrow Fellow", ["Kevin Teeter"]),
        ("Sarah Wolf, Murrow Fellow", ["Sarah Wolf"]),
        ("SARAH WOLF MURROW FELLOW", ["Sarah Wolf"]),
    ],
)
def test_the_title_is_removed_from_the_name(cleaner, byline, expected):
    assert cleaner.clean_byline(byline) == expected


def test_a_byline_that_is_only_the_title_has_no_author(cleaner):
    """Before: returned "Murrow Fellow" as if it were a person."""
    assert cleaner.clean_byline("Murrow Fellow") == []


def test_it_is_not_returned_as_a_second_author(cleaner):
    assert "Murrow Fellow" not in cleaner.clean_byline("Kevin Teeter, Murrow Fellow")


def test_the_measured_production_strings_lose_the_title(cleaner):
    for byline in (
        "Kevin Teeter Local/WSU Murrow Fellow",
        "Henry Brannan Murrow Fellow Sarah Wolf",
    ):
        cleaned = " ".join(cleaner.clean_byline(byline))
        assert "murrow" not in cleaned.lower()
        assert "fellow" not in cleaned.lower()


@pytest.mark.parametrize("byline", ["Henry Brannan", "Kevin Teeter", "Sarah Wolf"])
def test_a_plain_name_is_untouched(cleaner, byline):
    assert cleaner.clean_byline(byline) == [byline]


def test_the_word_alone_is_not_a_title(cleaner):
    """`fellow` and `murrow` are not in the list separately, only the phrase:
    a surname that happens to be either is not stripped."""
    assert cleaner.clean_byline("Anna Fellow") == ["Anna Fellow"]
    assert cleaner.clean_byline("Edward Murrow") == ["Edward Murrow"]
