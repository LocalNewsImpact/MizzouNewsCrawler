"""The gazetteer's schools came from OSM, and OSM did not have them.

Missouri's index held 3,759 names under `schools` and none of these:

    Battle High School          Columbia
    Smith-Cotton High School    Sedalia
    Warrior Ridge Elementary    Warrenton
    Hickman High School         Columbia
    Rock Bridge High School     Columbia

That is not cosmetic. The grounding gate admits a place the article does
not name ONLY when an institution it DOES name resolves there, so a
school the gazetteer has never heard of is a refused point. Measured over
150 stories the pipeline had itself classified as local, the model
designated a point 215 times and the gate accepted one.

NCES has every one of them -- and calls them things no newspaper prints.
"""

from io import StringIO

import pytest

from src.pipeline.school_gazetteer import (
    name_variants,
    normalize_city,
    read_places,
    read_schools,
    school_stem,
)

CENSUS = (
    "USPS\tGEOID\tANSICODE\tNAME\tLSAD\tFUNCSTAT\tALAND\tAWATER\t"
    "ALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG\n"
    "MO\t2915670\t02394786\tColumbia city\t25\tA\t1\t0\t1\t0\t38.9\t-92.3\n"
    "MO\t2965882\t02395532\tSedalia city\t25\tA\t1\t0\t1\t0\t38.7\t-93.2\n"
    "MO\t2977272\t02396404\tWarrenton city\t25\tA\t1\t0\t1\t0\t38.8\t-91.1\n"
    "MO\t2965000\t02396489\tSt. Louis city\t25\tA\t1\t0\t1\t0\t38.6\t-90.2\n"
)

SCHOOLS = (
    "source,school_id,name,city,state,county_geoid,lat,lon\n"
    "ccd,290000100048,MURIEL W. BATTLE HIGH SCHOOL,COLUMBIA,MO,29019,38.97,-92.22\n"
    "ccd,290000100049,SMITH-COTTON HIGH SCHOOL,SEDALIA,MO,29159,38.67,-93.25\n"
    "ccd,290000100050,WARRIOR RIDGE ELEM.,WARRENTON,MO,29219,38.79,-91.14\n"
    "ccd,290000100051,DAVID H. HICKMAN HIGH,COLUMBIA,MO,29019,38.96,-92.33\n"
    "pss,pss-1,ST LOUIS PRIORY SCHOOL,Saint Louis,MO,29189,38.6,-90.4\n"
    "ccd,290000100052,SOMEWHERE ELSE HIGH,NOWHEREVILLE,MO,29001,38.0,-92.0\n"
)


@pytest.fixture
def places():
    return read_places(StringIO(CENSUS))


class TestTheNameANewspaperPrints:
    """CCD carries the name on the paperwork. A story does not."""

    @pytest.mark.parametrize(
        "official,printed",
        [
            ("MURIEL W. BATTLE HIGH SCHOOL", "Battle High School"),
            ("DAVID H. HICKMAN HIGH", "Hickman High School"),
            ("ROCK BRIDGE SR. HIGH", "Rock Bridge High School"),
            ("WARRIOR RIDGE ELEM.", "Warrior Ridge Elementary"),
            ("SMITH COTTON JUNIOR HIGH SCHL", "Smith Cotton Junior High School"),
        ],
    )
    def test_the_printed_form_is_produced(self, official, printed):
        assert any(v.lower() == printed.lower() for v in name_variants(official))

    def test_the_official_form_is_kept_too(self):
        """A story CAN use the full name, and the index should hold both."""
        forms = [v.lower() for v in name_variants("MURIEL W. BATTLE HIGH SCHOOL")]
        assert "muriel w. battle high school" in forms
        assert "battle high school" in forms

    def test_a_name_needing_nothing_yields_one_form(self):
        assert name_variants("SMITH-COTTON HIGH SCHOOL") == ["Smith-Cotton High School"]

    def test_an_empty_name_yields_nothing(self):
        assert name_variants("") == []
        assert name_variants(None) == []


class TestTheShortFormAStoryWrites:
    """A story writes "Southern Boone beat Blair Oaks", not "Southern
    Boone High School beat Blair Oaks High School". The short form is 287
    articles for Southern Boone alone, and the index held none of them."""

    PLACES = {"poplar bluff", "st clair", "columbia", "ashland", "st peters"}

    @pytest.mark.parametrize(
        "official,short",
        [
            ("Southern Boone High School", "Southern Boone"),
            ("Blair Oaks High School", "Blair Oaks"),
            ("Blue Springs South High School", "Blue Springs South"),
            ("Saxony Lutheran High School", "Saxony Lutheran"),
        ],
    )
    def test_the_short_form_is_produced(self, official, short):
        assert school_stem(official, self.PLACES) == short

    @pytest.mark.parametrize(
        "official,why",
        [
            ("Poplar Bluff High School", "the stem is the town"),
            ("St Clair High School", "the stem is the town"),
            ("St Peters Elementary", "the stem is a DIFFERENT town"),
            ("Main Street Elementary", "which school in town, not a name"),
            ("North Elementary", "which school in town, not a name"),
            ("Battle High School", "one word could be a surname"),
        ],
    )
    def test_an_unsafe_stem_is_refused(self, official, why):
        assert school_stem(official, self.PLACES) is None, why

    def test_a_name_with_no_type_word_yields_no_stem(self):
        assert school_stem("Saxony Lutheran Academy", self.PLACES) is None


class TestTheShortFormOfAUniversity:
    """CCD and PSS are K-12. `Southeast Missouri State University` sits in
    the index from OSM, every story writes "Southeast Missouri State
    gymnastics", and nothing matched -- which is why stemming runs over
    the whole index rather than the federal extract alone."""

    PLACES = {"columbia", "poplar bluff", "marshall", "west plains"}

    @pytest.mark.parametrize(
        "official,short",
        [
            ("Southeast Missouri State University", "Southeast Missouri"),
            ("Missouri Western State University", "Missouri Western"),
            ("Central Methodist University", "Central Methodist"),
            ("Three Rivers College", "Three Rivers"),
            ("Mineral Area College", "Mineral Area"),
        ],
    )
    def test_the_short_form_is_produced(self, official, short):
        assert school_stem(official, self.PLACES) == short

    def test_a_generic_stem_is_matched_whole_not_as_a_prefix(self):
        """`Central Methodist` and `North Callaway` are real names. A
        prefix rule refused both."""
        assert school_stem("Central Methodist University", self.PLACES)
        assert school_stem("North Callaway High School", self.PLACES)
        assert school_stem("Main Street Elementary", self.PLACES) is None


class TestASaintIsASaint:
    """164 Missouri schools say `St Louis` and 92 say `Saint Louis`; the
    Census file says `St. Louis`. Untreated, 474 of 2,974 schools resolved
    to no place, and almost every one of them was a saint."""

    @pytest.mark.parametrize(
        "value", ["St. Louis", "St Louis", "Saint Louis", "St.Louis", "SAINT LOUIS"]
    )
    def test_every_spelling_normalises_alike(self, value):
        assert normalize_city(value) == normalize_city("St. Louis")

    def test_a_saint_school_resolves(self, places):
        rows = list(read_schools(StringIO(SCHOOLS), places))
        assert any(r["place_name"] == "St. Louis" for r in rows)


class TestThePlaceIndex:
    def test_a_place_name_in_two_places_is_dropped(self):
        """The index's own rule: a name in more than one place locates
        nothing, so it must not be used to place a school either."""
        twice = (
            CENSUS + "MO\t2999999\t0239\tColumbia town\t43\tA\t1\t0\t1\t0\t39\t-91\n"
        )
        assert "columbia" not in read_places(StringIO(twice))

    def test_the_legal_type_is_not_part_of_the_name(self, places):
        assert places[normalize_city("Columbia")] == ("2915670", "Columbia")


class TestReadingTheExtract:
    def test_the_schools_that_were_missing_are_produced(self, places):
        rows = list(read_schools(StringIO(SCHOOLS), places))
        by_name = {r["name"].lower(): r for r in rows}
        for printed, place in [
            ("battle high school", "Columbia"),
            ("smith-cotton high school", "Sedalia"),
            ("warrior ridge elementary", "Warrenton"),
            ("hickman high school", "Columbia"),
        ]:
            assert printed in by_name, f"{printed} missing"
            assert by_name[printed]["place_name"] == place

    def test_a_school_whose_city_is_not_a_place_is_skipped(self, places):
        """The index answers with a place geoid. A feature that cannot
        supply one would join the ambiguity count and never answer."""
        rows = list(read_schools(StringIO(SCHOOLS), places))
        assert not any("somewhere else" in r["name"].lower() for r in rows)

    def test_each_variant_gets_its_own_id(self, places):
        rows = list(read_schools(StringIO(SCHOOLS), places))
        ids = [(r["osm_type"], r["osm_id"]) for r in rows]
        assert len(ids) == len(set(ids)), "a duplicate id would be dropped on conflict"

    def test_every_row_is_categorised_as_a_school(self, places):
        rows = list(read_schools(StringIO(SCHOOLS), places))
        assert rows and all(r["category"] == "schools" for r in rows)

    def test_private_and_public_are_distinguishable(self, places):
        rows = list(read_schools(StringIO(SCHOOLS), places))
        assert {"ccd", "pss"} <= {r["osm_type"] for r in rows}

    def test_a_row_without_coordinates_is_skipped(self, places):
        broken = (
            "source,school_id,name,city,state,county_geoid,lat,lon\n"
            "ccd,1,BATTLE HIGH SCHOOL,COLUMBIA,MO,29019,,\n"
        )
        assert list(read_schools(StringIO(broken), places)) == []

    def test_a_generic_name_is_refused_like_any_other(self, places):
        """The same guard the OSM path applies: one corpus, one rule."""
        generic = (
            "source,school_id,name,city,state,county_geoid,lat,lon\n"
            "ccd,1,HIGH SCHOOL,COLUMBIA,MO,29019,38.9,-92.3\n"
        )
        assert list(read_schools(StringIO(generic), places)) == []
