"""Tests for work-queue retry logic in extraction command."""

from unittest.mock import Mock, patch

import pytest
import requests

from src.cli.commands.extraction import _get_work_from_queue


class TestWorkQueueRetryLogic:
    """Test retry logic for work-queue requests."""

    def test_get_work_from_queue_success_first_try(self):
        """Test successful work request on first attempt."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [
                {"id": "1", "url": "http://example.com/1", "source": "example.com"}
            ],
            "worker_domains": ["example.com"],
        }
        mock_response.raise_for_status = Mock()

        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_response

            result = _get_work_from_queue(
                worker_id="test-worker",
                batch_size=10,
                max_articles_per_domain=3,
            )

            assert len(result) == 1
            assert result[0]["id"] == "1"
            assert mock_post.call_count == 1

    def test_get_work_from_queue_retries_on_timeout(self):
        """Test retry logic when request times out."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [
                {"id": "1", "url": "http://example.com/1", "source": "example.com"}
            ],
            "worker_domains": ["example.com"],
        }
        mock_response.raise_for_status = Mock()

        with patch("requests.post") as mock_post:
            with patch("time.sleep") as mock_sleep:
                # Fail twice, succeed on third attempt
                mock_post.side_effect = [
                    requests.Timeout("Connection timeout"),
                    requests.Timeout("Connection timeout"),
                    mock_response,
                ]

                result = _get_work_from_queue(
                    worker_id="test-worker",
                    batch_size=10,
                    max_articles_per_domain=3,
                )

                assert len(result) == 1
                assert mock_post.call_count == 3
                # Verify exponential backoff sleep calls: 2s, 4s
                assert mock_sleep.call_count == 2
                mock_sleep.assert_any_call(1)  # 2^0 = 1
                mock_sleep.assert_any_call(2)  # 2^1 = 2

    def test_get_work_from_queue_fails_after_max_retries(self):
        """Test that request fails after exhausting all retries."""
        with patch("requests.post") as mock_post:
            with patch("time.sleep"):
                # Fail all 3 attempts
                mock_post.side_effect = [
                    requests.Timeout("Connection timeout"),
                    requests.Timeout("Connection timeout"),
                    requests.Timeout("Connection timeout"),
                ]

                with pytest.raises(requests.Timeout):
                    _get_work_from_queue(
                        worker_id="test-worker",
                        batch_size=10,
                        max_articles_per_domain=3,
                    )

                assert mock_post.call_count == 3

    def test_get_work_from_queue_timeout_increases(self):
        """Test that timeout increases with each retry attempt."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [],
            "worker_domains": [],
        }
        mock_response.raise_for_status = Mock()

        with patch("requests.post") as mock_post:
            with patch("time.sleep"):
                # Fail twice, succeed on third
                mock_post.side_effect = [
                    requests.Timeout("timeout"),
                    requests.Timeout("timeout"),
                    mock_response,
                ]

                _get_work_from_queue(
                    worker_id="test-worker",
                    batch_size=10,
                    max_articles_per_domain=3,
                )

                # Verify timeout values: 60s, 90s, 120s
                calls = mock_post.call_args_list
                assert calls[0][1]["timeout"] == 60
                assert calls[1][1]["timeout"] == 90
                assert calls[2][1]["timeout"] == 120

    def test_get_work_from_queue_http_error_retries(self):
        """Test retry on HTTP errors (500, 502, etc.)."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [{"id": "1", "url": "http://test.com", "source": "test.com"}],
            "worker_domains": ["test.com"],
        }
        mock_response.raise_for_status = Mock()

        with patch("requests.post") as mock_post:
            with patch("time.sleep"):
                # HTTP 500 error then success
                http_error = requests.HTTPError("500 Server Error")
                http_error.response = Mock(status_code=500)

                mock_post.side_effect = [
                    http_error,
                    mock_response,
                ]

                result = _get_work_from_queue(
                    worker_id="test-worker",
                    batch_size=10,
                    max_articles_per_domain=3,
                )

                assert len(result) == 1
                assert mock_post.call_count == 2

    def test_get_work_from_queue_connection_error_retries(self):
        """Test retry on connection errors."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [{"id": "1", "url": "http://test.com", "source": "test.com"}],
            "worker_domains": ["test.com"],
        }
        mock_response.raise_for_status = Mock()

        with patch("requests.post") as mock_post:
            with patch("time.sleep"):
                # Connection error then success
                mock_post.side_effect = [
                    requests.ConnectionError("Connection refused"),
                    mock_response,
                ]

                result = _get_work_from_queue(
                    worker_id="test-worker",
                    batch_size=10,
                    max_articles_per_domain=3,
                )

                assert len(result) == 1
                assert mock_post.call_count == 2

    def test_get_work_from_queue_empty_response_no_retry(self):
        """Test that empty work response doesn't trigger retry."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "items": [],
            "worker_domains": [],
        }
        mock_response.raise_for_status = Mock()

        with patch("requests.post") as mock_post:
            mock_post.return_value = mock_response

            result = _get_work_from_queue(
                worker_id="test-worker",
                batch_size=10,
                max_articles_per_domain=3,
            )

            assert len(result) == 0
            assert mock_post.call_count == 1  # No retries for empty response
