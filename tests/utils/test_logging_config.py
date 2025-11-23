"""Tests for structured logging configuration."""

import os
import logging
from io import StringIO
import sys

import pytest

from src.utils.logging_config import (
    setup_logging,
    get_logger,
    bind_trace_context,
    unbind_trace_context,
    bind_request_context,
    is_cloud_environment,
)


def test_is_cloud_environment_local():
    """Test cloud environment detection returns False locally."""
    # Ensure no cloud environment variables are set
    for var in ["KUBERNETES_SERVICE_HOST", "K_SERVICE", "GAE_ENV"]:
        os.environ.pop(var, None)

    assert is_cloud_environment() is False


def test_is_cloud_environment_kubernetes():
    """Test cloud environment detection for Kubernetes."""
    os.environ["KUBERNETES_SERVICE_HOST"] = "10.0.0.1"
    try:
        assert is_cloud_environment() is True
    finally:
        os.environ.pop("KUBERNETES_SERVICE_HOST", None)


def test_setup_logging_basic():
    """Test basic logging setup."""
    setup_logging(level="INFO")

    # Verify logging is configured
    logger = logging.getLogger()
    assert logger.level == logging.INFO


def test_setup_logging_debug_level():
    """Test logging setup with DEBUG level."""
    setup_logging(level="DEBUG")

    logger = logging.getLogger()
    assert logger.level == logging.DEBUG


def test_setup_logging_json_output():
    """Test JSON output format is enabled."""
    # Force JSON output
    setup_logging(level="INFO", force_json=True)

    # Verify setup doesn't raise errors
    logger = get_logger(__name__)
    logger.info("test_event", key="value")


def test_get_logger():
    """Test getting a logger instance."""
    logger = get_logger(__name__)

    assert logger is not None
    assert hasattr(logger, "info")
    assert hasattr(logger, "error")
    assert hasattr(logger, "warning")


def test_get_logger_with_name():
    """Test getting a named logger."""
    logger = get_logger("test_module")

    assert logger is not None


def test_bind_trace_context():
    """Test binding trace context."""
    bind_trace_context(trace_id="abc123", span_id="def456")

    # Context binding should not raise errors
    logger = get_logger(__name__)
    logger.info("test_with_trace")

    unbind_trace_context()


def test_bind_trace_context_partial():
    """Test binding trace context with only trace_id."""
    bind_trace_context(trace_id="abc123")

    logger = get_logger(__name__)
    logger.info("test_with_trace_only")

    unbind_trace_context()


def test_bind_request_context():
    """Test binding request context."""
    bind_request_context(request_id="req-123", user_id="user-456", endpoint="/api/test")

    logger = get_logger(__name__)
    logger.info("test_with_request_context")

    unbind_trace_context()


def test_bind_request_context_minimal():
    """Test binding request context with minimal fields."""
    bind_request_context(request_id="req-123")

    logger = get_logger(__name__)
    logger.info("test_minimal_context")

    unbind_trace_context()


def test_logging_with_structured_data():
    """Test logging with structured data."""
    setup_logging(level="INFO", force_json=True)
    logger = get_logger(__name__)

    # Log with structured data
    logger.info(
        "article_extracted", article_id=12345, source="example.com", duration_ms=1234.5
    )


def test_logging_error_with_exception():
    """Test logging errors with exception info."""
    setup_logging(level="INFO")
    logger = get_logger(__name__)

    try:
        raise ValueError("Test error")
    except ValueError:
        logger.error("error_occurred", error_type="ValueError", exc_info=True)


def test_unbind_trace_context():
    """Test unbinding trace context."""
    bind_trace_context(trace_id="abc123")
    unbind_trace_context()

    # Should not raise errors
    logger = get_logger(__name__)
    logger.info("test_after_unbind")
