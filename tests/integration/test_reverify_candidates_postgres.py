"""Integration tests for backlog re-verification against PostgreSQL.

Exercises get_reverify_candidates / reverify_candidates / release_paused
end-to-end against real candidate_links rows: junk that slipped into
status='article' under old rules gets demoted, good rows stay untouched,
and paused rows can be released back through the verification funnel.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.models import CandidateLink, Source

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


@pytest.fixture
def reverify_source(cloud_sql_session):
    source = Source(
        id=str(uuid.uuid4()),
        host="test-reverify.example.com",
        host_norm="test-reverify.example.com",
        canonical_name="Test Reverify Source",
    )
    cloud_sql_session.add(source)
    cloud_sql_session.commit()
    cloud_sql_session.refresh(source)
    return source


def _add_candidate(session, source, url, status):
    candidate = CandidateLink(
        id=str(uuid.uuid4()),
        url=url,
        source=source.canonical_name,
        source_host_id=source.id,
        crawl_depth=0,
        status=status,
        discovered_at=datetime.now(timezone.utc),
        discovered_by="test_reverify",
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


@pytest.fixture
def reverify_service(cloud_sql_session, monkeypatch):
    # The cloud_sql_session fixture keeps everything inside ONE
    # connection-level transaction that is rolled back at teardown -- a
    # fresh engine.connect() in the service would get a separate
    # connection that can't see any fixture data. Shim engine.connect()
    # to hand back the fixture's own connection, with commit() a no-op so
    # the service can't accidentally commit the outer test transaction.
    class _ConnShim:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            return self._conn.execute(*args, **kwargs)

        def commit(self):
            pass

    class _EngineShim:
        def __init__(self, conn):
            self._conn = conn

        def connect(self):
            return _ConnShim(self._conn)

    class _PatchedDatabaseManager:
        def __init__(self):
            self.engine = _EngineShim(cloud_sql_session.get_bind())

        def get_session(self):
            from contextlib import contextmanager

            @contextmanager
            def _session_context():
                yield cloud_sql_session

            return _session_context()

    monkeypatch.setattr(
        "src.services.url_verification.DatabaseManager",
        lambda *_, **__: _PatchedDatabaseManager(),
    )

    class _FakeTelemetry:
        def record_verification_batch(self, *args, **kwargs):
            return None

    from src.services.url_verification import URLVerificationService

    service = URLVerificationService(
        run_http_precheck=False, telemetry_tracker=_FakeTelemetry()
    )
    service._pattern_cache = None
    service._pattern_cache_expiry = 0
    return service


def _status_of(session, candidate_id):
    return session.execute(
        text("SELECT status FROM candidate_links WHERE id = :id"),
        {"id": candidate_id},
    ).scalar()


class TestReverifyPostgres:
    def test_asset_url_in_article_backlog_gets_demoted(
        self, cloud_sql_session, reverify_source, reverify_service
    ):
        """A favicon that old rules let through gets caught by the current
        asset-extension filter and demoted from 'article'."""
        junk = _add_candidate(
            cloud_sql_session,
            reverify_source,
            "https://test-reverify.example.com/wp-content/favicon-16x16.png",
            "article",
        )

        candidates = reverify_service.get_reverify_candidates(
            status="article", host="test-reverify.example.com"
        )
        assert any(c["id"] == junk.id for c in candidates)

        metrics = reverify_service.reverify_candidates(
            [c for c in candidates if c["id"] == junk.id]
        )

        assert metrics["reclassified"].get("not_article") == 1
        cloud_sql_session.expire_all()
        assert _status_of(cloud_sql_session, junk.id) == "not_article"

    def test_genuine_article_stays_article(
        self, cloud_sql_session, reverify_source, reverify_service, monkeypatch
    ):
        keeper = _add_candidate(
            cloud_sql_session,
            reverify_source,
            "https://test-reverify.example.com/news/city-council-votes",
            "article",
        )
        monkeypatch.setattr(reverify_service.sniffer, "guess", lambda _: True)

        candidates = reverify_service.get_reverify_candidates(
            status="article", host="test-reverify.example.com"
        )
        metrics = reverify_service.reverify_candidates(
            [c for c in candidates if c["id"] == keeper.id]
        )

        assert metrics["kept"] == 1
        cloud_sql_session.expire_all()
        assert _status_of(cloud_sql_session, keeper.id) == "article"

    def test_dry_run_leaves_rows_untouched(
        self, cloud_sql_session, reverify_source, reverify_service
    ):
        junk = _add_candidate(
            cloud_sql_session,
            reverify_source,
            "https://test-reverify.example.com/assets/logo.jpg",
            "article",
        )

        candidates = reverify_service.get_reverify_candidates(
            status="article", host="test-reverify.example.com"
        )
        metrics = reverify_service.reverify_candidates(
            [c for c in candidates if c["id"] == junk.id], dry_run=True
        )

        assert metrics["reclassified"].get("not_article") == 1
        cloud_sql_session.expire_all()
        assert _status_of(cloud_sql_session, junk.id) == "article"

    def test_release_paused_moves_to_discovered(
        self, cloud_sql_session, reverify_source, reverify_service
    ):
        paused = _add_candidate(
            cloud_sql_session,
            reverify_source,
            "https://test-reverify.example.com/paused-story",
            "paused",
        )

        count = reverify_service.release_paused(host="test-reverify.example.com")

        assert count >= 1
        cloud_sql_session.expire_all()
        assert _status_of(cloud_sql_session, paused.id) == "discovered"

    def test_release_paused_dry_run_counts_only(
        self, cloud_sql_session, reverify_source, reverify_service
    ):
        paused = _add_candidate(
            cloud_sql_session,
            reverify_source,
            "https://test-reverify.example.com/paused-story-2",
            "paused",
        )

        count = reverify_service.release_paused(
            host="test-reverify.example.com", dry_run=True
        )

        assert count >= 1
        cloud_sql_session.expire_all()
        assert _status_of(cloud_sql_session, paused.id) == "paused"
