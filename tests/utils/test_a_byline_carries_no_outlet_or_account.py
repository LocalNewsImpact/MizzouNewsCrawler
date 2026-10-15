"""Outlets, fellowships, CMS accounts and credits are not reporters.

Every case below is a real raw byline from the WSU corpus (production, re-parsed
from the archived page 2026-10-15) or a control that must not change.
"""

from __future__ import annotations

import time

import pytest

from src.utils.byline_cleaner import BylineCleaner

PUBLICATIONS = {
    "washington state standard",
    "spokesman-review",
    "the spokesman-review",
    "yakima herald-republic",
    "chinook observer",
    "northwest public broadcasting",
}


@pytest.fixture(scope="module")
def cleaner():
    c = BylineCleaner(enable_telemetry=False)
    c._publication_cache = set(PUBLICATIONS)
    c._publication_cache_timestamp = time.time() + 10**9
    c._organization_cache = set()
    c._organization_cache_timestamp = time.time() + 10**9
    return c


@pytest.mark.parametrize(
    "raw, source, want",
    [
        (
            "Kevin Teeter NonStop Local/WSU Murrow News Fellow",
            "KHQ NonStop Local",
            ["Kevin Teeter"],
        ),
        ("Aspen Ford/Washington State Standard", "Chinook Observer", ["Aspen Ford"]),
        ("Riley Yuan/Chinook Observer", "Chinook Observer", ["Riley Yuan"]),
        (
            "Mitchell Roland/The Spokesman-Review, Monica Carrillo-Casas",
            "Spokane Public Radio",
            ["Mitchell Roland", "Monica Carrillo-Casas"],
        ),
        (
            "Monica Carrillo-Casas, Bonny Matejowsky/Spokesman-Review",
            "Spokane Public Radio",
            ["Monica Carrillo-Casas", "Bonny Matejowsky"],
        ),
    ],
)
def test_the_outlet_after_a_slash_is_dropped(cleaner, raw, source, want):
    assert cleaner.clean_byline(raw, source_name=source) == want


def test_two_people_either_side_of_a_slash_are_both_kept(cleaner):
    assert cleaner.clean_byline(
        "Jane Doe/John Roe", source_name="Chinook Observer"
    ) == [
        "Jane Doe",
        "John Roe",
    ]


@pytest.mark.parametrize("raw", ["Administrator", "ohtadmin", "Admin"])
def test_a_cms_account_is_no_byline(cleaner, raw):
    assert cleaner.clean_byline(raw, source_name="My Lynnwood News") == []


def test_a_courtesy_credit_is_no_byline(cleaner):
    assert (
        cleaner.clean_byline(
            "Courtesy Port of Columbia", source_name="Walla Walla Union-Bulletin"
        )
        == []
    )


@pytest.mark.parametrize(
    "raw",
    [
        "ERICK BENGEL Special to the Yakima Herald-Republic",
        "ERICK BENGEL special to the Yakima Herald-Republic",
        "ERICK BENGEL For the Yakima Herald-Republic",
    ],
)
def test_special_to_the_paper_keeps_the_name(cleaner, raw):
    assert cleaner.clean_byline(raw, source_name="Yakima Herald-Republic") == [
        "Erick Bengel"
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "Reneé Dìaz World staff writer and Johanna Bejarano Northwest Public Broadcasting",
        "Reneé Dìaz, World staff writer  Johanna Bejarano, Northwest Public Broadcasting",
    ],
)
def test_each_co_author_loses_their_own_title(cleaner, raw):
    assert cleaner.clean_byline(raw, source_name="Wenatchee World") == [
        "Reneé Dìaz",
        "Johanna Bejarano",
    ]


def test_a_bare_writer_title(cleaner):
    assert cleaner.clean_byline(
        "Reneé DìazEmpire Press writer", source_name="Wenatchee World"
    ) == ["Reneé Dìaz"]


@pytest.mark.parametrize(
    "raw, want",
    [
        # A double space inside one name is not a line break.
        ("Larissa  Babiak", ["Larissa Babiak"]),
        ("Larissa  Babiak Staff Writer", ["Larissa Babiak"]),
        # A line that continues the names keeps its person.
        (
            "Sandra Tan  and Deidre Williams News Staff Reporters",
            ["Sandra Tan", "Deidre Williams"],
        ),
    ],
)
def test_controls(cleaner, raw, want):
    assert cleaner.clean_byline(raw, source_name="Tri-City Herald") == want


@pytest.mark.parametrize("name", ["Anna Fellow"])
def test_a_title_word_as_a_surname_stays(cleaner, name):
    assert cleaner.clean_byline(name, source_name="Tri-City Herald") == [name]
