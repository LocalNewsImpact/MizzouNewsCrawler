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
    lookup_keys,
    normalize_name,
)


class TestTheTrailingPossessive:
    """Asymmetric, and the asymmetry is the point.

    Stripping the possessive on BOTH sides was measured wrong on
    2026-09-16: it turned "Love's" into "love", "Casey's" into "casey"
    and "Applebee's" into "applebee" -- 335 Missouri names collapsing to
    a single common word -- after which the matcher fired on the word
    "love" in ordinary prose. On the SEMO gymnastics article it produced
    `love` -> Love's, `a lot` -> A Lot and `Show Me` -> Show Me's, none
    of them a place the story names.

    So the gazetteer keeps its possessive, because it is part of the
    business's name, and the ARTICLE's entity is looked up under both
    forms. That keeps the 640 matches a 0.85 threshold was papering over
    -- "Kansas City's" against "Kansas City" -- and loses the junk.
    """

    def test_the_gazetteer_keeps_its_possessive(self):
        assert normalize_name("Love's") == "love's"
        assert normalize_name("Casey's General Store") == "casey's general store"

    def test_a_common_word_no_longer_matches_a_business(self):
        """THE REGRESSION. Prose "love" must not reach Love's."""
        assert "love" not in lookup_keys("love") or normalize_name("Love's") != "love"
        assert lookup_keys("love") == ["love"]
        assert normalize_name("Love's") == "love's"

    def test_a_possessive_city_still_reaches_the_city(self):
        """463 matches for "Kansas City's", 177 for "Jefferson City's"."""
        assert normalize_name("Kansas City") in lookup_keys("Kansas City's")
        assert normalize_name("Jefferson City") in lookup_keys("Jefferson City's")

    def test_a_curly_apostrophe_is_the_same_possessive(self):
        """Copy is full of them and they are a different codepoint."""
        assert "jefferson city" in lookup_keys("Jefferson City\u2019s")

    def test_a_plural_possessive_too(self):
        assert "tigers" in lookup_keys("the Tigers'")

    def test_a_name_with_no_possessive_has_one_form(self):
        """No point looking a name up twice."""
        assert lookup_keys("Mizzou Arena") == ["mizzou arena"]

    def test_an_apostrophe_INSIDE_a_name_survives(self):
        """Stripping possessives anywhere rather than at the end turns
        Lee's Summit into Lee Summit, and O'Fallon into OFallon --
        towns, not possessives."""
        assert normalize_name("Lee's Summit") == "lee's summit"
        assert normalize_name("O'Fallon") == "o'fallon"

    def test_an_empty_name_has_no_keys(self):
        assert lookup_keys("") == []
        assert lookup_keys(None) == []


class TestTheLeadingArticle:
    """The same trap as the possessive, one word earlier.

    Stripping "the" from the GAZETTEER side turned "The Hill" into
    "hill" and "The Ridge" into "ridge", which then matched those words
    in prose. Measured on a boil-water story: `Hill` -> The Hill,
    `Ridge` -> The Ridge, neither a place the story names.
    """

    def test_the_gazetteer_keeps_its_article(self):
        assert normalize_name("The Hill") == "the hill"

    def test_a_bare_word_no_longer_reaches_it(self):
        """THE REGRESSION. Prose "Hill" must not match "The Hill"."""
        assert normalize_name("The Hill") not in lookup_keys("Hill")

    def test_an_article_on_the_ARTICLE_side_is_still_dropped(self):
        """ "the Kansas City Police Department" must still reach it --
        286 of the old fuzzy matches were that shape."""
        assert normalize_name("Kansas City Police Department") in lookup_keys(
            "the Kansas City Police Department"
        )

    def test_both_affixes_at_once(self):
        assert "tigers" in lookup_keys("the Tigers'")

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
