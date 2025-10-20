from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base
from src.models.api_backend import Candidate, DedupeAudit, Snapshot


@pytest.fixture()
def dashboard_fixture(tmp_path: Path):
    """Create test database with SQLAlchemy models (simulating Cloud SQL)."""
    db_path = tmp_path / "test_dashboard.db"
    csv_path = tmp_path / "articles.csv"

    # Create engine and session using SQLAlchemy (like Cloud SQL)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    # Create all tables using SQLAlchemy models
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Insert test data using ORM models (not raw SQL!)
    now = datetime.utcnow()

    # Create snapshots
    snapshots = [
        Snapshot(
            id="snap-1",
            host="broken.local",
            url="https://broken.local/article1",
            status="pending",
            reviewed_at=None,
        ),
        Snapshot(
            id="snap-2",
            host="broken.local",
            url="https://broken.local/article2",
            status="pending",
            reviewed_at=None,
        ),
        Snapshot(
            id="snap-3",
            host="healthy.local",
            url="https://healthy.local/article1",
            status="completed",
            reviewed_at=now,
        ),
    ]
    session.add_all(snapshots)

    # Create candidate_links (needed for articles)
    import json

    from src.models import Article, CandidateLink

    candidate_links = [
        CandidateLink(
            id="link-1",
            url="https://broken.local/article1",
            source="broken.local",
            discovered_at=now,
            status="fetched",
        ),
        CandidateLink(
            id="link-2",
            url="https://broken.local/article2",
            source="broken.local",
            discovered_at=now,
            status="fetched",
        ),
    ]
    session.add_all(candidate_links)

    # Create articles (2 total, 1 with wire attribution)
    articles = [
        Article(
            id="art-1",
            candidate_link_id="link-1",
            url="https://broken.local/article1",
            title="Article with Wire",
            status="extracted",
            wire=json.dumps([{"name": "Associated Press", "score": 0.95}]),
            extracted_at=now,
            created_at=now,
        ),
        Article(
            id="art-2",
            candidate_link_id="link-2",
            url="https://broken.local/article2",
            title="Regular Article",
            status="extracted",
            wire=None,
            extracted_at=now,
            created_at=now,
        ),
    ]
    session.add_all(articles)

    # Create candidates (2 with accepted=False for the test)
    candidates = [
        Candidate(
            id="cand-1",
            snapshot_id="snap-1",
            selector="meta.title",
            field="title",
            score=0.2,
            words=120,
            accepted=False,  # Not accepted = candidate issue
            created_at=now,
        ),
        Candidate(
            id="cand-2",
            snapshot_id="snap-1",
            selector="meta.description",
            field="description",
            score=0.8,
            words=200,
            accepted=False,  # Not accepted = candidate issue
            created_at=now,
        ),
        Candidate(
            id="cand-3",
            snapshot_id="snap-2",
            selector="meta.author",
            field="author",
            score=0.5,
            words=80,
            accepted=True,  # Accepted = not an issue
            created_at=now,
        ),
    ]
    session.add_all(candidates)

    # Create dedupe audit records (1 with similarity > 0.7 and dedupe_flag=0)
    dedupe_records = [
        DedupeAudit(
            article_uid="art-1",
            neighbor_uid="art-dup",
            host="broken.local",
            similarity=0.91,  # > 0.7 and dedupe_flag is None/0 = near miss
            dedupe_flag=None,
            created_at=now,
        ),
        DedupeAudit(
            article_uid="art-2",
            neighbor_uid="art-dup2",
            host="healthy.local",
            similarity=0.65,  # < 0.7 = not a near miss
            dedupe_flag=True,
            created_at=now,
        ),
    ]
    session.add_all(dedupe_records)

    # Add HTTP error summary data for test_http_errors_surface_verification_outages
    from datetime import timedelta

    from src.models.telemetry import HttpErrorSummary

    http_errors = [
        HttpErrorSummary(
            host="verification.local",
            status_code=429,
            error_type="4xx_client_error",
            count=2,
            first_seen=now - timedelta(hours=2),
            last_seen=now,
        ),
        HttpErrorSummary(
            host="broken.local",
            status_code=503,
            error_type="5xx_server_error",
            count=1,
            first_seen=now - timedelta(hours=1),
            last_seen=now,
        ),
    ]
    session.add_all(http_errors)

    session.commit()
    session.close()

    # Create test CSV with wire data
    csv_path.write_text("wire\n1\n0\n", encoding="utf-8")

    class Fixture:
        def __init__(self):
            self.db_path = db_path
            self.csv_path = csv_path
            self.engine = engine

    fixture = Fixture()
    yield fixture

    engine.dispose()


def _patch_dashboard_paths(monkeypatch: pytest.MonkeyPatch, fixture) -> None:
    from unittest.mock import MagicMock

    from backend.app import main as app_main

    # Patch ARTICLES_CSV for CSV-based operations
    monkeypatch.setattr(app_main, "ARTICLES_CSV", fixture.csv_path)

    # Create sessionmaker from the test database engine
    SessionLocal = sessionmaker(bind=fixture.engine)

    # Mock DatabaseManager.get_session to return a session from the test database
    def mock_get_session():
        @contextmanager
        def session_context():
            session = SessionLocal()
            try:
                yield session
            finally:
                session.close()

        return session_context()

    # Create a mock db_manager with our custom get_session
    mock_db_manager = MagicMock()
    mock_db_manager.get_session = mock_get_session

    # Replace the entire db_manager instance
    monkeypatch.setattr(app_main, "db_manager", mock_db_manager)


def test_ui_overview_highlights_dashboard_failures(
    dashboard_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import main as app_main

    _patch_dashboard_paths(monkeypatch, dashboard_fixture)

    result = app_main.ui_overview()

    assert result["total_articles"] == 2
    assert result["wire_count"] == 1
    assert result["candidate_issues"] == 2
    assert result["dedupe_near_misses"] == 1


def test_http_errors_surface_verification_outages(
    dashboard_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import main as app_main

    _patch_dashboard_paths(monkeypatch, dashboard_fixture)

    payload = app_main.get_http_errors(days=7, status_code=429)
    errors = payload["http_errors"]

    verification_rows = [row for row in errors if row["host"] == "verification.local"]
    assert verification_rows, "expected verification.local to appear in outage alerts"
    assert verification_rows[0]["error_count"] == 2


def test_domain_issues_group_by_host(
    dashboard_fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app import main as app_main

    _patch_dashboard_paths(monkeypatch, dashboard_fixture)

    issues = app_main.get_domain_issues()

    assert set(issues) == {"broken.local"}
    broken = issues["broken.local"]
    assert broken["total_urls"] == 2
    assert broken["issues"] == {"title": 1, "description": 1}
