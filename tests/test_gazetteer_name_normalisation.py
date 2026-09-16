"""One normaliser, and a guard that survives a statewide pool.

THE NORMALISER. The matcher accepted `fuzz.ratio >= 0.85`, and 26.3% of
the corpus's 73,330 gazetteer matches came from that band. Two of its
largest entries were not similarity at all:

    Kansas City's    -> Kansas City      0.917    463 matches
    Jefferson City's -> Jefferson City   0.933    177 matches

640 matches where a possessive had not been stripped before scoring. The
same band also held "St. Louis City" matched to St. Louis COUNTY (206)
and "the Kansas City Police Department" matched to NORTH Kansas City's
(286) -- different jurisdictions, indistinguishable from the possessives
by score alone. Normalise properly and the first kind becomes exact; the
threshold that admitted the second kind can then go.

THE GENERIC GUARD. Length and alphabetic-character rules sufficed against
one publisher's 20-mile slice. Against a whole state they admit "City
Hall", "Church" and "Plaza", which name a kind of place rather than a
place. Measured on the corpus: 472 of 63,108 distinct names rejected
(0.7%), removing 4,205 of 73,330 matches (5.7%) -- led by Church (459),
College (338), Plaza (209), City Hall (187), Stadium (183).
"""

from __future__ import annotations

import pytest

from src.utils.gazetteer_names import (
    is_generic_name,
    is_matchable_gazetteer_name,
    normalize_name,
)


class TestTheTrailingPossessive:
    """463 + 177 matches that a scorer was papering over."""

    def test_a_possessive_city_is_the_city(self):
        assert normalize_name("Kansas City's") == normalize_name("Kansas City")
        assert normalize_name("Jefferson City's") == normalize_name("Jefferson City")

    def test_a_curly_apostrophe_is_the_same_possessive(self):
        """Copy is full of them and they are a different codepoint."""
        assert normalize_name("Jefferson City’s") == "jefferson city"

    def test_a_plural_possessive_too(self):
        assert normalize_name("the Tigers'") == "tigers"

    def test_an_apostrophe_INSIDE_a_name_survives(self):
        """THE REGRESSION TO GUARD. Stripping possessives anywhere rather
        than at the end turns Lee's Summit into Lee Summit, and O'Fallon
        into OFallon -- towns, not possessives."""
        assert normalize_name("Lee's Summit") == "lee's summit"
        assert normalize_name("O'Fallon") == "o'fallon"


class TestTheLeadingArticle:
    def test_the_article_is_dropped(self):
        assert normalize_name("the Kansas City Police Department") == (
            normalize_name("Kansas City Police Department")
        )

    def test_a_name_beginning_with_another_word_is_untouched(self):
        assert normalize_name("Theatre Guild") == "theatre guild"


class TestTheSharedForm:
    def test_punctuation_and_case_fold(self):
        assert normalize_name("St. Louis") == "st louis"
        assert normalize_name("  SAINT   LOUIS  ") == "saint louis"

    def test_a_non_string_is_empty_rather_than_an_error(self):
        assert normalize_name(None) == ""
        assert normalize_name(42) == ""


class TestAGenericNameNamesNothing:
    @pytest.mark.parametrize(
        "name",
        [
            "City Hall",
            "Post Office",
            "Public Library",
            "Fire Station",
            "Church",
            "Plaza",
            "Stadium",
            "The House",
            "North Park",
        ],
    )
    def test_a_description_is_not_an_identity(self, name):
        assert is_generic_name(name)
        assert not is_matchable_gazetteer_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "Boone County Fire Protection District",
            "Mizzou Arena",
            "Westminster College",
            "Southeast Missouri State University",
            "Lee's Summit North High School",
        ],
    )
    def test_one_distinctive_token_is_enough_to_keep_a_name(self, name):
        assert not is_generic_name(name)
        assert is_matchable_gazetteer_name(name)

    def test_the_cost_is_accepted_deliberately(self):
        """ "West Middle School" is a real school whose every token is
        generic, and it is rejected. Statewide it would be ambiguous
        anyway -- §3.1 discards a name occurring in more than one place --
        so the rule loses little that the ambiguity rule would have kept."""
        assert not is_matchable_gazetteer_name("West Middle School")


class TestTheOlderRulesStillHold:
    """48.3% of matches were once on names of two characters or fewer."""

    @pytest.mark.parametrize("name", ["A", "P", "#1", "2", "1327", "99+", ""])
    def test_noise_is_still_refused(self, name):
        assert not is_matchable_gazetteer_name(name)

    @pytest.mark.parametrize("name", ["CVS", "AMC", "DMV", "Kia"])
    def test_three_letter_names_are_still_kept(self, name):
        assert is_matchable_gazetteer_name(name)

    def test_a_non_string_is_refused(self):
        assert not is_matchable_gazetteer_name(None)
        assert not is_matchable_gazetteer_name(7)
