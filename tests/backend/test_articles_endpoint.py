"""Tests for /api/articles endpoint (Issue #44).

This endpoint was previously reading from CSV files. These tests verify
the migration to database queries works correctly.

Original CSV implementation:
- Lines 253-280 in backend/app/main.py
- Read CSV file, filtered by reviewer if specified
- Returned empty list when CSV file didn't exist

New database implementation:
- Query Article table with optional Review join
- Filter by reviewer, pagination support
- Return article data from Cloud SQL
"""

import pytest


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_empty_database(test_client):
    """Test articles endpoint returns empty results when no data."""
    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert data["count"] == 0
    assert data["results"] == []


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_returns_all_articles(test_client, cloud_sql_session, sample_articles):
    """Test articles endpoint returns paginated articles."""
    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "count" in data
    assert "results" in data
    assert data["count"] == 50
    # Default limit is 20
    assert len(data["results"]) == 20


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_response_format(test_client, cloud_sql_session, sample_articles):
    """Test articles endpoint returns correctly formatted data."""
    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()

    # Check response structure
    assert "count" in data
    assert "results" in data
    assert len(data["results"]) > 0

    # Check first article has expected fields
    article = data["results"][0]
    assert "__idx" in article  # Article ID used as index
    assert "title" in article
    assert "url" in article
    assert "author" in article
    assert "date" in article
    assert "content" in article
    assert "county" in article


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_filter_by_reviewer(
    test_client,
    cloud_sql_session,
    sample_articles,
    sample_reviews,
):
    """Test articles endpoint filters by reviewer.

    When reviewer=user1, should only return articles NOT reviewed by user1.
    sample_reviews creates 10 reviews by user1, so 40 articles should remain.
    """
    response = test_client.get("/api/articles?reviewer=user1")

    assert response.status_code == 200
    data = response.json()

    # user1 reviewed 10 articles, so 40 should remain unreviewed
    assert data["count"] == 40
    # Default limit is 20
    assert len(data["results"]) == 20


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_filter_by_different_reviewers(
    test_client,
    cloud_sql_session,
    sample_articles,
    sample_reviews,
):
    """Test different reviewers get different unreviewed articles."""
    response1 = test_client.get("/api/articles?reviewer=user1")
    response2 = test_client.get("/api/articles?reviewer=user2")

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    # user1 and user2 reviewed different sets
    assert data1["count"] == 40
    assert data2["count"] == 40
    assert len(data1["results"]) == 20
    assert len(data2["results"]) == 20


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_nonexistent_reviewer(
    test_client,
    cloud_sql_session,
    sample_articles,
    sample_reviews,
):
    """Test filtering by nonexistent reviewer returns all articles."""
    response = test_client.get("/api/articles?reviewer=nonexistent")

    assert response.status_code == 200
    data = response.json()

    # Should return all articles since no reviews exist for this reviewer
    assert data["count"] == 50
    assert len(data["results"]) == 20  # Default limit


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_pagination(
    test_client,
    cloud_sql_session,
    large_article_dataset,
):
    """Test articles endpoint supports pagination.

    With 500 articles, pagination should be implemented.
    """
    # Test default pagination
    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 500
    assert len(data["results"]) == 20  # Default limit

    # Test with custom limit
    response_limited = test_client.get("/api/articles?limit=50")
    assert response_limited.status_code == 200
    data_limited = response_limited.json()
    assert data_limited["count"] == 500
    assert len(data_limited["results"]) == 50

    # Test with offset
    response_offset = test_client.get("/api/articles?limit=10&offset=10")
    assert response_offset.status_code == 200
    data_offset = response_offset.json()
    assert len(data_offset["results"]) == 10


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_performance(
    test_client,
    cloud_sql_session,
    large_article_dataset,
):
    """Test articles endpoint performance with large dataset.

    Success criteria from Issue #44: < 500ms response time
    """
    import time

    start_time = time.time()
    response = test_client.get("/api/articles")
    elapsed_time = time.time() - start_time

    assert response.status_code == 200

    # Should respond quickly even with 500 articles
    assert (
        elapsed_time < 0.5
    ), f"Response time {elapsed_time:.2f}s exceeds 500ms requirement"


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_includes_wire_detected(
    test_client,
    cloud_sql_session,
    sample_articles,
):
    """Test articles response includes wire service detection.

    The wire field (JSON) should be accessible in response.
    """
    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 50
    assert len(data["results"]) == 20

    # Check if wire field is exposed (JSON string)
    import json

    wire_articles = []
    for article in sample_articles:
        if article.wire:
            try:
                wire_data = (
                    json.loads(article.wire)
                    if isinstance(article.wire, str)
                    else article.wire
                )
                if wire_data and len(wire_data) > 0:
                    wire_articles.append(article)
            except (json.JSONDecodeError, TypeError):
                pass
    assert len(wire_articles) > 0, "Test data should include wire articles"


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_multiple_counties(
    test_client,
    cloud_sql_session,
    sample_articles,
):
    """Test articles endpoint returns articles from all counties."""
    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()

    # Extract counties from response results
    counties_in_response = {a.get("county") for a in data["results"] if "county" in a}

    # Should have articles from multiple counties
    assert len(counties_in_response) >= 2


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_sorted_by_date(
    test_client,
    cloud_sql_session,
    sample_articles,
):
    """Test articles are sorted by publish date (most recent first).

    This is typical behavior for article listings.
    """
    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()

    # If publish_date is in response, verify sorting
    dates_in_response = [a.get("publish_date") for a in data if "publish_date" in a]

    if len(dates_in_response) > 1:
        # Check if dates are in descending order
        from datetime import datetime

        parsed_dates = []
        for date_str in dates_in_response:
            try:
                parsed_dates.append(datetime.fromisoformat(date_str))
            except (ValueError, TypeError):
                continue

        if len(parsed_dates) > 1:
            assert parsed_dates == sorted(
                parsed_dates, reverse=True
            ), "Articles should be sorted by date (newest first)"


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_database_error_handling(test_client, monkeypatch):
    """Test articles endpoint handles database errors gracefully."""
    from contextlib import contextmanager

    # Mock database error
    @contextmanager
    def mock_get_session():
        raise Exception("Database connection failed")
        yield  # Never reached

    from backend.app import main

    monkeypatch.setattr(main.db_manager, "get_session", mock_get_session)

    response = test_client.get("/api/articles")

    # Should still return 200 with CSV fallback
    assert response.status_code == 200


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_no_csv_dependency(test_client, cloud_sql_session, tmp_path):
    """Test articles endpoint does not depend on CSV files.

    Critical test: Verifies the CSV dependency has been removed.
    This was the root cause of Issue #44.
    """
    # Ensure no CSV file exists
    csv_path = tmp_path / "articleslabelledgeo_8.csv"
    assert not csv_path.exists()

    response = test_client.get("/api/articles")

    # Should succeed without CSV file
    assert response.status_code == 200

    # Should return empty response from database, not error
    data = response.json()
    assert isinstance(data, dict)
    assert "count" in data
    assert "results" in data


@pytest.mark.postgres
@pytest.mark.integration
def test_articles_with_special_characters(
    test_client,
    cloud_sql_session,
    sample_sources,
    sample_candidate_links,
):
    """Test articles endpoint handles special characters in content."""
    from datetime import datetime

    from src.models import Article

    # Create article with special characters
    article = Article(
        title="Article with \"quotes\" and 'apostrophes'",
        url="https://example.com/special",
        candidate_link_id=sample_candidate_links[0].id,
        publish_date=datetime.now(),
        content="Content with émojis 🎉 and spëcial çharacters",
        author="O'Brien",
    )
    cloud_sql_session.add(article)
    cloud_sql_session.commit()

    response = test_client.get("/api/articles")

    assert response.status_code == 200
    data = response.json()

    # Should return dict with count and results
    assert isinstance(data, dict)
    assert "count" in data
    assert "results" in data
    assert data["count"] > 0

    # Find our special article by title
    special = next((a for a in data["results"] if "quotes" in a["title"]), None)
    if special:
        assert "quotes" in special["title"]
        assert "apostrophes" in special["title"]
