import logging
import pytest
from unittest.mock import MagicMock, patch
from src.crawler.discovery import NewsDiscovery


class TestDiscoveryLoopResilience:
    """Tests for resilience in discovery loops."""

    @pytest.fixture
    def discovery(self):
        """Create a NewsDiscovery instance with mocked dependencies."""
        with (
            patch("src.crawler.discovery.DatabaseManager"),
            patch("src.crawler.discovery.get_proxy_manager"),
        ):
            discovery = NewsDiscovery(max_articles_per_source=10)
            # Mock the database URL to avoid initialization errors
            discovery.database_url = "sqlite:///:memory:"
            return discovery

    def test_discover_from_sections_loop_resilience(self, discovery, caplog):
        """
        Test that _discover_from_sections continues processing subsequent sections
        even if one section fails (e.g. newspaper.build raises an exception).
        """
        caplog.set_level(logging.DEBUG)

        # Mock database response for discovered_sections
        mock_conn = MagicMock()
        mock_result = MagicMock()
        # Return a JSON string with two section URLs
        mock_result.fetchone.return_value = [
            '{"urls": ["http://example.com/section1", "http://example.com/section2"]}'
        ]

        # Mock the context manager for database connection
        with patch("src.models.database.DatabaseManager") as MockDB:
            MockDB.return_value.engine.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            # Mock safe_execute to return our result
            with patch("src.crawler.discovery.safe_execute", return_value=mock_result):

                # Mock newspaper.build
                # First call raises Exception, second call succeeds
                mock_paper = MagicMock()
                mock_paper.articles = []

                with patch(
                    "src.crawler.discovery.build",
                    side_effect=[Exception("Network Error"), mock_paper],
                ) as mock_build:

                    discovery._discover_from_sections(
                        source_url="http://example.com",
                        source_id="test-source-id",
                        source_meta={},
                    )

                    # Verify that build was called twice (loop continued)
                    assert mock_build.call_count == 2

                    # Verify that the error was logged
                    assert (
                        "Failed to crawl section http://example.com/section1: Network Error"
                        in caplog.text
                    )

                    # Verify that the second section was processed
                    assert (
                        "Crawling section: http://example.com/section2" in caplog.text
                    )

    def test_discover_from_sections_article_loop_resilience(self, discovery, caplog):
        """
        Test that the inner loop over articles continues even if processing one
        article fails.
        """
        caplog.set_level(logging.DEBUG)

        # Mock database response
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [
            '{"urls": ["http://example.com/section1"]}'
        ]

        with patch("src.models.database.DatabaseManager") as MockDB:
            MockDB.return_value.engine.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            with patch("src.crawler.discovery.safe_execute", return_value=mock_result):

                # Mock newspaper.build to return a paper with 2 articles
                mock_article1 = MagicMock()
                mock_article1.url = "http://example.com/article1"

                mock_article2 = MagicMock()
                mock_article2.url = "http://example.com/article2"

                mock_paper = MagicMock()
                mock_paper.articles = [mock_article1, mock_article2]

                with patch("src.crawler.discovery.build", return_value=mock_paper):
                    # Mock _normalize_candidate_url to fail for the first article
                    with patch.object(
                        discovery,
                        "_normalize_candidate_url",
                        side_effect=[
                            Exception("Normalization Error"),
                            "http://example.com/article2",
                        ],
                    ):

                        results = discovery._discover_from_sections(
                            source_url="http://example.com",
                            source_id="test-source-id",
                            source_meta={},
                        )

                        # Verify that the error was logged
                        assert (
                            "Error processing section article: Normalization Error"
                            in caplog.text
                        )

                        # Verify that we got the second article
                        assert len(results) == 1
                        assert results[0]["url"] == "http://example.com/article2"
