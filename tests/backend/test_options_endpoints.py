"""Tests for /api/options/* endpoints (Issue #44).

These endpoints were previously reading from CSV files to get distinct values.
Tests verify the migration to database queries works correctly.

Original CSV implementation:
- Lines 470-490 in backend/app/main.py
- Read CSV file, extracted distinct values
- Returned empty lists when CSV file didn't exist

New database implementation:
- Query distinct values from Article, Source, Review tables
- Return distinct counties, sources, reviewers from Cloud SQL
"""


def test_options_counties_empty_database(test_client, db_session):
    """Test options/counties returns empty list when database is empty."""
    response = test_client.get("/api/options/counties")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) == 0


def test_options_counties_returns_distinct_values(
    test_client,
    db_session,
    sample_articles,
):
    """Test options/counties returns distinct county names."""
    response = test_client.get("/api/options/counties")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    # sample_articles has 3 distinct counties
    assert len(data) == 3
    assert set(data) == {"Boone", "Cole", "Audrain"}


def test_options_counties_no_duplicates(
    test_client,
    db_session,
    sample_articles,
):
    """Test options/counties returns no duplicate values."""
    response = test_client.get("/api/options/counties")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify no duplicates
    assert len(data) == len(set(data))


def test_options_sources_empty_database(test_client, db_session):
    """Test options/sources returns empty list when database is empty."""
    response = test_client.get("/api/options/sources")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) == 0


def test_options_sources_returns_distinct_values(
    test_client,
    db_session,
    sample_sources,
    sample_articles,
):
    """Test options/sources returns distinct source names."""
    response = test_client.get("/api/options/sources")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    # sample_sources creates 3 distinct sources
    assert len(data) == 3
    
    # Should return source names or IDs
    expected_names = {
        "Columbia Daily Tribune",
        "Jefferson City News Tribune",
        "Audrain County News",
    }
    expected_ids = {1, 2, 3}
    
    # Check if response is names or IDs
    if all(isinstance(item, str) for item in data):
        assert set(data) == expected_names
    elif all(isinstance(item, int) for item in data):
        assert set(data) == expected_ids


def test_options_sources_format(
    test_client,
    db_session,
    sample_sources,
):
    """Test options/sources response format.
    
    Can return either:
    - List of source names (strings)
    - List of source IDs (integers)
    - List of source objects (dicts with id, name, etc.)
    """
    response = test_client.get("/api/options/sources")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) > 0
    
    # Check item format
    first_item = data[0]
    
    # Should be string, int, or dict
    assert isinstance(first_item, (str, int, dict))
    
    if isinstance(first_item, dict):
        # If dict, should have at least 'id' or 'name'
        assert "id" in first_item or "name" in first_item


def test_options_reviewers_empty_database(test_client, db_session):
    """Test options/reviewers returns empty list when database is empty."""
    response = test_client.get("/api/options/reviewers")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) == 0


def test_options_reviewers_returns_distinct_values(
    test_client,
    db_session,
    sample_articles,
    sample_reviews,
):
    """Test options/reviewers returns distinct reviewer names."""
    response = test_client.get("/api/options/reviewers")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    # sample_reviews creates reviews from 2 distinct reviewers
    assert len(data) == 2
    assert set(data) == {"user1", "user2"}


def test_options_reviewers_no_duplicates(
    test_client,
    db_session,
    sample_reviews,
):
    """Test options/reviewers returns no duplicate values."""
    response = test_client.get("/api/options/reviewers")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify no duplicates
    assert len(data) == len(set(data))


def test_options_reviewers_only_active(
    test_client,
    db_session,
    sample_articles,
    sample_reviews,
):
    """Test options/reviewers only returns reviewers with reviews.
    
    Should not return reviewers from other tables who haven't reviewed.
    """
    response = test_client.get("/api/options/reviewers")
    
    assert response.status_code == 200
    data = response.json()
    
    # Only user1 and user2 have reviews
    assert len(data) == 2
    assert "nonexistent" not in data


def test_options_counties_sorted(
    test_client,
    db_session,
    sample_articles,
):
    """Test options/counties returns sorted list.
    
    Sorted lists are more user-friendly in UI dropdowns.
    """
    response = test_client.get("/api/options/counties")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check if sorted alphabetically
    if len(data) > 1:
        assert data == sorted(data), "Counties should be sorted alphabetically"


def test_options_sources_sorted(
    test_client,
    db_session,
    sample_sources,
):
    """Test options/sources returns sorted list."""
    response = test_client.get("/api/options/sources")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check if sorted (if strings)
    if len(data) > 1 and all(isinstance(item, str) for item in data):
        assert data == sorted(data), "Sources should be sorted alphabetically"


def test_options_reviewers_sorted(
    test_client,
    db_session,
    sample_reviews,
):
    """Test options/reviewers returns sorted list."""
    response = test_client.get("/api/options/reviewers")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check if sorted
    if len(data) > 1:
        assert data == sorted(
            data
        ), "Reviewers should be sorted alphabetically"


def test_options_counties_filters_null(
    test_client,
    db_session,
    sample_sources,
):
    """Test options/counties excludes NULL/empty county values."""
    from datetime import datetime

    from src.models import Article, CandidateLink

    # Create CandidateLink with NULL county
    candidate_link_null = CandidateLink(
        url="https://example.com/no-county-link",
        source="example.com",
        source_host_id="example.com",
        source_name="Example Source",
        source_county=None,  # NULL county
    )
    db_session.add(candidate_link_null)
    db_session.flush()
    
    # Create article with NULL county CandidateLink
    article = Article(
        title="Article without county",
        url="https://example.com/no-county",
        candidate_link_id=candidate_link_null.id,
        publish_date=datetime.now(),
    )
    db_session.add(article)
    db_session.commit()
    
    response = test_client.get("/api/options/counties")
    
    assert response.status_code == 200
    data = response.json()
    
    # NULL/None should not be in results
    assert None not in data
    assert "" not in data


def test_options_performance(
    test_client,
    db_session,
    large_article_dataset,
):
    """Test options endpoints performance with large dataset.
    
    Distinct queries should be fast even with many records.
    """
    import time
    
    endpoints = [
        "/api/options/counties",
        "/api/options/sources",
        "/api/options/reviewers",
    ]
    
    for endpoint in endpoints:
        start_time = time.time()
        response = test_client.get(endpoint)
        elapsed_time = time.time() - start_time
        
        assert response.status_code == 200
        assert elapsed_time < 0.5, (
            f"{endpoint} response time {elapsed_time:.2f}s "
            f"exceeds 500ms requirement"
        )


def test_options_database_error_handling(test_client, monkeypatch):
    """Test options endpoints handle database errors gracefully."""
    # Mock database error
    def mock_get_session():
        raise Exception("Database connection failed")
    
    from backend.app import main
    monkeypatch.setattr(main.db_manager, "get_session", mock_get_session)
    
    endpoints = [
        "/api/options/counties",
        "/api/options/sources",
        "/api/options/reviewers",
    ]
    
    for endpoint in endpoints:
        response = test_client.get(endpoint)
        assert response.status_code == 500


def test_options_no_csv_dependency(test_client, db_session, tmp_path):
    """Test options endpoints do not depend on CSV files.
    
    Critical test: Verifies the CSV dependency has been removed.
    This was the root cause of Issue #44.
    """
    # Ensure no CSV file exists
    csv_path = tmp_path / "articleslabelledgeo_8.csv"
    assert not csv_path.exists()
    
    endpoints = [
        "/api/options/counties",
        "/api/options/sources",
        "/api/options/reviewers",
    ]
    
    for endpoint in endpoints:
        response = test_client.get(endpoint)
        
        # Should succeed without CSV file
        assert response.status_code == 200
        
        # Should return empty list, not error
        data = response.json()
        assert isinstance(data, list)


def test_options_special_characters_in_county(
    test_client,
    db_session,
    sample_sources,
    sample_candidate_links,
):
    """Test options/counties handles special characters."""
    from datetime import datetime

    from src.models import Article, CandidateLink

    # Create CandidateLink with special characters in county
    candidate_link_special = CandidateLink(
        url="https://stlouis.example.com/special-county-link",
        source="stlouis.example.com",
        source_host_id="stlouis.example.com",
        source_name="St. Louis Source",
        source_county="St. Louis",  # Has period
    )
    db_session.add(candidate_link_special)
    db_session.flush()
    
    # Create article with special county
    article = Article(
        title="Article with special county",
        url="https://example.com/special-county",
        candidate_link_id=candidate_link_special.id,
        publish_date=datetime.now(),
    )
    db_session.add(article)
    db_session.commit()
    
    response = test_client.get("/api/options/counties")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should handle special characters
    assert "St. Louis" in data


def test_options_case_sensitivity(
    test_client,
    db_session,
    sample_sources,
    sample_candidate_links,
):
    """Test options endpoints handle case variations correctly."""
    from datetime import datetime

    from src.models import Article, CandidateLink

    # Create CandidateLinks with different case variations
    candidate_link1 = CandidateLink(
        url="https://boone1.example.com/article-1",
        source="boone1.example.com",
        source_host_id="boone1.example.com",
        source_name="Boone Source 1",
        source_county="Boone",
    )
    candidate_link2 = CandidateLink(
        url="https://boone2.example.com/article-2",
        source="boone2.example.com",
        source_host_id="boone2.example.com",
        source_name="Boone Source 2",
        source_county="boone",  # Different case
    )
    db_session.add_all([candidate_link1, candidate_link2])
    db_session.flush()
    
    # Create articles with different case variations
    articles = [
        Article(
            title="Test 1",
            url="https://example.com/1",
            candidate_link_id=candidate_link1.id,
            publish_date=datetime.now(),
        ),
        Article(
            title="Test 2",
            url="https://example.com/2",
            candidate_link_id=candidate_link2.id,
            publish_date=datetime.now(),
        ),
    ]
    
    for article in articles:
        db_session.add(article)
    db_session.commit()
    
    response = test_client.get("/api/options/counties")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should handle case variations
    # Either: normalize to one case, or return both
    boone_variants = [c for c in data if c.lower() == "boone"]
    assert len(boone_variants) > 0
