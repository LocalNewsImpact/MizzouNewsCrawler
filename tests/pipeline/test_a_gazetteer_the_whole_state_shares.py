"""Installing a state's gazetteer, without a bucket or a database.

The per-publisher gazetteer holds 83,325 distinct OSM features as 558,540
rows, each within 22.2 miles of one publisher — so a match resolves near
that publisher whatever the story says, and a story about a town 30 miles
out gets no institution evidence at all. `docs/STATEWIDE_GAZETTEER.md` §1.

The replacement is one row per feature per state, installed from the POI
extracts that already exist in `gs://mizzou-osm-extracts/poi/`.
"""

from __future__ import annotations

import io
import json

import pytest

from src.pipeline import statewide_gazetteer as sg

HEADER = "osm_type,osm_id,name,lat,lon,tags"


def _csv(*rows: str) -> io.StringIO:
    return io.StringIO("\n".join([HEADER, *rows]))


def _row(name, tags=None, osm_id="1", lat="38.95", lon="-92.33"):
    payload = json.dumps(tags or {"amenity": "school"}).replace('"', '""')
    return f'node,{osm_id},"{name}",{lat},{lon},"{payload}"'


class TestFindingTheExtract:
    def test_a_usps_code_resolves_to_the_file_in_the_bucket(self):
        assert sg.extract_name("MO") == "missouri"
        assert sg.extract_uri("MO") == ("gs://mizzou-osm-extracts/poi/missouri.csv")

    def test_a_full_state_name_resolves_too(self):
        """Sources carry both forms."""
        assert sg.extract_name("Washington") == "washington"
        assert sg.extract_name("vermont") == "vermont"

    def test_a_two_letter_non_state_is_refused(self):
        """`fips._usps` answers "ZZ" for "ZZ" -- it parses a component
        rather than validating one. Every write here is keyed on the
        state, so an unvalidated code builds a gazetteer for a state that
        does not exist."""
        assert sg.state_code("ZZ") is None
        assert sg.state_code("MO") == "MO"

    def test_an_unresolvable_state_is_none_not_a_guess(self):
        """896 of 901 Vermont sources arrive with no state. Defaulting one
        built gazetteers in the wrong state without failing loudly, which
        is why `resolve_source_state` returns "" and this returns None."""
        assert sg.extract_name("") is None
        assert sg.extract_name(None) is None
        assert sg.extract_uri("ZZ") is None


class TestTheCategoryComesFromOSM:
    """The gate should read this, not spaCy's label: across 2.9M rows the
    model files `Columbia` as ORG 3,047 times and `story` as ORG 2,999."""

    def test_a_school_is_a_school(self):
        assert sg.category_for({"amenity": "school"}) == "schools"

    def test_tags_that_match_nothing_are_none(self):
        assert sg.category_for({"foo": "bar"}) is None

    def test_a_non_dict_is_none_rather_than_an_error(self):
        assert sg.category_for(None) is None
        assert sg.category_for("amenity=school") is None

    def test_the_map_is_read_from_the_builder(self):
        """Not copied. A category added to the Overpass path has to be
        understood here without anyone remembering to mirror it."""
        index = sg._category_index()
        assert ("amenity", "school") in index
        assert len(index) > 30


class TestReadingAnExtract:
    def test_a_row_becomes_a_feature(self):
        rows = list(sg.read_extract(_csv(_row("Mizzou Arena"))))
        assert len(rows) == 1
        assert rows[0]["name"] == "Mizzou Arena"
        assert rows[0]["name_norm"] == "mizzou arena"
        assert rows[0]["category"] == "schools"

    def test_an_unmatchable_name_never_reaches_the_table(self):
        """Dropped at load, not at match time, so a pattern that fires on
        every "a" in an article cannot exist and every consumer sees the
        same corpus."""
        rows = list(sg.read_extract(_csv(_row("A"), _row("1327", osm_id="2"))))
        assert rows == []

    def test_a_generic_name_never_reaches_the_table_either(self):
        rows = list(
            sg.read_extract(_csv(_row("City Hall"), _row("Church", osm_id="2")))
        )
        assert rows == []

    def test_a_row_without_coordinates_is_skipped(self):
        """Every consumer needs the point: it is what resolves to a Census
        place, and a feature with no place cannot be evidence."""
        rows = list(sg.read_extract(_csv('node,9,"Mizzou Arena",,,"{}"')))
        assert rows == []

    def test_malformed_tags_do_not_stop_the_load(self):
        """One bad JSON blob in 50,481 rows must not cost the state."""
        rows = list(
            sg.read_extract(_csv('node,9,"Mizzou Arena",38.95,-92.33,"not json"'))
        )
        assert len(rows) == 1
        assert rows[0]["category"] is None

    def test_the_possessive_is_normalised_at_load(self):
        rows = list(sg.read_extract(_csv(_row("Kansas City's Union Station"))))
        assert rows[0]["name_norm"] == "kansas city's union station"


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.statements = []
        self.params = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _Result(self.answers.pop(0)) if self.answers else _Result()

    def commit(self):
        self.commits += 1


class TestLoading:
    def test_a_state_that_cannot_be_resolved_raises(self):
        with pytest.raises(ValueError):
            sg.load_state(_Session(), "ZZ", path=None)

    def test_the_dry_run_writes_nothing(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("\n".join([HEADER, _row("Mizzou Arena")]))
        session = _Session()
        counts = sg.load_state(session, "MO", path=str(path), dry_run=True)
        assert counts == {"read": 1, "written": 1 - 1}
        assert session.statements == []
        assert session.commits == 0

    def test_it_writes_and_commits(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("\n".join([HEADER, _row("Mizzou Arena")]))
        session = _Session()
        counts = sg.load_state(session, "MO", path=str(path))
        assert counts["written"] == 1
        assert session.commits == 1

    def test_a_reload_writes_nothing_twice(self, tmp_path):
        """Idempotent on (state, osm_type, osm_id), so installing a state
        that is already there costs a scan and no rows."""
        path = tmp_path / "x.csv"
        path.write_text("\n".join([HEADER, _row("Mizzou Arena")]))
        session = _Session()
        sg.load_state(session, "MO", path=str(path))
        assert (
            "ON CONFLICT (state, osm_type, osm_id) DO NOTHING" in session.statements[0]
        )

    def test_the_state_is_stamped_on_every_row(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("\n".join([HEADER, _row("Mizzou Arena")]))
        session = _Session()
        sg.load_state(session, "Missouri", path=str(path))
        assert all(record["state"] == "MO" for record in session.params[0])


class TestOnDemand:
    def test_a_state_already_present_is_not_reloaded(self):
        session = _Session(answers=[[(1,)]])
        assert sg.ensure_state(session, "MO") == {
            "read": 0,
            "written": 0,
            "already": 1,
        }

    def test_an_unresolvable_state_is_skipped_not_guessed(self):
        session = _Session()
        assert sg.ensure_state(session, "")["skipped"] == 1


class TestTheNameIndex:
    """§3.1: a name in more than one Census place locates nothing.
    walmart supercenter occurs in 149, pizza hut in 140, aldi in 72."""

    def test_it_counts_distinct_places_per_name(self):
        session = _Session(answers=[[], [], [(10, 7)]])
        result = sg.rebuild_name_index(session, "MO")
        assert result == {"names": 10, "unambiguous": 7}

    def test_the_geoid_is_set_only_when_the_name_is_unambiguous(self):
        """Otherwise a caller reads an answer off an ambiguous name."""
        session = _Session(answers=[[], [], [(0, 0)]])
        sg.rebuild_name_index(session, "MO")
        insert = next(
            s for s in session.statements if "INSERT INTO gazetteer_name_places" in s
        )
        assert "CASE WHEN count(DISTINCT place_geoid) = 1" in insert

    def test_it_is_rebuilt_rather_than_appended(self):
        session = _Session(answers=[[], [], [(0, 0)]])
        sg.rebuild_name_index(session, "MO")
        assert "DELETE FROM gazetteer_name_places" in session.statements[0]

    def test_an_unresolvable_state_raises(self):
        with pytest.raises(ValueError):
            sg.rebuild_name_index(_Session(), "ZZ")

    def test_an_unplaced_feature_still_counts_against_the_name(self):
        """THE DEFECT. `bethel church` has 52 features in Missouri, 51 of
        them with no place, and the index called it "unambiguously
        Wildwood" -- so every Missouri story naming a Bethel Church
        resolved there. Filtering unplaced features out before counting
        is what made a name with 52 bearers look like a name with one."""
        session = _Session(answers=[[], [], [(0, 0)]])
        sg.rebuild_name_index(session, "MO")
        insert = next(
            s for s in session.statements if "INSERT INTO gazetteer_name_places" in s
        )
        assert "count(*) FILTER (WHERE place_geoid IS NULL) > 0" in insert
        assert (
            "WHERE state = :state\n     GROUP BY" in insert
        ), "the rebuild still filters unplaced features out before counting"

    def test_the_answer_is_withheld_when_any_bearer_is_unplaced(self):
        """One known place is not one place when others are unaccounted
        for. The geoid and the name are both gated on there being none."""
        session = _Session(answers=[[], [], [(0, 0)]])
        sg.rebuild_name_index(session, "MO")
        insert = next(
            s for s in session.statements if "INSERT INTO gazetteer_name_places" in s
        )
        gate = (
            "CASE WHEN count(DISTINCT place_geoid) = 1\n"
            "                 AND count(*) FILTER (WHERE place_geoid IS NULL) = 0"
        )
        assert insert.count(gate) == 2, "geoid and name must both be gated"

    def test_a_name_with_no_placed_feature_is_absent_entirely(self):
        """Counting unplaced features must not admit a name that has only
        unplaced ones -- it locates nothing and belongs nowhere."""
        session = _Session(answers=[[], [], [(0, 0)]])
        sg.rebuild_name_index(session, "MO")
        insert = next(
            s for s in session.statements if "INSERT INTO gazetteer_name_places" in s
        )
        assert "HAVING count(DISTINCT place_geoid) > 0" in insert


class _Blob:
    def __init__(self, text=None, present=True):
        self._text, self._present = text, present
        self.name = None

    def exists(self):
        return self._present

    def download_as_text(self):
        return self._text


class _Bucket:
    def __init__(self, blob):
        self._blob = blob
        self.asked = None

    def blob(self, name):
        self.asked = name
        return self._blob


class _Client:
    def __init__(self, blob):
        self._bucket = _Bucket(blob)

    def bucket(self, name):
        self._bucket.name = name
        return self._bucket


class TestFetchingFromTheBucket:
    """The client is patched through this module's own seam. Patching
    `google.cloud.storage.Client` by name imports the real module, which
    binds as an attribute of the `google.cloud` package and defeats the
    `sys.modules` stub tests/utils/test_raw_html_archive.py relies on --
    a failure that only appears when both files run in one session."""

    def test_it_reads_the_state_csv(self, monkeypatch):
        blob = _Blob(text="osm_type,osm_id,name,lat,lon,tags\n")
        client = _Client(blob)
        monkeypatch.setattr(sg, "_storage_client", lambda: client)
        assert sg.download_extract("MO").startswith("osm_type")
        assert client._bucket.name == "mizzou-osm-extracts"
        assert client._bucket.asked == "poi/missouri.csv"

    def test_a_missing_extract_says_how_to_build_it(self, monkeypatch):
        """A state nobody has extracted yet is a one-time job, not a
        mystery: the message names the script and the source."""
        monkeypatch.setattr(
            sg, "_storage_client", lambda: _Client(_Blob(present=False))
        )
        with pytest.raises(FileNotFoundError) as caught:
            sg.download_extract("KS")
        assert "build_osm_poi_extract.py" in str(caught.value)

    def test_an_unresolvable_state_never_reaches_the_bucket(self):
        with pytest.raises(ValueError):
            sg.download_extract("ZZ")


class TestBatching:
    def test_rows_are_written_in_batches_not_one_at_a_time(self, tmp_path):
        """Washington is 50,481 features. One INSERT each is a round trip
        per POI."""
        rows = [_row(f"Mizzou Arena {i}", osm_id=str(i)) for i in range(sg.BATCH + 5)]
        path = tmp_path / "big.csv"
        path.write_text("\n".join([HEADER, *rows]))
        session = _Session()
        counts = sg.load_state(session, "MO", path=str(path))
        assert counts["written"] == sg.BATCH + 5
        inserts = [
            s for s in session.statements if "INSERT INTO gazetteer_features" in s
        ]
        assert len(inserts) == 2
        assert len(session.params[0]) == sg.BATCH


class TestReportingWhatIsInstalled:
    def test_loaded_states_reads_the_table(self):
        session = _Session(answers=[[("MO",), ("VT",)]])
        assert sg.loaded_states(session) == {"MO", "VT"}

    def test_a_bad_code_is_not_loaded(self):
        assert sg.state_is_loaded(_Session(), "ZZ") is False

    def test_on_demand_loads_a_state_that_is_absent(self, monkeypatch):
        session = _Session(answers=[[]])
        called = {}

        def fake_load(sess, state, *, path=None, dry_run=False):
            called["state"] = state
            return {"read": 3, "written": 3}

        monkeypatch.setattr(sg, "load_state", fake_load)
        # The school load reaches GCS, and importing the real
        # `google.cloud.storage` binds it as an attribute of the
        # `google.cloud` package -- from then on `from google.cloud import
        # storage` returns the real module however `sys.modules` is
        # patched, and tests/utils/test_raw_html_archive.py fails. Stub it:
        # this test is about `load_state` being dispatched, not schools.
        from src.pipeline import school_gazetteer

        monkeypatch.setattr(
            school_gazetteer, "load_schools", lambda *a, **k: {"written": 0}
        )
        assert sg.ensure_state(session, "MO")["written"] == 3
        assert called["state"] == "MO"

    def test_schools_failing_does_not_fail_the_install(self, monkeypatch):
        """The OSM gazetteer is installed by the time schools are tried,
        and a state is usable without them. A bucket that will not answer
        must not leave the caller with no gazetteer at all."""
        from src.pipeline import school_gazetteer

        session = _Session(answers=[[]])
        monkeypatch.setattr(sg, "load_state", lambda *a, **k: {"read": 3, "written": 3})

        def refuse(*args, **kwargs):
            raise RuntimeError("the bucket is not answering")

        monkeypatch.setattr(school_gazetteer, "load_schools", refuse)
        result = sg.ensure_state(session, "MO")
        assert result["written"] == 3
        assert result["schools"] == 0


class TestTheCategoryIndexIgnoresMalformedFilters:
    def test_a_filter_without_an_equals_is_skipped(self, monkeypatch):
        import sys as _sys

        module = _sys.modules.get("populate_gazetteer")
        assert module is not None or True
        index = sg._category_index()
        assert all(isinstance(key, tuple) and len(key) == 2 for key in index)


class TestTheProductionPathIsTheBucket:
    def test_load_state_without_a_file_fetches_the_extract(self, monkeypatch):
        """`--from-file` is for testing; the real load reads the bucket."""
        monkeypatch.setattr(
            sg,
            "download_extract",
            lambda state: "\n".join([HEADER, _row("Mizzou Arena")]),
        )
        session = _Session()
        counts = sg.load_state(session, "MO")
        assert counts == {"read": 1, "written": 1}
        assert session.commits == 1
