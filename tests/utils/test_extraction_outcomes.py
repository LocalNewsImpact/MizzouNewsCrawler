"""Tests for extraction outcomes module."""

from datetime import datetime

import pytest

from src.utils.extraction_outcomes import ExtractionOutcome, ExtractionResult


class TestExtractionResult:
    """Test ExtractionResult dataclass properties."""

    def test_is_content_success_true(self):
        """Test is_content_success returns True for CONTENT_EXTRACTED."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.CONTENT_EXTRACTED,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        assert result.is_content_success is True

    def test_is_content_success_false(self):
        """Test is_content_success returns False for partial content."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.PARTIAL_CONTENT,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        assert result.is_content_success is False

    def test_is_technical_failure_http_error(self):
        """Test is_technical_failure returns True for HTTP errors."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.HTTP_ERROR,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        assert result.is_technical_failure is True

    def test_is_technical_failure_timeout(self):
        """Test is_technical_failure returns True for timeouts."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.TIMEOUT,
            extraction_time_ms=5000,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        assert result.is_technical_failure is True

    def test_is_bot_protection_cloudflare(self):
        """Test is_bot_protection returns True for Cloudflare blocks."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.CLOUDFLARE_BLOCKED,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        assert result.is_bot_protection is True

    def test_is_bot_protection_captcha(self):
        """Test is_bot_protection returns True for CAPTCHA."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.CAPTCHA_REQUIRED,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        assert result.is_bot_protection is True

    def test_content_quality_score_full( self):
        """Test content quality score with all fields present."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.CONTENT_EXTRACTED,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
            has_title=True,
            has_content=True,
            has_author=True,
            has_publish_date=True,
        )
        assert result.content_quality_score == 1.0

    def test_content_quality_score_partial(self):
        """Test content quality score with some fields missing."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.CONTENT_EXTRACTED,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
            has_title=True,
            has_content=True,
            has_author=False,
            has_publish_date=False,
        )
        assert result.content_quality_score == 0.5

    def test_content_quality_score_failure(self):
        """Test content quality score returns 0 for failures."""
        result = ExtractionResult(
            url="https://example.com/article",
            article_id=1,
            operation_id="test-123",
            outcome=ExtractionOutcome.HTTP_ERROR,
            extraction_time_ms=100,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        assert result.content_quality_score == 0.0
