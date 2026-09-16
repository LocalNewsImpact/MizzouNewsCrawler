"""`gazetteer_places` without a network or a database.

This exists because the grounding gate deleted correct geography. The
model induces a place from an institution a story names -- "Southeast
Missouri State gymnastics" is a Cape Girardeau story -- and a gate that
asks only whether the place NAME appears in the text throws that away
with the fabrication it was built to stop. 70 of the 803 points the
first backfill cleared were this.

The verifier is the gazetteer. What it lacked was the Census place, and
`tags->>'addr:city'` does not supply it: present on 223,771 of 558,540
rows, absent on the rest, and a postal name rather than a GEOID.
"""

from __future__ import annotations

import json
import urllib.parse

import pytest

from src.enrichment import gazetteer_places as gp

SEMO = {
    "result": {
        "geographies": {
            # The key carries the vintage, which is why layers are matched
            # by substring and not by an exact name that changes.
            "Incorporated Places": [
                {"NAME": "Cape Girardeau city", "GEOID": "2911242"}
            ],
            "Counties": [{"NAME": "Cape Girardeau County", "GEOID": "29031"}],
        }
    }
}


class TestTheRequest:
    def test_longitude_is_x_and_latitude_is_y(self):
        """Reversed, every point lands in the wrong hemisphere and the
        geocoder answers with nothing rather than an error."""
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(gp.url_for(37.3126, -89.5265)).query
        )
        assert query["x"] == ["-89.5265"]
        assert query["y"] == ["37.3126"]

    def test_both_rungs_are_asked_for_at_once(self):
        """One call, not two: this is thousands of requests to somebody
        else's free service."""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(gp.url_for(1.0, 2.0)).query)
        assert "Incorporated Places" in query["layers"][0]
        assert "Counties" in query["layers"][0]


class TestTheAnswer:
    def test_a_placement_is_read_out(self):
        placement = gp.parse(SEMO)
        assert placement.place_geoid == "2911242"
        assert placement.county_geoid == "29031"

    def test_the_legal_word_is_dropped_from_the_name(self):
        """Stored the way it will later be compared: copy prints "Cape
        Girardeau", never "Cape Girardeau city"."""
        assert gp.parse(SEMO).place_name == "Cape Girardeau"

    def test_a_vintage_prefixed_layer_is_still_found(self):
        payload = {
            "result": {
                "geographies": {
                    "2020 Census Incorporated Places": [
                        {"NAME": "Fulton city", "GEOID": "2926586"}
                    ]
                }
            }
        }
        assert gp.parse(payload).place_name == "Fulton"

    def test_no_place_is_an_answer_not_a_crash(self):
        """A point in open water or outside any incorporated place."""
        placement = gp.parse({"result": {"geographies": {"Counties": []}}})
        assert placement == gp.Placement()

    def test_an_empty_body_parses(self):
        assert gp.parse({}) == gp.Placement()


class TestAFailedCallIsNotAnAnswer:
    def test_resolve_returns_none_when_the_call_fails(self, monkeypatch):
        """None means "ask again". An empty Placement means "asked, and
        this point is nowhere". Conflating them either loses points
        forever or re-asks them forever."""

        def boom(*_a, **_k):
            raise TimeoutError("census is down")

        monkeypatch.setattr(gp.urllib.request, "urlopen", boom)
        assert gp.resolve(37.0, -89.0) is None

    def test_resolve_returns_a_placement_on_success(self, monkeypatch):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def read(self):
                return json.dumps(SEMO).encode()

        monkeypatch.setattr(gp.json, "load", lambda _fh: SEMO)
        monkeypatch.setattr(gp.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
        assert gp.resolve(37.3126, -89.5265).place_name == "Cape Girardeau"


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.statements = []
        self.params = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        if len(self.statements) == 1:
            return _Result(self._rows)
        return _Result()

    def commit(self):
        self.commits += 1


class TestTheBackfill:
    ROWS = [("g1", 37.3126, -89.5265)]

    @pytest.fixture
    def placed(self, monkeypatch):
        monkeypatch.setattr(gp, "resolve", lambda *_a, **_k: gp.parse(SEMO))

    def test_only_matched_entries_are_asked_for(self):
        """11,440 of 558,540. Asking for all of them is a week of calls
        to answer a question the gate never puts."""
        session = _Session()
        gp.geocode(session, dry_run=True)
        assert "matched_gazetteer_id = g.id" in session.statements[0]

    def test_all_can_be_requested(self):
        session = _Session()
        gp.geocode(session, only_matched=False, dry_run=True)
        assert "matched_gazetteer_id" not in session.statements[0]

    def test_a_point_already_looked_up_is_not_asked_again(self):
        session = _Session()
        gp.geocode(session, dry_run=True)
        assert "geocoded_at IS NULL" in session.statements[0]

    def test_the_dry_run_writes_nothing(self, placed):
        session = _Session(self.ROWS)
        counts = gp.geocode(session, dry_run=True)
        assert counts["pending"] == 1
        assert len(session.statements) == 1
        assert session.commits == 0

    def test_a_placement_is_stored(self, placed):
        session = _Session(self.ROWS)
        counts = gp.geocode(session, dry_run=False)
        assert counts["placed"] == 1
        stored = session.params[1]
        assert stored["place_geoid"] == "2911242"
        assert stored["place_name"] == "Cape Girardeau"
        assert stored["county_geoid"] == "29031"
        assert stored["now"] is not None

    def test_a_point_in_no_place_is_stamped_anyway(self, monkeypatch):
        """Otherwise every such point is re-asked on every run, forever."""
        monkeypatch.setattr(gp, "resolve", lambda *_a, **_k: gp.Placement())
        session = _Session(self.ROWS)
        counts = gp.geocode(session, dry_run=False)
        assert counts["no_place"] == 1
        assert session.params[1]["now"] is not None

    def test_a_failed_call_leaves_the_row_alone(self, monkeypatch):
        monkeypatch.setattr(gp, "resolve", lambda *_a, **_k: None)
        session = _Session(self.ROWS)
        counts = gp.geocode(session, dry_run=False)
        assert counts["failed"] == 1
        assert not [s for s in session.statements if s.startswith("\n    UPDATE")]

    def test_nothing_pending_short_circuits(self):
        session = _Session([])
        assert gp.geocode(session, dry_run=False)["pending"] == 0
        assert session.commits == 0


class TestTheCallIsRecorded:
    """Thousands of requests to somebody else's free service. The
    telemetry that answers "how many, how fast, how often refused" is the
    same one `fips` uses, and it has to be reached from here too."""

    class _Call:
        def __init__(self):
            self.meta = {}
            self.failure = None

        def failed(self, name):
            self.failure = name

    class _Recorder:
        def __init__(self, call):
            self.call_obj = call
            self.asked = None

        def call(self, service, operation, **kwargs):
            self.asked = (service, operation, kwargs)
            recorder = self

            class _Ctx:
                def __enter__(self_inner):
                    return recorder.call_obj

                def __exit__(self_inner, *_a):
                    return False

            return _Ctx()

    def test_a_success_is_recorded_as_placed(self, monkeypatch):
        call = self._Call()
        recorder = self._Recorder(call)
        monkeypatch.setattr(gp.json, "load", lambda _fh: SEMO)
        monkeypatch.setattr(
            gp.urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse()
        )
        gp.resolve(1.0, 2.0, call_recorder=recorder, subject_id="g1")
        assert recorder.asked[0] == "census_geocoder"
        assert recorder.asked[1] == "coordinates"
        assert recorder.asked[2]["subject_id"] == "g1"
        assert call.meta["placed"] is True

    def test_a_failure_is_recorded_with_its_class(self, monkeypatch):
        call = self._Call()

        def boom(*_a, **_k):
            raise TimeoutError("census is down")

        monkeypatch.setattr(gp.urllib.request, "urlopen", boom)
        assert gp.resolve(1.0, 2.0, call_recorder=self._Recorder(call)) is None
        assert call.failure == "TimeoutError"


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class TestScopingAndProgress:
    def test_a_limit_reaches_the_query(self):
        session = _Session()
        gp.geocode(session, limit=50, dry_run=True)
        assert "LIMIT 50" in session.statements[0]

    def test_it_commits_and_reports_as_it_goes(self, monkeypatch):
        """11,440 lookups is a long job. Committing only at the end
        throws the whole run away when it is interrupted -- which is what
        happened to the first backfill at 11,000 of 14,061."""
        monkeypatch.setattr(gp, "resolve", lambda *_a, **_k: gp.parse(SEMO))
        rows = [(f"g{i}", 37.0, -89.0) for i in range(200)]
        session = _Session(rows)
        seen = []
        gp.geocode(session, dry_run=False, on_batch=lambda n, c: seen.append(n))
        assert seen == [200]
        assert session.commits >= 2


class TestWhichTableIsResolved:
    """`gazetteer` is the per-source build; `gazetteer_features` is the
    statewide one that replaces it for matching. Both carry points, and
    the statewide one needs every point resolved rather than only the
    features some article happened to match -- the ambiguity rule counts
    places across every feature sharing a name."""

    def test_the_table_name_is_whitelisted(self):
        """It reaches SQL."""
        with pytest.raises(ValueError):
            gp.pending(_Session(), table="articles; DROP TABLE gazetteer")

    def test_the_per_source_table_narrows_to_matched_features(self):
        session = _Session()
        gp.geocode(session, table="gazetteer", dry_run=True)
        assert "matched_gazetteer_id = g.id" in session.statements[0]

    def test_the_statewide_table_does_not_narrow(self):
        """A statewide feature is not tied to a publisher, and §3.1 needs
        a place for every one of them to count ambiguity."""
        session = _Session()
        gp.geocode(session, table="gazetteer_features", dry_run=True)
        assert "matched_gazetteer_id" not in session.statements[0]
        assert "FROM gazetteer_features" in session.statements[0]

    def test_the_update_targets_the_same_table(self, monkeypatch):
        monkeypatch.setattr(gp, "resolve", lambda *_a, **_k: gp.parse(SEMO))
        session = _Session([("g1", 37.0, -89.0)])
        gp.geocode(session, table="gazetteer_features", dry_run=False)
        update = next(s for s in session.statements if "UPDATE" in s)
        assert "UPDATE gazetteer_features" in update


class TestTheCommandLineExposesWhatTheHandlerReads:
    """The gap that shipped a broken command: the handler passed
    `args.table` while the parser never registered `--table`, so the job
    died on "unrecognized arguments" after the commit looked fine. A
    handler reading an argument the parser does not define is a runtime
    error, not a type error, and nothing else here would catch it."""

    def _parser(self):
        import argparse

        from src.cli.commands.gazetteer_geocode import add_gazetteer_geocode_parser

        parser = argparse.ArgumentParser()
        add_gazetteer_geocode_parser(parser.add_subparsers(dest="cmd"))
        return parser

    def test_every_argument_the_handler_reads_is_defined(self):
        import re
        from pathlib import Path

        source = Path("src/cli/commands/gazetteer_geocode.py").read_text()
        handler = source[source.index("def handle_gazetteer_geocode_command") :]
        read = set(re.findall(r"args\.([a-z_]+)", handler))
        parsed = vars(self._parser().parse_args(["geocode-gazetteer"]))
        assert read <= set(
            parsed
        ), f"handler reads undefined args: {read - set(parsed)}"

    def test_the_statewide_table_can_be_asked_for(self):
        args = self._parser().parse_args(
            ["geocode-gazetteer", "--table", "gazetteer_features"]
        )
        assert args.table == "gazetteer_features"

    def test_an_unknown_table_is_refused_at_the_command_line(self):
        with pytest.raises(SystemExit):
            self._parser().parse_args(["geocode-gazetteer", "--table", "articles"])
