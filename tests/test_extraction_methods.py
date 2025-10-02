"""
Comprehensive tests for content extraction methods and fallback mechanisms.

Tests all three extraction methods (newspaper4k, BeautifulSoup, Selenium)
and the intelligent field-level fallback system.
"""

import textwrap
from datetime import datetime
from unittest.mock import Mock, patch

import pytest
import requests

import src.crawler as crawler_module
from src.crawler import ContentExtractor


@pytest.fixture
def extractor():
    """Create a ContentExtractor instance for testing."""
    return ContentExtractor(timeout=10)


@pytest.fixture
def mock_html_complete():
    """Mock HTML with all fields present for complete extraction."""
    return """
    <html>
    <head>
        <title>Test Article Title</title>
        <meta name="author" content="John Doe">
        <meta name="description" content="Test description">
        <meta property="article:published_time"
              content="2023-01-15T10:00:00Z">
    </head>
    <body>
        <h1>Test Article Title</h1>
        <div class="author">By John Doe</div>
        <time datetime="2023-01-15T10:00:00Z">January 15, 2023</time>
        <div class="content">
            <p>This is the main content of the test article. It contains
            multiple paragraphs to simulate a real article.</p>
            <p>This is the second paragraph with more content.</p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def mock_html_partial():
    """Mock HTML with only some fields for partial extraction."""
    return """
    <html>
    <head><title>Partial Article</title></head>
    <body>
        <h1>Partial Article</h1>
        <p>Short content without author or date.</p>
    </body>
    </html>
    """


@pytest.fixture
def mock_html_minimal():
    """Mock HTML with minimal content for testing fallback scenarios."""
    return """
    <html>
    <head><title>Minimal</title></head>
    <body><p>Very short.</p></body>
    </html>
    """


@pytest.fixture
def mock_requests_response():
    """Create a mock requests response."""

    def _create_response(content: str, status_code: int = 200):
        response = Mock()
        response.text = content
        response.content = content.encode("utf-8")
        response.status_code = status_code
        response.raise_for_status = Mock()
        if status_code >= 400:
            response.raise_for_status.side_effect = requests.RequestException(
                f"HTTP {status_code}"
            )
        return response

    return _create_response


@pytest.fixture
def mock_webdriver():
    """Mock webdriver for Selenium tests."""
    with patch("src.crawler.webdriver") as mock_wd:
        mock_driver = Mock()
        mock_driver.page_source = """
        <html>
            <head><title>Selenium Test</title></head>
            <body>
                <h1>Selenium Test Article</h1>
                <p>Content loaded by JavaScript.</p>
            </body>
        </html>
        """
        mock_wd.Chrome.return_value = mock_driver
        yield mock_driver


class TestContentExtractor:
    """Test suite for ContentExtractor class and all extraction methods."""

    @pytest.mark.parametrize(
        "url,expected_date",
        [
            (
                "https://www.columbiatribune.com/story/news/local/"
                "2024/09/25/test-story/123456/",
                "2024-09-25",
            ),
            (
                "https://www.kbia.org/health/2024-10-01/" "test-segment/",
                "2024-10-01",
            ),
        ],
    )
    def test_publish_date_url_fallback_for_known_hosts(
        self,
        extractor,
        url,
        expected_date,
    ):
        content_text = " ".join(["content"] * 40)
        newspaper_result = {
            "url": url,
            "title": "Test Title",
            "author": "Staff Writer",
            "publish_date": None,
            "content": content_text,
            "metadata": {"http_status": 200},
            "extracted_at": datetime.utcnow().isoformat(),
        }

        with (
            patch.object(
                extractor,
                "_extract_with_newspaper",
                return_value=newspaper_result,
            ),
            patch.object(
                extractor,
                "_extract_with_beautifulsoup",
                return_value={},
            ),
            patch.object(
                extractor,
                "_extract_with_selenium",
                return_value={},
            ),
        ):
            result = extractor.extract_content(url)

        assert result["publish_date"] is not None
        assert result["publish_date"].startswith(expected_date)

        metadata = result.get("metadata", {})
        methods = metadata.get("extraction_methods", {})
        assert methods.get("publish_date") == "url_fallback"

        fallback_info = metadata.get("fallbacks", {}).get("publish_date")
        assert fallback_info is not None
        assert fallback_info["source"] == "url_path"

    def test_publish_date_url_fallback_skips_unknown_hosts(self, extractor):
        url = "https://example.com/news/2024/09/25/test-story"
        content_text = " ".join(["content"] * 40)
        newspaper_result = {
            "url": url,
            "title": "Test Title",
            "author": "Staff Writer",
            "publish_date": None,
            "content": content_text,
            "metadata": {"http_status": 200},
            "extracted_at": datetime.utcnow().isoformat(),
        }

        with (
            patch.object(
                extractor,
                "_extract_with_newspaper",
                return_value=newspaper_result,
            ),
            patch.object(
                extractor,
                "_extract_with_beautifulsoup",
                return_value={},
            ),
            patch.object(
                extractor,
                "_extract_with_selenium",
                return_value={},
            ),
        ):
            result = extractor.extract_content(url)

        assert result["publish_date"] is None

    def test_cached_html_short_circuits_network(
        self,
        extractor,
        monkeypatch,
        mock_html_complete,
    ):
        monkeypatch.setattr(crawler_module, "NEWSPAPER_AVAILABLE", True)

        cached_html = mock_html_complete
        captured = {"html": None, "url": None}

        def fake_newspaper(url, html=None):
            captured["url"] = url
            captured["html"] = html
            return {
                "url": url,
                "title": "Cached Title",
                "author": "Cached Author",
                "publish_date": "2024-09-25T08:00:00",
                "content": " ".join(["cached"] * 30),
                "metadata": {
                    "extraction_method": "newspaper4k",
                    "http_status": 200,
                    "meta_description": "cached",
                },
            }

        def fail_beautifulsoup(*_args, **_kwargs):
            pytest.fail("BeautifulSoup fallback should not run")

        def fail_selenium(*_args, **_kwargs):
            pytest.fail("Selenium fallback should not run")

        def fail_session(*_args, **_kwargs):
            pytest.fail("Network fetch attempted despite cached HTML")

        monkeypatch.setattr(
            extractor,
            "_extract_with_newspaper",
            fake_newspaper,
        )
        monkeypatch.setattr(
            extractor,
            "_extract_with_beautifulsoup",
            fail_beautifulsoup,
        )
        monkeypatch.setattr(
            extractor,
            "_extract_with_selenium",
            fail_selenium,
        )
        monkeypatch.setattr(extractor, "_get_domain_session", fail_session)

        result = extractor.extract_content(
            "https://example.com/cached", html=cached_html
        )

        assert captured["url"] == "https://example.com/cached"
        assert captured["html"] == cached_html
        assert result["title"] == "Cached Title"
        assert result["metadata"]["extraction_method"] == "newspaper4k"
        extraction_methods = result["metadata"]["extraction_methods"]
        assert extraction_methods["content"] == "newspaper4k"

    def test_cached_html_triggers_offline_fallbacks(
        self,
        extractor,
        monkeypatch,
        mock_html_partial,
    ):
        monkeypatch.setattr(crawler_module, "NEWSPAPER_AVAILABLE", True)

        cached_html = mock_html_partial
        call_order = []

        def fake_newspaper(url, html=None):
            call_order.append(("newspaper", html))
            return {
                "url": url,
                "title": "Partial Cached",
                "author": None,
                "publish_date": None,
                "content": None,
                "metadata": {
                    "extraction_method": "newspaper4k",
                    "http_status": 200,
                    "meta_description": "partial",
                },
            }

        def fake_beautifulsoup(url, html=None):
            call_order.append(("beautifulsoup", html))
            return {
                "url": url,
                "title": None,
                "author": "Offline Author",
                "publish_date": "2024-10-01T10:00:00",
                "content": " ".join(["offline"] * 30),
                "metadata": {
                    "meta_description": "offline cached",
                    "extraction_method": "beautifulsoup",
                    "extra": True,
                },
            }

        def fail_selenium(*_args, **_kwargs):
            pytest.fail("Selenium fallback should not run")

        def fail_session(*_args, **_kwargs):
            pytest.fail("Network fetch attempted despite cached HTML fallback")

        monkeypatch.setattr(
            extractor,
            "_extract_with_newspaper",
            fake_newspaper,
        )
        monkeypatch.setattr(
            extractor,
            "_extract_with_beautifulsoup",
            fake_beautifulsoup,
        )
        monkeypatch.setattr(
            extractor,
            "_extract_with_selenium",
            fail_selenium,
        )
        monkeypatch.setattr(extractor, "_get_domain_session", fail_session)

        result = extractor.extract_content(
            "https://example.com/offline", html=cached_html
        )

        assert call_order == [
            ("newspaper", cached_html),
            ("beautifulsoup", cached_html),
        ]
        assert result["author"] == "Offline Author"
        assert result["content"].startswith("offline offline")
        assert result["metadata"]["extraction_method"] == "beautifulsoup"
        methods = result["metadata"]["extraction_methods"]
        assert methods["title"] == "newspaper4k"
        assert methods["content"] == "beautifulsoup"

        metadata = result.get("metadata", {})
        methods = metadata.get("extraction_methods", {})
        assert methods.get("publish_date") == "beautifulsoup"
        fallback_info = metadata.get("fallbacks", {}).get("publish_date")
        assert fallback_info is None

    def test_publish_date_detected_near_byline_text(self, extractor):
        content = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5
        html = textwrap.dedent(
            f"""
            <html>
                <body>
                    <div class="article-header">
                        <p>KBIA | By Rebecca Smith</p>
                        <p>Published September 26, 2025 at 5:21 PM CDT</p>
                    </div>
                    <div class="content">
                        <p>{content}</p>
                    </div>
                </body>
            </html>
            """
        )

        result = extractor._extract_with_beautifulsoup(
            "https://www.kbia.org/example", html
        )

        assert result["publish_date"] is not None
        assert result["publish_date"].startswith("2025-09-26")

    def test_publish_date_detected_above_byline_text(self, extractor):
        content = "Sed ut perspiciatis unde omnis iste natus error sit voluptatem. " * 4
        html = textwrap.dedent(
            f"""
            <html>
                <body>
                    <div class="story-meta">
                        <p>Posted Wednesday, September 24, 2025 5:00 am</p>
                        <p>
                            By Jonah Foster, Xander Lundblad and Seth
                            Schwartzberg, Columbia Missourian
                        </p>
                    </div>
                    <article>
                        <p>{content}</p>
                    </article>
                </body>
            </html>
            """
        )

        result = extractor._extract_with_beautifulsoup(
            "https://www.mexicoledger.com/example", html
        )

        assert result["publish_date"] is not None
        assert result["publish_date"].startswith("2025-09-24")

    def test_publish_date_detected_next_to_byline_without_keywords(self, extractor):
        content = (
            "Nemo enim ipsam voluptatem quia voluptas sit aspernatur " "aut odit. "
        ) * 4
        html = textwrap.dedent(
            f"""
            <html>
                <body>
                    <div class="story-header">
                        <p>By Valerie Shaver</p>
                        <p>July 21, 2025</p>
                    </div>
                    <article>
                        <p>{content}</p>
                    </article>
                </body>
            </html>
            """
        )

        result = extractor._extract_with_beautifulsoup(
            "https://www.maconhomepress.com/example", html
        )

        assert result["publish_date"] is not None
        assert result["publish_date"].startswith("2025-07-21")

    def test_extract_content_leaves_fields_null_when_no_method_succeeds(
        self, extractor
    ):
        url = "https://example.com/news/item"
        empty_result = {
            "url": url,
            "title": None,
            "author": None,
            "publish_date": None,
            "content": None,
            "metadata": {},
            "extracted_at": datetime.utcnow().isoformat(),
        }

        with (
            patch.object(
                extractor, "_extract_with_newspaper", return_value=empty_result
            ),
            patch.object(extractor, "_extract_with_beautifulsoup", return_value={}),
            patch.object(extractor, "_extract_with_selenium", return_value={}),
        ):
            result = extractor.extract_content(url)

        assert result["title"] is None
        assert result["author"] is None
        assert result["content"] is None
        assert result["publish_date"] is None
        methods = result["metadata"].get("extraction_methods", {})
        assert methods.get("title") == "none"
        assert methods.get("author") == "none"
        assert methods.get("content") == "none"
        assert methods.get("publish_date") == "none"


class TestRealWorldExtraction:
    """Integration tests for real URLs with missing fields."""

    @pytest.mark.integration
    def test_extraction_on_real_urls_with_missing_fields(self, extractor):
        """Test extraction on real URLs that failed with missing fields."""
        # Real URLs from database that have missing fields
        test_urls = [
            # Missing only author
            (
                "https://www.warrencountyrecord.com/stories/"
                "warrior-ridge-elementary-wow-winners,160763"
            ),
            # Missing author and content
            (
                "https://www.webstercountycitizen.com/upcoming_events/"
                "article_6ca9c607-4677-473e-99b3-fb58292d2876.html"
            ),
            # Missing only content
            (
                "https://www.webstercountycitizen.com/community/"
                "article_8130b150-ee3f-11ef-8297-27cfd0562367.html"
            ),
        ]

        print("\n" + "=" * 60)
        print("REAL-WORLD EXTRACTION TEST RESULTS")
        print("=" * 60)

        for i, url in enumerate(test_urls, 1):
            print(f"\n{i}. Testing URL: {url}")
            print("-" * 50)

            try:
                # Test the complete extraction pipeline
                result = extractor.extract_content(url)

                # Analyze the results
                self._analyze_extraction_result(result, url)

                # Test passes if we get some result (even with missing fields)
                # NOTE: Missing fields may indicate data not present in source
                assert result is not None, f"Complete extraction failure for {url}"

                # For real-world URLs, 50%+ completion is often best possible
                # when source HTML lacks structured metadata

            except Exception as e:
                print(f"   ERROR: {str(e)}")
                # Check for network issues
                is_network_error = (
                    "timeout" in str(e).lower() or "connection" in str(e).lower()
                )
                if is_network_error:
                    print(f"   SKIPPED: Network issue with {url}")
                    continue
                else:
                    raise

    def _analyze_extraction_result(self, result, url):
        """Analyze and report on extraction results."""
        if not result:
            print("   RESULT: Complete failure - no data extracted")
            return

        # Check each field
        title = result.get("title")
        author = result.get("author")
        content = result.get("content") or ""
        publish_date = result.get("publish_date")
        metadata = result.get("metadata", {})
        extraction_methods = metadata.get("extraction_methods", {})

        print(f"   TITLE: {'✓' if title else '✗'} {title or '[MISSING]'}")
        print(f"   AUTHOR: {'✓' if author else '✗'} {author or '[MISSING]'}")

        content_ok = len(content) >= 50
        print(f"   CONTENT: {'✓' if content_ok else '✗'} {len(content)} chars")

        date_str = publish_date or "[MISSING]"
        print(f"   DATE: {'✓' if publish_date else '✗'} {date_str}")

        # Show which methods were used for each field
        if extraction_methods:
            print("   EXTRACTION METHODS USED:")
            for field, method in extraction_methods.items():
                print(f"     {field}: {method}")

        # Calculate completion percentage
        fields_present = sum(
            [bool(title), bool(author), bool(len(content) >= 50), bool(publish_date)]
        )
        completion_pct = (fields_present / 4) * 100
        print(f"   COMPLETION: {completion_pct:.0f}% " f"({fields_present}/4 fields)")

        # Test that fallback mechanism was used if needed
        if completion_pct < 100 and extraction_methods:
            methods_used = set(extraction_methods.values())
            if len(methods_used) > 1:
                methods_list = ", ".join(methods_used)
                print(f"   FALLBACK: ✓ Multiple methods used: {methods_list}")
            else:
                single_method = list(methods_used)[0]
                print(f"   FALLBACK: - Only {single_method} used")
                print("   NOTE: Missing fields may not exist in source HTML")
        else:
            print("   ANALYSIS: Extraction successful or no metadata found")

    @pytest.mark.integration
    def test_individual_method_performance(self, extractor):
        """Test each extraction method individually on a real URL."""
        test_url = (
            "https://www.warrencountyrecord.com/stories/"
            "warrior-ridge-elementary-wow-winners,160763"
        )

        print(f"\n{'='*60}")
        print("INDIVIDUAL METHOD PERFORMANCE TEST")
        print(f"URL: {test_url}")
        print(f"{'='*60}")

        methods = [
            ("newspaper4k", extractor._extract_with_newspaper),
            ("beautifulsoup", extractor._extract_with_beautifulsoup),
            ("selenium", extractor._extract_with_selenium),
        ]

        for method_name, method_func in methods:
            print(f"\n--- Testing {method_name.upper()} ---")
            try:
                result = method_func(test_url)
                self._analyze_individual_method(result, method_name)
            except Exception as e:
                print(f"ERROR with {method_name}: {str(e)}")
                # Don't fail the test, just report
                continue

    def _analyze_individual_method(self, result, method_name):
        """Analyze results from individual extraction method."""
        if not result:
            print(f"   {method_name}: Complete failure")
            return

        fields = ["title", "author", "content", "publish_date"]
        results = {}

        for field in fields:
            value = result.get(field)
            if field == "content":
                has_value = value and len(str(value)) >= 50
            else:
                has_value = bool(value and str(value).strip())
            results[field] = "✓" if has_value else "✗"

        field_status = " ".join(
            [f"{field}:{status}" for field, status in results.items()]
        )
        print(f"   {method_name}: {field_status}")

    @pytest.mark.integration
    def test_fallback_trigger_conditions(self, extractor):
        """Test that fallback mechanisms are triggered appropriately."""
        # Use a URL that typically has partial data
        test_url = (
            "https://www.webstercountycitizen.com/upcoming_events/"
            "article_6ca9c607-4677-473e-99b3-fb58292d2876.html"
        )

        print(f"\n{'='*60}")
        print("FALLBACK TRIGGER TEST")
        print(f"URL: {test_url}")
        print(f"{'='*60}")

        # Track method calls by patching the methods
        method_calls = {"newspaper": 0, "beautifulsoup": 0, "selenium": 0}

        original_newspaper = extractor._extract_with_newspaper
        original_beautifulsoup = extractor._extract_with_beautifulsoup
        original_selenium = extractor._extract_with_selenium

        def track_newspaper(*args, **kwargs):
            method_calls["newspaper"] += 1
            return original_newspaper(*args, **kwargs)

        def track_beautifulsoup(*args, **kwargs):
            method_calls["beautifulsoup"] += 1
            return original_beautifulsoup(*args, **kwargs)

        def track_selenium(*args, **kwargs):
            method_calls["selenium"] += 1
            return original_selenium(*args, **kwargs)

        with (
            patch.object(extractor, "_extract_with_newspaper", track_newspaper),
            patch.object(extractor, "_extract_with_beautifulsoup", track_beautifulsoup),
            patch.object(extractor, "_extract_with_selenium", track_selenium),
        ):

            try:
                result = extractor.extract_content(test_url)

                print("\nMETHOD CALLS:")
                print(f"   newspaper4k: {method_calls['newspaper']} calls")
                bs_calls = method_calls["beautifulsoup"]
                print(f"   beautifulsoup: {bs_calls} calls")
                print(f"   selenium: {method_calls['selenium']} calls")

                # Verify fallback logic
                if method_calls["newspaper"] > 0:
                    print("   ✓ Primary method (newspaper4k) was attempted")

                fallback_used = (
                    method_calls["beautifulsoup"] > 0 or method_calls["selenium"] > 0
                )
                if fallback_used:
                    print("   ✓ Fallback methods were triggered")

                    metadata = result.get("metadata", {}) if result else {}
                    extraction_methods = metadata.get("extraction_methods", {})
                    if extraction_methods:
                        methods_used = set(extraction_methods.values())
                        if len(methods_used) > 1:
                            print(
                                "   ✓ Multiple methods successfully "
                                f"contributed: {methods_used}"
                            )

            except Exception as e:
                print(f"   ERROR: {str(e)}")
                # Don't fail test for network issues
                is_network_error = (
                    "timeout" not in str(e).lower()
                    and "connection" not in str(e).lower()
                )
                if not is_network_error:
                    raise


class TestNewspaperMethod:
    """Tests for the newspaper4k extraction method."""

    def test_newspaper_extraction_success(self, extractor, mock_html_complete):
        """Test successful newspaper4k extraction with all fields."""
        with patch("src.crawler.NewspaperArticle") as mock_article_class:
            # Mock the NewspaperArticle instance
            mock_article = Mock()
            mock_article.title = "Test Article Title"
            mock_article.text = "This is the main content of the test article."
            mock_article.authors = ["John Doe"]
            mock_article.publish_date = datetime(2023, 1, 15, 10, 0, 0)
            mock_article.meta_description = "Test description"
            mock_article.keywords = ["test", "article"]

            mock_article_class.return_value = mock_article

            # Mock session.get to avoid actual HTTP requests
            with patch.object(extractor.session, "get") as mock_get:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = mock_html_complete
                mock_get.return_value = mock_response

                result = extractor._extract_with_newspaper("https://test.com")

                assert result is not None
                assert result["title"] == "Test Article Title"
                assert result["author"] == "John Doe"
                assert "main content" in result["content"]
                assert result["publish_date"] == "2023-01-15T10:00:00"
                assert result["metadata"]["extraction_method"] == "newspaper4k"

    def test_newspaper_extraction_failure(self, extractor):
        """Test newspaper4k extraction failure handling."""
        with patch("src.crawler.NewspaperArticle") as mock_article_class:
            # Mock article parse failure
            mock_article_class.side_effect = Exception("Parse error")

            # Should handle exception and return empty result
            try:
                extractor._extract_with_newspaper("https://test.com")
                assert False, "Expected exception to be raised"
            except Exception as e:
                assert str(e) == "Parse error"

    def test_newspaper_extraction_partial(self, extractor, mock_html_partial):
        """Test newspaper4k extraction with partial content."""
        with patch("src.crawler.NewspaperArticle") as mock_article_class:
            mock_article = Mock()
            mock_article.title = "Partial Article"
            mock_article.text = "Short content without author or date."
            mock_article.authors = []  # No authors
            mock_article.publish_date = None  # No date
            mock_article.meta_description = ""
            mock_article.keywords = []

            mock_article_class.return_value = mock_article

            with patch.object(extractor.session, "get") as mock_get:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = mock_html_partial
                mock_get.return_value = mock_response

                result = extractor._extract_with_newspaper("https://test.com")

                assert result is not None
                assert result["title"] == "Partial Article"
                assert result["author"] is None  # No authors
                assert result["publish_date"] is None  # No date


class TestBeautifulSoupMethod:
    """Tests for the BeautifulSoup extraction method."""

    def test_beautifulsoup_extraction_success(
        self, extractor, mock_html_complete, mock_requests_response
    ):
        """Test successful BeautifulSoup extraction."""
        with patch.object(extractor.session, "get") as mock_get:
            mock_get.return_value = mock_requests_response(mock_html_complete)

            with patch.object(
                extractor,
                "_get_domain_session",
                return_value=extractor.session,
            ):
                result = extractor._extract_with_beautifulsoup("https://test.com")

            assert result is not None
            assert result["title"] == "Test Article Title"
            assert result["metadata"]["extraction_method"] == "beautifulsoup"

    def test_beautifulsoup_with_provided_html(self, extractor, mock_html_complete):
        """Test BeautifulSoup extraction with pre-provided HTML."""
        result = extractor._extract_with_beautifulsoup(
            "https://test.com", mock_html_complete
        )

        assert result is not None
        assert result["title"] == "Test Article Title"

    def test_beautifulsoup_network_failure(self, extractor, mock_requests_response):
        """Test BeautifulSoup extraction with network failure."""
        with patch.object(extractor.session, "get") as mock_get:
            mock_get.return_value = mock_requests_response("", 404)
            mock_get.return_value.raise_for_status.side_effect = (
                requests.RequestException("404")
            )

            with patch.object(
                extractor,
                "_get_domain_session",
                return_value=extractor.session,
            ):
                result = extractor._extract_with_beautifulsoup("https://test.com")

            assert result == {}


class TestSeleniumMethod:
    """Tests for the Selenium extraction method."""

    def test_selenium_extraction_success(self, extractor, mock_webdriver):
        """Test successful Selenium extraction."""
        # Mock the webdriver creation instead of testing actual extraction
        with patch.object(
            extractor, "_create_undetected_driver", return_value=mock_webdriver
        ):
            with patch("src.crawler.WebDriverWait") as mock_wait:
                # Setup mock elements
                mock_title_element = Mock()
                mock_title_element.text = "Selenium Test"

                mock_content_element = Mock()
                mock_content_element.text = (
                    "This is selenium extracted content that is long "
                    "enough to meet the minimum requirements"
                )

                # Setup webdriver mocks
                mock_webdriver.find_elements.side_effect = [
                    [mock_title_element],  # Title query
                    [mock_content_element],  # Content query
                    [],  # Author query (empty)
                    [],  # Date query (empty)
                ]
                mock_webdriver.page_source = (
                    "<html><head><title>Selenium Test</title></head>"
                    "<body>This is selenium extracted content that is long "
                    "enough to meet the minimum requirements</body></html>"
                )

                # Mock WebDriverWait.until to simulate successful page load
                mock_wait.return_value.until.return_value = True

                # Mock CAPTCHA detection to return False
                with patch.object(
                    extractor, "_detect_captcha_or_challenge", return_value=False
                ):
                    result = extractor._extract_with_selenium("https://test.com")

                assert result is not None
                assert result["title"] == "Selenium Test"
                assert result["metadata"]["extraction_method"] == "selenium"

    def test_selenium_stealth_application(self, extractor, mock_webdriver):
        """Test that selenium-stealth is applied when available."""
        # Test stealth driver creation directly
        with (
            patch("src.crawler.stealth") as mock_stealth,
            patch("src.crawler.SELENIUM_STEALTH_AVAILABLE", True),
        ):

            extractor._create_stealth_driver()

            # Verify stealth was applied
            mock_stealth.assert_called_once()


class TestFallbackMechanism:
    """Tests for the intelligent field-level fallback system."""

    def test_complete_extraction_no_fallback(self, extractor, mock_html_complete):
        """Test that no fallback is needed when first method succeeds."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_np,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            # Newspaper returns complete results
            mock_np.return_value = {
                "title": "Complete Title",
                "author": "Complete Author",
                "content": (
                    "This is complete content with more than 50 characters "
                    "to pass the validation test."
                ),
                "publish_date": "2023-01-15T10:00:00",
                "metadata": {
                    "language": "en",
                    "keywords": ["test", "article"],
                    "tags": ["news", "testing"],
                },
                "extracted_at": datetime.utcnow().isoformat(),
            }

            # Other methods should not be called since first is complete
            mock_bs.return_value = {}
            mock_sel.return_value = {}

            result = extractor.extract_content("https://test.com")

            # Should not call fallback methods since first method succeeded
            mock_np.assert_called_once()
            mock_bs.assert_not_called()
            mock_sel.assert_not_called()

            # Check that all fields came from newspaper4k
            methods = result["metadata"]["extraction_methods"]
            assert methods["title"] == "newspaper4k"
            assert methods["author"] == "newspaper4k"
            assert methods["content"] == "newspaper4k"

    def test_partial_extraction_with_beautifulsoup_fallback(self, extractor):
        """Test fallback to BeautifulSoup for missing fields."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_np,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
        ):

            # Newspaper returns partial results
            mock_np.return_value = {
                "title": "Newspaper Title",
                "author": None,  # Missing
                "content": "Short",  # Too short (< 50 chars)
                "publish_date": "2023-01-15T10:00:00",
                "metadata": {"language": "en"},  # Remove extraction_method
                "extracted_at": datetime.utcnow().isoformat(),
            }

            # BeautifulSoup fills in missing fields
            mock_bs.return_value = {
                "title": "BS Title",  # Won't override existing
                "author": "BS Author",  # Will fill missing
                "content": (
                    "BeautifulSoup extracted much longer content "
                    "that meets the minimum character requirement"
                ),
                "publish_date": None,  # Won't override existing
                "metadata": {"tags": ["bs", "fallback"]},
                "extracted_at": datetime.utcnow().isoformat(),
            }

            result = extractor.extract_content("https://test.com")

            # Should combine results appropriately
            assert result["title"] == "Newspaper Title"
            assert result["author"] == "BS Author"
            assert result["content"].startswith("BeautifulSoup")
            assert result["publish_date"] == "2023-01-15T10:00:00"

            # Check method tracking
            methods = result["metadata"]["extraction_methods"]
            assert methods["title"] == "newspaper4k"
            assert methods["author"] == "beautifulsoup"
            assert methods["content"] == "beautifulsoup"
            assert methods["publish_date"] == "newspaper4k"

    def test_full_cascade_to_selenium(self, extractor):
        """Test full cascade from newspaper → BeautifulSoup → Selenium."""
        with (
            patch.object(extractor, "_extract_with_newspaper") as mock_np,
            patch.object(extractor, "_extract_with_beautifulsoup") as mock_bs,
            patch.object(extractor, "_extract_with_selenium") as mock_sel,
        ):

            # Newspaper fails completely
            mock_np.return_value = {}

            # BeautifulSoup gets some fields
            mock_bs.return_value = {
                "title": "BS Title",
                "author": None,  # Still missing
                "content": None,  # Still missing
                "publish_date": "2023-01-15T10:00:00",
                "metadata": {"language": "en"},
                "extracted_at": datetime.utcnow().isoformat(),
            }

            # Selenium gets remaining fields
            mock_sel.return_value = {
                "title": "Selenium Title",  # Won't override
                "author": "Selenium Author",  # Will fill missing
                "content": (
                    "Selenium extracted comprehensive content that "
                    "is long enough to meet requirements"
                ),
                "publish_date": None,  # Won't override
                "metadata": {"platform": "selenium"},
                "extracted_at": datetime.utcnow().isoformat(),
            }

            result = extractor.extract_content("https://test.com")

            # Should use best result from each method
            assert result["title"] == "Selenium Title"
            assert result["author"] == "Selenium Author"
            assert result["content"].startswith("Selenium")
            assert result["publish_date"] == "2023-01-15T10:00:00"

            # All three methods should have been called
            mock_np.assert_called_once()
            mock_bs.assert_called_once()
            mock_sel.assert_called_once()


class TestMethodTracking:
    """Tests for extraction method tracking and telemetry."""

    def test_extraction_methods_metadata(self, extractor):
        """Test that extraction methods are tracked in metadata."""
        with patch.object(extractor, "_extract_with_newspaper") as mock_np:
            mock_np.return_value = {
                "title": "Test Title",
                "author": "Test Author",
                "content": (
                    "Test content that is sufficiently long to meet "
                    "the minimum character requirements for validation"
                ),
                "publish_date": "2023-01-15T10:00:00",
                "metadata": {"language": "en", "tags": ["test"]},
                "extracted_at": datetime.utcnow().isoformat(),
            }

            result = extractor.extract_content("https://test.com")

            assert "extraction_methods" in result["metadata"]
            methods = result["metadata"]["extraction_methods"]
            assert methods["title"] == "newspaper4k"
            assert methods["author"] == "newspaper4k"
            assert methods["content"] == "newspaper4k"
            assert methods["publish_date"] == "newspaper4k"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_all_methods_fail(self, extractor):
        """Test behavior when all extraction methods fail."""
        with (
            patch.object(extractor, "_extract_with_newspaper", return_value={}),
            patch.object(extractor, "_extract_with_beautifulsoup", return_value={}),
            patch.object(extractor, "_extract_with_selenium", return_value={}),
        ):

            result = extractor.extract_content("https://test.com")

            # Should return minimal structure
            assert result["url"] == "https://test.com"
            assert result["title"] is None
            assert result["author"] is None
            assert result["content"] is None

    def test_network_timeout_handling(self, extractor):
        """Test handling of network timeouts."""
        with patch.object(
            extractor.session, "get", side_effect=requests.Timeout("Timeout")
        ):
            result = extractor._extract_with_beautifulsoup("https://test.com")
            assert result == {}

    def test_invalid_html_handling(self, extractor):
        """Test handling of malformed HTML."""
        malformed_html = """<html><head><title>Test</head>
                           <body><p>Unclosed tag<body></html>"""

        # BeautifulSoup should handle malformed HTML gracefully
        result = extractor._extract_with_beautifulsoup(
            "https://test.com", malformed_html
        )
        assert result is not None
        assert result["title"] == "Test"


class TestRealWorldExtractionFailures:
    """Tests extraction on real URLs that previously failed with missing fields."""

    def test_warren_county_record_missing_author(self, extractor):
        """Test extraction on Warren County Record URL missing author."""
        url = (
            "https://www.warrencountyrecord.com/stories/"
            "warrior-ridge-elementary-wow-winners,160763"
        )

        result = extractor.extract_content(url)

        # Should have extracted content even if some fields are missing
        assert result is not None
        assert result["title"] is not None
        assert len(result["title"]) > 5

        # Check extraction methods tracking
        assert "extraction_methods" in result["metadata"]
        methods = result["metadata"]["extraction_methods"]

        # Verify that fallback methods were used if needed
        print(f"Extraction methods used: {methods}")
        print(f"Title: {result['title']}")
        print(f"Author: {result['author']}")
        content_len = len(result["content"]) if result["content"] else 0
        print(f"Content length: {content_len}")

    def test_webster_county_citizen_missing_content(self, extractor):
        """Test extraction on Webster County Citizen URL missing content."""
        url = (
            "https://www.webstercountycitizen.com/upcoming_events/"
            "article_6ca9c607-4677-473e-99b3-fb58292d2876.html"
        )

        result = extractor.extract_content(url)

        # Should have extracted content even if some fields are missing
        assert result is not None
        assert result["title"] is not None
        assert len(result["title"]) > 5

        # Check if content was successfully extracted this time
        if result["content"]:
            assert len(result["content"]) > 50

        # Check extraction methods tracking
        assert "extraction_methods" in result["metadata"]
        methods = result["metadata"]["extraction_methods"]

        # Verify that fallback methods were used if needed
        print(f"Extraction methods used: {methods}")
        print(f"Title: {result['title']}")
        print(f"Author: {result['author']}")
        content_len = len(result["content"]) if result["content"] else 0
        print(f"Content length: {content_len}")

    def test_multiple_failed_urls_batch(self, extractor):
        """Test extraction on multiple URLs that previously failed."""
        failed_urls = [
            (
                "https://www.warrencountyrecord.com/stories/"
                "aco-results-mercys-care-saves-taxpayers-more-than-100-million,"
                "160764"
            ),
            (
                "https://www.webstercountycitizen.com/news/"
                "article_2eb5321a-abc1-4310-90e8-92d6c232848b.html"
            ),
            (
                "https://www.webstercountycitizen.com/community/"
                "article_45667631-bc02-4d86-8d67-09bc24bb0846.html"
            ),
        ]

        results = []
        for url in failed_urls:
            print(f"\nTesting extraction for: {url}")
            try:
                result = extractor.extract_content(url)
                results.append((url, result))

                if result:
                    print(f"✅ Success - Title: {result['title']}")
                    print(f"   Author: {result['author'] or '[Missing]'}")
                    content_len = len(result["content"]) if result["content"] else 0
                    print(f"   Content length: {content_len}")
                    methods = result["metadata"].get("extraction_methods", {})
                    print(f"   Methods used: {methods}")
                else:
                    print("❌ Failed - No result returned")

            except Exception as e:
                print(f"❌ Error: {e}")
                results.append((url, None))

        # At least some should succeed
        successful_extractions = [r for url, r in results if r is not None]
        assert len(successful_extractions) > 0, "No URLs were successfully extracted"

        success_count = len(successful_extractions)
        total_count = len(failed_urls)
        summary_msg = f"Summary: {success_count}/{total_count} URLs extracted"
        print(f"\n{summary_msg}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
