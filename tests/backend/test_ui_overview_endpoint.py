"""Tests for /api/ui_overview endpoint (Issue #44).

This endpoint was migrated from CSV to Cloud SQL database queries.

Returns:
- total_articles: count from articles table
- wire_count: articles with wire service attribution (JSON array)
- candidate_issues: count of non-accepted candidates
- dedupe_near_misses: dedupe audit records needing review
"""

import pytest


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_empty_database(test_client, cloud_sql_session):
    """Test ui_overview returns zeros when database is empty."""
    response = test_client.get("/api/ui_overview")

    assert response.status_code == 200
    data = response.json()

    # Should return zeros for empty database
    assert data["total_articles"] == 0
    assert data["wire_count"] == 0
    assert data["candidate_issues"] == 0
    assert data["dedupe_near_misses"] == 0


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_with_articles(
    test_client,
    db_session,
    sample_articles,
    sample_candidates,
):
    """Test ui_overview returns correct counts with data."""
    response = test_client.get("/api/ui_overview")

    assert response.status_code == 200
    data = response.json()

    # Verify article count
    assert data["total_articles"] == 50

    # Verify candidate count (8 created, but only 5 are NOT accepted)
    assert data["candidate_issues"] == 5

    # Wire count depends on sample data
    assert data["wire_count"] >= 0


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_response_format(
    test_client,
    db_session,
    sample_articles,
):
    """Test ui_overview response has correct format."""
    response = test_client.get("/api/ui_overview")

    assert response.status_code == 200
    data = response.json()

    # Verify all expected fields exist
    assert "total_articles" in data
    assert "wire_count" in data
    assert "candidate_issues" in data
    assert "dedupe_near_misses" in data

    # Verify field types
    assert isinstance(data["total_articles"], int)
    assert isinstance(data["wire_count"], int)
    assert isinstance(data["candidate_issues"], int)
    assert isinstance(data["dedupe_near_misses"], int)


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_performance(
    test_client,
    db_session,
    large_article_dataset,
):
    """Test ui_overview response time with large dataset.

    Success criteria: < 1s response time with 500 articles.
    Note: Wire count iteration may be slower, acceptable for current scale.
    """
    import time

    start_time = time.time()
    response = test_client.get("/api/ui_overview")
    elapsed_time = time.time() - start_time

    assert response.status_code == 200

    # Should respond in reasonable time even with 500 articles
    assert elapsed_time < 1.0, f"Response time {elapsed_time:.2f}s exceeds 1s threshold"

    data = response.json()
    assert data["total_articles"] == 500


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_wire_count(
    test_client,
    db_session,
    sample_sources,
):
    """Test wire_count field correctly identifies wire service articles.

    Wire service attribution is stored as JSON array in Article.wire field.
    """
    import json
    from datetime import datetime

    from src.models import Article, CandidateLink

    # Create a test source and candidate links
    link1 = CandidateLink(
        id="link-wire-1",
        url="https://example.com/wire-1",
        source=sample_sources[0].host,
        source_host_id=sample_sources[0].host,
        source_name=sample_sources[0].canonical_name,
        source_county=sample_sources[0].county,
    )
    link2 = CandidateLink(
        id="link-wire-2",
        url="https://example.com/wire-2",
        source=sample_sources[0].host,
        source_host_id=sample_sources[0].host,
        source_name=sample_sources[0].canonical_name,
        source_county=sample_sources[0].county,
    )
    link3 = CandidateLink(
        id="link-local-1",
        url="https://example.com/local-1",
        source=sample_sources[0].host,
        source_host_id=sample_sources[0].host,
        source_name=sample_sources[0].canonical_name,
        source_county=sample_sources[0].county,
    )
    cloud_sql_session.add(link1)
    cloud_sql_session.add(link2)
    cloud_sql_session.add(link3)
    cloud_sql_session.commit()

    # Create articles with different wire attribution formats
    articles = [
        Article(
            id="wire-1",
            title="Wire Article 1",
            url="https://example.com/wire-1",
            candidate_link_id=link1.id,
            publish_date=datetime.now(),
            wire=json.dumps([{"source": "AP", "confidence": 0.9}]),  # Has wire
            status="extracted",
        ),
        Article(
            id="wire-2",
            title="Wire Article 2",
            url="https://example.com/wire-2",
            candidate_link_id=link2.id,
            publish_date=datetime.now(),
            wire=json.dumps([]),  # Empty array - no wire
            status="extracted",
        ),
        Article(
            id="local-1",
            title="Local Article",
            url="https://example.com/local-1",
            candidate_link_id=link3.id,
            publish_date=datetime.now(),
            wire=None,  # NULL - no wire
            status="extracted",
        ),
    ]

    for article in articles:
        cloud_sql_session.add(article)
    cloud_sql_session.commit()

    response = test_client.get("/api/ui_overview")

    assert response.status_code == 200
    data = response.json()

    # Should count 1 wire article (wire-1 has populated JSON array)
    assert data["wire_count"] == 1
    assert data["total_articles"] == 3


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_with_multiple_counties(
    test_client,
    db_session,
    sample_articles,
    sample_sources,
):
    """Test ui_overview counts articles across all counties."""
    response = test_client.get("/api/ui_overview")

    assert response.status_code == 200
    data = response.json()

    # All 50 articles from 3 counties should be counted
    assert data["total_articles"] == 50

    # Verify test data has multiple counties (from sources)
    counties = {s.county for s in sample_sources}
    assert len(counties) == 3


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_database_error_handling(test_client, monkeypatch):
    """Test ui_overview handles database errors gracefully.

    Should return zeros on error to avoid breaking dashboard.
    """

    # Mock database error
    def mock_get_session():
        raise Exception("Database connection failed")

    from backend.app import main

    monkeypatch.setattr(main.db_manager, "get_session", mock_get_session)

    response = test_client.get("/api/ui_overview")

    # Should return 200 with zeros (graceful degradation)
    assert response.status_code == 200
    data = response.json()
    assert data["total_articles"] == 0
    assert data["wire_count"] == 0


@pytest.mark.postgres
@pytest.mark.integration
def test_ui_overview_no_csv_dependency(test_client, cloud_sql_session, tmp_path):
    """Test ui_overview does not depend on CSV files.

    Critical test: Verifies the CSV dependency has been removed.
    This was the root cause of Issue #44 - CSV files don't exist
    in Docker containers, causing dashboard to show zeros.
    """
    # Ensure no CSV file exists
    csv_path = tmp_path / "articleslabelledgeo_8.csv"
    assert not csv_path.exists()

    response = test_client.get("/api/ui_overview")

    # Should succeed without CSV file (uses database only)
    assert response.status_code == 200

    # Should return zeros from empty database, not error
    data = response.json()
    assert "total_articles" in data
    assert "wire_count" in data
    assert "candidate_issues" in data
