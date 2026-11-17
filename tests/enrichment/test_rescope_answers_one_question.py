"""`enrich rescope`: scope asked again, geography moved only where it must.

Without a database: the session records the SQL it is given and answers the
three reads `apply` makes -- the record before, the stored places, the
record after.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.enrichment import rescope
from src.enrichment.types import ArticleInput, StepResult


def _article():
    return ArticleInput(
        id="a1",
        title="Chewelah clinic wins grant",
        content="CHEWELAH -- NEW Health won a grant to expand care in Chewelah.",
        dataset_slug="WSU-Washington-State",
        publication_city="Colville",
        publication_state="WA",
    )


def _scope(category, ok=True, cost="0.001"):
    payload = (
        {
            "article_metadata": {
                "category": category,
                "confidence": 0.9,
                "rationale": f"about {category}",
            }
        }
        if category
        else None
    )
    return StepResult(
        step="scope",
        ok=ok,
        payload=payload,
        error=None if ok else "timeout",
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal(cost),
    )


def _record(scope, point_geoid=None, geoids=(), place=None):
    return {
        "scope": scope,
        "scope_confidence": 0.8,
        "rationales": {"scope": "old reason"},
        "point_place": place,
        "point_method": "focus_model" if place else None,
        "point_geoid": point_geoid,
        "geoids": list(geoids),
        "geo_skip_reason": None if point_geoid else "regional_uses_place_set",
    }


class _Result:
    def __init__(self, mapping=None, rows=()):
        self._mapping = mapping
        self._rows = list(rows)

    def mappings(self):
        return self

    def first(self):
        return self._mapping

    def fetchall(self):
        return self._rows


class _Session:
    def __init__(self, states, places=()):
        self.states = list(states)
        self.places = list(places)
        self.statements = []
        self.params = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(params)
        if "FROM article_enrichment" in sql and "SELECT scope" in sql:
            return _Result(mapping=self.states.pop(0))
        if "FROM article_places" in sql:
            return _Result(rows=self.places)
        return _Result()

    def commit(self):
        self.commits += 1

    def log_row(self):
        (params,) = [
            p
            for s, p in zip(self.statements, self.params, strict=True)
            if "INSERT INTO enrichment_rescope_log" in s
        ]
        return params


# ---- which stories are re-placed --------------------------------------------


@pytest.mark.parametrize(
    "old, new, placed",
    [
        ("city_municipality", "city_municipality", False),
        ("city_municipality", "neighborhood_community", False),
        # a point story keeps its point under a crossing scope
        ("city_municipality", "elsewhere_to_local", False),
        ("regional", "regional", False),
        ("regional", "city_municipality", True),
        ("city_municipality", "regional", True),
        ("regional", "statewide", True),
        # before v4 a crossing scope got no point; it gets one now
        ("local_to_elsewhere", "local_to_elsewhere", True),
        ("elsewhere_to_local", "city_municipality", True),
    ],
)
def test_a_story_is_re_placed_only_when_its_geography_is_wrong(old, new, placed):
    assert rescope.needs_placing(new, old) is placed


def test_focus_is_asked_only_for_a_story_that_needs_a_point(monkeypatch):
    calls = []
    monkeypatch.setattr(
        rescope.adapter, "run_scope", lambda a, m: _scope("city_municipality")
    )
    monkeypatch.setattr(
        rescope.adapter, "run_focus", lambda a, m: calls.append(a.id) or _scope(None)
    )
    assert rescope.ask(_article(), "city_municipality", "m").focus is None
    assert rescope.ask(_article(), "regional", "m").focus is not None
    assert calls == ["a1"]


def test_an_answer_outside_the_categories_is_no_answer():
    assert rescope.scope_meta(_scope("county")) is None
    assert rescope.scope_meta(_scope(None, ok=False)) is None
    assert rescope.scope_meta(_scope("regional"))["category"] == "regional"


# ---- what the log says ------------------------------------------------------


def test_the_change_is_read_off_the_record():
    city = _record("city_municipality", "5312345", ["5300065"], "Chewelah")
    regional = _record("regional", None, ["5312345", "5300065"])
    assert rescope.classify(city, regional) == "point_removed"
    assert rescope.classify(regional, city) == "point_added"
    assert rescope.classify(city, {**city, "point_geoid": "5399999"}) == "point_moved"
    assert (
        rescope.classify(regional, {**regional, "geoids": ["53"]})
        == "place_set_changed"
    )
    assert (
        rescope.classify(city, {**city, "scope": "neighborhood_community"})
        == "scope_only"
    )
    assert rescope.classify(city, city) == "unchanged"
    # a crossing story that keeps its scope and gains a point has changed
    crossing = _record("local_to_elsewhere")
    assert (
        rescope.classify(crossing, {**crossing, "point_geoid": "5312345"})
        == "point_added"
    )


# ---- what is written --------------------------------------------------------


def test_a_failed_answer_changes_nothing_and_is_logged():
    before = _record("regional", geoids=["5312345"])
    session = _Session([before])
    answer = rescope.Answer(_article(), "regional", _scope(None, ok=False), None)
    assert rescope.apply(session, answer, run_id="r", model="m") == "error"
    assert not any("UPDATE article_enrichment" in s for s in session.statements)
    log = session.log_row()
    assert log["change"] == "error" and log["error"] == "timeout"
    assert log["new_geoids"] == log["old_geoids"]
    assert session.commits == 1


def test_a_story_keeping_its_kind_of_geography_has_only_its_scope_written():
    before = _record("city_municipality", "5312345", place="Chewelah")
    after = {
        **before,
        "scope": "neighborhood_community",
        "rationales": {"scope": "about neighborhood_community"},
    }
    session = _Session([before, after])
    answer = rescope.Answer(
        _article(), "city_municipality", _scope("neighborhood_community"), None
    )
    assert rescope.apply(session, answer, run_id="r", model="m") == "scope_only"
    updates = [s for s in session.statements if "UPDATE article_enrichment" in s]
    assert len(updates) == 1 and "point_place" not in updates[0]
    assert not any("article_geoids" in s for s in session.statements)
    log = session.log_row()
    assert (log["old_scope"], log["new_scope"]) == (
        "city_municipality",
        "neighborhood_community",
    )
    assert log["old_rationale"] == "old reason"
    assert log["new_rationale"] == "about neighborhood_community"


def test_a_story_that_became_regional_loses_its_point(monkeypatch):
    """The enrichment upsert COALESCEs the point columns, which would keep
    a point the story no longer has. Rescope writes them outright."""
    before = _record("city_municipality", "5312345", ["5300065"], "Chewelah")
    after = _record("regional", None, ["5312345", "5300065"])
    session = _Session(
        [before, after],
        places=[
            SimpleNamespace(
                id=7,
                full_name="Chewelah, WA",
                place_type="city",
                city="Chewelah",
                county="Stevens",
                state="WA",
                address=None,
                description=None,
                mention_text="Chewelah",
            )
        ],
    )
    seen = {}

    def fake_point(sess, article, scope, payload, focus, named):
        seen["payload"], seen["scope"], seen["focus"] = payload, scope, focus
        return None, None, "regional_uses_place_set"

    monkeypatch.setattr(rescope, "story_point", fake_point)
    monkeypatch.setattr(rescope, "institution_places", lambda s, i: [])
    monkeypatch.setattr(
        rescope, "write_story_geoids", lambda *a, **k: seen.setdefault("geoids", k)
    )
    answer = rescope.Answer(_article(), "city_municipality", _scope("regional"), None)

    assert rescope.apply(session, answer, run_id="r", model="m") == "point_removed"
    (placed,) = [
        p
        for s, p in zip(session.statements, session.params, strict=True)
        if "point_place = :point_place" in s
    ]
    assert placed["point_place"] is None and placed["point_geoid"] is None
    assert placed["focus_ran"] is False
    # the stored places, in the shape the places step returns
    components = seen["payload"]["locations"][0]["location"]["components"]
    assert components == {
        "city": "Chewelah",
        "county": "Stevens",
        "state": "WA",
        "address": None,
    }
    assert seen["geoids"]["scope_category"] == "regional"
    # the place is no longer the point
    (flag,) = [
        p
        for s, p in zip(session.statements, session.params, strict=True)
        if "UPDATE article_places" in s
    ]
    assert flag == {"p": False, "id": 7}


def test_a_new_point_story_is_placed_by_the_focus_answer(monkeypatch):
    before = _record("regional", None, ["5312345"])
    after = _record("city_municipality", "5312345", place="Chewelah")
    session = _Session([before, after])
    focus = StepResult(
        step="focus",
        ok=True,
        payload={"central": {"city": "Chewelah"}},
        error=None,
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal("0.0009"),
    )
    seen = {}

    def fake_point(sess, article, scope, payload, focus_payload, named):
        seen["focus"] = focus_payload
        geoid = SimpleNamespace(geoid="5312345", level="place", lat=48.3, lon=-117.7)
        return ("Chewelah", "focus_model"), geoid, None

    monkeypatch.setattr(rescope, "story_point", fake_point)
    monkeypatch.setattr(rescope, "institution_places", lambda s, i: [])
    monkeypatch.setattr(rescope, "write_story_geoids", lambda *a, **k: None)
    answer = rescope.Answer(_article(), "regional", _scope("city_municipality"), focus)

    assert rescope.apply(session, answer, run_id="r", model="m") == "point_added"
    assert seen["focus"] == {"central": {"city": "Chewelah"}}
    (placed,) = [
        p
        for s, p in zip(session.statements, session.params, strict=True)
        if "point_place = :point_place" in s
    ]
    assert placed["point_place"] == "Chewelah" and placed["focus_ran"] is True
    assert placed["point_support"] is not None
    assert session.log_row()["cost"] == Decimal("0.0019")
    assert session.log_row()["focus_run"] is True


def test_a_rescoped_record_is_not_selected_again():
    """The version recorded is the version selected against, so a run that
    stops resumes, and one that finished is a no-op."""
    assert ":version" in str(rescope._CANDIDATES)
    assert "'scope'" in str(rescope._CANDIDATES)
    assert "jsonb_build_object('scope', CAST(:version AS text))" in rescope._SCOPE_SET


def test_a_new_enrichment_records_its_scope_prompt():
    from src.cli.commands.enrichment import _prompt_versions

    assert _prompt_versions()["scope"] == rescope.adapter.SCOPE_PROMPT_VERSION
