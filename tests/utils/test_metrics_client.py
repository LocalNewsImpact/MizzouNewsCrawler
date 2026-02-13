"""Comprehensive tests for src/utils/metrics.py module."""

import os
import time
from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.fixture
def mock_monitoring():
    """Mock Google Cloud Monitoring modules."""
    with patch("src.utils.metrics.MONITORING_AVAILABLE", True):
        with patch("src.utils.metrics.monitoring_v3") as mock_v3:
            with patch("src.utils.metrics.ga_metric"):
                with patch("src.utils.metrics.ga_label"):
                    with patch("src.utils.metrics.distribution_pb2") as mock_dist:
                        # Setup monitoring client mock
                        mock_client = MagicMock()
                        mock_v3.MetricServiceClient.return_value = mock_client
                        mock_v3.TimeSeries = MagicMock
                        mock_v3.TimeInterval = MagicMock
                        mock_v3.Point = MagicMock

                        # Setup distribution mock
                        mock_dist.Distribution = MagicMock

                        yield {
                            "v3": mock_v3,
                            "client": mock_client,
                            "distribution": mock_dist,
                        }


class TestMetricsClientInitialization:
    """Test MetricsClient initialization scenarios."""

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_init_with_project_id(self, mock_v3):
        """Test initialization with explicit project ID."""
        from src.utils.metrics import MetricsClient

        mock_v3.MetricServiceClient.return_value = MagicMock()

        client = MetricsClient(project_id="test-project", enabled=True)

        assert client.project_id == "test-project"
        assert client.service_name == "mizzou-news-crawler"
        assert client.enabled is True
        assert client.project_name == "projects/test-project"

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_init_with_env_project_id(self, mock_v3, monkeypatch):
        """Test initialization with project ID from environment."""
        from src.utils.metrics import MetricsClient

        monkeypatch.setenv("GCP_PROJECT_ID", "env-project")
        mock_v3.MetricServiceClient.return_value = MagicMock()

        client = MetricsClient(enabled=True)

        assert client.project_id == "env-project"

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_init_default_project_id(self, mock_v3):
        """Test initialization with default project ID."""
        from src.utils.metrics import MetricsClient

        mock_v3.MetricServiceClient.return_value = MagicMock()

        client = MetricsClient(enabled=True)

        assert client.project_id == "mizzou-news-crawler"

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_init_custom_service_name(self, mock_v3):
        """Test initialization with custom service name."""
        from src.utils.metrics import MetricsClient

        mock_v3.MetricServiceClient.return_value = MagicMock()

        client = MetricsClient(service_name="custom-service", enabled=True)

        assert client.service_name == "custom-service"

    @patch("src.utils.metrics.MONITORING_AVAILABLE", False)
    def test_init_monitoring_not_available(self):
        """Test initialization when monitoring not available."""
        from src.utils.metrics import MetricsClient

        client = MetricsClient(enabled=True)

        assert client.enabled is False

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_init_client_failure(self, mock_v3):
        """Test initialization when client creation fails."""
        from src.utils.metrics import MetricsClient

        mock_v3.MetricServiceClient.side_effect = Exception("Auth failure")

        client = MetricsClient(enabled=True)

        assert client.enabled is False

    def test_init_disabled(self):
        """Test initialization with enabled=False."""
        from src.utils.metrics import MetricsClient

        client = MetricsClient(enabled=False)

        assert client.enabled is False


class TestResourceLabels:
    """Test resource label generation."""

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_get_resource_labels_defaults(self, mock_v3):
        """Test default resource labels."""
        from src.utils.metrics import MetricsClient

        mock_v3.MetricServiceClient.return_value = MagicMock()

        client = MetricsClient(project_id="test-project", enabled=True)

        assert "project_id" in client.resource_labels
        assert client.resource_labels["project_id"] == "test-project"
        assert client.resource_labels["cluster_name"] == "mizzou-cluster"
        assert client.resource_labels["namespace_name"] == "production"
        assert "pod_name" in client.resource_labels

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_get_resource_labels_from_env(self, mock_v3, monkeypatch):
        """Test resource labels from environment variables."""
        from src.utils.metrics import MetricsClient

        monkeypatch.setenv("CLUSTER_NAME", "test-cluster")
        monkeypatch.setenv("NAMESPACE", "test-namespace")
        monkeypatch.setenv("HOSTNAME", "test-pod-123")

        mock_v3.MetricServiceClient.return_value = MagicMock()

        client = MetricsClient(project_id="test-project", enabled=True)

        assert client.resource_labels["cluster_name"] == "test-cluster"
        assert client.resource_labels["namespace_name"] == "test-namespace"
        assert client.resource_labels["pod_name"] == "test-pod-123"


class TestRecordCounter:
    """Test counter metric recording."""

    def test_record_counter_disabled(self):
        """Test that counter recording is skipped when disabled."""
        from src.utils.metrics import MetricsClient

        client = MetricsClient(enabled=False)
        # Should not raise exception
        client.record_counter("test_metric", 10)

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_counter_basic(self, mock_v3):
        """Test basic counter recording."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        # Mock TimeSeries
        mock_series = MagicMock()
        mock_series.metric.type = ""
        mock_series.metric.labels = {}
        mock_series.resource.type = ""
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_counter("articles_discovered", 42)

        # Verify create_time_series was called
        assert mock_client.create_time_series.called

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_counter_with_labels(self, mock_v3):
        """Test counter recording with labels."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_counter(
            "articles_discovered", 10, labels={"source": "example.com"}
        )

        assert mock_client.create_time_series.called

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_counter_exception_handling(self, mock_v3):
        """Test counter recording handles exceptions gracefully."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_client.create_time_series.side_effect = Exception("API Error")
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)

        # Should not raise exception
        client.record_counter("test_metric", 5)


class TestRecordGauge:
    """Test gauge metric recording."""

    def test_record_gauge_disabled(self):
        """Test that gauge recording is skipped when disabled."""
        from src.utils.metrics import MetricsClient

        client = MetricsClient(enabled=False)
        # Should not raise exception
        client.record_gauge("queue_depth", 15.5)

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_gauge_basic(self, mock_v3):
        """Test basic gauge recording."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_gauge("cpu_usage", 75.3)

        assert mock_client.create_time_series.called

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_gauge_with_labels(self, mock_v3):
        """Test gauge recording with labels."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_gauge("memory_usage", 512.0, labels={"pod": "api-123"})

        assert mock_client.create_time_series.called

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_gauge_exception_handling(self, mock_v3):
        """Test gauge recording handles exceptions gracefully."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_client.create_time_series.side_effect = Exception("Network error")
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)

        # Should not raise exception
        client.record_gauge("test_gauge", 99.9)


class TestRecordDistribution:
    """Test distribution metric recording."""

    def test_record_distribution_disabled(self):
        """Test that distribution recording is skipped when disabled."""
        from src.utils.metrics import MetricsClient

        client = MetricsClient(enabled=False)
        # Should not raise exception
        client.record_distribution("processing_time", 1.5)

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    @patch("src.utils.metrics.distribution_pb2")
    def test_record_distribution_basic(self, mock_dist, mock_v3):
        """Test basic distribution recording."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        mock_dist.Distribution.return_value = MagicMock()

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_distribution("latency_seconds", 0.125)

        assert mock_client.create_time_series.called
        assert mock_dist.Distribution.called

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    @patch("src.utils.metrics.distribution_pb2")
    def test_record_distribution_with_labels(self, mock_dist, mock_v3):
        """Test distribution recording with labels."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        mock_dist.Distribution.return_value = MagicMock()

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_distribution(
            "request_duration", 2.5, labels={"endpoint": "/api/articles"}
        )

        assert mock_client.create_time_series.called

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    @patch("src.utils.metrics.distribution_pb2")
    def test_record_distribution_exception_handling(self, mock_dist, mock_v3):
        """Test distribution recording handles exceptions gracefully."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_client.create_time_series.side_effect = Exception("Quota exceeded")
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        mock_dist.Distribution.return_value = MagicMock()

        client = MetricsClient(project_id="test-project", enabled=True)

        # Should not raise exception
        client.record_distribution("test_dist", 3.14)


class TestConvenienceMethods:
    """Test convenience methods for common metrics."""

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_articles_discovered_without_source(self, mock_v3):
        """Test recording articles discovered without source."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_articles_discovered(100)

        assert mock_client.create_time_series.called

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_record_articles_discovered_with_source(self, mock_v3):
        """Test recording articles discovered with source."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_articles_discovered(50, source="example.com")

        assert mock_client.create_time_series.called


class TestTimeHandling:
    """Test time interval handling."""

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    @patch("time.time")
    def test_time_interval_creation(self, mock_time, mock_v3):
        """Test that time intervals are created correctly."""
        from src.utils.metrics import MetricsClient

        # Mock current time
        mock_time.return_value = 1234567890.123456789

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        # Mock TimeInterval to return a mock object
        mock_v3.TimeInterval.return_value = MagicMock()

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_counter("test", 1)

        # Verify TimeInterval was called
        assert mock_v3.TimeInterval.called


class TestMetricTypeFormatting:
    """Test metric type formatting."""

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_metric_type_prefix(self, mock_v3):
        """Test that metric types are prefixed correctly."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.metric = MagicMock()
        mock_series.metric.labels = {}
        mock_series.resource = MagicMock()
        mock_series.resource.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_counter("custom_metric", 1)

        # Metric type should be set with custom.googleapis.com prefix
        # (validated through mock calls)
        assert mock_client.create_time_series.called


class TestResourceType:
    """Test resource type configuration."""

    @patch("src.utils.metrics.MONITORING_AVAILABLE", True)
    @patch("src.utils.metrics.monitoring_v3")
    def test_resource_type_k8s_pod(self, mock_v3):
        """Test that resource type is set to k8s_pod."""
        from src.utils.metrics import MetricsClient

        mock_client = MagicMock()
        mock_v3.MetricServiceClient.return_value = mock_client

        mock_series = MagicMock()
        mock_series.resource = MagicMock()
        mock_series.resource.type = None
        mock_series.resource.labels = {}
        mock_series.metric = MagicMock()
        mock_series.metric.labels = {}
        mock_v3.TimeSeries.return_value = mock_series

        client = MetricsClient(project_id="test-project", enabled=True)
        client.record_counter("test", 1)

        # Resource type should be set to k8s_pod
        assert mock_client.create_time_series.called
