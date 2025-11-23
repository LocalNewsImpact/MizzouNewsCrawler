"""Custom metrics client for Google Cloud Monitoring.

This module provides a simple interface for emitting custom metrics to
Google Cloud Monitoring (formerly Stackdriver).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

try:
    from google.api import distribution_pb2
    from google.api import label_pb2 as ga_label
    from google.api import metric_pb2 as ga_metric
    from google.cloud import monitoring_v3  # type: ignore[attr-defined]

    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False
    monitoring_v3 = None  # type: ignore
    ga_metric = None  # type: ignore
    ga_label = None  # type: ignore
    distribution_pb2 = None  # type: ignore

logger = logging.getLogger(__name__)


class MetricsClient:
    """Client for emitting custom metrics to Cloud Monitoring."""

    def __init__(
        self,
        project_id: str | None = None,
        service_name: str = "mizzou-news-crawler",
        enabled: bool = True,
    ):
        """Initialize metrics client.

        Args:
            project_id: GCP project ID. Auto-detected if None.
            service_name: Service name for metric labeling
            enabled: Whether to emit metrics (disable in tests/local dev)
        """
        self.project_id = (
            project_id or os.getenv("GCP_PROJECT_ID") or "mizzou-news-crawler"
        )
        self.service_name = service_name
        self.enabled = enabled and MONITORING_AVAILABLE

        if not MONITORING_AVAILABLE:
            logger.warning(
                "Google Cloud Monitoring not available. Install google-cloud-monitoring."
            )
            self.enabled = False

        if self.enabled:
            try:
                self.client = monitoring_v3.MetricServiceClient()
                self.project_name = f"projects/{self.project_id}"
            except Exception as e:
                logger.warning(f"Failed to initialize Cloud Monitoring client: {e}")
                self.enabled = False

        # Resource labels for Kubernetes environment
        self.resource_labels = self._get_resource_labels()

    def _get_resource_labels(self) -> dict[str, str]:
        """Get resource labels from environment."""
        return {
            "project_id": self.project_id,
            "cluster_name": os.getenv("CLUSTER_NAME") or "mizzou-cluster",
            "namespace_name": os.getenv("NAMESPACE") or "production",
            "pod_name": os.getenv("HOSTNAME") or "unknown",
        }

    def record_counter(
        self,
        metric_name: str,
        value: int,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Record a counter metric.

        Args:
            metric_name: Name of the metric (e.g., 'articles_discovered')
            value: Integer value to record
            labels: Additional metric labels
        """
        if not self.enabled:
            return

        try:
            series = monitoring_v3.TimeSeries()
            series.metric.type = f"custom.googleapis.com/{metric_name}"

            # Add metric labels
            if labels:
                for key, val in labels.items():
                    series.metric.labels[key] = str(val)

            # Set resource type and labels
            series.resource.type = "k8s_pod"
            series.resource.labels.update(self.resource_labels)

            # Set the data point
            now = time.time()
            seconds = int(now)
            nanos = int((now - seconds) * 10**9)

            interval = monitoring_v3.TimeInterval(
                {"end_time": {"seconds": seconds, "nanos": nanos}}
            )
            point = monitoring_v3.Point(
                {"interval": interval, "value": {"int64_value": value}}
            )
            series.points = [point]

            # Write to Cloud Monitoring
            self.client.create_time_series(name=self.project_name, time_series=[series])

            logger.debug(f"Recorded metric {metric_name}={value} labels={labels}")

        except Exception as e:
            logger.error(f"Failed to record metric {metric_name}: {e}")

    def record_gauge(
        self,
        metric_name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Record a gauge metric (current value).

        Args:
            metric_name: Name of the metric (e.g., 'queue_depth')
            value: Float value to record
            labels: Additional metric labels
        """
        if not self.enabled:
            return

        try:
            series = monitoring_v3.TimeSeries()
            series.metric.type = f"custom.googleapis.com/{metric_name}"

            # Add metric labels
            if labels:
                for key, val in labels.items():
                    series.metric.labels[key] = str(val)

            # Set resource type and labels
            series.resource.type = "k8s_pod"
            series.resource.labels.update(self.resource_labels)

            # Set the data point
            now = time.time()
            seconds = int(now)
            nanos = int((now - seconds) * 10**9)

            interval = monitoring_v3.TimeInterval(
                {"end_time": {"seconds": seconds, "nanos": nanos}}
            )
            point = monitoring_v3.Point(
                {"interval": interval, "value": {"double_value": value}}
            )
            series.points = [point]

            # Write to Cloud Monitoring
            self.client.create_time_series(name=self.project_name, time_series=[series])

            logger.debug(f"Recorded gauge {metric_name}={value} labels={labels}")

        except Exception as e:
            logger.error(f"Failed to record gauge {metric_name}: {e}")

    def record_distribution(
        self,
        metric_name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Record a distribution metric (for percentiles, histograms).

        Args:
            metric_name: Name of the metric (e.g., 'processing_time_seconds')
            value: Float value to record
            labels: Additional metric labels
        """
        if not self.enabled:
            return

        try:
            series = monitoring_v3.TimeSeries()
            series.metric.type = f"custom.googleapis.com/{metric_name}"

            # Add metric labels
            if labels:
                for key, val in labels.items():
                    series.metric.labels[key] = str(val)

            # Set resource type and labels
            series.resource.type = "k8s_pod"
            series.resource.labels.update(self.resource_labels)

            # Set the data point
            now = time.time()
            seconds = int(now)
            nanos = int((now - seconds) * 10**9)

            interval = monitoring_v3.TimeInterval(
                {"end_time": {"seconds": seconds, "nanos": nanos}}
            )

            # Create a simple distribution with a single value
            # Cloud Monitoring will aggregate these into percentiles
            distribution = distribution_pb2.Distribution(
                count=1,
                mean=value,
                sum_of_squared_deviation=0.0,
            )

            point = monitoring_v3.Point(
                {"interval": interval, "value": {"distribution_value": distribution}}
            )
            series.points = [point]

            # Write to Cloud Monitoring
            self.client.create_time_series(name=self.project_name, time_series=[series])

            logger.debug(f"Recorded distribution {metric_name}={value} labels={labels}")

        except Exception as e:
            logger.error(f"Failed to record distribution {metric_name}: {e}")

    def record_articles_discovered(self, count: int, source: str | None = None) -> None:
        """Record articles discovered metric.

        Args:
            count: Number of articles discovered
            source: Source hostname (optional)
        """
        labels = {}
        if source:
            labels["source"] = source

        self.record_counter("articles_discovered", count, labels)

    def record_articles_extracted(
        self, count: int, source: str | None = None, success: bool = True
    ) -> None:
        """Record articles extracted metric.

        Args:
            count: Number of articles extracted
            source: Source hostname (optional)
            success: Whether extraction was successful
        """
        labels = {"success": str(success).lower()}
        if source:
            labels["source"] = source

        self.record_counter("articles_extracted", count, labels)

    def record_pipeline_success_rate(self, stage: str, success_rate: float) -> None:
        """Record pipeline success rate metric.

        Args:
            stage: Pipeline stage (discovery, extraction, analysis)
            success_rate: Success rate as a float (0.0 to 1.0)
        """
        labels = {"stage": stage}
        self.record_gauge("pipeline_success_rate", success_rate, labels)

    def record_processing_time(self, stage: str, duration_seconds: float) -> None:
        """Record processing time metric.

        Args:
            stage: Pipeline stage (discovery, extraction, analysis)
            duration_seconds: Duration in seconds
        """
        labels = {"stage": stage}
        self.record_distribution("processing_time_seconds", duration_seconds, labels)

    def record_queue_depth(self, queue_name: str, depth: int) -> None:
        """Record queue depth metric.

        Args:
            queue_name: Name of the queue
            depth: Current queue depth
        """
        labels = {"queue": queue_name}
        self.record_gauge("queue_depth", float(depth), labels)


# Global metrics client instance
_metrics_client: Optional[MetricsClient] = None


def get_metrics_client(
    project_id: str | None = None,
    service_name: str = "mizzou-news-crawler",
    enabled: bool = True,
) -> MetricsClient:
    """Get or create the global metrics client.

    Args:
        project_id: GCP project ID
        service_name: Service name for metric labeling
        enabled: Whether to emit metrics

    Returns:
        MetricsClient instance
    """
    global _metrics_client

    # Check if metrics should be disabled based on environment
    if os.getenv("DISABLE_METRICS", "").lower() in ("true", "1", "yes"):
        enabled = False

    if _metrics_client is None:
        _metrics_client = MetricsClient(
            project_id=project_id,
            service_name=service_name,
            enabled=enabled,
        )

    return _metrics_client
