"""A `\\uXXXX` escape whose backslash the publisher lost is decoded, not kept.

`ptleader.com`'s JSON-LD carries `"name": "By Mallory Krumlu00a0"`. The page's
visible byline is correct -- `By Mallory Kruml&nbsp;` -- but structured data is
what the extractor prefers, so four articles stored `Mallory Krumlu00A` on
2026-09-19: the escape glued to the surname, its last digit lost to
title-casing.

Decoded rather than deleted, because `u0027` is an apostrophe: deleting it
renames An'Quan Smith to Anquan Smith.
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


class TestTheEscapeIsDecoded:
    def test_a_lost_nbsp_leaves_the_name_intact(self, cleaner):
        assert _authors(cleaner, "By Mallory Krumlu00a0") == ["Mallory Kruml"]

    def test_a_lost_apostrophe_is_restored_not_dropped(self, cleaner):
        assert _authors(cleaner, "By Anu0027Quan Smith") == ["An'Quan Smith"]

    def test_a_lost_accent_is_restored(self, cleaner):
        assert _authors(cleaner, "Renu00e9e Diaz") == ["Renée Diaz"]

    def test_the_decoder_alone_is_exact(self):
        assert BylineCleaner._decode_lost_escapes("Krumlu00a0") == "Kruml "
        assert BylineCleaner._decode_lost_escapes("Anu0027Quan") == "An'Quan"
        assert BylineCleaner._decode_lost_escapes("") == ""
        assert BylineCleaner._decode_lost_escapes(None) is None


class TestRealNamesAreNotTouched:
    @pytest.mark.parametrize(
        "raw,want",
        [
            ("By Mallory Kruml", ["Mallory Kruml"]),
            ("By Jean Bourbeau", ["Jean Bourbeau"]),
            ("By Sophia Gates", ["Sophia Gates"]),
            ("By Questen Inghram", ["Questen Inghram"]),
            (
                "By Mallory Kruml and James Robinson",
                ["Mallory Kruml", "James Robinson"],
            ),
        ],
    )
    def test_ordinary_bylines_are_unchanged(self, cleaner, raw, want):
        assert _authors(cleaner, raw) == want

    def test_four_hex_letters_without_a_digit_are_left_alone(self):
        """`u` plus four hex LETTERS can occur inside a real name; a name never
        carries a digit there, so a digit is required before decoding."""
        for text in ("Ubadec", "Laudabe", "Mcudaef"):
            assert BylineCleaner._decode_lost_escapes(text) == text

    def test_an_escape_at_the_start_of_a_token_is_left_alone(self):
        """The lookbehind requires a letter before `u`: a standalone token is
        not a lost escape glued to a name."""
        assert BylineCleaner._decode_lost_escapes("u0027Quan") == "u0027Quan"


class TestTheEmailCaseStillWorks:
    def test_an_email_after_the_name_is_removed(self, cleaner):
        """The 2026-07-25 extraction stored `Mallory Kruml, Mkrumlptleader` from
        this input; the cleaner already handles it and this pins that."""
        assert _authors(cleaner, "BY MALLORY KRUML, MKRUML@PTLEADER.COM") == [
            "Mallory Kruml"
        ]
