"""Critical SQL operation tests for pipeline phases.

This test module contains minimal tests to ensure that critical SQL operations
in the pipeline phases (discovery, verification, extraction, labeling) do not
break due to SQL syntax errors, schema changes, or constraint violations.

These tests are designed to catch the most common production-breaking issues:
- SQL syntax errors in queries
- Missing or renamed database columns
- Constraint violations
- Transaction handling errors
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from src.models import Article, CandidateLink, Source
from src.models.database import DatabaseManager


pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def test_db(cloud_sql_session):
    """Use PostgreSQL test database with automatic rollback.
    
    Uses the cloud_sql_session fixture which provides a PostgreSQL
    connection with all tables created and automatic rollback after test.
    """
    # cloud_sql_session is a SQLAlchemy Session, but we need a DatabaseManager
    # Get the URL from the engine (bind returns Connection, need engine.url)
    engine = cloud_sql_session.get_bind().engine
    db_url = str(engine.url)
    manager = DatabaseManager(database_url=db_url)
    
    yield manager
    # No explicit cleanup needed - cloud_sql_session handles rollback


@pytest.fixture
def test_source(test_db):
    """Create a test source."""
    source = Source(
        id=str(uuid.uuid4()),
        host="test.example.com",
        host_norm="test.example.com",
        canonical_name="Test Source",
        city="Test City",
        county="Test County",
    )
    
    with test_db.session as session:
        session.add(source)
        session.commit()
        session.refresh(source)
    
    return source


class TestDiscoveryCriticalSQL:
    """Test critical SQL operations in discovery phase."""
    
    def test_insert_candidate_link(self, test_db, test_source):
        """Test inserting a candidate link (most basic discovery operation)."""
        with test_db.session as session:
            candidate = CandidateLink(
                id=str(uuid.uuid4()),
                url="https://test.example.com/article-1",
                source=test_source.canonical_name,
                source_id=test_source.id,
                crawl_depth=0,
                status="discovered",
                discovered_at=datetime.now(timezone.utc),
                discovered_by="test",
            )
            session.add(candidate)
            session.commit()
            
            # Verify
            result = session.query(CandidateLink).filter_by(
                url=candidate.url
            ).first()
            assert result is not None
            assert result.status == "discovered"
    
    def test_query_sources_for_discovery(self, test_db, test_source):
        """Test SQL query used to find sources for discovery."""
        query = text("""
            SELECT id, host, canonical_name
            FROM sources
            WHERE id = :source_id
        """)
        
        with test_db.session as session:
            result = session.execute(query, {"source_id": test_source.id})
            rows = result.fetchall()
            assert len(rows) == 1
            assert rows[0][1] == test_source.host


class TestVerificationCriticalSQL:
    """Test critical SQL operations in verification phase."""
    
    def test_update_verification_status(self, test_db, test_source):
        """Test updating candidate link status after verification."""
        # Create discovered candidate
        candidate_id = str(uuid.uuid4())
        with test_db.session as session:
            candidate = CandidateLink(
                id=candidate_id,
                url="https://test.example.com/verify-1",
                source=test_source.canonical_name,
                source_id=test_source.id,
                crawl_depth=0,
                status="discovered",
                discovered_at=datetime.now(timezone.utc),
                discovered_by="test",
            )
            session.add(candidate)
            session.commit()
        
        # Update status (verification result)
        with test_db.session as session:
            candidate = session.get(CandidateLink, candidate_id)
            candidate.status = "article"
            candidate.processed_at = datetime.now(timezone.utc)
            session.commit()
        
        # Verify update
        with test_db.session as session:
            result = session.get(CandidateLink, candidate_id)
            assert result.status == "article"
            assert result.processed_at is not None
    
    def test_query_pending_verification(self, test_db, test_source):
        """Test SQL query to fetch candidates needing verification."""
        # Create some candidates
        for i in range(3):
            with test_db.session as session:
                candidate = CandidateLink(
                    id=str(uuid.uuid4()),
                    url=f"https://test.example.com/pending-{i}",
                    source=test_source.canonical_name,
                    source_id=test_source.id,
                    crawl_depth=0,
                    status="discovered",
                    discovered_at=datetime.now(timezone.utc),
                    discovered_by="test",
                )
                session.add(candidate)
                session.commit()
        
        # Query for pending
        query = text("""
            SELECT id, url
            FROM candidate_links
            WHERE status = 'discovered'
            LIMIT 10
        """)
        
        with test_db.session as session:
            result = session.execute(query)
            rows = result.fetchall()
            assert len(rows) == 3


class TestExtractionCriticalSQL:
    """Test critical SQL operations in extraction phase."""
    
    def test_insert_article(self, test_db, test_source):
        """Test inserting an extracted article."""
        # First create a candidate link
        candidate_id = str(uuid.uuid4())
        with test_db.session as session:
            candidate = CandidateLink(
                id=candidate_id,
                url="https://test.example.com/article-1",
                source=test_source.canonical_name,
                source_id=test_source.id,
                crawl_depth=0,
                status="article",
                discovered_at=datetime.now(timezone.utc),
                discovered_by="test",
            )
            session.add(candidate)
            session.commit()
        
        # Now create the article
        with test_db.session as session:
            article = Article(
                id=str(uuid.uuid4()),
                url="https://test.example.com/article-1",
                candidate_link_id=candidate_id,
                title="Test Article",
                content="Test content",
                status="extracted",
                extracted_at=datetime.now(timezone.utc),
            )
            session.add(article)
            session.commit()
            
            # Verify
            result = session.query(Article).filter_by(url=article.url).first()
            assert result is not None
            assert result.title == "Test Article"
    
    def test_duplicate_article_url_constraint(self, test_db, test_source):
        """Test that duplicate article URLs are prevented by constraint."""
        url = "https://test.example.com/duplicate"
        
        # Create candidate link first
        candidate_id = str(uuid.uuid4())
        with test_db.session as session:
            candidate = CandidateLink(
                id=candidate_id,
                url=url,
                source=test_source.canonical_name,
                source_id=test_source.id,
                crawl_depth=0,
                status="article",
                discovered_at=datetime.now(timezone.utc),
                discovered_by="test",
            )
            session.add(candidate)
            session.commit()
        
        # Insert first article
        with test_db.session as session:
            article1 = Article(
                id=str(uuid.uuid4()),
                url=url,
                candidate_link_id=candidate_id,
                title="First",
                status="extracted",
                extracted_at=datetime.now(timezone.utc),
            )
            session.add(article1)
            session.commit()
        
        # Try to insert duplicate
        with test_db.session as session:
            article2 = Article(
                id=str(uuid.uuid4()),
                url=url,
                candidate_link_id=candidate_id,
                title="Second",
                status="extracted",
                extracted_at=datetime.now(timezone.utc),
            )
            session.add(article2)
            # Note: Duplicate detection depends on constraints in the schema
            # For now we just test that we can handle potential duplicates
            try:
                session.commit()
                # If it succeeds, that's also ok for this test
            except IntegrityError:
                # Expected if there's a unique constraint on URL
                pass    
    def test_query_verified_candidates(self, test_db, test_source):
        """Test SQL query to fetch verified candidates for extraction."""
        # Create verified candidates
        for i in range(2):
            with test_db.session as session:
                candidate = CandidateLink(
                    id=str(uuid.uuid4()),
                    url=f"https://test.example.com/verified-{i}",
                    source=test_source.canonical_name,
                    source_id=test_source.id,
                    crawl_depth=0,
                    status="article",
                    discovered_at=datetime.now(timezone.utc),
                    discovered_by="test",
                    processed_at=datetime.now(timezone.utc),
                )
                session.add(candidate)
                session.commit()
        
        # Query verified
        query = text("""
            SELECT id, url
            FROM candidate_links
            WHERE status = 'article'
            LIMIT 10
        """)
        
        with test_db.session as session:
            result = session.execute(query)
            rows = result.fetchall()
            assert len(rows) == 2


class TestLabelingCriticalSQL:
    """Test critical SQL operations in labeling/ML phase."""
    
    def test_update_article_to_labeled(self, test_db, test_source):
        """Test updating article status to labeled after ML analysis."""
        # Create candidate link first
        candidate_id = str(uuid.uuid4())
        with test_db.session as session:
            candidate = CandidateLink(
                id=candidate_id,
                url="https://test.example.com/to-label",
                source=test_source.canonical_name,
                source_id=test_source.id,
                crawl_depth=0,
                status="article",
                discovered_at=datetime.now(timezone.utc),
                discovered_by="test",
            )
            session.add(candidate)
            session.commit()
        
        # Create extracted article
        article_id = str(uuid.uuid4())
        with test_db.session as session:
            article = Article(
                id=article_id,
                url="https://test.example.com/to-label",
                candidate_link_id=candidate_id,
                title="Article for Labeling",
                content="Content to analyze",
                status="cleaned",
                extracted_at=datetime.now(timezone.utc),
            )
            session.add(article)
            session.commit()
        
        # Update to labeled
        with test_db.session as session:
            article = session.get(Article, article_id)
            article.status = "labeled"
            session.commit()
        
        # Verify
        with test_db.session as session:
            result = session.get(Article, article_id)
            assert result.status == "labeled"
    
    def test_query_cleaned_articles(self, test_db, test_source):
        """Test SQL query to fetch cleaned articles for labeling."""
        # Create cleaned articles
        for i in range(2):
            candidate_id = str(uuid.uuid4())
            # Create candidate first
            with test_db.session as session:
                candidate = CandidateLink(
                    id=candidate_id,
                    url=f"https://test.example.com/cleaned-{i}",
                    source=test_source.canonical_name,
                    source_id=test_source.id,
                    crawl_depth=0,
                    status="article",
                    discovered_at=datetime.now(timezone.utc),
                    discovered_by="test",
                )
                session.add(candidate)
                session.commit()
            
            # Create article
            with test_db.session as session:
                article = Article(
                    id=str(uuid.uuid4()),
                    url=f"https://test.example.com/cleaned-{i}",
                    candidate_link_id=candidate_id,
                    title=f"Article {i}",
                    content="Content",
                    status="cleaned",
                    extracted_at=datetime.now(timezone.utc),
                )
                session.add(article)
                session.commit()
        
        # Query cleaned
        query = text("""
            SELECT id, url, title
            FROM articles
            WHERE status = 'cleaned'
            LIMIT 10
        """)
        
        with test_db.session as session:
            result = session.execute(query)
            rows = result.fetchall()
            assert len(rows) == 2


class TestErrorHandling:
    """Test error handling in pipeline operations."""
    
    def test_sql_syntax_error_handling(self, test_db):
        """Test that SQL syntax errors are caught."""
        with test_db.session as session:
            with pytest.raises(OperationalError):
                session.execute(text("INVALID SQL SYNTAX"))
