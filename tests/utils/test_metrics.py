"""Tests for custom metrics client."""

import os
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.utils.metrics import (
    MetricsClient,
    get_metrics_client,
    MONITORING_AVAILABLE,
)


@pytest.fixture
def mock_monitoring_client():
    """Mock Google Cloud Monitoring client."""
    with patch("src.utils.metrics.monitoring_v3") as mock_monitoring:
        mock_client = Mock()
        mock_monitoring.MetricServiceClient.return_value = mock_client
        # Properly mock the classes as return values
        mock_monitoring.TimeSeries.return_value = MagicMock()
        mock_monitoring.Point.return_value = MagicMock()
        mock_monitoring.TimeInterval.return_value = MagicMock()
        yield mock_client


def test_metrics_client_disabled_when_library_unavailable():
    """Test metrics client is disabled when google-cloud-monitoring is not available."""
    with patch("src.utils.metrics.MONITORING_AVAILABLE", False):
        client = MetricsClient()
        assert client.enabled is False


def test_metrics_client_initialization():
    """Test metrics client initialization."""
    client = MetricsClient(
        project_id="test-project",
        service_name="test-service",
        enabled=False  # Disable actual connection
    )
    
    assert client.project_id == "test-project"
    assert client.service_name == "test-service"
    assert client.enabled is False


def test_metrics_client_resource_labels():
    """Test resource labels are set from environment."""
    os.environ["CLUSTER_NAME"] = "test-cluster"
    os.environ["NAMESPACE"] = "test-namespace"
    os.environ["HOSTNAME"] = "test-pod"
    
    try:
        client = MetricsClient(project_id="test-project", enabled=False)
        
        labels = client.resource_labels
        assert labels["cluster_name"] == "test-cluster"
        assert labels["namespace_name"] == "test-namespace"
        assert labels["pod_name"] == "test-pod"
        assert labels["project_id"] == "test-project"
    finally:
        os.environ.pop("CLUSTER_NAME", None)
        os.environ.pop("NAMESPACE", None)
        os.environ.pop("HOSTNAME", None)


def test_record_counter_disabled():
    """Test recording counter when metrics are disabled."""
    client = MetricsClient(enabled=False)
    
    # Should not raise errors
    client.record_counter("test_metric", 10)


def test_record_counter_with_labels():
    """Test recording counter with labels."""
    client = MetricsClient(enabled=False)
    
    client.record_counter(
        "test_metric",
        10,
        labels={"source": "example.com"}
    )


def test_record_gauge_disabled():
    """Test recording gauge when metrics are disabled."""
    client = MetricsClient(enabled=False)
    
    client.record_gauge("test_gauge", 42.5)


def test_record_gauge_with_labels():
    """Test recording gauge with labels."""
    client = MetricsClient(enabled=False)
    
    client.record_gauge(
        "test_gauge",
        42.5,
        labels={"queue": "verification"}
    )


def test_record_distribution_disabled():
    """Test recording distribution when metrics are disabled."""
    client = MetricsClient(enabled=False)
    
    client.record_distribution("test_distribution", 1.234)


def test_record_distribution_with_labels():
    """Test recording distribution with labels."""
    client = MetricsClient(enabled=False)
    
    client.record_distribution(
        "test_distribution",
        1.234,
        labels={"stage": "extraction"}
    )


def test_record_articles_discovered():
    """Test recording articles discovered metric."""
    client = MetricsClient(enabled=False)
    
    client.record_articles_discovered(count=42, source="example.com")


def test_record_articles_discovered_no_source():
    """Test recording articles discovered without source."""
    client = MetricsClient(enabled=False)
    
    client.record_articles_discovered(count=42)


def test_record_articles_extracted_success():
    """Test recording articles extracted metric (success)."""
    client = MetricsClient(enabled=False)
    
    client.record_articles_extracted(count=38, source="example.com", success=True)


def test_record_articles_extracted_failure():
    """Test recording articles extracted metric (failure)."""
    client = MetricsClient(enabled=False)
    
    client.record_articles_extracted(count=4, source="example.com", success=False)


def test_record_pipeline_success_rate():
    """Test recording pipeline success rate."""
    client = MetricsClient(enabled=False)
    
    client.record_pipeline_success_rate(stage="extraction", success_rate=0.95)


def test_record_processing_time():
    """Test recording processing time."""
    client = MetricsClient(enabled=False)
    
    client.record_processing_time(stage="discovery", duration_seconds=12.345)


def test_record_queue_depth():
    """Test recording queue depth."""
    client = MetricsClient(enabled=False)
    
    client.record_queue_depth(queue_name="verification_pending", depth=1234)


def test_get_metrics_client_singleton():
    """Test get_metrics_client returns singleton."""
    client1 = get_metrics_client(enabled=False)
    client2 = get_metrics_client(enabled=False)
    
    assert client1 is client2


def test_get_metrics_client_disabled_by_env():
    """Test metrics can be disabled via environment variable."""
    os.environ["DISABLE_METRICS"] = "true"
    
    try:
        # Reset singleton
        import src.utils.metrics as metrics_module
        metrics_module._metrics_client = None
        
        client = get_metrics_client()
        assert client.enabled is False
    finally:
        os.environ.pop("DISABLE_METRICS", None)
        # Reset singleton
        import src.utils.metrics as metrics_module
        metrics_module._metrics_client = None


def test_metrics_client_with_invalid_credentials():
    """Test metrics client handles invalid credentials gracefully."""
    with patch("src.utils.metrics.MONITORING_AVAILABLE", True):
        with patch("src.utils.metrics.monitoring_v3.MetricServiceClient") as mock_client:
            mock_client.side_effect = Exception("Authentication failed")
            
            # Should not raise, just disable
            client = MetricsClient(project_id="test-project", enabled=True)
            assert client.enabled is False


@pytest.mark.skipif(not MONITORING_AVAILABLE, reason="google-cloud-monitoring not installed")
def test_record_counter_integration(mock_monitoring_client):
    """Integration test for recording counter (with mocked client)."""
    client = MetricsClient(project_id="test-project", enabled=True)
    
    client.record_counter("test_metric", 10, labels={"key": "value"})
    
    # Verify client was called
    assert mock_monitoring_client.create_time_series.called


@pytest.mark.skipif(not MONITORING_AVAILABLE, reason="google-cloud-monitoring not installed")
def test_record_gauge_integration(mock_monitoring_client):
    """Integration test for recording gauge (with mocked client)."""
    client = MetricsClient(project_id="test-project", enabled=True)
    
    client.record_gauge("test_gauge", 42.5, labels={"key": "value"})
    
    # Verify client was called
    assert mock_monitoring_client.create_time_series.called


def test_metrics_error_handling():
    """Test metrics client handles errors gracefully."""
    with patch("src.utils.metrics.MONITORING_AVAILABLE", True):
        with patch("src.utils.metrics.monitoring_v3.MetricServiceClient") as mock_client_class:
            mock_client = Mock()
            mock_client.create_time_series.side_effect = Exception("Network error")
            mock_client_class.return_value = mock_client
            
            client = MetricsClient(project_id="test-project", enabled=True)
            
            # Should not raise, just log error
            client.record_counter("test_metric", 10)
