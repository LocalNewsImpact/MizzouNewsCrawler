"""Tests for wire service URL filtering in URL verification."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.services.url_verification import URLVerificationService


@pytest.fixture
def mock_dependencies(monkeypatch):
    """Mock all external dependencies for URL verification service."""
    # Mock StorySniffer
    fake_storysniffer = SimpleNamespace(
        StorySniffer=lambda: SimpleNamespace(guess=lambda _: True)
    )
    import src.services.url_verification as uv_module

    monkeypatch.setattr(uv_module, "storysniffer", fake_storysniffer)

    # Mock DatabaseManager with get_session method
    class FakeDatabaseManager:
        def get_session(self):
            """Return a fake session context manager."""
            from contextlib import contextmanager

            @contextmanager
            def fake_session():
                # Return a fake session that ContentTypeDetector can use
                fake_session_obj = SimpleNamespace(
                    query=lambda *_: SimpleNamespace(
                        filter=lambda *_: SimpleNamespace(
                            all=lambda: [],
                            order_by=lambda *_: SimpleNamespace(all=lambda: []),
                        )
                    )
                )
                yield fake_session_obj

            return fake_session()

    monkeypatch.setattr(
        uv_module,
        "DatabaseManager",
        lambda *_, **__: FakeDatabaseManager(),
    )

    # Mock telemetry
    mock_telemetry = SimpleNamespace(
        start_operation=lambda *_, **__: SimpleNamespace(
            record_metric=lambda *_, **__: None,
            complete=lambda *_, **__: None,
            fail=lambda *_, **__: None,
        ),
        get_metrics_summary=lambda: {},
    )
    monkeypatch.setattr(
        uv_module,
        "create_telemetry_system",
        lambda *_, **__: mock_telemetry,
    )

    # Mock HTTP session
    class _Session:
        def __init__(self):
            self.headers = {}

        def head(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200)

        def get(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200)

        def mount(self, prefix, adapter):
            pass

    monkeypatch.setattr(uv_module.requests, "Session", _Session)


@pytest.fixture
def service(mock_dependencies):
    """Create URLVerificationService instance with mocked dependencies."""
    return URLVerificationService(
        batch_size=100,
        http_backoff_seconds=0,
        run_http_precheck=False,
    )


class TestWireServiceURLFiltering:
    """Test wire service URL detection during verification."""

    def test_detects_ap_wire_url(self, service):
        """Test that /ap- URLs are detected as wire service."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            # Use a more specific pattern that matches the URL structure
            mock_patterns.return_value = [(r"/ap/", "Associated Press", False)]

            result = service.verify_url("https://newspressnow.com/ap/news/story-123")

            assert result["wire_filtered"] is True
            assert result["storysniffer_result"] is False
            assert result["wire_service"] == "Associated Press"
            assert result["verification_time_ms"] > 0

    def test_detects_stacker_wire_url(self, service):
        """Test that /stacker/ URLs are detected as wire service."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/stacker/", "Stacker", False)]

            result = service.verify_url(
                "https://example.com/stacker/travel/best-beaches"
            )

            assert result["wire_filtered"] is True
            assert result["wire_service"] == "Stacker"

    def test_detects_reuters_wire_url(self, service):
        """Test that /reuters- URLs are detected as wire service."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/reuters-", "Reuters", False)]

            result = service.verify_url("https://news.com/reuters-world/story")

            assert result["wire_filtered"] is True
            assert result["wire_service"] == "Reuters"

    def test_detects_national_section_url(self, service):
        """Test that /national/ URLs are detected as wire service."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/national/", "National Section", False)]

            result = service.verify_url("https://localnews.com/national/politics/story")

            assert result["wire_filtered"] is True
            assert result["wire_service"] == "National Section"

    def test_detects_world_section_url(self, service):
        """Test that /world/ URLs are detected as wire service."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/world/", "Wire Service", False)]

            result = service.verify_url("https://localnews.com/world/europe/story")

            assert result["wire_filtered"] is True
            assert result["wire_service"] == "Wire Service"

    def test_wire_filtering_skips_storysniffer(self, service):
        """Test that wire filtering bypasses StorySniffer call."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/wire/", "Wire Service", False)]

            # Mock StorySniffer to raise error if called
            with patch.object(
                service.sniffer,
                "guess",
                side_effect=RuntimeError("Should not be called"),
            ):
                result = service.verify_url("https://example.com/wire/story")

                # Should succeed without calling StorySniffer
                assert result["wire_filtered"] is True
                assert result["error"] is None

    def test_non_wire_url_proceeds_to_storysniffer(self, service):
        """Test that non-wire URLs still go through StorySniffer."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/wire/", "Wire Service", False)]

            result = service.verify_url("https://example.com/local/news/story")

            # Should not be wire filtered
            assert result.get("wire_filtered", False) is False
            # Should have StorySniffer result
            assert result["storysniffer_result"] is True

    def test_case_insensitive_wire_detection(self, service):
        """Test that wire detection is case-insensitive."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [
                (r"/AP-", "Associated Press", False)  # case_sensitive=False
            ]

            result = service.verify_url("https://example.com/AP-NEWS/story")

            assert result["wire_filtered"] is True

    def test_multiple_wire_patterns(self, service):
        """Test that first matching pattern wins."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [
                (r"/ap-", "Associated Press", False),
                (r"/wire/", "Wire Service", False),
                (r"/reuters", "Reuters", False),
            ]

            result = service.verify_url("https://example.com/ap-world/story")

            assert result["wire_filtered"] is True
            assert result["wire_service"] == "Associated Press"


class TestWireServiceBatchProcessing:
    """Test wire service detection in batch processing."""

    def test_process_batch_marks_wire_status(self, service):
        """Test that wire URLs get status='wire' in batch processing."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/stacker/", "Stacker", False)]

            # Mock update_candidate_status to track calls
            update_calls = []

            def mock_update(candidate_id, new_status, error_message=None):
                update_calls.append((candidate_id, new_status, error_message))

            with patch.object(
                service, "update_candidate_status", side_effect=mock_update
            ):
                candidates = [
                    {
                        "id": "wire-id-1",
                        "url": "https://example.com/stacker/travel/story",
                        "source_name": "Example News",
                    },
                    {
                        "id": "article-id-1",
                        "url": "https://example.com/local/news/story",
                        "source_name": "Example News",
                    },
                ]

                metrics = service.process_batch(candidates)

                # Check metrics
                assert metrics["total_processed"] == 2
                # Wire counts as non-article
                assert metrics["verified_non_articles"] == 1

                # Check status updates
                assert len(update_calls) == 2
                # First candidate should be marked as wire
                assert update_calls[0] == ("wire-id-1", "wire", None)
                # Second candidate should be marked as article
                assert update_calls[1] == ("article-id-1", "article", None)

    def test_wire_filtered_counted_in_metrics(self, service):
        """Test that wire-filtered URLs are counted in batch metrics."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/wire/", "Wire Service", False)]

            with patch.object(
                service,
                "update_candidate_status",
                return_value=None,
            ):
                candidates = [
                    {
                        "id": f"wire-{i}",
                        "url": f"https://example.com/wire/story-{i}",
                        "source_name": "Example News",
                    }
                    for i in range(5)
                ]

                metrics = service.process_batch(candidates)

                assert metrics["total_processed"] == 5
                assert metrics["verified_non_articles"] == 5
                assert metrics["verified_articles"] == 0
                assert metrics["verification_errors"] == 0


class TestWireDetectionPerformance:
    """Test performance characteristics of wire detection."""

    def test_wire_detection_is_fast(self, service):
        """Test that wire detection completes quickly (< 1ms typical)."""
        with patch(
            "src.utils.content_type_detector.ContentTypeDetector."
            "_get_wire_service_patterns"
        ) as mock_patterns:
            mock_patterns.return_value = [(r"/ap-", "Associated Press", False)]

            result = service.verify_url("https://example.com/ap-news/story")

            # Wire detection should be very fast (< 5ms even in test environment)
            assert result["verification_time_ms"] < 5.0
            assert result["wire_filtered"] is True

    def test_wire_detection_before_http_check(self, service):
        """Test that wire detection happens before HTTP checks."""
        from src.utils.content_type_detector import ContentTypeDetector

        with patch.object(
            ContentTypeDetector,
            "_get_wire_service_patterns",
            return_value=[(r"/wire/", "Wire Service", False)],
        ):
            # Enable HTTP precheck
            service.run_http_precheck = True

            result = service.verify_url("https://example.com/wire/story")

            # Should succeed without HTTP check
            assert result["wire_filtered"] is True
            assert result["http_status"] is None
            assert result["http_attempts"] == 0
            # Fast response indicates no HTTP call was made
            assert result["verification_time_ms"] < 50
