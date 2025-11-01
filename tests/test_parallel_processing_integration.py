"""Integration tests for parallel processing with row-level locking.

These tests validate that FOR UPDATE SKIP LOCKED prevents duplicate processing
without using ThreadPoolExecutor (which causes CI hangs/deadlocks).
"""

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.orm import sessionmaker

from src.models import Article, ArticleEntity, ArticleLabel
from src.models.database import save_article_classification, save_article_entities


@pytest.mark.postgres
@pytest.mark.parallel
def test_save_article_entities_autocommit_false_holds_lock(cloud_sql_session):
    """Test that autocommit=False doesn't commit immediately."""
    # Create a test article
    article = Article(
        url="http://test.com/parallel-entity-test",
        title="Test Article",
        text="Test content",
        status="cleaned",
    )
    cloud_sql_session.add(article)
    cloud_sql_session.commit()
    article_id = str(article.id)
    
    # Save entities without committing
    entities = [{"entity_text": "TestCity", "entity_label": "LOC"}]
    save_article_entities(
        cloud_sql_session,
        article_id,
        entities,
        "test-v1",
        autocommit=False,
    )
    
    # Open new session - should NOT see the entities yet
    Session = sessionmaker(bind=cloud_sql_session.get_bind())
    session2 = Session()
    try:
        count = session2.query(ArticleEntity).filter_by(
            article_id=article_id
        ).count()
        assert count == 0, "Entities visible before commit!"
        
        # Now commit
        cloud_sql_session.commit()
        
        # Should see entities now
        session2.expire_all()  # Clear cache
        count = session2.query(ArticleEntity).filter_by(
            article_id=article_id
        ).count()
        assert count == 1, "Entities not visible after commit"
    finally:
        session2.close()


@pytest.mark.postgres
@pytest.mark.parallel
def test_save_article_classification_autocommit_false_holds_lock(cloud_sql_session):
    """Test that autocommit=False doesn't commit immediately."""
    from src.ml.article_classifier import Prediction
    
    # Create a test article
    article = Article(
        url="http://test.com/parallel-class-test",
        title="Test Article",
        text="Test content",
        status="cleaned",
    )
    cloud_sql_session.add(article)
    cloud_sql_session.commit()
    article_id = str(article.id)
    
    # Save classification without committing
    pred = Prediction(label="local_news", score=0.95)
    save_article_classification(
        cloud_sql_session,
        article_id,
        "test-v1",
        "model-v1",
        pred,
        autocommit=False,
    )
    
    # Open new session - should NOT see the label yet
    Session = sessionmaker(bind=cloud_sql_session.get_bind())
    session2 = Session()
    try:
        count = session2.query(ArticleLabel).filter_by(
            article_id=article_id
        ).count()
        assert count == 0, "Label visible before commit!"
        
        # Now commit
        cloud_sql_session.commit()
        
        # Should see label now
        session2.expire_all()
        count = session2.query(ArticleLabel).filter_by(
            article_id=article_id
        ).count()
        assert count == 1, "Label not visible after commit"
    finally:
        session2.close()


@pytest.mark.postgres
@pytest.mark.parallel
def test_skip_locked_prevents_row_blocking(cloud_sql_session):
    """Test that SKIP LOCKED skips locked rows instead of waiting."""
    # Create test articles
    for i in range(3):
        article = Article(
            url=f"http://test.com/skip-locked-{i}",
            title=f"Article {i}",
            text="Test",
            content="Test",
            status="cleaned",
        )
        cloud_sql_session.add(article)
    cloud_sql_session.commit()
    
    # Session 1: Lock first 2 articles
    Session = sessionmaker(bind=cloud_sql_session.get_bind())
    session1 = Session()
    session2 = Session()
    
    try:
        # Session 1 locks articles with FOR UPDATE (blocks others)
        query1 = sql_text("""
            SELECT a.id FROM articles a
            WHERE a.url LIKE 'http://test.com/skip-locked-%'
            ORDER BY a.id
            LIMIT 2
            FOR UPDATE
        """)
        result1 = session1.execute(query1)
        locked_ids = [row[0] for row in result1.fetchall()]
        assert len(locked_ids) == 2, "Should lock 2 articles"
        
        # Session 2: Try to select with SKIP LOCKED (should skip locked rows)
        query2 = sql_text("""
            SELECT a.id FROM articles a
            WHERE a.url LIKE 'http://test.com/skip-locked-%'
            ORDER BY a.id
            FOR UPDATE SKIP LOCKED
        """)
        result2 = session2.execute(query2)
        available_ids = [row[0] for row in result2.fetchall()]
        
        # Should only get the unlocked article (the 3rd one)
        assert len(available_ids) == 1, "Should only get 1 unlocked article"
        assert available_ids[0] not in locked_ids, "Got a locked article!"
        
        # Commit session 1 to release locks
        session1.commit()
        
        # Now session 2 should be able to get all 3
        result3 = session2.execute(query2)
        all_ids = [row[0] for row in result3.fetchall()]
        assert len(all_ids) == 3, "Should get all 3 after locks released"
        
    finally:
        session1.close()
        session2.close()


@pytest.mark.postgres
@pytest.mark.parallel
def test_batch_commit_holds_locks_until_commit(cloud_sql_session):
    """Test that batch processing with autocommit=False holds locks."""
    # Create test articles
    articles = []
    for i in range(5):
        article = Article(
            url=f"http://test.com/batch-{i}",
            title=f"Article {i}",
            text="Test content",
            content="Test",
            status="cleaned",
        )
        cloud_sql_session.add(article)
        articles.append(article)
    cloud_sql_session.commit()
    
    # Session 1: Lock and process articles without committing
    Session = sessionmaker(bind=cloud_sql_session.get_bind())
    session1 = Session()
    session2 = Session()
    
    try:
        # Lock articles in session 1
        query = sql_text("""
            SELECT a.id FROM articles a
            WHERE a.url LIKE 'http://test.com/batch-%'
            ORDER BY a.id
            FOR UPDATE
        """)
        result = session1.execute(query)
        locked_ids = [row[0] for row in result.fetchall()]
        assert len(locked_ids) == 5
        
        # Process each article with autocommit=False
        for article_id in locked_ids:
            entities = [{"entity_text": "City", "entity_label": "LOC"}]
            save_article_entities(
                session1,
                str(article_id),
                entities,
                "test-batch-v1",
                autocommit=False,  # Don't commit yet
            )
        
        # Session 2 should still not be able to lock these rows
        query2 = sql_text("""
            SELECT a.id FROM articles a
            WHERE a.url LIKE 'http://test.com/batch-%'
            FOR UPDATE SKIP LOCKED
        """)
        result2 = session2.execute(query2)
        available = result2.fetchall()
        assert len(available) == 0, "Articles should still be locked!"
        
        # Now commit session 1
        session1.commit()
        
        # Session 2 should now see the entities
        result3 = session2.execute(query2)
        available2 = result3.fetchall()
        assert len(available2) == 5, "All articles should be available now"
        
    finally:
        session1.close()
        session2.close()
