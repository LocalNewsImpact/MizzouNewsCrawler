"""FIPS ladder unit tests. Gazetteer lookups are local; the block-level Census
call is exercised only in the live contract test."""

from unittest.mock import patch

from src.enrichment import fips
from src.enrichment.fips import (
    county_geoid,
    place_geoid,
    resolve_geoid,
    state_geoid,
)


class TestGazetteer:
    def test_place(self):
        r = place_geoid("Columbia", "MO")
        assert r.geoid == "2915670" and r.level == "place"
        assert r.lat and r.lon

    def test_place_with_lsad_suffix_input(self):
        assert place_geoid("Lee's Summit", "MO").geoid == "2941348"

    def test_place_unknown(self):
        assert place_geoid("Not A Real Town", "MO") is None

    def test_county_with_and_without_suffix(self):
        assert county_geoid("Boone County", "MO").geoid == "29019"
        assert county_geoid("Boone", "MO").geoid == "29019"

    def test_state(self):
        assert state_geoid("MO").geoid == "29"
        assert state_geoid("XX") is None


class TestLadder:
    def test_place_beats_county(self):
        r = resolve_geoid(
            point_city="Columbia",
            state="MO",
            county="Boone County",
            street_address=None,
            address_city=None,
            census_lookup=False,
        )
        assert (r.geoid, r.level) == ("2915670", "place")

    def test_falls_back_to_county_then_state(self):
        r = resolve_geoid(
            point_city="Nowhereville",
            state="MO",
            county="Boone",
            street_address=None,
            address_city=None,
            census_lookup=False,
        )
        assert (r.geoid, r.level) == ("29019", "county")
        r = resolve_geoid(
            point_city=None,
            state="MO",
            county=None,
            street_address=None,
            address_city=None,
            census_lookup=False,
        )
        assert (r.geoid, r.level) == ("29", "state")

    def test_nothing_resolves_to_none(self):
        assert (
            resolve_geoid(
                point_city=None,
                state=None,
                county=None,
                street_address=None,
                address_city=None,
            )
            is None
        )

    def test_block_upgrade_wins_when_available(self):
        fake = fips.GeoidResult("290190021003016", "block", 38.95, -92.33)
        with patch.object(fips, "block_geoid", return_value=fake):
            r = resolve_geoid(
                point_city="Columbia",
                state="MO",
                county="Boone",
                street_address="221 N 8th St",
                address_city="Columbia",
            )
        assert r.level == "block" and len(r.geoid) == 15
        assert r.geoid[:5] == "29019"  # nests to the county

    def test_no_house_number_never_calls_census(self):
        called = []
        with patch.object(
            fips, "block_geoid", side_effect=lambda *a, **k: called.append(1)
        ):
            fips._HOUSE_NUMBER.match("Haile Street") or None
        assert fips._HOUSE_NUMBER.match("Haile Street") is None
        assert fips._HOUSE_NUMBER.match("221 N 8th St") is not None
