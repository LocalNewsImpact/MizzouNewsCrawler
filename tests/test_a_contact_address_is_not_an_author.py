"""A byline token that is a contact address is dropped, not turned into a name.

`ptleader.com` serves `"name": "MKRUMLPTLEADER.COM"` in its JSON-LD. That is
`mkruml@ptleader.com` with the "@" eaten by the publisher's CMS and the whole
thing upper-cased. No escape was lost, so the decoder added in #622 cannot help
— the character is simply absent.

Two things then went wrong. The email rule needs an "@" (`if "@" in part and
"." in part`), so the token was not recognised. And a later step strips the
`.COM` and leaves `MKRUMLPTLEADER`, which reads as a surname — so six articles
stored `Mallory Kruml, Mkrumlptleader` and friends as the byline.

The check therefore runs FIRST, while the TLD is still there to recognise, and
drops the whole token. Removing only the suffix is what manufactured the name.

Verified against the archived capture
`gs://.../2026/09/19/ptleader.com/23c2b140-....html.gz`, whose JSON-LD and
visible byline both read `MKRUMLPTLEADER.COM` with no "@" anywhere.
"""

from __future__ import annotations

import pytest

from src.utils.byline_cleaner import BylineCleaner


@pytest.fixture(scope="module")
def cleaner():
    return BylineCleaner()


def _authors(cleaner, raw):
    out = cleaner.clean_byline(raw)
    return getattr(out, "authors", out)


class TestTheAddressIsDropped:
    def test_the_real_ptleader_byline(self, cleaner):
        assert _authors(cleaner, "Mallory Kruml, MKRUMLPTLEADER.COM") == [
            "Mallory Kruml"
        ]

    def test_with_the_by_prefix(self, cleaner):
        assert _authors(cleaner, "By Mallory Kruml, MKRUMLPTLEADER.COM") == [
            "Mallory Kruml"
        ]

    def test_an_intact_address_still_goes(self, cleaner):
        # The pre-existing rule handles this one; it must keep working.
        assert _authors(cleaner, "Mallory Kruml, mkruml@ptleader.com") == [
            "Mallory Kruml"
        ]

    def test_a_byline_that_is_only_an_address_yields_no_author(self, cleaner):
        # Returning the original text here put the bug back: the `.COM` was
        # stripped downstream and the stem became an author.
        assert _authors(cleaner, "MKRUMLPTLEADER.COM") == []
        assert _authors(cleaner, "mkruml@ptleader.com") == []

    def test_the_token_is_dropped_whole_not_trimmed(self):
        got = BylineCleaner._drop_contact_tokens("Mallory Kruml, MKRUMLPTLEADER.COM")
        assert "MKRUML" not in got.upper()
        assert got.strip().rstrip(",") == "Mallory Kruml"


class TestRealNamesSurvive:
    @pytest.mark.parametrize(
        "raw,want",
        [
            # A name never ends in a TLD, but plenty contain dots.
            ("Martin Luther King Jr.", ["Martin Luther King Jr."]),
            ("J.R. Ewing", ["J.R. Ewing"]),
            ("Mary St. Clair", ["Mary St. Clair"]),
            ("Jane Smith", ["Jane Smith"]),
            ("Jean-Luc Picard", ["Jean-Luc Picard"]),
        ],
    )
    def test_a_dot_alone_is_not_a_domain(self, cleaner, raw, want):
        assert _authors(cleaner, raw) == want

    def test_the_lost_escape_fix_still_works(self, cleaner):
        # #622's decoder runs before this and must be unaffected.
        assert _authors(cleaner, "By Mallory Krumlu00a0") == ["Mallory Kruml"]

    def test_two_real_authors_are_both_kept(self, cleaner):
        assert _authors(cleaner, "By Mallory Kruml and James Robinson") == [
            "Mallory Kruml",
            "James Robinson",
        ]


class TestTheMatcherItself:
    @pytest.mark.parametrize(
        "token",
        ["MKRUMLPTLEADER.COM", "editor@x.org", "news.net", "a.co", "x.media"],
    )
    def test_a_domain_tail_matches(self, token):
        assert BylineCleaner._DOMAIN_TAIL.match(token)

    @pytest.mark.parametrize(
        "token", ["Jr.", "J.R.", "St.", "Kruml", "Mallory Kruml", ".com", ""]
    )
    def test_a_name_does_not_match(self, token):
        # "Mallory Kruml" has whitespace, so it can never be one token; the
        # bare ".com" has nothing before the dot.
        assert not BylineCleaner._DOMAIN_TAIL.match(token)

    def test_text_with_no_dot_is_returned_unchanged(self):
        assert BylineCleaner._drop_contact_tokens("Jane Smith") == "Jane Smith"
        assert BylineCleaner._drop_contact_tokens("") == ""
