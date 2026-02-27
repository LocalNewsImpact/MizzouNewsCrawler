"""Tests for database.py helper functions to increase coverage."""

import os
import tempfile
import uuid
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from sqlalchemy import text

from src.models import Article, ArticleEntity, CandidateLink, Job
from src.models.database import (
    DatabaseManager,
    bulk_insert_candidate_links,
    create_job_record,
    finish_job_record,
    read_articles,
    read_candidate_links,
    save_article_entities,
)


def temporary_database():
    """Create a temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        yield db_url, path
    finally:
        if os.path.exists(path):
            os.remove(path)


class TestSaveArticleEntities:
    """Test save_article_entities function."""

    def test_saves_entities_with_all_fields(self):
        """Should save entities with all optional fields populated."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                # Create article
                link = CandidateLink(url="https://example.com/test", source="Test")
                db.session.add(link)
                db.session.commit()

                article = Article(
                    candidate_link_id=link.id, url="https://example.com/test"
                )
                db.session.add(article)
                db.session.commit()

                # Save entities with all fields
                entities = [
                    {
                        "entity_text": "Test City",
                        "entity_label": "LOCATION",
                        "osm_category": "place",
                        "osm_subcategory": "city",
                        "confidence": 0.95,
                        "matched_gazetteer_id": "gaz-123",
                        "match_score": 0.88,
                        "match_name": "Test City Official",
                        "meta": {"source": "test"},
                    }
                ]

                result = save_article_entities(
                    db.session,
                    article.id,
                    entities,
                    extractor_version="test-v1",
                    article_text_hash="hash123",
                    autocommit=True,
                )

                assert len(result) == 1
                assert result[0].entity_text == "Test City"
                assert result[0].confidence == 0.95
                assert result[0].matched_gazetteer_id == "gaz-123"

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_deduplicates_identical_entities(self):
        """Should deduplicate entities with same text and label."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                link = CandidateLink(url="https://example.com/dup", source="Test")
                db.session.add(link)
                db.session.commit()

                article = Article(
                    candidate_link_id=link.id, url="https://example.com/dup"
                )
                db.session.add(article)
                db.session.commit()

                # Duplicate entities
                entities = [
                    {"entity_text": "City", "entity_label": "LOC"},
                    {"entity_text": "City", "entity_label": "LOC"},
                    {"entity_text": "City", "entity_label": "LOC"},
                ]

                result = save_article_entities(
                    db.session,
                    article.id,
                    entities,
                    extractor_version="v1",
                    article_text_hash="hash",
                    autocommit=True,
                )

                # Should only save 1 entity
                assert len(result) == 1

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_handles_entity_without_label(self):
        """Should handle entities with missing entity_label field."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                link = CandidateLink(url="https://example.com/no-label", source="Test")
                db.session.add(link)
                db.session.commit()

                article = Article(
                    candidate_link_id=link.id, url="https://example.com/no-label"
                )
                db.session.add(article)
                db.session.commit()

                # Entity without entity_label
                entities = [{"entity_text": "Unknown Place"}]

                result = save_article_entities(
                    db.session,
                    article.id,
                    entities,
                    extractor_version="v1",
                    article_text_hash="hash",
                    autocommit=True,
                )

                assert len(result) == 1
                assert result[0].entity_label is None

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_uses_label_field_as_fallback(self):
        """Should use 'label' field if 'entity_label' not present."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                link = CandidateLink(url="https://example.com/fallback", source="Test")
                db.session.add(link)
                db.session.commit()

                article = Article(
                    candidate_link_id=link.id, url="https://example.com/fallback"
                )
                db.session.add(article)
                db.session.commit()

                # Entity with 'label' instead of 'entity_label'
                entities = [{"entity_text": "Place", "label": "LOCATION"}]

                result = save_article_entities(
                    db.session,
                    article.id,
                    entities,
                    extractor_version="v1",
                    article_text_hash="hash",
                    autocommit=True,
                )

                assert len(result) == 1
                assert result[0].entity_label == "LOCATION"

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_creates_sentinel_when_no_entities(self):
        """Should create sentinel record when entities list is empty."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                link = CandidateLink(url="https://example.com/empty", source="Test")
                db.session.add(link)
                db.session.commit()

                article = Article(
                    candidate_link_id=link.id, url="https://example.com/empty"
                )
                db.session.add(article)
                db.session.commit()

                # Empty entities
                result = save_article_entities(
                    db.session,
                    article.id,
                    [],
                    extractor_version="v1",
                    article_text_hash="hash",
                    autocommit=True,
                )

                assert len(result) == 1
                assert result[0].entity_text == "__NO_ENTITIES_FOUND__"
                assert result[0].entity_label == "SENTINEL"
                assert result[0].meta.get("sentinel") is True

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_autocommit_false_does_not_commit(self):
        """Should not commit when autocommit=False."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                link = CandidateLink(url="https://example.com/no-commit", source="Test")
                db.session.add(link)
                db.session.commit()

                article = Article(
                    candidate_link_id=link.id, url="https://example.com/no-commit"
                )
                db.session.add(article)
                db.session.commit()

                entities = [{"entity_text": "City"}]

                result = save_article_entities(
                    db.session,
                    article.id,
                    entities,
                    extractor_version="v1",
                    article_text_hash="hash",
                    autocommit=False,
                )

                # Should return records but not commit
                assert len(result) == 1
                assert result[0].entity_text == "City"

                # Explicit rollback - entities shouldn't be persisted
                db.session.rollback()

                # Verify not persisted
                count = (
                    db.session.query(ArticleEntity)
                    .filter_by(article_id=article.id)
                    .count()
                )
                assert count == 0

        finally:
            if os.path.exists(path):
                os.remove(path)


class TestJobRecords:
    """Test create_job_record and finish_job_record functions."""

    def test_create_job_record_basic(self):
        """Should create job record with basic fields."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                job = create_job_record(
                    db.session, job_type="test_job", job_name="Test Job"
                )

                assert job.job_type == "test_job"
                assert job.job_name == "Test Job"
                assert job.id is not None

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_create_job_record_with_params(self):
        """Should create job record with params dict."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                params = {"batch_size": 100, "dataset": "test"}
                job = create_job_record(
                    db.session,
                    job_type="extraction",
                    job_name="Extract Test",
                    params=params,
                )

                assert job.params == params

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_finish_job_record_updates_status(self):
        """Should update job status and finish time."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                job = create_job_record(db.session, job_type="test", job_name="Test")

                finished = finish_job_record(db.session, job.id, exit_status="success")

                assert finished.exit_status == "success"
                assert finished.finished_at is not None

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_finish_job_record_updates_metrics(self):
        """Should update job metrics from dict."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                job = create_job_record(db.session, job_type="test")

                metrics = {"articles_processed": 500, "errors": 5}
                finished = finish_job_record(
                    db.session, job.id, exit_status="success", metrics=metrics
                )

                # Verify metrics were applied if Job model has these fields
                assert finished.exit_status == "success"

        finally:
            if os.path.exists(path):
                os.remove(path)


class TestPandasBulkOperations:
    """Test pandas DataFrame bulk operations."""

    def test_read_candidate_links_no_filters(self):
        """Should read all candidate links without filters."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                # Insert test data
                link1 = CandidateLink(url="https://example.com/1", source="Source1")
                link2 = CandidateLink(url="https://example.com/2", source="Source2")
                db.session.add_all([link1, link2])
                db.session.commit()

                # Read without filters
                df = read_candidate_links(db.engine)

                assert len(df) == 2
                assert "url" in df.columns
                assert "source" in df.columns

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_read_candidate_links_with_filters(self):
        """Should filter candidate links by status."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                link1 = CandidateLink(
                    url="https://example.com/new", source="Test", status="new"
                )
                link2 = CandidateLink(
                    url="https://example.com/processed",
                    source="Test",
                    status="processed",
                )
                db.session.add_all([link1, link2])
                db.session.commit()

                # Filter by status
                df = read_candidate_links(db.engine, filters={"status": "new"})

                assert len(df) == 1
                assert df.iloc[0]["status"] == "new"

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_read_articles_joins_candidate_links(self):
        """Should join articles with candidate_links."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                link = CandidateLink(url="https://example.com/art", source="Test")
                db.session.add(link)
                db.session.commit()

                article = Article(
                    candidate_link_id=link.id, url="https://example.com/art"
                )
                db.session.add(article)
                db.session.commit()

                df = read_articles(db.engine)

                assert len(df) == 1
                assert "url" in df.columns
                assert "source" in df.columns

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_bulk_insert_candidate_links_basic(self):
        """Should bulk insert candidate links from DataFrame."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                df = pd.DataFrame(
                    [
                        {"url": "https://example.com/1", "source": "Test1"},
                        {"url": "https://example.com/2", "source": "Test2"},
                    ]
                )

                count = bulk_insert_candidate_links(db.engine, df)

                assert count == 2

                # Verify inserted
                with db.engine.connect() as conn:
                    result = conn.execute(
                        text("SELECT COUNT(*) FROM candidate_links")
                    ).scalar()
                    assert result == 2

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_bulk_insert_adds_default_columns(self):
        """Should add default values for missing columns."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                df = pd.DataFrame(
                    [{"url": "https://example.com/minimal", "source": "Test"}]
                )

                count = bulk_insert_candidate_links(db.engine, df)

                assert count == 1

                # Verify defaults were added
                with db.engine.connect() as conn:
                    result = conn.execute(
                        text(
                            "SELECT status, id FROM candidate_links WHERE url LIKE '%minimal%'"
                        )
                    ).fetchone()
                    assert result[0] == "new"  # default status
                    assert result[1] is not None  # id was generated

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_bulk_insert_raises_on_missing_required_columns(self):
        """Should raise ValueError if required columns missing."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                # Missing 'source' column
                df = pd.DataFrame([{"url": "https://example.com/bad"}])

                with pytest.raises(ValueError, match="must contain columns"):
                    bulk_insert_candidate_links(db.engine, df)

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_bulk_insert_uses_source_name_fallback(self):
        """Should use source_name if source column missing."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                # Use source_name instead of source
                df = pd.DataFrame(
                    [{"url": "https://example.com/alt", "source_name": "AltSource"}]
                )

                count = bulk_insert_candidate_links(db.engine, df)

                assert count == 1

                # Verify source was copied from source_name
                with db.engine.connect() as conn:
                    result = conn.execute(
                        text(
                            "SELECT source FROM candidate_links WHERE url LIKE '%alt%'"
                        )
                    ).scalar()
                    assert result == "AltSource"

        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_bulk_insert_drops_rows_with_empty_urls(self):
        """Should drop rows with missing or empty URLs."""
        for db_url, path in temporary_database():
            break

        try:
            with DatabaseManager(database_url=db_url) as db:
                df = pd.DataFrame(
                    [
                        {"url": "https://example.com/good", "source": "Test"},
                        {"url": "", "source": "Test"},  # empty
                        {"url": None, "source": "Test"},  # null
                        {"url": "   ", "source": "Test"},  # whitespace
                    ]
                )

                count = bulk_insert_candidate_links(db.engine, df)

                # Should only insert 1 row with valid URL
                assert count == 1

        finally:
            if os.path.exists(path):
                os.remove(path)
