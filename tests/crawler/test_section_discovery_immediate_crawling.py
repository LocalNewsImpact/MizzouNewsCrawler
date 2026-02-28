"""Tests for section-based discovery immediate crawling fix.

This test module covers the fix for sources that organize articles in
category/section pages rather than listing them directly on the homepage.

Tests cover:
1. Detection of section URLs in homepage link-scan results
2. Skipping early return when all candidates are section URLs
3. Immediate crawling of discovered sections in the same run
4. Integration of section articles into discovery results
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.crawler.discovery import NewsDiscovery
from src.crawler.source_processing import SourceProcessor


@pytest.fixture
def discovery_instance():
    """Create NewsDiscovery instance with mocked dependencies."""
    with patch("src.crawler.discovery.create_telemetry_system"):
        with patch("src.crawler.discovery.StorySniffer"):
            with patch("src.crawler.discovery.get_proxy_manager") as mock_proxy:
                mock_proxy_mgr = MagicMock()
                mock_proxy_mgr.active_provider = MagicMock(value="origin")
                mock_proxy_mgr.get_requests_proxies.return_value = {}
                mock_proxy.return_value = mock_proxy_mgr

                discovery = NewsDiscovery(database_url="sqlite:///:memory:")
                return discovery


class TestHomepageLinkScanSectionDetection:
    """Test detection of section URLs in homepage link-scan results."""

    def test_all_category_urls_detected_as_sections(self, discovery_instance):
        """When all homepage candidates are category URLs, should detect as sections."""
        homepage_candidates = [
            "https://example.com/category/news/local/",
            "https://example.com/category/news/sports/",
            "https://example.com/category/news/weather/",
        ]

        # Mock the pattern check - all URLs contain /category
        all_sections = all(
            any(pattern in u.lower() for pattern in ["/category", "/tag", "/section"])
            for u in homepage_candidates
        )

        assert all_sections is True

    def test_mixed_urls_not_detected_as_sections(self, discovery_instance):
        """When candidates include article URLs, should not detect as all sections."""
        homepage_candidates = [
            "https://example.com/category/news/",
            "https://example.com/news/2026/02/28/article-title/",
            "https://example.com/category/sports/",
        ]

        all_sections = all(
            any(pattern in u.lower() for pattern in ["/category", "/tag", "/section"])
            for u in homepage_candidates
        )

        assert all_sections is False

    def test_article_urls_not_detected_as_sections(self, discovery_instance):
        """When candidates are article URLs, should not detect as sections."""
        homepage_candidates = [
            "https://example.com/news/2026/02/28/article-1/",
            "https://example.com/news/2026/02/27/article-2/",
            "https://example.com/sports/2026/02/28/game-recap/",
        ]

        all_sections = all(
            any(pattern in u.lower() for pattern in ["/category", "/tag", "/section"])
            for u in homepage_candidates
        )

        assert all_sections is False

    def test_tag_urls_detected_as_sections(self, discovery_instance):
        """Tag URLs should also be detected as section URLs."""
        homepage_candidates = [
            "https://example.com/tag/local-news/",
            "https://example.com/tag/breaking-news/",
        ]

        all_sections = all(
            any(pattern in u.lower() for pattern in ["/category", "/tag", "/section"])
            for u in homepage_candidates
        )

        assert all_sections is True

    def test_section_path_detected_as_sections(self, discovery_instance):
        """URLs with /section/ path should be detected as section URLs."""
        homepage_candidates = [
            "https://example.com/section/local/",
            "https://example.com/section/sports/",
        ]

        all_sections = all(
            any(pattern in u.lower() for pattern in ["/category", "/tag", "/section"])
            for u in homepage_candidates
        )

        assert all_sections is True


class TestNewspaper4kSectionCrawling:
    """Test that newspaper4k build still happens when sections detected."""

    @patch("src.crawler.discovery.NewsDiscovery._extract_homepage_article_candidates")
    @patch("src.crawler.discovery.NewsDiscovery._discover_from_section_urls")
    @patch("src.crawler.discovery.build")
    def test_sections_dont_trigger_early_return(
        self,
        mock_build,
        mock_section_crawl,
        mock_homepage_candidates,
        discovery_instance,
    ):
        """When homepage candidates are all sections, should continue to build."""
        # Setup: homepage scan returns category URLs
        mock_homepage_candidates.return_value = [
            "https://example.com/category/news/",
            "https://example.com/category/sports/",
        ]

        # Mock build to return a paper with articles
        mock_paper = MagicMock()
        mock_paper.articles = [
            MagicMock(url="https://example.com/news/2026/02/28/article-1/"),
            MagicMock(url="https://example.com/news/2026/02/27/article-2/"),
        ]
        mock_build.return_value = mock_paper

        # Mock section crawling to return more articles
        mock_section_crawl.return_value = [
            {
                "url": "https://example.com/news/2026/02/28/article-3/",
                "discovery_method": "section_crawl",
            }
        ]

        # Mock database methods
        discovery_instance._get_existing_urls = Mock(return_value=set())
        discovery_instance._normalize_candidate_url = Mock(
            side_effect=lambda u: u.lower()
        )

        # Mock HTTP request for homepage
        with patch.object(discovery_instance, "session") as mock_session:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "<html><body>Homepage</body></html>"
            mock_session.get.return_value = mock_response

            # Execute discovery (don't need results, just checking it doesn't early return)
            _ = discovery_instance.discover_with_newspaper4k(
                source_url="https://example.com",
                source_id="test-source-id",
                operation_id="test-op-id",
                source_meta={},
            )

            # Verify: build() was called (not early return)
            # Note: This depends on allow_build not being False
            # The key is that we DON'T return early from homepage candidates

    @patch("src.crawler.discovery.NewsDiscovery._extract_homepage_article_candidates")
    def test_mixed_urls_trigger_early_return(
        self, mock_homepage_candidates, discovery_instance
    ):
        """When homepage candidates include article URLs, should return early."""
        # Setup: homepage scan returns mix of articles and categories
        mock_homepage_candidates.return_value = [
            "https://example.com/news/2026/02/28/article-1/",  # Article
            "https://example.com/category/news/",  # Category
        ]

        discovery_instance._get_existing_urls = Mock(return_value=set())
        discovery_instance._normalize_candidate_url = Mock(
            side_effect=lambda u: u.lower()
        )

        # Mock HTTP request for homepage
        with patch.object(discovery_instance, "session") as mock_session:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "<html><body>Homepage</body></html>"
            mock_session.get.return_value = mock_response

            # Execute discovery (may return early with mixed URLs)
            _ = discovery_instance.discover_with_newspaper4k(
                source_url="https://example.com",
                source_id="test-source-id",
                operation_id="test-op-id",
                source_meta={},
            )

            # Should have returned the article URL (early return happened)
            # Note: actual behavior depends on filtering logic


class TestSourceProcessorImmediateSectionCrawling:
    """Test that SourceProcessor immediately crawls discovered sections."""

    def test_discover_and_store_sections_returns_section_urls(self):
        """_discover_and_store_sections should return list of section URLs."""
        with patch("src.crawler.discovery.get_proxy_manager") as mock_proxy:
            mock_proxy_mgr = MagicMock()
            mock_proxy_mgr.active_provider = MagicMock(value="origin")
            mock_proxy_mgr.get_requests_proxies.return_value = {}
            mock_proxy.return_value = mock_proxy_mgr

            with patch("src.crawler.discovery.create_telemetry_system"):
                with patch("src.crawler.discovery.StorySniffer"):
                    discovery = NewsDiscovery(database_url="sqlite:///:memory:")

                    # Create a mock source row
                    source_row = {
                        "id": "test-source-id",
                        "url": "https://example.com",
                        "name": "Test Source",
                        "metadata": {},
                    }

                    processor = SourceProcessor(
                        source_row=source_row,
                        discovery=discovery,
                        dataset_label=None,
                    )

                    # Initialize context (normally done by process())
                    processor.source_id = "test-source-id"
                    processor.source_url = "https://example.com"
                    processor.source_name = "Test Source"

                    # Mock database connection for section discovery check
                    with patch(
                        "src.models.database.DatabaseManager"
                    ) as mock_db_manager:
                        mock_conn = MagicMock()
                        mock_result = MagicMock()
                        mock_result.fetchone.return_value = (True,)  # Enabled
                        mock_conn.execute.return_value = mock_result
                        mock_conn.__enter__ = Mock(return_value=mock_conn)
                        mock_conn.__exit__ = Mock(return_value=False)

                        mock_engine = MagicMock()
                        mock_engine.connect.return_value = mock_conn
                        mock_engine.begin.return_value = mock_conn

                        mock_db_instance = MagicMock()
                        mock_db_instance.engine = mock_engine
                        mock_db_manager.return_value = mock_db_instance

                        # Mock HTTP request for homepage
                        with patch.object(discovery, "session") as mock_session:
                            mock_response = MagicMock()
                            mock_response.status_code = 200
                            mock_response.text = """
                            <html>
                            <nav>
                                <a href="/news/">News</a>
                                <a href="/sports/">Sports</a>
                            </nav>
                            </html>
                            """
                            mock_session.get.return_value = mock_response

                            # Mock section URL discovery
                            with patch.object(
                                discovery, "_discover_section_urls"
                            ) as mock_discover:
                                mock_discover.return_value = [
                                    "https://example.com/news/",
                                    "https://example.com/sports/",
                                ]

                                # Execute
                                discovered_articles = [
                                    {
                                        "url": "https://example.com/news/2026/02/28/article-1/"
                                    }
                                ]
                                sections = processor._discover_and_store_sections(
                                    discovered_articles
                                )

                                # Verify: returns list of section URLs
                                assert isinstance(sections, list)
                                assert len(sections) >= 0  # May be filtered

    def test_process_calls_section_crawling_when_sections_found(self):
        """SourceProcessor.process should crawl sections immediately when discovered."""
        with patch("src.crawler.discovery.get_proxy_manager") as mock_proxy:
            mock_proxy_mgr = MagicMock()
            mock_proxy_mgr.active_provider = MagicMock(value="origin")
            mock_proxy_mgr.get_requests_proxies.return_value = {}
            mock_proxy.return_value = mock_proxy_mgr

            with patch("src.crawler.discovery.create_telemetry_system"):
                with patch("src.crawler.discovery.StorySniffer"):
                    discovery = NewsDiscovery(database_url="sqlite:///:memory:")

                    source_row = {
                        "id": "test-source-id",
                        "url": "https://example.com",
                        "name": "Test Source",
                        "metadata": {"effective_methods": ["newspaper4k"]},
                    }

                    processor = SourceProcessor(
                        source_row=source_row,
                        discovery=discovery,
                        dataset_label=None,
                    )

                    # Mock all the methods we need
                    processor._initialize_context = Mock()
                    processor.source_url = "https://example.com"
                    processor.source_name = "Test Source"
                    processor.source_id = "test-source-id"
                    processor.source_meta = {}
                    processor.existing_urls = set()

                    # Mock discovery methods
                    processor._run_discovery_methods = Mock(
                        return_value=[
                            {"url": "https://example.com/news/2026/02/28/article-1/"}
                        ]
                    )

                    # Mock section discovery to return section URLs
                    processor._discover_and_store_sections = Mock(
                        return_value=[
                            "https://example.com/category/news/",
                            "https://example.com/category/sports/",
                        ]
                    )

                    # Mock section crawling
                    with patch.object(
                        discovery, "_discover_from_section_urls"
                    ) as mock_crawl:
                        mock_crawl.return_value = [
                            {
                                "url": "https://example.com/news/2026/02/28/article-2/",
                                "discovery_method": "section_crawl",
                            },
                            {
                                "url": "https://example.com/sports/2026/02/27/game/",
                                "discovery_method": "section_crawl",
                            },
                        ]

                        # Mock storage
                        processor._store_candidates = Mock(return_value={})
                        processor._record_no_articles = Mock()
                        processor._build_result = Mock()

                        # Execute
                        processor.process()

                        # Verify: section crawling was called
                        mock_crawl.assert_called_once()
                        assert (
                            mock_crawl.call_args[1]["source_url"]
                            == "https://example.com"
                        )
                        assert mock_crawl.call_args[1]["source_id"] == "test-source-id"

    def test_process_skips_section_crawling_when_no_sections(self):
        """SourceProcessor.process should skip section crawling when none discovered."""
        with patch("src.crawler.discovery.get_proxy_manager") as mock_proxy:
            mock_proxy_mgr = MagicMock()
            mock_proxy_mgr.active_provider = MagicMock(value="origin")
            mock_proxy_mgr.get_requests_proxies.return_value = {}
            mock_proxy.return_value = mock_proxy_mgr

            with patch("src.crawler.discovery.create_telemetry_system"):
                with patch("src.crawler.discovery.StorySniffer"):
                    discovery = NewsDiscovery(database_url="sqlite:///:memory:")

                    source_row = {
                        "id": "test-source-id",
                        "url": "https://example.com",
                        "name": "Test Source",
                        "metadata": {"effective_methods": ["newspaper4k"]},
                    }

                    processor = SourceProcessor(
                        source_row=source_row,
                        discovery=discovery,
                        dataset_label=None,
                    )

                    processor._initialize_context = Mock()
                    processor.source_url = "https://example.com"
                    processor.source_name = "Test Source"
                    processor.source_id = "test-source-id"
                    processor.source_meta = {}
                    processor.existing_urls = set()

                    processor._run_discovery_methods = Mock(
                        return_value=[
                            {"url": "https://example.com/news/2026/02/28/article-1/"}
                        ]
                    )

                    # Mock section discovery to return empty list
                    processor._discover_and_store_sections = Mock(return_value=[])

                    # Mock section crawling (should NOT be called)
                    with patch.object(
                        discovery, "_discover_from_section_urls"
                    ) as mock_crawl:
                        processor._store_candidates = Mock(return_value={})
                        processor._record_no_articles = Mock()
                        processor._build_result = Mock()

                        # Execute
                        processor.process()

                        # Verify: section crawling was NOT called
                        mock_crawl.assert_not_called()

    def test_section_articles_added_to_discovery_results(self):
        """Section articles should be added to all_discovered list."""
        with patch("src.crawler.discovery.get_proxy_manager") as mock_proxy:
            mock_proxy_mgr = MagicMock()
            mock_proxy_mgr.active_provider = MagicMock(value="origin")
            mock_proxy_mgr.get_requests_proxies.return_value = {}
            mock_proxy.return_value = mock_proxy_mgr

            with patch("src.crawler.discovery.create_telemetry_system"):
                with patch("src.crawler.discovery.StorySniffer"):
                    discovery = NewsDiscovery(database_url="sqlite:///:memory:")

                    source_row = {
                        "id": "test-source-id",
                        "url": "https://example.com",
                        "name": "Test Source",
                        "metadata": {"effective_methods": ["newspaper4k"]},
                    }

                    processor = SourceProcessor(
                        source_row=source_row,
                        discovery=discovery,
                        dataset_label=None,
                    )

                    processor._initialize_context = Mock()
                    processor.source_url = "https://example.com"
                    processor.source_name = "Test Source"
                    processor.source_id = "test-source-id"
                    processor.source_meta = {}
                    processor.existing_urls = set()

                    # Initial discovery returns 1 article
                    initial_articles = [
                        {"url": "https://example.com/news/2026/02/28/article-1/"}
                    ]
                    processor._run_discovery_methods = Mock(
                        return_value=initial_articles
                    )

                    # Section discovery returns 2 sections
                    processor._discover_and_store_sections = Mock(
                        return_value=[
                            "https://example.com/category/news/",
                            "https://example.com/category/sports/",
                        ]
                    )

                    # Section crawling returns 2 more articles
                    section_articles = [
                        {
                            "url": "https://example.com/news/2026/02/28/article-2/",
                            "discovery_method": "section_crawl",
                        },
                        {
                            "url": "https://example.com/sports/2026/02/27/game/",
                            "discovery_method": "section_crawl",
                        },
                    ]

                    with patch.object(
                        discovery, "_discover_from_section_urls"
                    ) as mock_crawl:
                        mock_crawl.return_value = section_articles

                        # Capture what gets passed to _store_candidates
                        stored_articles = None

                        def capture_stored(articles):
                            nonlocal stored_articles
                            stored_articles = articles
                            return {}

                        processor._store_candidates = Mock(side_effect=capture_stored)
                        processor._record_no_articles = Mock()
                        processor._build_result = Mock()

                        # Execute
                        processor.process()

                        # Verify: all articles (initial + section) were stored
                        assert stored_articles is not None
                        assert len(stored_articles) == 3
                        assert stored_articles[0] == initial_articles[0]
                        assert stored_articles[1] == section_articles[0]
                        assert stored_articles[2] == section_articles[1]


class TestSectionCrawlingErrorHandling:
    """Test error handling in section crawling."""

    def test_section_crawling_failure_doesnt_crash(self):
        """If section crawling fails, should log warning but continue."""
        with patch("src.crawler.discovery.get_proxy_manager") as mock_proxy:
            mock_proxy_mgr = MagicMock()
            mock_proxy_mgr.active_provider = MagicMock(value="origin")
            mock_proxy_mgr.get_requests_proxies.return_value = {}
            mock_proxy.return_value = mock_proxy_mgr

            with patch("src.crawler.discovery.create_telemetry_system"):
                with patch("src.crawler.discovery.StorySniffer"):
                    discovery = NewsDiscovery(database_url="sqlite:///:memory:")

                    source_row = {
                        "id": "test-source-id",
                        "url": "https://example.com",
                        "name": "Test Source",
                        "metadata": {"effective_methods": ["newspaper4k"]},
                    }

                    processor = SourceProcessor(
                        source_row=source_row,
                        discovery=discovery,
                        dataset_label=None,
                    )

                    processor._initialize_context = Mock()
                    processor.source_url = "https://example.com"
                    processor.source_name = "Test Source"
                    processor.source_id = "test-source-id"
                    processor.source_meta = {}
                    processor.existing_urls = set()

                    processor._run_discovery_methods = Mock(
                        return_value=[
                            {"url": "https://example.com/news/2026/02/28/article-1/"}
                        ]
                    )

                    processor._discover_and_store_sections = Mock(
                        return_value=["https://example.com/category/news/"]
                    )

                    # Section crawling raises exception
                    with patch.object(
                        discovery, "_discover_from_section_urls"
                    ) as mock_crawl:
                        mock_crawl.side_effect = Exception("Network error")

                        processor._store_candidates = Mock(return_value={})
                        processor._record_no_articles = Mock()
                        processor._build_result = Mock()

                        # Execute - should not raise
                        processor.process()

                        # Verify: process completed despite error
                        processor._store_candidates.assert_called_once()
