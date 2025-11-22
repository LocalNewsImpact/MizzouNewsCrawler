"""Structured logging configuration for MizzouNewsCrawler.

This module sets up structured logging with:
- JSON output for production (Cloud Logging compatible)
- Human-readable output for local development
- Trace ID correlation for request tracking
- Integration with Google Cloud Logging
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def is_cloud_environment() -> bool:
    """Check if running in a cloud environment (GKE, Cloud Run, etc.)."""
    return bool(
        os.getenv("KUBERNETES_SERVICE_HOST")
        or os.getenv("K_SERVICE")  # Cloud Run
        or os.getenv("GAE_ENV")  # App Engine
    )


def setup_logging(
    level: str = "INFO",
    force_json: bool = False,
    service_name: str | None = None,
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        force_json: Force JSON output even in non-cloud environments
        service_name: Name of the service for log identification
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Determine output format based on environment
    use_json = force_json or is_cloud_environment()

    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    # Add service name if provided
    if service_name:
        processors.insert(
            0,
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
        )

    # Add appropriate renderer based on environment
    if use_json:
        # JSON output for production/cloud environments
        processors.extend(
            [
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ]
        )
    else:
        # Human-readable output for local development
        processors.extend(
            [
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
            ]
        )

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )

    # Set log level for structlog
    logging.getLogger().setLevel(log_level)

    # Reduce noise from verbose libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("google.cloud").setLevel(logging.INFO)


def get_logger(name: str | None = None) -> Any:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__ of the calling module)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


def bind_trace_context(trace_id: str | None = None, span_id: str | None = None) -> None:
    """Bind trace context to current execution context.

    This allows correlation of logs with distributed traces.

    Args:
        trace_id: Trace ID from Cloud Trace or custom tracing
        span_id: Span ID for the current operation
    """
    context = {}
    if trace_id:
        context["trace_id"] = trace_id
    if span_id:
        context["span_id"] = span_id

    if context:
        structlog.contextvars.bind_contextvars(**context)


def unbind_trace_context() -> None:
    """Clear trace context from current execution context."""
    structlog.contextvars.clear_contextvars()


def bind_request_context(
    request_id: str | None = None,
    user_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Bind request context to current execution context.

    Args:
        request_id: Unique request identifier
        user_id: User identifier for the request
        **kwargs: Additional context to bind
    """
    context = {}
    if request_id:
        context["request_id"] = request_id
    if user_id:
        context["user_id"] = user_id
    context.update(kwargs)

    if context:
        structlog.contextvars.bind_contextvars(**context)
