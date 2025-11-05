"""Integration tests for parallel processing with row-level locking.

These tests validate that FOR UPDATE SKIP LOCKED prevents duplicate processing
without using ThreadPoolExecutor (which causes CI hangs/deadlocks).
"""

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.orm import sessionmaker

from src.models import Article, ArticleEntity, ArticleLabel, CandidateLink
from src.models.database import save_article_classification, save_article_entities


@pytest.mark.postgres
@pytest.mark.parallel
@pytest.mark.integration
def test_save_article_entities_with_autocommit_false(cloud_sql_session):
    """Test that save_article_entities works with autocommit=False."""
    # Create candidate link first (required FK)
    candidate_link = CandidateLink(
        url="http://test.com/parallel-entity-test",
        source="test_source",
    )
    cloud_sql_session.add(candidate_link)
    cloud_sql_session.commit()

    # Create a test article
    article = Article(
        candidate_link_id=candidate_link.id,
        url="http://test.com/parallel-entity-test",
        title="Test Article",
        text="Test content",
        text_hash="testhash123",
        status="cleaned",
    )
    cloud_sql_session.add(article)
    cloud_sql_session.commit()
    article_id = str(article.id)

    # Save entities without autocommit
    entities = [{"entity_text": "TestCity", "entity_label": "LOC"}]
    records = save_article_entities(
        cloud_sql_session,
        article_id,
        entities,
        "test-v1",
        "testhash123",
        autocommit=False,
    )

    # Should return records
    assert len(records) == 1
    assert records[0].entity_text == "TestCity"

    # Manually commit (simulating batch commit)
    cloud_sql_session.commit()

    # Verify entities persisted
    count = (
        cloud_sql_session.query(ArticleEntity).filter_by(article_id=article_id).count()
    )
    assert count == 1


@pytest.mark.postgres
@pytest.mark.parallel
@pytest.mark.integration
def test_save_article_classification_with_autocommit_false(cloud_sql_session):
    """Test that save_article_classification works with autocommit=False."""
    from src.ml.article_classifier import Prediction

    # Create candidate link first (required FK)
    candidate_link = CandidateLink(
        url="http://test.com/parallel-class-test",
        source="test_source",
    )
    cloud_sql_session.add(candidate_link)
    cloud_sql_session.commit()

    # Create a test article
    article = Article(
        candidate_link_id=candidate_link.id,
        url="http://test.com/parallel-class-test",
        title="Test Article",
        text="Test content",
        status="cleaned",
    )
    cloud_sql_session.add(article)
    cloud_sql_session.commit()
    article_id = str(article.id)

    # Save classification without autocommit
    pred = Prediction(label="local_news", score=0.95)
    record = save_article_classification(
        cloud_sql_session,
        article_id,
        "test-v1",
        "model-v1",
        pred,
        autocommit=False,
    )

    # Should return record
    assert record.primary_label == "local_news"
    assert record.primary_label_confidence == 0.95

    # Manually commit (simulating batch commit)
    cloud_sql_session.commit()

    # Verify label persisted
    count = (
        cloud_sql_session.query(ArticleLabel).filter_by(article_id=article_id).count()
    )
    assert count == 1


@pytest.mark.postgres
@pytest.mark.parallel
@pytest.mark.integration
def test_parallel_entity_extraction_with_skip_locked(cloud_sql_session):
    """Test that multiple workers can extract entities in parallel without blocking.

    Simulates production: Worker 1 locks and processes articles,
    while Worker 2 receives a different batch.
    """
    import time

    timestamp = int(time.time() * 1000)

    # Create candidate link and 10 articles
    # Use dedicated setup session so committed rows are visible to parallel connections
    engine = cloud_sql_session.bind.engine
    SessionFactory = sessionmaker(bind=engine)

    candidate_link_id: str | None = None
    setup_session = SessionFactory()
    try:
        candidate_link = CandidateLink(
            url=f"http://test.com/parallel-{timestamp}",
            source="test_source",
        )
        setup_session.add(candidate_link)
        setup_session.commit()
        candidate_link_id = str(candidate_link.id)

        for i in range(10):
            article = Article(
                candidate_link_id=candidate_link.id,
                url=f"http://test.com/parallel-{timestamp}-{i}",
                title=f"Article {i}",
                text="Test content for entity extraction",
                content="Test content for entity extraction",
                status="cleaned",
            )
            setup_session.add(article)
        setup_session.commit()
    finally:
        setup_session.close()

    pattern = f"http://test.com/parallel-{timestamp}%"

    # Worker 1: Lock and process first 5 articles (simulating entity extraction batch)
    conn1 = engine.connect()
    trans1 = conn1.begin()
    try:
        # Worker 1 selects with FOR UPDATE SKIP LOCKED (like production)
        query_worker1 = sql_text(
            """
            SELECT a.id, a.text
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.url LIKE :pattern
            AND a.text IS NOT NULL
            AND a.status = 'cleaned'
            ORDER BY a.id
            LIMIT 5
            FOR UPDATE OF a SKIP LOCKED
        """
        )
        result1 = conn1.execute(query_worker1, {"pattern": pattern})
        worker1_ids = [row[0] for row in result1.fetchall()]
        assert len(worker1_ids) == 5, "Worker 1 should lock 5 articles"

        # Worker 2: Tries to select with SKIP LOCKED (should get different articles)
        conn2 = engine.connect()
        trans2 = conn2.begin()
        try:
            result2 = conn2.execute(query_worker1, {"pattern": pattern})
            worker2_ids = [row[0] for row in result2.fetchall()]

            # Worker 2 should get the remaining 5 articles (not blocked!)
            assert len(worker2_ids) == 5, "Worker 2 should get 5 unlocked articles"

            # No overlap - parallel processing working!
            assert set(worker1_ids).isdisjoint(
                set(worker2_ids)
            ), "Workers got same articles!"

            trans2.commit()
        finally:
            conn2.close()

        trans1.commit()
    finally:
        conn1.close()

    # Cleanup inserted rows
    cleanup_session = SessionFactory()
    try:
        cleanup_session.query(Article).filter(Article.url.like(pattern)).delete(
            synchronize_session=False
        )
        if candidate_link_id is not None:
            cleanup_session.query(CandidateLink).filter_by(
                id=candidate_link_id
            ).delete()
        cleanup_session.commit()
    finally:
        cleanup_session.close()


@pytest.mark.postgres
@pytest.mark.parallel
@pytest.mark.integration
def test_parallel_classification_batch_processing(cloud_sql_session):
    """Validate parallel classification: workers process different batches."""
    import time

    from src.ml.article_classifier import Prediction

    timestamp = int(time.time() * 1000)

    # Create test data
    engine = cloud_sql_session.bind.engine
    SessionFactory = sessionmaker(bind=engine)
    candidate_link_id: str | None = None
    article_ids: list[str] = []
    setup_session = SessionFactory()
    try:
        candidate_link = CandidateLink(
            url=f"http://test.com/classify-{timestamp}",
            source="test_source",
        )
        setup_session.add(candidate_link)
        setup_session.commit()
        candidate_link_id = str(candidate_link.id)

        pattern = f"http://test.com/classify-{timestamp}%"

        for i in range(10):
            article = Article(
                candidate_link_id=candidate_link.id,
                url=f"http://test.com/classify-{timestamp}-{i}",
                title=f"Article {i}",
                text="Test",
                status="cleaned",
            )
            setup_session.add(article)
        setup_session.commit()
        article_ids = [
            str(row[0])
            for row in setup_session.query(Article.id)
            .filter(Article.url.like(pattern))
            .all()
        ]
    finally:
        setup_session.close()

    # Worker 1: Process batch
    conn1 = engine.connect()
    trans1 = conn1.begin()
    Session1 = sessionmaker(bind=conn1)
    session1 = Session1()

    try:
        from sqlalchemy import select

        stmt = (
            select(Article)
            .where(Article.url.like(pattern))
            .limit(5)
            .with_for_update(skip_locked=True)
        )
        worker1_articles = list(session1.scalars(stmt))
        assert len(worker1_articles) == 5

        # Process with autocommit=False
        for article in worker1_articles:
            pred = Prediction(label="local_news", score=0.9)
            save_article_classification(
                session1,
                str(article.id),
                "v1",
                "m1",
                pred,
                autocommit=False,
            )

        # Worker 2: Gets different articles
        conn2 = engine.connect()
        trans2 = conn2.begin()
        Session2 = sessionmaker(bind=conn2)
        session2 = Session2()

        try:
            worker2_articles = list(session2.scalars(stmt))
            assert len(worker2_articles) == 5

            # No overlap - parallel processing works
            w1_ids = {str(a.id) for a in worker1_articles}
            w2_ids = {str(a.id) for a in worker2_articles}
            assert w1_ids.isdisjoint(w2_ids)

            trans2.commit()
        finally:
            session2.close()
            conn2.close()

        trans1.commit()
    finally:
        session1.close()
        conn1.close()

    cleanup_session = SessionFactory()
    try:
        if article_ids:
            cleanup_session.query(ArticleLabel).filter(
                ArticleLabel.article_id.in_(article_ids)
            ).delete(synchronize_session=False)
        cleanup_session.query(Article).filter(Article.url.like(pattern)).delete(
            synchronize_session=False
        )
        if candidate_link_id is not None:
            cleanup_session.query(CandidateLink).filter_by(
                id=candidate_link_id
            ).delete()
        cleanup_session.commit()
    finally:
        cleanup_session.close()
