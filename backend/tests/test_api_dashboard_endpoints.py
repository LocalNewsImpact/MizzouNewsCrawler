"""Tests for dashboard API endpoints migrated from CSV to database queries."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from src.models import Article, CandidateLink, Base
from src.models.api_backend import Review, Candidate, Snapshot, DedupeAudit
from src.models.database import DatabaseManager


@pytest.fixture
def test_db(tmp_path):
    """Create an in-memory test database with sample data."""
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    db_manager = DatabaseManager(db_url)
    
    # Create all tables
    engine = db_manager.engine
    Base.metadata.create_all(engine)
    
    # Seed test data
    with db_manager.get_session() as session:
        # Create candidate links
        link1 = CandidateLink(
            id=str(uuid4()),
            url="https://example.com/article1",
            source="example.com",
            source_host_id="example.com",
            source_name="Example News",
            source_county="Test County",
        )
        link2 = CandidateLink(
            id=str(uuid4()),
            url="https://wire.com/article2",
            source="wire.com",
            source_host_id="wire.com",
            source_name="Wire Service",
            source_county="Wire County",
        )
        link3 = CandidateLink(
            id=str(uuid4()),
            url="https://local.com/article3",
            source="local.com",
            source_host_id="local.com",
            source_name="Local News",
            source_county="Local County",
        )
        
        session.add_all([link1, link2, link3])
        session.flush()
        
        # Create articles
        article1 = Article(
            id=str(uuid4()),
            candidate_link_id=link1.id,
            url=link1.url,
            title="Test Article 1",
            author="John Doe",
            publish_date=datetime.utcnow() - timedelta(days=1),
            content="This is test article 1 content.",
            text="This is test article 1 content.",
            status="extracted",
            wire=None,  # Not a wire article
            primary_label="local_news",
            primary_label_confidence=0.95,
        )
        
        article2 = Article(
            id=str(uuid4()),
            candidate_link_id=link2.id,
            url=link2.url,
            title="Wire Article 2",
            author="Associated Press",
            publish_date=datetime.utcnow() - timedelta(days=2),
            content="This is wire article 2 content.",
            text="This is wire article 2 content.",
            status="wire",
            wire=json.dumps(["Associated Press"]),  # Wire article
            primary_label="national_news",
            primary_label_confidence=0.88,
        )
        
        article3 = Article(
            id=str(uuid4()),
            candidate_link_id=link3.id,
            url=link3.url,
            title="Test Article 3",
            author="Jane Smith",
            publish_date=datetime.utcnow() - timedelta(days=3),
            content="This is test article 3 content.",
            text="This is test article 3 content.",
            status="extracted",
            wire=json.dumps([]),  # Empty wire array
            primary_label="local_news",
            primary_label_confidence=0.92,
        )
        
        session.add_all([article1, article2, article3])
        session.flush()
        
        # Create snapshots for candidate testing
        snapshot1 = Snapshot(
            id=str(uuid4()),
            host="broken.local",
            url="https://broken.local/test",
            path="/test",
            reviewed_at=None,
        )
        snapshot2 = Snapshot(
            id=str(uuid4()),
            host="fixed.local",
            url="https://fixed.local/test",
            path="/test",
            reviewed_at=datetime.utcnow(),
        )
        session.add_all([snapshot1, snapshot2])
        session.flush()
        
        # Create candidates (non-accepted issues)
        candidate1 = Candidate(
            id=str(uuid4()),
            snapshot_id=snapshot1.id,
            field="title",
            selector="h1.title",
            score=0.3,
            accepted=False,
        )
        candidate2 = Candidate(
            id=str(uuid4()),
            snapshot_id=snapshot1.id,
            field="author",
            selector=".byline",
            score=0.4,
            accepted=False,
        )
        candidate3 = Candidate(
            id=str(uuid4()),
            snapshot_id=snapshot2.id,
            field="date",
            selector=".publish-date",
            score=0.9,
            accepted=True,  # This one is accepted
        )
        session.add_all([candidate1, candidate2, candidate3])
        session.flush()
        
        # Create dedupe audit entries
        dedupe1 = DedupeAudit(
            article_uid=article1.id,
            neighbor_uid=article2.id,
            host="example.com",
            similarity=0.85,  # Near miss (> 0.7, dedupe_flag=0)
            dedupe_flag=0,
        )
        dedupe2 = DedupeAudit(
            article_uid=article2.id,
            neighbor_uid=article3.id,
            host="wire.com",
            similarity=0.95,  # Confirmed duplicate
            dedupe_flag=1,
        )
        session.add_all([dedupe1, dedupe2])
        
        # Create a review for article1
        review1 = Review(
            article_uid=article1.id,
            article_idx=0,
            reviewer="test_reviewer",
            reviewed_at=datetime.utcnow(),
            tags="test,reviewed",
        )
        session.add(review1)
        
        session.commit()
        
        # Store article IDs for test assertions
        return {
            "db_manager": db_manager,
            "article1_id": article1.id,
            "article2_id": article2.id,
            "article3_id": article3.id,
        }


@pytest.fixture
def client(test_db, monkeypatch):
    """Create a test client with the test database."""
    # Patch the db_manager in the main module
    monkeypatch.setattr("backend.app.main.db_manager", test_db["db_manager"])
    return TestClient(app)


def test_ui_overview_returns_correct_counts(client, test_db):
    """Test that /api/ui_overview returns correct article and wire counts from database."""
    response = client.get("/api/ui_overview")
    assert response.status_code == 200
    
    data = response.json()
    assert "total_articles" in data
    assert "wire_count" in data
    assert "candidate_issues" in data
    assert "dedupe_near_misses" in data
    
    # Should have 3 articles total
    assert data["total_articles"] == 3
    
    # Should have 1 wire article (article2 with non-empty wire JSON)
    assert data["wire_count"] == 1
    
    # Should have 2 non-accepted candidates
    assert data["candidate_issues"] == 2
    
    # Should have 1 dedupe near miss (similarity > 0.7 and dedupe_flag=0)
    assert data["dedupe_near_misses"] == 1


def test_ui_overview_handles_empty_database(client, test_db):
    """Test that /api/ui_overview handles empty database gracefully."""
    # Clear all data
    with test_db["db_manager"].get_session() as session:
        session.query(Article).delete()
        session.query(Candidate).delete()
        session.query(DedupeAudit).delete()
        session.commit()
    
    response = client.get("/api/ui_overview")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total_articles"] == 0
    assert data["wire_count"] == 0
    assert data["candidate_issues"] == 0
    assert data["dedupe_near_misses"] == 0


def test_list_articles_returns_paginated_results(client, test_db):
    """Test that /api/articles returns paginated results from database."""
    response = client.get("/api/articles?limit=2&offset=0")
    assert response.status_code == 200
    
    data = response.json()
    assert "count" in data
    assert "results" in data
    
    assert data["count"] == 3  # Total articles
    assert len(data["results"]) == 2  # Limited to 2
    
    # Check that results have expected fields
    for article in data["results"]:
        assert "url" in article
        assert "title" in article
        assert "author" in article
        assert "__idx" in article  # Index for review posting


def test_list_articles_filters_by_reviewer(client, test_db):
    """Test that /api/articles filters out reviewed articles when reviewer specified."""
    # Without filter, should get 3 articles
    response = client.get("/api/articles")
    assert response.status_code == 200
    assert response.json()["count"] == 3
    
    # With reviewer filter, should get 2 articles (article1 is reviewed by test_reviewer)
    response = client.get("/api/articles?reviewer=test_reviewer")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    
    # Verify that article1 is not in the results
    article_ids = [a["id"] for a in data["results"]]
    assert test_db["article1_id"] not in article_ids


def test_list_articles_handles_empty_database(client, test_db):
    """Test that /api/articles handles empty database gracefully."""
    # Clear all articles
    with test_db["db_manager"].get_session() as session:
        session.query(Article).delete()
        session.commit()
    
    response = client.get("/api/articles")
    assert response.status_code == 200
    
    data = response.json()
    assert data["count"] == 0
    assert len(data["results"]) == 0


def test_get_article_by_id(client, test_db):
    """Test that /api/articles/{id} returns a single article by ID."""
    article_id = test_db["article1_id"]
    response = client.get(f"/api/articles/{article_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["id"] == article_id
    assert data["title"] == "Test Article 1"
    assert data["author"] == "John Doe"
    assert "url" in data
    assert "content" in data


def test_get_article_not_found(client, test_db):
    """Test that /api/articles/{id} returns 404 for non-existent article."""
    fake_id = str(uuid4())
    response = client.get(f"/api/articles/{fake_id}")
    assert response.status_code == 404


def test_list_articles_pagination_second_page(client, test_db):
    """Test that pagination works correctly for second page."""
    # Get first page
    response1 = client.get("/api/articles?limit=2&offset=0")
    assert response1.status_code == 200
    page1 = response1.json()
    
    # Get second page
    response2 = client.get("/api/articles?limit=2&offset=2")
    assert response2.status_code == 200
    page2 = response2.json()
    
    # Should have different articles
    page1_ids = {a["id"] for a in page1["results"]}
    page2_ids = {a["id"] for a in page2["results"]}
    assert page1_ids != page2_ids
    
    # Second page should have 1 article (total is 3)
    assert len(page2["results"]) == 1


def test_wire_count_null_vs_empty_json(client, test_db):
    """Test that wire count correctly distinguishes null, empty, and populated JSON."""
    # We have:
    # - article1: wire=None (null)
    # - article2: wire=["Associated Press"] (populated)
    # - article3: wire=[] (empty array)
    
    response = client.get("/api/ui_overview")
    assert response.status_code == 200
    
    data = response.json()
    # Only article2 should count as wire content
    assert data["wire_count"] == 1
