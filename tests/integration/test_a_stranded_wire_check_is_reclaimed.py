"""A wire check that never finished goes back in the queue.

`wire_check_status` is set to `processing` before the call and to a
verdict after it, and nothing sets it back -- so a worker that dies
mid-call strands its article behind a flag describing a run that ended
months ago. Four articles were found in exactly that state on
2026-09-14, attempted 2026-02-09, 02-18, 03-05 and 09-05. The oldest had
been stuck ten months, and it surfaced only because one of the four
happened to be holding an open rework row somebody chased.

`error` is the same failure with a different shape: written when the
lookup raises, never retried, so a transient outage is permanent. All 15
in the corpus fall in two windows -- one December evening, one March day
-- which is MediaCloud being down, not 15 bad articles.

POSTGRES, NOT SQLITE. The reclaim turns on `now() - interval` and on
reading an integer out of a `json` column, and sqlite has neither. A
version of this that passed on sqlite would be testing a different query
than the one that runs.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = bool(POSTGRES_TEST_URL)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

#: Every row this file makes. The database is shared with every other
#: integration test in the run, so the rows are named and only the named
#: ones are removed.
#:
#: THE FIRST VERSION DROPPED `articles` AND REBUILT IT as a five-column
#: stub. That is not a fixture, it is a schema change: twenty tests in
#: other files failed on `column a.enrichment_attempts does not exist`,
#: and the cause sat three files away from every one of those failures.
#: Never DDL a shared table in a test -- put rows into the real one and
#: take them back out.
PREFIX = "reclaim-test-"


@pytest.fixture
def engine():
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured (set TEST_DATABASE_URL)")
    engine = create_engine(POSTGRES_TEST_URL)
    _clean(engine)
    yield engine
    _clean(engine)


def _clean(engine):
    # Articles first: the foreign key points that way.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM articles WHERE id LIKE :p"), {"p": f"{PREFIX}%"})
        conn.execute(
            text("DELETE FROM candidate_links WHERE id LIKE :p"), {"p": f"{PREFIX}%"}
        )


def _article(engine, article_id, status, *, hours_ago=None, reclaims=None):
    """One row in the REAL `articles` table.

    `candidate_link_id`, `status`, `created_at` and `extracted_at` are
    NOT NULL with no default, so they are supplied. The reclaim does not
    read them; the table does.
    """
    attempted = "NULL" if hours_ago is None else f"now() - interval '{hours_ago} hours'"
    meta = "NULL" if reclaims is None else f"""'{{"reclaims": {reclaims}}}'"""
    with engine.begin() as conn:
        # `articles.candidate_link_id` is a real foreign key, so the link
        # comes first. `candidate_links` has no foreign keys of its own,
        # so this is the whole parent chain.
        conn.execute(
            text("""
                INSERT INTO candidate_links
                    (id, url, source, discovered_at, status)
                VALUES (:id, :url, 'reclaim-test', now(), 'extracted')
                """),
            {"id": PREFIX + article_id, "url": f"https://example.com/{article_id}"},
        )
        conn.execute(
            text(f"""
                INSERT INTO articles
                    (id, candidate_link_id, status, created_at, extracted_at,
                     wire_check_status, wire_check_attempted_at,
                     wire_check_error, wire_check_metadata)
                VALUES (:id, :id, 'labeled', now(), now(),
                        :wcs, {attempted}, 'error:Whatever',
                        CAST({meta} AS json))
                """),
            {"id": PREFIX + article_id, "wcs": status},
        )


def _status(engine, article_id):
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT wire_check_status FROM articles WHERE id = :id"),
            {"id": PREFIX + article_id},
        ).scalar()


def _reclaims(engine, article_id):
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT CAST(wire_check_metadata::json->>'reclaims' AS integer) "
                "FROM articles WHERE id = :id"
            ),
            {"id": PREFIX + article_id},
        ).scalar()


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestWhatGetsReclaimed:
    def test_a_long_stranded_processing_row_goes_back_to_pending(self, engine):
        """The four found in production. Ten months at `processing`."""
        from src.services.wire_detection.reclaim import reclaim_stranded

        _article(engine, "stuck", "processing", hours_ago=7000)
        moved = reclaim_stranded(engine)
        assert moved["processing"] == 1
        assert _status(engine, "stuck") == "pending"

    def test_an_error_row_is_retried(self, engine):
        """A transient outage must not be permanent. 15 articles left the
        pipeline for good over two bad days on somebody else's service."""
        from src.services.wire_detection.reclaim import reclaim_stranded

        _article(engine, "errored", "error", hours_ago=7000)
        moved = reclaim_stranded(engine)
        assert moved["error"] == 1
        assert _status(engine, "errored") == "pending"

    def test_the_stale_error_string_does_not_survive(self, engine):
        """A row at `pending` still carrying `error:JSONDecodeError`
        reads as one that both failed and is waiting."""
        from src.services.wire_detection.reclaim import reclaim_stranded

        _article(engine, "e2", "error", hours_ago=7000)
        reclaim_stranded(engine)
        with engine.begin() as conn:
            assert (
                conn.execute(
                    text("SELECT wire_check_error FROM articles WHERE id = 'e2'")
                ).scalar()
                is None
            )

    def test_a_row_with_no_attempt_time_is_reclaimed(self, engine):
        """`processing` with a null timestamp cannot be aged out on time,
        and leaving it is the exact bug -- stranded forever."""
        from src.services.wire_detection.reclaim import reclaim_stranded

        _article(engine, "notime", "processing", hours_ago=None)
        reclaim_stranded(engine)
        assert _status(engine, "notime") == "pending"


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestWhatIsLeftAlone:
    def test_a_check_still_in_flight_is_not_touched(self, engine):
        """RECLAIMING A LIVE CALL MAKES A SECOND REQUEST to somebody
        else's service, which is the opposite of the point. One hour is
        generous against a checker whose limiter allows 30 seconds
        between calls."""
        from src.services.wire_detection.reclaim import reclaim_stranded

        _article(engine, "inflight", "processing", hours_ago=0)
        moved = reclaim_stranded(engine)
        assert moved["processing"] == 0
        assert _status(engine, "inflight") == "processing"

    def test_a_finished_check_is_not_touched(self, engine):
        from src.services.wire_detection.reclaim import reclaim_stranded

        for status in ("complete", "wire", "local", "pending"):
            _article(engine, status, status, hours_ago=7000)
        reclaim_stranded(engine)
        for status in ("complete", "wire", "local", "pending"):
            assert _status(engine, status) == status

    def test_it_stops_after_the_bound(self, engine):
        """An article that fails every time is telling us about the
        article. Cycling it forever is its own impoliteness."""
        from src.services.wire_detection.reclaim import MAX_RECLAIMS, reclaim_stranded

        _article(engine, "hopeless", "error", hours_ago=7000, reclaims=MAX_RECLAIMS)
        moved = reclaim_stranded(engine)
        assert moved["error"] == 0
        assert _status(engine, "hopeless") == "error"

    def test_the_count_survives_the_reclaim(self, engine):
        """THE BOUND IS ONLY A BOUND IF IT PERSISTS. Writing fresh
        metadata on every pass would reset the count to zero and the
        article would cycle forever -- which is how the flag got stuck in
        the first place, by nobody keeping track."""
        from src.services.wire_detection.reclaim import reclaim_stranded

        _article(engine, "counted", "error", hours_ago=7000, reclaims=1)
        reclaim_stranded(engine)
        assert _reclaims(engine, "counted") == 2


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestWhatItReports:
    def test_the_two_causes_are_counted_apart(self, engine):
        """400 reclaimed `error` rows is an outage; 400 reclaimed
        `processing` rows is workers dying. One number would hide which."""
        from src.services.wire_detection.reclaim import reclaim_stranded

        _article(engine, "p1", "processing", hours_ago=7000)
        _article(engine, "p2", "processing", hours_ago=7000)
        _article(engine, "e1", "error", hours_ago=7000)
        assert reclaim_stranded(engine) == {"processing": 2, "error": 1}

    def test_nothing_to_do_reports_zero(self, engine):
        from src.services.wire_detection.reclaim import reclaim_stranded

        assert reclaim_stranded(engine) == {"processing": 0, "error": 0}
