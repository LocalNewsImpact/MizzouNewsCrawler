"""Which states a source's entities may be matched against.

A Washington publisher reading the Missouri gazetteer, and eighteen
others, is 99% wasted work and a standing invitation to match the wrong
Springfield. `docs/STATEWIDE_GAZETTEER.md` §9.

The scope is NOT the dataset's state. A dataset is a coverage list, not a
location list: the Mizzou dataset legitimately holds KMBZ (Mission, KS)
and Dos Mundos (Overland Park, KS) because the Kansas City metro spans
the line, and the VT-Community-News dataset is 901 student papers from
around the country -- DePauw, Oklahoma, Loyola New Orleans -- which carry
no state at all and must therefore be scoped to NOTHING rather than to
Vermont. Guessing one on 2026-09-16 assigned 896 national outlets to the
Vermont gazetteer; the guess was reverted, and these tests are what stop
it returning.

The threshold is 10% of a source's own 20-mile OSM build, and the
distribution chose it: 23 secondary states are at 20% or more (Dos Mundos
is 45% Kansas), 7 more at 10-20%, then one in the 5-10% band and 17 below
5% -- several at a single POI.
"""

from __future__ import annotations

from src.pipeline import statewide_gazetteer as sg


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _Result(self._rows if len(self.statements) == 1 else [])


class TestWhatIsInReach:
    def test_the_home_state_is_in_scope_even_with_no_build(self):
        """A source with no gazetteer yet still belongs somewhere."""
        scope = sg.reachable_states(_Session([]), "s1", home="MO")
        assert [entry["state"] for entry in scope] == ["MO"]
        assert scope[0]["is_home"] is True

    def test_a_real_border_metro_reaches_both(self):
        """Dos Mundos sits in Overland Park and covers Kansas City."""
        scope = sg.reachable_states(
            _Session([("KS", 3712), ("MO", 4550)]), "s1", home="KS"
        )
        assert {entry["state"] for entry in scope} == {"KS", "MO"}

    def test_the_home_state_is_listed_first(self):
        scope = sg.reachable_states(
            _Session([("MO", 4550), ("KS", 3712)]), "s1", home="KS"
        )
        assert scope[0]["state"] == "KS"

    def test_a_spillover_of_one_poi_does_not_open_a_state(self):
        """THE POINT OF THE THRESHOLD. auroraadvertiser.net touches
        Kansas by a single POI; admitting it hands a Missouri weekly the
        whole 17,997-feature Kansas gazetteer."""
        scope = sg.reachable_states(_Session([("MO", 393), ("KS", 1)]), "s1", home="MO")
        assert [entry["state"] for entry in scope] == ["MO"]

    def test_the_share_is_recorded_so_the_decision_can_be_re_read(self):
        scope = sg.reachable_states(_Session([("MO", 50), ("KS", 50)]), "s1", home="MO")
        assert {entry["state"]: entry["share"] for entry in scope} == {
            "MO": 0.5,
            "KS": 0.5,
        }

    def test_a_source_with_no_state_and_no_build_reaches_nothing(self):
        """The 901 national student papers. Nothing, not everything."""
        assert sg.reachable_states(_Session([]), "s1", home=None) == []
        assert sg.reachable_states(_Session([]), "s1", home="") == []

    def test_a_state_that_is_not_a_state_is_not_home(self):
        assert sg.reachable_states(_Session([]), "s1", home="ZZ") == []


class TestReadingItBack:
    def test_an_unscoped_source_matches_nothing(self):
        """Empty means match nothing. A source whose state could not be
        resolved is never handed the whole country."""
        assert sg.scope_for(_Session([]), "s1") == []

    def test_the_home_state_comes_first(self):
        session = _Session([("MO",), ("KS",)])
        assert sg.scope_for(session, "s1") == ["MO", "KS"]
        assert "ORDER BY is_home DESC" in session.statements[0]

    def test_storing_replaces_rather_than_appends(self):
        """A source that loses a state must stop reaching it."""
        session = _Session()
        sg.store_scope(
            session, "s1", [{"state": "MO", "is_home": True, "pois": 9, "share": 1.0}]
        )
        assert "DELETE FROM source_gazetteer_scope" in session.statements[0]
