"""Unit tests for extraction command functionality."""

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.cli.commands.extraction import handle_extraction_command
from src.utils.content_type_detector import ContentTypeDetector


def _default_driver_stats():
    return {
        "has_persistent_driver": False,
        "driver_reuse_count": 0,
        "driver_creation_count": 0,
    }


@contextmanager
def mocked_extraction_env():
    """Provide standard patches for extraction command tests."""

    with (
        patch("src.cli.commands.extraction.DatabaseManager") as db_class,
        patch("src.cli.commands.extraction.ContentExtractor") as extractor_class,
        patch("src.cli.commands.extraction.BylineCleaner") as byline_class,
        patch(
            "src.cli.commands.extraction.ComprehensiveExtractionTelemetry"
        ) as telemetry_class,
        patch("src.cli.commands.extraction._run_post_extraction_cleaning") as cleaning,
    ):
        session = Mock()
        db = Mock()
        db.session = session
        db_class.return_value = db

        extractor = Mock()
        extractor._check_rate_limit.return_value = False
        extractor.extract_content.return_value = {}
        extractor.get_driver_stats.return_value = _default_driver_stats()
        extractor_class.return_value = extractor

        byline_cleaner = Mock()
        byline_cleaner.clean_byline.return_value = {
            "authors": [],
            "wire_services": [],
            "is_wire_content": False,
        }
        byline_class.return_value = byline_cleaner

        telemetry = Mock()
        telemetry_class.return_value = telemetry

        yield SimpleNamespace(
            db_class=db_class,
            db=db,
            session=session,
            extractor=extractor,
            byline=byline_cleaner,
            telemetry=telemetry,
            cleaning=cleaning,
        )


def _build_args():
    args = Mock()
    args.limit = 10
    args.source = None
    args.batches = 1
    return args


def test_successful_extraction_saves_to_articles_table():
    """Successful extraction should persist article data."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (
                "url-123",
                "https://example.com/article1",
                "Test Source",
                "article",
                "Example Site",
            )
        ]
        env.session.execute.return_value = mock_result
        env.extractor.extract_content.return_value = {
            "title": "Test Article Title",
            "content": "Test article content",
            "author": "Test Author",
            "publish_date": "2025-09-20T10:00:00",
            "metadata": {"source": "test"},
        }

        outcome = handle_extraction_command(args)

        assert outcome == 0
        execute_calls = env.session.execute.call_args_list
        assert len(execute_calls) >= 3
        assert env.session.commit.called
        env.session.close.assert_called()
        env.cleaning.assert_called_once()


def test_opinion_detection_sets_status():
    """Articles detected as opinion pieces should be tagged accordingly."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (
                "url-456",
                "https://example.com/opinion/column",
                "Test Source",
                "article",
                "Example Site",
            )
        ]
        env.session.execute.return_value = mock_result
        env.extractor.extract_content.return_value = {
            "title": "Opinion: Why the parks matter",
            "content": "Opinion content",
            "author": "Columnist",
            "metadata": {},
        }

        outcome = handle_extraction_command(args)

        assert outcome == 0
        execute_calls = env.session.execute.call_args_list
        assert len(execute_calls) >= 3
    # Insert call is the second call (index 1)
    insert_params = execute_calls[1].args[1]
    assert insert_params["status"] == "opinion"
    metadata_payload = json.loads(insert_params["metadata"])
    detection_meta = metadata_payload["content_type_detection"]
    assert detection_meta["status"] == "opinion"
    assert detection_meta["version"] == ContentTypeDetector.VERSION
    assert "detected_at" in detection_meta
    assert detection_meta["confidence_score"] == pytest.approx(
        4 / 6,
        rel=1e-3,
    )

    # Candidate link update call (index 2) should match
    candidate_params = execute_calls[2].args[1]
    assert candidate_params["status"] == "opinion"

    metrics_arg = env.telemetry.record_extraction.call_args_list[-1][0][0]
    detection_metrics = metrics_arg.content_type_detection
    assert detection_metrics["status"] == "opinion"
    assert detection_metrics["confidence_score"] == pytest.approx(
        4 / 6,
        rel=1e-3,
    )


def test_extraction_failure_no_content_no_database_changes():
    """Extraction without content should not write to the database."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (
                "url-123",
                "https://example.com/article1",
                "Test Source",
                "article",
                "Example Site",
            )
        ]
        env.session.execute.return_value = mock_result
        env.extractor.extract_content.return_value = {
            "title": None,
            "content": None,
        }

        outcome = handle_extraction_command(args)

        assert outcome == 0
        assert env.session.execute.call_count == 1
        env.session.commit.assert_not_called()
        env.cleaning.assert_not_called()


def test_database_error_rollback_and_no_status_update():
    """Database errors should trigger rollback without commits."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (
                "url-123",
                "https://example.com/article1",
                "Test Source",
                "article",
                "Example Site",
            )
        ]
        env.session.execute.side_effect = [
            mock_result,
            sqlite3.OperationalError("database is locked"),
        ]
        env.extractor.extract_content.return_value = {
            "title": "Test Article Title",
            "content": "Test article content",
            "author": "Test Author",
            "publish_date": "2025-09-20T10:00:00",
            "metadata": {"source": "test"},
        }

        outcome = handle_extraction_command(args)

        assert outcome == 0
        env.session.rollback.assert_called()
        env.session.commit.assert_not_called()
        env.cleaning.assert_not_called()


def test_foreign_key_constraint_violation_rollback():
    """Foreign key errors should roll back without committing."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (
                "invalid-url-id",
                "https://example.com/article1",
                "Test Source",
                "article",
                "Example Site",
            )
        ]
        env.session.execute.side_effect = [
            mock_result,
            sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
        ]
        env.extractor.extract_content.return_value = {
            "title": "Test Article Title",
            "content": "Test article content",
            "author": "Test Author",
            "publish_date": "2025-09-20T10:00:00",
            "metadata": {"source": "test"},
        }

        outcome = handle_extraction_command(args)

        assert outcome == 0
        env.session.rollback.assert_called()
        env.session.commit.assert_not_called()
        env.cleaning.assert_not_called()


def test_duplicate_article_constraint_rollback():
    """Duplicate article errors should roll back without committing."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (
                "url-123",
                "https://example.com/article1",
                "Test Source",
                "article",
                "Example Site",
            )
        ]
        env.session.execute.side_effect = [
            mock_result,
            sqlite3.IntegrityError("UNIQUE constraint failed: articles.id"),
        ]
        env.extractor.extract_content.return_value = {
            "title": "Test Article Title",
            "content": "Test article content",
            "author": "Test Author",
            "publish_date": "2025-09-20T10:00:00",
            "metadata": {"source": "test"},
        }

        outcome = handle_extraction_command(args)

        assert outcome == 0
        env.session.rollback.assert_called()
        env.session.commit.assert_not_called()
        env.cleaning.assert_not_called()


def test_no_articles_found_returns_gracefully():
    """Gracefully handle empty candidate result sets."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        env.session.execute.return_value = mock_result

        outcome = handle_extraction_command(args)

        assert outcome == 0
        env.session.close.assert_called()
        env.cleaning.assert_not_called()


def test_database_manager_exception_returns_error():
    """Errors creating the database manager should bubble up as failures."""

    args = _build_args()

    with mocked_extraction_env() as env:
        env.db_class.side_effect = Exception("Database connection failed")

        outcome = handle_extraction_command(args)

        assert outcome == 1
        env.cleaning.assert_not_called()
        env.session.commit.assert_not_called()


def test_content_extraction_exception_handling():
    """Extraction exceptions should roll back and continue."""

    args = _build_args()

    with mocked_extraction_env() as env:
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (
                "url-123",
                "https://example.com/article1",
                "Test Source",
                "article",
                "Example Site",
            )
        ]
        env.session.execute.return_value = mock_result
        env.extractor.extract_content.side_effect = Exception("Network error")

        outcome = handle_extraction_command(args)

        assert outcome == 0
        assert env.session.execute.call_count == 1
        env.session.rollback.assert_called()
        env.session.commit.assert_not_called()
        env.cleaning.assert_not_called()
