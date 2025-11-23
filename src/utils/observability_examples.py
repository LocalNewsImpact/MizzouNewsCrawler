"""Example: Integrating observability into pipeline stages.

This module demonstrates how to add structured logging and custom metrics
to discovery, extraction, and processing pipeline stages.

Usage in your CLI commands or pipeline code:

```python
from src.utils.observability_examples import (
    log_discovery_stage,
    log_extraction_stage,
    log_processing_stage,
)

# In discovery command
articles = discover_articles(source)
log_discovery_stage(source, len(articles), duration)

# In extraction command
result = extract_article(url)
log_extraction_stage(url, result, duration)

# In processing command
process_articles(articles)
log_processing_stage("entity_extraction", len(articles), duration)
```
"""

from __future__ import annotations

import time
from typing import Any

from src.utils.logging_config import get_logger
from src.utils.metrics import get_metrics_client

logger = get_logger(__name__)
metrics = get_metrics_client()


def log_discovery_stage(
    source: str,
    articles_found: int,
    duration_seconds: float,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Log and emit metrics for article discovery stage.

    Args:
        source: Source hostname (e.g., "example.com")
        articles_found: Number of articles discovered
        duration_seconds: Time taken for discovery
        success: Whether discovery succeeded
        error: Error message if failed
    """
    # Structured logging
    if success:
        logger.info(
            "discovery_complete",
            source=source,
            articles_found=articles_found,
            duration_seconds=duration_seconds,
        )
    else:
        logger.error(
            "discovery_failed",
            source=source,
            duration_seconds=duration_seconds,
            error=error,
        )

    # Custom metrics
    if success and articles_found > 0:
        metrics.record_articles_discovered(
            count=articles_found,
            source=source,
        )

    metrics.record_processing_time(
        stage="discovery",
        duration_seconds=duration_seconds,
    )

    # Record success rate (1.0 for success, 0.0 for failure)
    success_rate = 1.0 if success else 0.0
    metrics.record_pipeline_success_rate(
        stage="discovery",
        success_rate=success_rate,
    )


def log_extraction_stage(
    url: str,
    extraction_result: dict[str, Any],
    duration_seconds: float,
    source: str | None = None,
) -> None:
    """Log and emit metrics for article extraction stage.

    Args:
        url: Article URL
        extraction_result: Dictionary with extraction results
        duration_seconds: Time taken for extraction
        source: Source hostname (optional)
    """
    success = extraction_result.get("success", False)
    error = extraction_result.get("error")

    # Structured logging
    if success:
        logger.info(
            "extraction_complete",
            url=url,
            source=source or extraction_result.get("source"),
            duration_seconds=duration_seconds,
            method=extraction_result.get("method"),
            content_length=len(extraction_result.get("text", "")),
        )
    else:
        logger.error(
            "extraction_failed",
            url=url,
            source=source or extraction_result.get("source"),
            duration_seconds=duration_seconds,
            error=error,
        )

    # Custom metrics
    metrics.record_articles_extracted(
        count=1,
        source=source or extraction_result.get("source"),
        success=success,
    )

    metrics.record_processing_time(
        stage="extraction",
        duration_seconds=duration_seconds,
    )

    # Record success rate
    success_rate = 1.0 if success else 0.0
    metrics.record_pipeline_success_rate(
        stage="extraction",
        success_rate=success_rate,
    )


def log_processing_stage(
    stage_name: str,
    items_processed: int,
    duration_seconds: float,
    success_count: int | None = None,
    error_count: int | None = None,
) -> None:
    """Log and emit metrics for processing stages (entity extraction, classification, etc.).

    Args:
        stage_name: Name of the processing stage (e.g., "entity_extraction", "classification")
        items_processed: Total number of items processed
        duration_seconds: Time taken for processing
        success_count: Number of successfully processed items
        error_count: Number of failed items
    """
    success_count = success_count or items_processed
    error_count = error_count or 0

    # Structured logging
    logger.info(
        "processing_complete",
        stage=stage_name,
        items_processed=items_processed,
        success_count=success_count,
        error_count=error_count,
        duration_seconds=duration_seconds,
    )

    # Custom metrics
    metrics.record_processing_time(
        stage=stage_name,
        duration_seconds=duration_seconds,
    )

    # Record success rate
    if items_processed > 0:
        success_rate = success_count / items_processed
        metrics.record_pipeline_success_rate(
            stage=stage_name,
            success_rate=success_rate,
        )


def log_queue_status(queue_name: str, depth: int) -> None:
    """Log and emit metrics for queue depth.

    Args:
        queue_name: Name of the queue (e.g., "verification_pending", "extraction_pending")
        depth: Current queue depth
    """
    logger.debug("queue_status", queue=queue_name, depth=depth)

    metrics.record_queue_depth(
        queue_name=queue_name,
        depth=depth,
    )


class PipelineStageTimer:
    """Context manager for timing pipeline stages with automatic logging and metrics.

    Usage:
        with PipelineStageTimer("discovery", source="example.com") as timer:
            articles = discover_articles(source)
            timer.set_result(articles_found=len(articles))
    """

    def __init__(self, stage: str, **context: Any):
        """Initialize timer.

        Args:
            stage: Pipeline stage name
            **context: Additional context to log
        """
        self.stage = stage
        self.context = context
        self.start_time: float | None = None
        self.result: dict[str, Any] = {}

    def __enter__(self) -> PipelineStageTimer:
        """Start timing."""
        self.start_time = time.time()
        logger.debug(f"{self.stage}_started", **self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timing and log results."""
        if self.start_time is None:
            return

        duration = time.time() - self.start_time

        # Log completion
        if exc_type is None:
            logger.info(
                f"{self.stage}_complete",
                duration_seconds=duration,
                **self.context,
                **self.result,
            )
            success = True
        else:
            logger.error(
                f"{self.stage}_failed",
                duration_seconds=duration,
                error=str(exc_val),
                **self.context,
                exc_info=True,
            )
            success = False

        # Record metrics
        metrics.record_processing_time(
            stage=self.stage,
            duration_seconds=duration,
        )

        success_rate = 1.0 if success else 0.0
        metrics.record_pipeline_success_rate(
            stage=self.stage,
            success_rate=success_rate,
        )

    def set_result(self, **result: Any) -> None:
        """Set result data to include in logs.

        Args:
            **result: Result data to log
        """
        self.result.update(result)


# Example usage functions for documentation


def example_discovery_integration():
    """Example: Integrate observability into discovery command.

    This shows how to add logging and metrics to the discovery pipeline.
    """
    source = "example.com"

    # Method 1: Manual logging
    start = time.time()
    try:
        articles = ["url1", "url2", "url3"]  # Simulated discovery
        duration = time.time() - start

        log_discovery_stage(
            source=source,
            articles_found=len(articles),
            duration_seconds=duration,
            success=True,
        )
    except Exception as e:
        duration = time.time() - start
        log_discovery_stage(
            source=source,
            articles_found=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )
        raise

    # Method 2: Using context manager
    with PipelineStageTimer("discovery", source=source) as timer:
        articles = ["url1", "url2", "url3"]  # Simulated discovery
        timer.set_result(articles_found=len(articles))


def example_extraction_integration():
    """Example: Integrate observability into extraction command.

    This shows how to add logging and metrics to the extraction pipeline.
    """
    url = "https://example.com/article1"

    # Method 1: Manual logging
    start = time.time()
    result = {
        "success": True,
        "source": "example.com",
        "method": "trafilatura",
        "text": "Article content...",
    }
    duration = time.time() - start

    log_extraction_stage(
        url=url,
        extraction_result=result,
        duration_seconds=duration,
    )

    # Method 2: Using context manager
    with PipelineStageTimer("extraction", url=url) as timer:
        result = {"success": True, "text": "Article content..."}
        timer.set_result(
            method="trafilatura",
            content_length=len(result["text"]),
        )


def example_processing_integration():
    """Example: Integrate observability into processing commands.

    This shows how to add logging and metrics to entity extraction,
    classification, and other processing stages.
    """
    # Entity extraction
    start = time.time()
    articles = ["article1", "article2", "article3"]
    success_count = 3
    error_count = 0
    duration = time.time() - start

    log_processing_stage(
        stage_name="entity_extraction",
        items_processed=len(articles),
        duration_seconds=duration,
        success_count=success_count,
        error_count=error_count,
    )

    # Using context manager
    with PipelineStageTimer("entity_extraction") as timer:
        # Process articles...
        timer.set_result(items_processed=len(articles))


def example_queue_monitoring():
    """Example: Monitor queue depths.

    This shows how to emit queue depth metrics.
    """
    # Get queue depths from database
    verification_pending = 1234
    extraction_pending = 567
    analysis_pending = 89

    log_queue_status("verification_pending", verification_pending)
    log_queue_status("extraction_pending", extraction_pending)
    log_queue_status("analysis_pending", analysis_pending)
