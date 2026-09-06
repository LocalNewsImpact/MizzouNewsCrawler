"""The verification stage records each decision, and the reason for it.

`url_verifications` has held zero rows since it was created. It has the
right columns -- the verdict, the confidence, the headline, and the human
label a reviewer would write -- and the implementation that fills them,
`src/services/url_verification_service.py`, is not the one that runs. The
CLI and the Argo step import `src/services/url_verification.py`, which
updates `candidate_links.status` and writes a batch summary.

The consequence is that no rejection can be attributed. Two thirds of
them turn out to be a rule overruling the model, but that is only sayable
by re-running the model offline against the corpus -- and for a URL that
was rejected, there is no corpus row at all. Nothing measures precision
or recall for either stage, because the machine's decision is not written
down beside the human's.

So: one row per verified URL, carrying which of the four mechanisms
decided, and never failing the batch to get it.
"""

import re

import pytest

from src.services.verification_rules import ORIGINALS, REPAIRS


class _Sniffer:
    def __init__(self, answer=True):
        self.answer = answer

    def guess(self, url):
        return self.answer


class _Session:
    """The requests session, which verification must not use here."""

    def __init__(self):
        self.headers = {}

    def head(self, *args, **kwargs):
        raise RuntimeError("HEAD should not be called")


def _service(answer=True):
    from src.services.url_verification import URLVerificationService

    svc = URLVerificationService(http_session=_Session(), run_http_precheck=False)
    svc.sniffer = _Sniffer(answer)
    return svc


# --- which mechanism decided -------------------------------------------------


def test_the_wire_filter_is_named():
    svc = _service()
    assert svc._decided_by({"wire_filtered": True}) == "wire"


def test_a_rule_is_named_with_its_type():
    """A rule that rejects too widely is fixed once, for every URL it will
    ever match -- but only if the row says which rule it was."""
    svc = _service()
    decided = svc._decided_by({"pattern_filtered": True, "pattern_type": "video"})
    assert decided == "pattern:video"


def test_an_unnamed_rule_still_says_it_was_a_rule():
    svc = _service()
    assert svc._decided_by({"pattern_filtered": True}) == "pattern:unnamed"


def test_the_model_is_named():
    svc = _service()
    assert svc._decided_by({"storysniffer_result": True}) == "sniffer"


def test_nothing_matching_is_its_own_answer():
    """The default branch rejects when no rule fired and the model said
    no. That is not the same as a rule rejecting it, and a queue that
    cannot tell them apart cannot review either."""
    svc = _service()
    assert svc._decided_by({"storysniffer_result": False}) == "default"


def test_an_error_is_not_a_verdict():
    svc = _service()
    assert svc._decided_by({"error": "timeout", "storysniffer_result": None}) == "error"


# --- recording ---------------------------------------------------------------


def test_a_batch_records_one_row_per_decision(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "update_candidate_status", lambda *a, **k: None)
    recorded = {}
    monkeypatch.setattr(
        svc,
        "record_verifications",
        lambda records, job_name: recorded.update(rows=records, job=job_name)
        or len(records),
    )

    svc._job_name = "verification_20260906"
    svc.process_batch(
        [
            {"id": "c1", "url": "https://example.org/a-story", "status": "discovered"},
            {"id": "c2", "url": "https://example.org/another", "status": "discovered"},
        ]
    )

    assert recorded["job"] == "verification_20260906"
    assert [r["candidate_link_id"] for r in recorded["rows"]] == ["c1", "c2"]


def test_the_row_carries_the_decision_and_its_reason(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "update_candidate_status", lambda *a, **k: None)
    rows = []
    monkeypatch.setattr(
        svc, "record_verifications", lambda records, job_name: rows.extend(records)
    )

    svc._job_name = "job"
    svc.process_batch(
        [{"id": "c1", "url": "https://example.org/a-story", "status": "discovered"}]
    )

    row = rows[0]
    assert row["new_status"] == "article"
    assert row["previous_status"] == "discovered"
    assert row["storysniffer_result"] is True
    assert row["meta"]["decided_by"] == "sniffer"
    # The probability behind the boolean comes from a GaussianNB that
    # saturates, so recording a number would invite ranking on something
    # that cannot rank.
    assert row["verification_confidence"] is None


def test_nothing_is_recorded_until_the_run_names_itself(monkeypatch):
    """The batch can be driven directly in a test, and then the decisions
    are made and simply not recorded."""
    svc = _service()
    monkeypatch.setattr(svc, "update_candidate_status", lambda *a, **k: None)
    called = []
    monkeypatch.setattr(
        svc, "record_verifications", lambda records, job_name: called.append(records)
    )

    svc.process_batch([{"id": "c1", "url": "https://example.org/x", "status": "d"}])
    assert called == []


def test_a_recording_failure_is_swallowed(monkeypatch):
    """Recording is bookkeeping. A run that stopped because it could not
    write its own audit row would trade the pipeline for the record of
    it."""
    svc = _service()
    monkeypatch.setattr(svc, "_ensure_job", lambda job_name: "job-1")

    def _explode(*args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(svc.db, "get_session", _explode)

    assert svc.record_verifications([{"candidate_link_id": "c1"}], "job") == 0


def test_no_job_means_no_rows_rather_than_an_exception(monkeypatch):
    """`url_verifications.verification_job_id` is NOT NULL, so a decision
    cannot be recorded without a job row."""
    svc = _service()
    monkeypatch.setattr(svc, "_ensure_job", lambda job_name: None)
    assert svc.record_verifications([{"candidate_link_id": "c1"}], "job") == 0


# --- the rules themselves ----------------------------------------------------


def test_every_shipped_rule_compiles():
    """Four of the 46 rules in production carry regexes that do not
    compile -- `/(entertainment`, `obituar(y`, `/(us-world-news`,
    `/(weather` -- so they have never matched a URL. The repairs are in
    migration q2r3s4t5u6v7 and this is what keeps the next one honest."""
    for pattern_type, regex, _ in REPAIRS:
        try:
            re.compile(regex)
        except re.error as exc:  # pragma: no cover - the assertion is the point
            pytest.fail(f"{pattern_type} does not compile: {exc}")

    # And the originals are recorded as they were, broken, so `downgrade`
    # restores the state it found rather than a tidied version of it.
    broken = [t for t, rx, _ in ORIGINALS if not _compiles(rx)]
    assert sorted(broken) == ["obituary", "us_world_news", "weather"]


def _compiles(regex):
    try:
        re.compile(regex)
        return True
    except re.error:
        return False


def test_the_repaired_world_rule_does_not_match_local_coverage():
    """Kansas City hosts the 2026 World Cup, so `/world` unbounded is a
    growing category of local journalism: Worlds of Fun, the World Cup
    trophy coming to St. Louis, a world record broken by a Nixa
    10-year-old."""
    rule = {t: rx for t, rx, _ in REPAIRS}["us_world_news"]
    matcher = re.compile(rule)

    assert matcher.search("https://example.org/world/ukraine-talks-resume")
    for local in (
        "https://www.kmbc.com/article/worlds-of-fun-chaperone-policy/679",
        "https://kctv5.com/2025/10/30/world-cup-draw-kansas-city-hopes",
        "https://christiancountyheadliner.com/world-record-broken-by-nixa-10-year-old",
    ):
        assert matcher.search(local) is None, local


def test_the_repaired_feed_rule_does_not_match_a_story_about_feed():
    """`/feed` unbounded rejects `/feeding-the-hungry`, `/feed-seed-grain`
    and `/feeders-pet-and-supply`: twenty local stories treated as RSS."""
    rule = {t: rx for t, rx, _ in REPAIRS}["feed"]
    matcher = re.compile(rule)

    assert matcher.search("https://example.org/feed/")
    assert matcher.search("https://example.org/feed")
    for story in (
        "https://www.cassville-democrat.com/2025/11/18/feeding-the-hungry",
        "https://www.lawrencecountyrecord.com/content/feed-seed-grain-3",
        "https://standard-democrat.com/posterboard/feeders-pet-and-supply-b30",
    ):
        assert matcher.search(story) is None, story


def test_a_topic_rule_never_says_not_article():
    """`us_world_news` is activated by the migration, and a story from the
    national desk is a story. Recording it as `not_article` would be false
    about the URL and terminal: the row is never fetched, so nothing
    downstream can notice."""
    from src.services.url_verification import URLVerificationService

    svc = URLVerificationService(http_session=_Session(), run_http_precheck=False)
    assert svc._map_pattern_type_to_status("us_world_news") == "wire"
    assert svc._map_pattern_type_to_status("obituary") == "obituary"
    assert svc._map_pattern_type_to_status("opinion") == "opinion"
    # Anything without a topic of its own still says what it means.
    assert svc._map_pattern_type_to_status("video") == "not_article"
