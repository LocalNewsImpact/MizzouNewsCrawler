"""Entity matching, exact and contained to the source's own states.

THE THRESHOLD WAS THE PROBLEM. `_score_match` accepted `fuzz.ratio >=
0.85`. Exact hits were 72.0% of the corpus's 73,330 matches; the fuzzy
band was 26.3% and held two different things at once:

    St. Louis City                    -> St. Louis COUNTY   0.857   206
    the Kansas City Police Department -> NORTH Kansas City's 0.941   286
    Cardinals                         -> Cardinal           0.941   802
    Marshall                          -> Marshalls          0.941   257
    Kansas City                       -> Q Kansas City      0.917   218
    Kansas City's                     -> Kansas City        0.917   463
    Jefferson City's                  -> Jefferson City     0.933   177

The first five are wrong -- different jurisdictions, unrelated places.
The last two are possessives that should never have reached a scorer.
`normalize_name` handles those, so nothing is left for a similarity
threshold to do that is not an error, and a statewide pool of tens of
thousands of candidates would make every one of them likelier.
"""

from __future__ import annotations

from src.pipeline.entity_extraction import Feature, attach_state_matches


def _feature(name, category="schools", fid=None):
    from src.utils.gazetteer_names import normalize_name

    return Feature(
        id=fid or name.lower().replace(" ", "-"),
        name=name,
        name_norm=normalize_name(name),
        category=category,
    )


def _entity(text):
    return {"entity_text": text, "entity_label": "ORG"}


class TestExactMatchingOnly:
    def test_a_name_matches_itself(self):
        entities = attach_state_matches(
            [_entity("Mizzou Arena")], [_feature("Mizzou Arena")]
        )
        assert entities[0]["matched_gazetteer_id"] == "mizzou-arena"
        assert entities[0]["match_score"] == 1.0

    def test_a_different_jurisdiction_no_longer_matches(self):
        """206 matches put "St. Louis City" into St. Louis COUNTY."""
        entities = attach_state_matches(
            [_entity("St. Louis City")], [_feature("St. Louis County", "government")]
        )
        assert "matched_gazetteer_id" not in entities[0]

    def test_a_different_municipality_no_longer_matches(self):
        """286 matches put the Kansas City PD into North Kansas City's."""
        entities = attach_state_matches(
            [_entity("the Kansas City Police Department")],
            [_feature("North Kansas City Police Department", "emergency")],
        )
        assert "matched_gazetteer_id" not in entities[0]

    def test_a_plural_no_longer_matches_a_singular(self):
        """Cardinals -> Cardinal, 802 times. Marshall -> Marshalls, 257."""
        assert (
            "matched_gazetteer_id"
            not in attach_state_matches([_entity("Cardinals")], [_feature("Cardinal")])[
                0
            ]
        )
        assert (
            "matched_gazetteer_id"
            not in attach_state_matches(
                [_entity("Marshall")], [_feature("Marshalls", "businesses")]
            )[0]
        )

    def test_a_city_no_longer_matches_a_business_named_after_it(self):
        """Kansas City -> Q Kansas City, 218 times."""
        entities = attach_state_matches(
            [_entity("Kansas City")], [_feature("Q Kansas City", "businesses")]
        )
        assert "matched_gazetteer_id" not in entities[0]


class TestWhatNormalisationRecovers:
    """The 640 matches the threshold was covering for. These must still
    match -- exactly, through normalisation, not by score."""

    def test_a_possessive_city_still_matches(self):
        entities = attach_state_matches(
            [_entity("Kansas City's")], [_feature("Kansas City", "government")]
        )
        assert entities[0]["match_name"] == "Kansas City"

    def test_a_leading_article_still_matches(self):
        entities = attach_state_matches(
            [_entity("the St. Louis Metropolitan Police Department")],
            [_feature("St. Louis Metropolitan Police Department", "emergency")],
        )
        assert entities[0]["match_score"] == 1.0

    def test_punctuation_still_matches(self):
        entities = attach_state_matches([_entity("St Louis")], [_feature("St. Louis")])
        assert entities[0]["match_score"] == 1.0


class TestTheCategoryComesFromTheGazetteer:
    def test_the_osm_category_is_recorded(self):
        """Not spaCy's label: it files `Columbia` as ORG 3,047 times and
        `story` as ORG 2,999."""
        entities = attach_state_matches(
            [_entity("Westminster College")],
            [_feature("Westminster College", "schools")],
        )
        assert entities[0]["osm_category"] == "schools"


class TestScoping:
    def test_no_features_means_no_matches(self):
        """A source with no resolvable state matches nothing, not
        everything -- the 901 national student papers."""
        entities = attach_state_matches([_entity("Mizzou Arena")], [])
        assert "matched_gazetteer_id" not in entities[0]

    def test_no_entities_is_not_an_error(self):
        assert attach_state_matches([], [_feature("Mizzou Arena")]) == []

    def test_an_empty_entity_is_skipped(self):
        entities = attach_state_matches([_entity("")], [_feature("Mizzou Arena")])
        assert "matched_gazetteer_id" not in entities[0]

    def test_the_query_refuses_an_empty_state_list(self):
        """It must not fall back to every state in the table."""
        from src.pipeline.entity_extraction import get_state_features

        class _S:
            def execute(self, *a, **k):
                raise AssertionError("must not query with no states")

        assert get_state_features(_S(), []) == []


class TestAOneWordNameMustBeCapitalised:
    """Three classes of junk, all found by running the matcher against
    real articles rather than by reasoning about it.

    A POI called "Mobile" fired on the word "mobile" in a Kansas City
    policing story. A proper noun is capitalised where it names
    something; the common noun sharing its spelling is not. Multi-word
    names need no such rule -- "kansas city police department" is not a
    phrase that occurs by accident.
    """

    def test_a_lowercase_common_word_does_not_match(self):
        entities = attach_state_matches(
            [_entity("mobile")], [_feature("Mobile", "businesses")]
        )
        assert "matched_gazetteer_id" not in entities[0]

    def test_the_capitalised_form_still_matches(self):
        entities = attach_state_matches(
            [_entity("Mobile")], [_feature("Mobile", "businesses")]
        )
        assert entities[0]["match_name"] == "Mobile"

    def test_an_all_caps_headline_form_matches(self):
        entities = attach_state_matches(
            [_entity("MOBILE")], [_feature("Mobile", "businesses")]
        )
        assert entities[0]["match_name"] == "Mobile"

    def test_a_multi_word_name_is_not_subject_to_the_rule(self):
        """Lowercased in a headline or a URL slug, it is still that place."""
        entities = attach_state_matches(
            [_entity("kansas city police department")],
            [_feature("Kansas City Police Department", "government")],
        )
        assert entities[0]["match_score"] == 1.0

    def test_the_ruler_carries_the_same_rule(self):
        """Asserted on the source: the pattern is where it bites first."""
        from pathlib import Path

        source = Path("src/pipeline/entity_extraction.py").read_text()
        assert '"IS_LOWER"' in source


class TestAffixesAreEntitySideOnly:
    """Two more classes of junk from the same run.

    Stripping a trailing possessive from the GAZETTEER turned "Love's"
    into "love" -- 335 Missouri names collapsing to a single common word.
    Stripping a leading article turned "The Hill" into "hill". Both then
    fired on ordinary prose.
    """

    def test_a_business_possessive_is_not_a_common_word(self):
        entities = attach_state_matches(
            [_entity("love")], [_feature("Love's", "businesses")]
        )
        assert "matched_gazetteer_id" not in entities[0]

    def test_an_articled_name_is_not_a_bare_word(self):
        entities = attach_state_matches(
            [_entity("Hill")], [_feature("The Hill", "religious")]
        )
        assert "matched_gazetteer_id" not in entities[0]

    def test_the_article_side_affixes_are_still_stripped(self):
        """The 640 matches a 0.85 threshold was papering over."""
        assert (
            attach_state_matches(
                [_entity("Kansas City's")], [_feature("Kansas City", "government")]
            )[0]["match_name"]
            == "Kansas City"
        )
