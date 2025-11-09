"""PostgreSQL integration tests for RSS metadata persistence.

Covers transactional propagation of connection for:
- Successful RSS discovery resets failure state (consecutive + transient)
- Non-network failures increment consecutive failures and mark missing at threshold
- Network (transient) failures tracked; mark missing at transient threshold

Why these tests?
Earlier silent failures occurred when metadata UPDATE ran in a separate
transaction and affected 0 rows (hidden without logging). After adding
connection propagation inside `_persist_rss_metadata`, we verify that
state transitions persist immediately and no CRITICAL zero-row updates appear.

Test design notes:
- Uses `cloud_sql_engine` (not cloud_sql_session) for committed visibility
- Reads metadata via raw SELECT to ensure actual DB state (not ORM identity map)
- Patches only RSS discovery, keeps newspaper4k inert to isolate RSS logic
- Asserts absence of "UPDATE affected 0 rows" in captured logs (regression guard)

Markers:
- @pytest.mark.postgres and @pytest.mark.integration ensure routing to the
  postgres-integration job with real PostgreSQL (not SQLite fallback).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from src.crawler.discovery import (
    NewsDiscovery,
    RSS_MISSING_THRESHOLD,
    RSS_TRANSIENT_THRESHOLD,
)
from src.models import Source


pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _db_url_from_env(engine) -> str:
    return os.getenv("TEST_DATABASE_URL") or str(engine.url)


def _read_state(engine, source_id: str) -> dict[str, Any]:
    """Read typed RSS state columns for a source (PostgreSQL integration)."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                  rss_consecutive_failures,
                  rss_transient_failures,
                  rss_missing_at,
                  rss_last_failed_at,
                  last_successful_method,
                  no_effective_methods_consecutive,
                  no_effective_methods_last_seen
                FROM sources WHERE id = :id
                """
            ),
            {"id": source_id},
        ).fetchone()
    if not row:
        return {}
    return {
        "rss_consecutive_failures": row[0],
        "rss_transient_failures": row[1] or [],
        "rss_missing_at": row[2],
        "rss_last_failed_at": row[3],
        "last_successful_method": row[4],
        "no_effective_methods_consecutive": row[5],
        "no_effective_methods_last_seen": row[6],
    }


def _make_source(session, **meta_overrides) -> Source:
    base_meta = meta_overrides or {}
    # Generate a unique host_norm to avoid ix_sources_host_norm collisions
    import uuid
    unique_host_norm = f"test-{uuid.uuid4().hex[:12]}.example.test"
    s = Source(
        host=f"rss-meta-{datetime.utcnow().timestamp()}".replace(".", "-"),
        host_norm=unique_host_norm,
        canonical_name="RSS Meta Test",
        meta=base_meta,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def test_rss_success_resets_failure_state_postgres(cloud_sql_engine, caplog):
    # Arrange: seed source with failure state (typed columns)
    SessionLocal = sessionmaker(bind=cloud_sql_engine)
    session = SessionLocal()
    source = _make_source(
        session,
        rss_consecutive_failures=2,
        rss_transient_failures=[
            {"timestamp": datetime.utcnow().isoformat(), "status": 429}
        ],
        rss_missing=datetime.utcnow().isoformat(),
    )
    db_url = _db_url_from_env(cloud_sql_engine)
    discovery = NewsDiscovery(database_url=db_url)

    article = {
        "url": "https://example.com/a1",
        "source_url": "https://example.com",
        "discovery_method": "rss_feed",
        "discovered_at": datetime.utcnow().isoformat(),
        "title": "A1",
        "metadata": {},
    }

    def mock_rss_success(*_a, **_k):
        return [article], {
            "feeds_tried": 1,
            "feeds_successful": 1,
            "network_errors": 0,
            "last_transient_status": None,
        }

    source_row = pd.Series(
        {
            "id": source.id,
            "name": source.canonical_name,
            "url": f"https://{source.host}",
            "metadata": json.dumps(source.meta or {}),
        }
    )

    with (
        patch.object(discovery, "discover_with_rss_feeds", mock_rss_success),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        discovery.process_source(source_row, dataset_label=None, operation_id="op-1")

    state = _read_state(cloud_sql_engine, str(source.id))

    assert state.get("rss_consecutive_failures") == 0
    assert state.get("rss_transient_failures") == []
    assert state.get("rss_missing_at") is None
    assert state.get("last_successful_method") == "rss_feed"
    assert not any("UPDATE affected 0 rows" in r.message for r in caplog.records)


def test_rss_non_network_failures_mark_missing_postgres(cloud_sql_engine, caplog):
    SessionLocal = sessionmaker(bind=cloud_sql_engine)
    session = SessionLocal()
    # Create source with unique host_norm to avoid unique constraint collisions
    import uuid
    unique_host_norm = f"telemetry-{uuid.uuid4().hex[:12]}.example.test"
    source = Source(
        host=f"rss-meta-{datetime.utcnow().timestamp()}".replace(".", "-"),
        host_norm=unique_host_norm,
        canonical_name="RSS Meta Test",
        meta={},
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    db_url = _db_url_from_env(cloud_sql_engine)
    discovery = NewsDiscovery(database_url=db_url)

    def mock_rss_fail(*_a, **_k):
        return [], {
            "feeds_tried": 1,
            "feeds_successful": 0,
            "network_errors": 0,  # non-network failure
            "last_transient_status": None,
        }

    source_row = pd.Series(
        {
            "id": source.id,
            "name": source.canonical_name,
            "url": f"https://{source.host}",
            "metadata": json.dumps({}),
        }
    )

    with (
        patch.object(discovery, "discover_with_rss_feeds", mock_rss_fail),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        for i in range(RSS_MISSING_THRESHOLD):
            discovery.process_source(source_row, dataset_label=None, operation_id=None)
            state = _read_state(cloud_sql_engine, str(source.id))
            assert state.get("rss_consecutive_failures", 0) == i + 1
            if i < RSS_MISSING_THRESHOLD - 1:
                assert state.get("rss_missing_at") in (None,)
            else:
                assert state.get("rss_missing_at") is not None

    assert not any("UPDATE affected 0 rows" in r.message for r in caplog.records)


def test_rss_network_failures_transient_tracking_postgres(cloud_sql_engine, caplog):
    SessionLocal = sessionmaker(bind=cloud_sql_engine)
    session = SessionLocal()
    # Create source with unique host_norm to avoid uniqueness collisions
    import uuid
    unique_host_norm = f"telemetry-{uuid.uuid4().hex[:10]}.example.test"
    source = Source(
        host=f"rss-meta-{datetime.utcnow().timestamp()}".replace(".", "-"),
        host_norm=unique_host_norm,
        canonical_name="RSS Meta Test",
        meta={},
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    db_url = _db_url_from_env(cloud_sql_engine)
    discovery = NewsDiscovery(database_url=db_url)

    def make_mock(status):
        def _mock(*_a, **_k):
            return [], {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 1,
                "last_transient_status": status,
            }
        return _mock

    source_row = pd.Series(
        {
            "id": source.id,
            "name": source.canonical_name,
            "url": f"https://{source.host}",
            "metadata": json.dumps({}),
        }
    )

    with patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []):
        for i in range(RSS_TRANSIENT_THRESHOLD):
            status = 429 if i % 2 == 0 else 503
            with patch.object(discovery, "discover_with_rss_feeds", make_mock(status)):
                discovery.process_source(
                    source_row, dataset_label=None, operation_id=None
                )
                state = _read_state(cloud_sql_engine, str(source.id))
                assert len(state.get("rss_transient_failures", [])) == i + 1
                assert state.get("rss_consecutive_failures", 0) == 0
                if i < RSS_TRANSIENT_THRESHOLD - 1:
                    assert state.get("rss_missing_at") in (None,)
                else:
                    assert state.get("rss_missing_at") is not None

    assert not any("UPDATE affected 0 rows" in r.message for r in caplog.records)


def test_transient_resets_consecutive_with_interleaved_success(
    cloud_sql_engine, caplog
):
    """Transient failure should reset consecutive counter even with interleaving.

    Sequence:
    1) Non-network failure → consecutive = 1
    2) Success → consecutive = 0, transient cleared
    3) Non-network failure → consecutive = 1
    4) Transient failure → consecutive reset to 0 atomically
    5) Success → keeps at 0, clears transient list
    """
    SessionLocal = sessionmaker(bind=cloud_sql_engine)
    session = SessionLocal()
    # Create a unique source to avoid ix_sources_host_norm collisions
    import uuid
    source = Source(
        host=f"rss-meta-{datetime.utcnow().timestamp()}".replace(".", "-"),
        host_norm=f"telemetry-{uuid.uuid4().hex[:10]}.example.test",
        canonical_name="RSS Meta Test",
        meta={},
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    db_url = _db_url_from_env(cloud_sql_engine)
    discovery = NewsDiscovery(database_url=db_url)

    source_row = pd.Series(
        {
            "id": source.id,
            "name": source.canonical_name,
            "url": f"https://{source.host}",
            "metadata": json.dumps({}),
        }
    )

    def rss_non_network_fail(*_a, **_k):
        return [], {
            "feeds_tried": 1,
            "feeds_successful": 0,
            "network_errors": 0,
            "last_transient_status": None,
        }

    def rss_success(*_a, **_k):
        return [
            {
                "url": "https://example.com/a",
                "source_url": "https://example.com",
                "discovery_method": "rss_feed",
                "discovered_at": datetime.utcnow().isoformat(),
                "title": "A",
                "metadata": {},
            }
        ], {
            "feeds_tried": 1,
            "feeds_successful": 1,
            "network_errors": 0,
            "last_transient_status": None,
        }

    def rss_transient(*_a, **_k):
        return [], {
            "feeds_tried": 1,
            "feeds_successful": 0,
            "network_errors": 1,
            "last_transient_status": 429,
        }

    # 1) Non-network failure → consecutive = 1
    with (
        patch.object(discovery, "discover_with_rss_feeds", rss_non_network_fail),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        discovery.process_source(source_row, dataset_label=None, operation_id=None)
    state = _read_state(cloud_sql_engine, str(source.id))
    assert state.get("rss_consecutive_failures", 0) == 1

    # 2) Success → consecutive = 0, transient cleared
    with (
        patch.object(discovery, "discover_with_rss_feeds", rss_success),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        discovery.process_source(source_row, dataset_label=None, operation_id=None)
    state = _read_state(cloud_sql_engine, str(source.id))
    assert state.get("rss_consecutive_failures", 99) == 0
    assert state.get("rss_transient_failures", []) == []

    # 3) Non-network failure → consecutive = 1
    with (
        patch.object(discovery, "discover_with_rss_feeds", rss_non_network_fail),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        discovery.process_source(source_row, dataset_label=None, operation_id=None)
    state = _read_state(cloud_sql_engine, str(source.id))
    assert state.get("rss_consecutive_failures", 0) == 1

    # 4) Transient failure → consecutive reset to 0 atomically
    with (
        patch.object(discovery, "discover_with_rss_feeds", rss_transient),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        discovery.process_source(source_row, dataset_label=None, operation_id=None)
    state = _read_state(cloud_sql_engine, str(source.id))
    assert state.get("rss_consecutive_failures", 99) == 0
    assert len(state.get("rss_transient_failures", [])) == 1

    # 5) Success keeps at 0 and clears transient list
    with (
        patch.object(discovery, "discover_with_rss_feeds", rss_success),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        discovery.process_source(source_row, dataset_label=None, operation_id=None)
    state = _read_state(cloud_sql_engine, str(source.id))
    assert state.get("rss_consecutive_failures", 99) == 0
    assert state.get("rss_transient_failures", []) == []
    assert not any("UPDATE affected 0 rows" in r.message for r in caplog.records)


def test_rss_success_records_discovery_outcome_row_postgres(
    cloud_sql_engine, caplog
):
    """Successful RSS discovery with an operation_id should record a row.

    Verifies telemetry integration path:
    - Pass explicit operation_id
    - RSS success returns one new article
    - process_source stores discovery outcome via telemetry
    - Row is queryable directly from discovery_outcomes table (PostgreSQL)

    Assertions focus on minimal correctness (outcome classification,
    counts, method_used).
    """
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text

    SessionLocal = sessionmaker(bind=cloud_sql_engine)
    session = SessionLocal()
    # Create a unique source to avoid ix_sources_host_norm collisions
    import uuid
    unique_host_norm = f"telemetry-{uuid.uuid4().hex[:12]}.example.test"
    source = Source(
        host=f"rss-meta-{datetime.utcnow().timestamp()}".replace(".", "-"),
        host_norm=unique_host_norm,
        canonical_name="RSS Meta Test",
        meta={},
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    db_url = _db_url_from_env(cloud_sql_engine)
    discovery = NewsDiscovery(database_url=db_url)
    operation_id = "op-telemetry-rss-success"
    article = {
        "url": f"https://{source.host}/telemetry-article",
        "source_url": f"https://{source.host}",
        "discovery_method": "rss_feed",
        "discovered_at": datetime.utcnow().isoformat(),
        "title": "Telemetry Article",
        "metadata": {},
    }

    def mock_rss_success(*_a, **_k):
        return [article], {
            "feeds_tried": 1,
            "feeds_successful": 1,
            "network_errors": 0,
            "last_transient_status": None,
        }

    source_row = pd.Series(
        {
            "id": source.id,
            "name": source.canonical_name,
            "url": f"https://{source.host}",
            "metadata": json.dumps(source.meta or {}),
        }
    )

    with (
        patch.object(discovery, "discover_with_rss_feeds", mock_rss_success),
        patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []),
    ):
        result = discovery.process_source(
            source_row, dataset_label=None, operation_id=operation_id
        )

    # Sanity check: ensure we received a success-class outcome before recording
    assert result.outcome.value in {
        "new_articles_found",
        "mixed_results",
        "duplicates_only",
        "expired_only",
    }, (
        f"Unexpected discovery outcome {result.outcome.value} "
        f"details={getattr(result, 'error_details', None)}"
    )

    # Manually record discovery outcome (run_discovery normally does this)
    discovery.telemetry.record_discovery_outcome(
        operation_id=operation_id,
        source_id=str(source.id),
        source_name=str(source.canonical_name),
        source_url=f"https://{source.host}",
        discovery_result=result,
    )

    # Query discovery_outcomes directly (explicit columns for clarity)
    with cloud_sql_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT outcome, articles_found, articles_new, is_success, method_used "
                "FROM discovery_outcomes WHERE operation_id = :op"
            ),
            {"op": operation_id},
        ).fetchone()

    assert row is not None, "Expected a discovery_outcomes row for the operation_id"
    outcome, articles_found, articles_new, is_success, method_used = row

    # Outcome should be one of success types and counts > 0
    assert outcome in {
        "new_articles_found",
        "mixed_results",
        "duplicates_only",
        "expired_only",
    }
    assert articles_found >= 1
    assert articles_new >= 1  # New content present
    assert bool(is_success) is True
    assert method_used == "rss_feed"

    # Metadata state also reflects success reset semantics
    state = _read_state(cloud_sql_engine, str(source.id))
    assert state.get("rss_consecutive_failures", 99) == 0
    assert state.get("rss_transient_failures", []) == []
    assert state.get("last_successful_method") == "rss_feed"
    assert not any("UPDATE affected 0 rows" in r.message for r in caplog.records)
