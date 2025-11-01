"""Integration tests for parallel processing with row-level locking."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text as sql_text

from src.models import Article, ArticleEntity, ArticleLabel
from src.models.database import save_article_classification, save_article_entities


@pytest.mark.postgres
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
    from src.models.database import DatabaseManager
    db2 = DatabaseManager()
    try:
        count = db2.session.query(ArticleEntity).filter_by(
            article_id=article_id
        ).count()
        assert count == 0, "Entities visible before commit!"
        
        # Now commit
        cloud_sql_session.commit()
        
        # Should see entities now
        count = db2.session.query(ArticleEntity).filter_by(
            article_id=article_id
        ).count()
        assert count == 1, "Entities not visible after commit"
    finally:
        db2.close()


@pytest.mark.postgres
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
    from src.models.database import DatabaseManager
    db2 = DatabaseManager()
    try:
        count = db2.session.query(ArticleLabel).filter_by(
            article_id=article_id
        ).count()
        assert count == 0, "Label visible before commit!"
        
        # Now commit
        cloud_sql_session.commit()
        
        # Should see label now
        count = db2.session.query(ArticleLabel).filter_by(
            article_id=article_id
        ).count()
        assert count == 1, "Label not visible after commit"
    finally:
        db2.close()


@pytest.mark.postgres
@pytest.mark.slow
def test_parallel_entity_extraction_no_duplicate_work(cloud_sql_session):
    """Test that parallel workers don't process the same articles."""
    # Create 10 test articles (reduced from 20 for memory efficiency)
    articles = []
    for i in range(10):
        article = Article(
            url=f"http://test.com/parallel-{i}",
            title=f"Test Article {i}",
            text="Test content with location",
            content="Test content",
            status="cleaned",
        )
        cloud_sql_session.add(article)
        articles.append(article)
    cloud_sql_session.commit()
    
    processed_articles = []
    lock = threading.Lock()
    
    def worker(worker_id):
        """Simulate a worker processing articles."""
        from src.models.database import DatabaseManager
        db = DatabaseManager()
        try:
            # Select articles with FOR UPDATE SKIP LOCKED
            query = sql_text("""
                SELECT a.id, a.text
                FROM articles a
                WHERE a.content IS NOT NULL
                AND a.text IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id
                )
                AND a.url LIKE 'http://test.com/parallel-%'
                ORDER BY a.id
                LIMIT 3
                FOR UPDATE OF a SKIP LOCKED
            """)
            
            result = db.session.execute(query)
            rows = result.fetchall()
            
            # Process each article
            for row in rows:
                article_id, text = row
                
                # Track which articles this worker is processing
                with lock:
                    if article_id in processed_articles:
                        raise AssertionError(
                            f"Worker {worker_id} processing duplicate "
                            f"article {article_id}!"
                        )
                    processed_articles.append(article_id)
                
                # Simulate processing time
                time.sleep(0.01)
                
                # Save entities without committing
                entities = [
                    {
                        "entity_text": f"Worker{worker_id}City",
                        "entity_label": "LOC",
                    }
                ]
                save_article_entities(
                    db.session,
                    str(article_id),
                    entities,
                    "test-parallel-v1",
                    autocommit=False,
                )
            
            # Batch commit
            db.session.commit()
            
        finally:
            db.close()
    
    # Run 3 workers in parallel (reduced for memory efficiency)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(worker, i) for i in range(3)]
        for future in futures:
            future.result()  # Will raise if any worker had duplicate
    
    # Verify all 10 articles were processed exactly once
    assert len(processed_articles) == 10, f"Expected 10, got {len(processed_articles)}"
    assert len(set(processed_articles)) == 10, "Duplicate articles found!"


@pytest.mark.postgres
@pytest.mark.slow
def test_parallel_classification_no_duplicate_work(cloud_sql_session):
    """Test that parallel classification workers don't duplicate work."""
    # Create 10 test articles (reduced from 20 for memory efficiency)
    articles = []
    for i in range(10):
        article = Article(
            url=f"http://test.com/parallel-class-{i}",
            title=f"Test Article {i}",
            text="Test content for classification",
            content="Test content",
            status="cleaned",
        )
        cloud_sql_session.add(article)
        articles.append(article)
    cloud_sql_session.commit()
    
    processed_articles = []
    lock = threading.Lock()
    
    def worker(worker_id):
        """Simulate a classification worker."""
        from src.models.database import DatabaseManager
        from src.ml.article_classifier import Prediction
        from sqlalchemy import select
        
        db = DatabaseManager()
        try:
            # Select articles with row-level locking
            label_version = "test-parallel-v1"
            
            # Subquery for label existence
            label_exists = (
                select(ArticleLabel.id)
                .where(
                    ArticleLabel.article_id == Article.id,
                    ArticleLabel.label_version == label_version,
                )
                .exists()
            )
            
            stmt = (
                select(Article)
                .where(Article.status == "cleaned")
                .where(Article.url.like("http://test.com/parallel-class-%"))
                .where(~label_exists)
                .order_by(Article.id)
                .limit(3)
                .with_for_update(skip_locked=True)
            )
            
            articles_batch = list(db.session.scalars(stmt))
            
            # Process each article
            for article in articles_batch:
                with lock:
                    if article.id in processed_articles:
                        raise AssertionError(
                            f"Worker {worker_id} processing duplicate "
                            f"article {article.id}!"
                        )
                    processed_articles.append(article.id)
                
                # Simulate processing time
                time.sleep(0.01)
                
                # Save classification without committing
                pred = Prediction(label=f"label_worker_{worker_id}", score=0.85)
                save_article_classification(
                    db.session,
                    str(article.id),
                    label_version,
                    "model-test-v1",
                    pred,
                    autocommit=False,
                )
            
            # Batch commit
            db.session.commit()
            
        finally:
            db.close()
    
    # Run 3 workers in parallel (reduced for memory efficiency)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(worker, i) for i in range(3)]
        for future in futures:
            future.result()
    
    # Verify all 10 articles were processed exactly once
    assert len(processed_articles) == 10, f"Expected 10, got {len(processed_articles)}"
    assert len(set(processed_articles)) == 10, "Duplicate articles found!"
