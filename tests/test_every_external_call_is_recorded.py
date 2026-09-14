"""Every call to somebody else's service leaves exactly one row.

We could not answer "how many MediaCloud calls do we make a day". The
only evidence was `articles.wire_check_attempted_at` -- one column per
ARTICLE, overwritten on retry -- so a call that failed and then succeeded
looked like one call, and the answer was a lower bound with no margin.

This is not about cost. MediaCloud is free; the questions are whether we
are being a good neighbour, whether the service is up, and whether we are
being blocked. Each of those is a query over these rows, and each is
asserted here against rows the code actually wrote.

THE TESTS RUN ON A REAL DATABASE, sqlite in-memory with the same DDL the
migration creates. A recorder tested against a mock proves the mock was
called; it does not prove a row exists, that the columns line up, or that
counting them gives the number somebody will act on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.telemetry.external_calls import ExternalCallRecorder

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic/versions/y0z1a2b3c4d5_every_external_call_is_recorded.py"
)

# The same shape the migration creates. Kept beside a test that asserts
# the two agree, so a column added there and not here fails rather than
# drifting.
DDL = """
CREATE TABLE external_api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    operation TEXT NOT NULL,
    called_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms INTEGER,
    waited_ms INTEGER,
    outcome TEXT NOT NULL,
    status_code INTEGER,
    error_class TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    subject_type TEXT,
    subject_id TEXT,
    dataset_id TEXT,
    meta TEXT
)
"""


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(DDL))
    return engine


@pytest.fixture
def recorder(engine):
    return ExternalCallRecorder(engine)


def rows(engine, **where):
    sql = "SELECT * FROM external_api_calls"
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = :{k}" for k in where)
    sql += " ORDER BY id"
    with engine.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), where)]


class TestOneRowPerCall:
    def test_a_successful_call_is_recorded(self, recorder, engine):
        with recorder.call("mediacloud", "story_list"):
            pass
        [row] = rows(engine)
        assert row["service"] == "mediacloud"
        assert row["operation"] == "story_list"
        assert row["outcome"] == "ok"

    def test_a_raising_call_is_recorded(self, recorder, engine):
        """THE ROWS THAT MATTER MOST. A `record()` written after the call
        never runs on the path that raised, which is precisely the path
        an outage takes."""
        with pytest.raises(ValueError):
            with recorder.call("mediacloud", "story_list"):
                raise ValueError("boom")
        [row] = rows(engine)
        assert row["outcome"] == "error"
        assert row["error_class"] == "ValueError"

    def test_the_exception_still_reaches_the_caller(self, recorder, engine):
        """Recording must not swallow. A telemetry layer that eats an
        exception turns an outage into a wrong answer."""
        with pytest.raises(KeyError):
            with recorder.call("mediacloud", "story_list"):
                raise KeyError("still mine")

    def test_three_calls_are_three_rows(self, recorder, engine):
        """The grain is the call. This is the whole reason the table
        exists -- the per-article column could not count retries."""
        for _ in range(3):
            with recorder.call("mediacloud", "story_list"):
                pass
        assert len(rows(engine)) == 3

    def test_a_retry_is_two_rows_that_can_be_read_as_one_sequence(
        self, recorder, engine
    ):
        with pytest.raises(TimeoutError):
            with recorder.call("mediacloud", "story_list", attempt=1, subject_id="a1"):
                raise TimeoutError
        with recorder.call("mediacloud", "story_list", attempt=2, subject_id="a1"):
            pass
        found = rows(engine, subject_id="a1")
        assert [r["attempt"] for r in found] == [1, 2]
        assert [r["outcome"] for r in found] == ["error", "ok"]


class TestTheThreeQuestionsItAnswers:
    """Politeness, outages, blocking. Each asserted as the query somebody
    would actually run."""

    def test_the_rate_is_countable(self, recorder, engine):
        """ "How many calls a day" -- the question that started this."""
        for _ in range(7):
            with recorder.call("mediacloud", "story_list"):
                pass
        with engine.begin() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) FROM external_api_calls "
                    "WHERE service = 'mediacloud'"
                )
            ).scalar()
        assert count == 7

    def test_politeness_is_measured_not_claimed(self, recorder, engine):
        """`waited_ms` is what the limiter actually held back. A run of
        zeroes is a limiter that is not binding -- which is a finding,
        not a pass."""
        with recorder.call("mediacloud", "story_list", waited_ms=0):
            pass
        with recorder.call("mediacloud", "story_list", waited_ms=30_000):
            pass
        with engine.begin() as conn:
            never_waited = conn.execute(
                text(
                    "SELECT count(*) FROM external_api_calls "
                    "WHERE service='mediacloud' AND waited_ms = 0"
                )
            ).scalar()
        assert never_waited == 1

    def test_blocking_is_separable_from_an_outage(self, recorder, engine):
        """The failure this table was built for. 14 production failures
        read `error:JSONDecodeError` -- one string that a rate-limit
        page, a gateway error and an empty body all produce. A 429 needs
        backing off and a 500 needs waiting out."""
        with recorder.call("mediacloud", "story_list") as call:
            call.failed("api_error", status_code=429, error_class="APIResponseError")
        with recorder.call("mediacloud", "story_list") as call:
            call.failed("api_error", status_code=503, error_class="APIResponseError")
        with recorder.call("mediacloud", "story_list") as call:
            call.failed("error", error_class="JSONDecodeError")
        with engine.begin() as conn:
            blocked = conn.execute(
                text("SELECT count(*) FROM external_api_calls WHERE status_code = 429")
            ).scalar()
            unavailable = conn.execute(
                text("SELECT count(*) FROM external_api_calls WHERE status_code = 503")
            ).scalar()
        assert (blocked, unavailable) == (1, 1)

    def test_a_failure_traces_back_to_its_subject(self, recorder, engine):
        with recorder.call(
            "mediacloud", "story_list", subject_type="article", subject_id="art-9"
        ) as call:
            call.failed("error", error_class="ReadTimeout")
        [row] = rows(engine, subject_id="art-9")
        assert row["subject_type"] == "article"
        assert row["error_class"] == "ReadTimeout"


class TestWhatTheCallCarries:
    def test_a_client_that_returns_its_errors_is_not_recorded_ok(
        self, recorder, engine
    ):
        """`MediaCloudDetector.detect` catches its own exceptions and
        answers with a status string. By the time the wrapper's `except`
        would see one there is nothing left to catch, so without
        `failed()` every such call is written `ok` and the blocking
        signal is lost."""
        with recorder.call("mediacloud", "story_list") as call:
            call.failed("api_error", status_code=429)
        [row] = rows(engine)
        assert row["outcome"] == "api_error"
        assert row["status_code"] == 429

    def test_duration_is_recorded(self, recorder, engine):
        with recorder.call("mediacloud", "story_list"):
            pass
        [row] = rows(engine)
        assert row["duration_ms"] is not None
        assert row["duration_ms"] >= 0

    def test_meta_round_trips(self, recorder, engine):
        with recorder.call("mediacloud", "story_list") as call:
            call.meta["story_count"] = 12
        [row] = rows(engine)
        assert json.loads(row["meta"])["story_count"] == 12

    def test_an_empty_meta_is_null_not_an_empty_object(self, recorder, engine):
        with recorder.call("mediacloud", "story_list"):
            pass
        [row] = rows(engine)
        assert row["meta"] is None

    def test_a_status_code_on_the_exception_is_read(self, recorder, engine):
        """A 429 raised rather than returned is still a 429. Recording it
        as "some exception" throws the blocking signal away."""

        class Throttled(Exception):
            status_code = 429

        with pytest.raises(Throttled):
            with recorder.call("mediacloud", "story_list"):
                raise Throttled()
        [row] = rows(engine)
        assert row["status_code"] == 429

    def test_a_status_code_on_the_response_is_read_too(self, recorder, engine):
        """The official mediacloud client hangs it off `response`
        instead, which is the shape that already caused one production
        bug in `_status_code_of`."""

        class Response:
            status_code = 503

        class Down(Exception):
            response = Response()

        with pytest.raises(Down):
            with recorder.call("mediacloud", "story_list"):
                raise Down()
        [row] = rows(engine)
        assert row["status_code"] == 503


class TestItNeverBreaksTheCaller:
    def test_a_write_failure_does_not_stop_the_work(self, engine, caplog):
        """The work is the point and the observation is not. But it is
        logged at error, because no rows and no complaint reads exactly
        like making no calls -- the confusion this table exists to end."""
        broken = create_engine("sqlite://")  # no table
        recorder = ExternalCallRecorder(broken)
        with caplog.at_level("ERROR"):
            with recorder.call("mediacloud", "story_list"):
                pass
        assert "could not record" in caplog.text

    def test_a_write_failure_does_not_swallow_the_real_exception(self, caplog):
        broken = create_engine("sqlite://")
        recorder = ExternalCallRecorder(broken)
        with caplog.at_level("ERROR"):
            with pytest.raises(ValueError):
                with recorder.call("mediacloud", "story_list"):
                    raise ValueError("the real problem")


class TestTheSchemaHereMatchesTheMigration:
    """The DDL above is a copy, and a copy drifts. Asserted rather than
    trusted."""

    def test_every_column_the_insert_names_is_in_the_migration(self):
        migration = MIGRATION.read_text()
        for column in re.findall(r'sa\.Column\(\s*"(\w+)"', migration):
            assert column in DDL, f"{column} is in the migration and not in the test"

    def test_every_column_the_test_creates_is_in_the_migration(self):
        migration = MIGRATION.read_text()
        declared = set(re.findall(r'sa\.Column\(\s*"(\w+)"', migration))
        for line in DDL.strip().splitlines()[1:-1]:
            name = line.strip().split()[0]
            assert name in declared, f"{name} is in the test and not in the migration"

    def test_the_migration_indexes_the_three_questions(self):
        """Rate, failures, and tracing back to a subject. Without the
        partial index on failures, the outage query scans every call ever
        made."""
        migration = MIGRATION.read_text()
        assert "ix_external_api_calls_rate" in migration
        assert "ix_external_api_calls_failures" in migration
        assert "ix_external_api_calls_subject" in migration
        assert "outcome <> 'ok'" in migration


# --- end to end, through the code that actually makes the calls -------------


class _FakeSearchApi:
    """MediaCloud's client, answering however the test needs.

    `story_list` is the real method name and signature the detector
    calls, so a rename in the detector breaks this rather than being
    papered over by a Mock that accepts anything.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def story_list(self, **kwargs):
        answer = self.answers[self.calls] if self.calls < len(self.answers) else []
        self.calls += 1
        if isinstance(answer, Exception):
            raise answer
        return answer, None


def _article(article_id):
    from src.services.wire_detection.mediacloud import MediaCloudArticle

    return MediaCloudArticle(
        article_id=article_id,
        source="The Example",
        title=f"A headline for {article_id}",
        url=f"https://example.com/{article_id}",
        extracted_at=None,
    )


def _detector(engine, answers):
    from src.services.wire_detection.mediacloud import (
        MediaCloudDetector,
        RateLimiter,
    )

    return MediaCloudDetector(
        search_api=_FakeSearchApi(answers),
        # A rate nobody has to wait for: the limiter's behaviour is
        # tested on its own, and sleeping here would only make the suite
        # slow.
        rate_limiter=RateLimiter(60_000),
        call_recorder=ExternalCallRecorder(engine),
    )


class TestTheDetectorRecordsWhatItDid:
    """The wiring, end to end. The recorder being correct proves nothing
    if the detector never calls it -- which is the failure mode this repo
    has hit before: code that does not execute on the path it is needed
    on."""

    def test_a_successful_lookup_leaves_a_row(self, engine):
        detector = _detector(engine, [[{"id": 1, "url": "https://ap.org/x"}]])
        result = detector.detect(_article("art-1"))
        assert result.status == "ok"
        [row] = rows(engine)
        assert row["service"] == "mediacloud"
        assert row["operation"] == "story_list"
        assert row["outcome"] == "ok"
        assert row["subject_id"] == "art-1"

    def test_the_story_count_is_kept(self, engine):
        detector = _detector(engine, [[{"id": 1}, {"id": 2}]])
        detector.detect(_article("art-2"))
        [row] = rows(engine)
        assert json.loads(row["meta"])["story_count"] == 2

    def test_a_failed_lookup_is_not_recorded_ok(self, engine):
        """THE BUG THIS GUARDS. `detect` catches its own exceptions and
        answers with a status string, so the recorder's `except` never
        sees one. Without `call.failed()` every outage in the corpus
        would be a row saying the call succeeded."""
        detector = _detector(engine, [ValueError("Expecting value")])
        result = detector.detect(_article("art-3"))
        assert result.status == "error:ValueError"
        [row] = rows(engine)
        assert row["outcome"] == "error"
        assert row["error_class"] == "ValueError"

    def test_the_detector_still_returns_a_result_when_recording(self, engine):
        """Telemetry must not change the answer. A failed lookup is still
        a DetectionResult with no matches, not an exception."""
        detector = _detector(engine, [ValueError("boom")])
        result = detector.detect(_article("art-4"))
        assert result.story_count == 0
        assert result.matched_story_count == 0

    def test_every_article_is_one_row(self, engine):
        """Three articles, three calls, three rows. The per-article
        column this replaces could not have counted them."""
        detector = _detector(engine, [[], [], []])
        for i in range(3):
            detector.detect(_article(f"art-{i}"))
        assert len(rows(engine)) == 3

    def test_a_detector_with_no_recorder_still_works(self, engine):
        """Optional means optional: an offline run and a unit test have
        no database, and the detector must not require one."""
        from src.services.wire_detection.mediacloud import (
            MediaCloudDetector,
            RateLimiter,
        )

        detector = MediaCloudDetector(
            search_api=_FakeSearchApi([[]]),
            rate_limiter=RateLimiter(60_000),
        )
        assert detector.detect(_article("art-5")).status == "ok"
        assert rows(engine) == []


class TestTheNumbersComeOutRight:
    """What somebody would actually ask the table, over rows the detector
    wrote rather than rows the test inserted."""

    def test_the_call_count_is_the_call_count(self, engine):
        detector = _detector(engine, [[], [], ValueError("x"), [], []])
        for i in range(5):
            detector.detect(_article(f"n-{i}"))
        with engine.begin() as conn:
            total = conn.execute(
                text(
                    "SELECT count(*) FROM external_api_calls "
                    "WHERE service = 'mediacloud'"
                )
            ).scalar()
        assert total == 5

    def test_the_failure_rate_is_readable(self, engine):
        """One failure in five. The corpus could not state this at all --
        `wire_check_status` is overwritten, so a call that failed and was
        retried left no evidence it had ever failed."""
        detector = _detector(engine, [[], [], ValueError("x"), [], []])
        for i in range(5):
            detector.detect(_article(f"f-{i}"))
        with engine.begin() as conn:
            failed = conn.execute(
                text("SELECT count(*) FROM external_api_calls WHERE outcome <> 'ok'")
            ).scalar()
        assert failed == 1

    def test_an_outage_reads_as_a_cluster(self, engine):
        """What the 15 production failures look like: all of them
        together, not spread across the corpus. The query is 'failures
        grouped by error class', and it has to name the class."""
        detector = _detector(
            engine, [ValueError("a"), ValueError("b"), ValueError("c")]
        )
        for i in range(3):
            detector.detect(_article(f"o-{i}"))
        with engine.begin() as conn:
            by_class = dict(
                conn.execute(
                    text(
                        "SELECT error_class, count(*) FROM external_api_calls "
                        "WHERE outcome <> 'ok' GROUP BY error_class"
                    )
                ).all()
            )
        assert by_class == {"ValueError": 3}


# --- the wiring, which is the part that has failed before --------------------


class TestItIsWiredWhereItRuns:
    """A recorder that works and is never constructed records nothing.

    This repository has shipped that exact shape more than once -- code
    correct in isolation, on a path production does not take. Each of
    these asserts the connection rather than the component.
    """

    def _source(self, path):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / path).read_text()

    def test_from_token_passes_the_recorder_through(self):
        """The production constructor goes through `from_token`. It
        taking the argument and dropping it would leave every test
        passing and nothing recorded."""
        import inspect

        from src.services.wire_detection.mediacloud import MediaCloudDetector

        assert (
            "call_recorder"
            in inspect.signature(MediaCloudDetector.from_token).parameters
        )
        body = inspect.getsource(MediaCloudDetector.from_token)
        assert "call_recorder=call_recorder" in body

    def test_the_production_detector_is_given_one(self):
        source = self._source("orchestration/continuous_processor.py")
        block = source[source.index("def get_mediacloud_detector") :]
        block = block[: block.index("\n@dataclass")]
        assert "call_recorder=_call_recorder()" in block

    def test_the_geoid_ladder_carries_it_to_the_census_call(self):
        """The recorder has to reach the one rung that leaves the
        machine. `resolve_geoid` taking it and not passing it down is a
        silent no-op."""
        import inspect

        from src.enrichment.fips import resolve_geoid

        body = inspect.getsource(resolve_geoid)
        assert "call_recorder=call_recorder" in body

    def test_enrichment_supplies_one_to_the_ladder(self):
        source = self._source("src/enrichment/repository.py")
        assert "call_recorder=_call_recorder(session)" in source

    def test_the_census_call_records_its_failures(self):
        """The bare `except Exception: return None` is right for the
        ladder and was wrong for observability: it swallowed every
        outage, timeout and rate limit with no log, no counter and no
        column."""
        import inspect

        from src.enrichment.fips import block_geoid

        body = inspect.getsource(block_geoid)
        assert 'call.failed("error"' in body

    def test_housekeeping_reclaims_stranded_checks(self):
        """A reclaim nothing runs is a reclaim that does not happen."""
        from pathlib import Path

        import yaml

        spec = yaml.safe_load(
            (
                Path(__file__).resolve().parent.parent
                / "k8s/argo/housekeeping-workflow.yaml"
            ).read_text()
        )
        templates = {t["name"] for t in spec["spec"]["templates"]}
        assert "reclaim-wire-checks-step" in templates
        steps = [s[0]["name"] for s in spec["spec"]["templates"][0]["steps"]]
        assert "reclaim-wire-checks" in steps

    def test_the_reclaim_runs_before_the_rework_gate(self):
        """UNGATED, and the order is the reason. `anything-owed` counts
        `pipeline_rework`, and a stranded wire check owes nothing -- no
        review rewound it, so no row names it. Behind that gate it would
        run only on nights that happen to have rework, which is almost
        never."""
        from pathlib import Path

        import yaml

        spec = yaml.safe_load(
            (
                Path(__file__).resolve().parent.parent
                / "k8s/argo/housekeeping-workflow.yaml"
            ).read_text()
        )
        steps = spec["spec"]["templates"][0]["steps"]
        names = [s[0]["name"] for s in steps]
        assert names.index("reclaim-wire-checks") < names.index("anything-owed")
        reclaim = next(s[0] for s in steps if s[0]["name"] == "reclaim-wire-checks")
        assert "when" not in reclaim, "the reclaim is gated on rework being owed"
