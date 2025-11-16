"""Unit tests for section discovery functionality."""

import pytest

from src.crawler.discovery import NewsDiscovery


class TestSectionDiscovery:
    """Tests for _discover_section_urls method."""

    def test_discover_section_urls_empty_html(self):
        """Test section discovery with empty HTML returns empty list."""
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            "",
        )
        assert sections == []

    def test_discover_section_urls_no_sections(self):
        """Test section discovery with HTML containing no section links."""
        html = """
        <html>
            <body>
                <a href="/contact">Contact</a>
                <a href="/about">About</a>
            </body>
        </html>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )
        assert sections == []

    def test_discover_section_urls_basic_sections(self):
        """Test section discovery finds basic news sections via fuzzy matching."""
        html = """
        <html>
            <nav>
                <a href="/news">News</a>
                <a href="/sports">Sports</a>
                <a href="/weather">Weather</a>
            </nav>
        </html>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching: should find /news, /sports, /weather
        # because keywords match path segments or link text
        assert len(sections) == 3
        assert "https://example.com/news/" in sections
        assert "https://example.com/sports/" in sections
        assert "https://example.com/weather/" in sections

    def test_discover_section_urls_relative_paths(self):
        """
        Test section discovery handles relative paths correctly
        with fuzzy matching.
        """
        html = """
        <nav>
            <a href="/local/">Local News</a>
            <a href="/news/politics">Politics</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching: /local/ matches "local" keyword via link text "Local News"
        # /news/politics matches "news" and "politics" keywords
        assert "https://example.com/local/" in sections
        assert "https://example.com/news/politics/" in sections

    def test_discover_section_urls_filters_rss_feeds(self):
        """Test section discovery filters out RSS/feed URLs."""
        html = """
        <nav>
            <a href="/news">News</a>
            <a href="/rss">RSS Feed</a>
            <a href="/news/feed">News Feed</a>
            <a href="/sports.xml">Sports XML</a>
            <a href="/local">Local</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching: should find /news, /local, /sports.xml
        # (matched "sports" keyword) but filters out /rss, /news/feed
        # (contains "feed")
        # Note: /sports.xml will be filtered by extension check
        assert "https://example.com/news/" in sections
        assert "https://example.com/local/" in sections
        assert not any("feed" in s for s in sections)
        assert not any(".xml" in s for s in sections)

    def test_discover_section_urls_same_domain_only(self):
        """Test section discovery only returns same-domain URLs."""
        html = """
        <nav>
            <a href="/news">News</a>
            <a href="https://external.com/news">External News</a>
            <a href="//other.com/sports">Other Sports</a>
            <a href="/local">Local</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Should only include same-domain URLs (external URLs filtered out)
        assert len(sections) == 2
        assert "https://example.com/news/" in sections
        assert "https://example.com/local/" in sections

    def test_discover_section_urls_deduplicates(self):
        """
        Test section discovery deduplicates URLs with
        trailing slash normalization.
        """
        html = """
        <nav>
            <a href="/news">News</a>
            <a href="/news/">News Alt</a>
            <a href="/news?page=1">News Query</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Should deduplicate: all normalize to /news/ with trailing slash
        # Query params are stripped during normalization
        assert len(sections) == 1
        assert "https://example.com/news/" in sections

    def test_discover_section_urls_limits_results(self):
        """Test section discovery limits number of sections returned."""
        # Create HTML with many section links that match "news" keyword
        links = "".join(f'<a href="/news-{i}">News {i}</a>' for i in range(30))
        html = f"<nav>{links}</nav>"

        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Should limit to max 20 sections (updated from 10)
        assert len(sections) <= 20

    def test_discover_section_urls_nav_element(self):
        """Test section discovery works with <nav> element and fuzzy matching."""
        html = """
        <nav class="main-menu">
            <a href="/news">News</a>
            <a href="/sports">Sports</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching finds both via keyword match
        assert len(sections) == 2
        assert "https://example.com/news/" in sections
        assert "https://example.com/sports/" in sections

    def test_discover_section_urls_menu_element(self):
        """Test section discovery works with <menu> element and fuzzy matching."""
        html = """
        <menu>
            <a href="/local">Local</a>
            <a href="/weather">Weather</a>
        </menu>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching finds both via keyword match
        assert len(sections) == 2
        assert "https://example.com/local/" in sections
        assert "https://example.com/weather/" in sections

    def test_discover_section_urls_div_with_nav_class(self):
        """
        Test section discovery works with div having nav-related class
        and fuzzy matching.
        """
        html = """
        <div class="navigation">
            <a href="/news">News</a>
            <a href="/business">Business</a>
        </div>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching finds both via keyword match
        assert len(sections) == 2
        assert "https://example.com/news/" in sections
        assert "https://example.com/business/" in sections

    def test_discover_section_urls_case_insensitive(self):
        """Test section discovery is case-insensitive for fuzzy matching."""
        html = """
        <nav>
            <a href="/NEWS">News</a>
            <a href="/Local">Local</a>
            <a href="/SPORTS">Sports</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching is case-insensitive (lowercases for matching)
        # URLs are normalized to lowercase during processing
        assert len(sections) == 3
        assert "https://example.com/news/" in sections
        assert "https://example.com/local/" in sections
        assert "https://example.com/sports/" in sections

    def test_discover_section_urls_common_patterns(self):
        """
        Test section discovery finds all common section keywords
        via fuzzy matching.
        """
        html = """
        <nav>
            <a href="/news">News</a>
            <a href="/local">Local</a>
            <a href="/sports">Sports</a>
            <a href="/weather">Weather</a>
            <a href="/politics">Politics</a>
            <a href="/business">Business</a>
            <a href="/entertainment">Entertainment</a>
            <a href="/opinion">Opinion</a>
            <a href="/lifestyle">Lifestyle</a>
            <a href="/community">Community</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Fuzzy matching finds all 10 common keywords
        assert len(sections) == 10
        assert "https://example.com/news/" in sections
        assert "https://example.com/local/" in sections
        assert "https://example.com/sports/" in sections
        assert "https://example.com/weather/" in sections
        assert "https://example.com/politics/" in sections
        assert "https://example.com/business/" in sections
        assert "https://example.com/entertainment/" in sections
        assert "https://example.com/opinion/" in sections
        assert "https://example.com/lifestyle/" in sections
        assert "https://example.com/community/" in sections

    def test_discover_section_urls_skips_non_http_protocols(self):
        """Test section discovery skips mailto, tel, javascript links."""
        html = """
        <nav>
            <a href="/news">News</a>
            <a href="mailto:editor@example.com">Email</a>
            <a href="tel:555-1234">Phone</a>
            <a href="javascript:void(0)">Click</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Should only include /news (non-HTTP protocols filtered)
        assert len(sections) == 1
        assert "https://example.com/news/" in sections

    def test_discover_section_urls_strips_query_params(self):
        """Test section discovery strips query parameters from URLs."""
        html = """
        <nav>
            <a href="/news?ref=homepage">News</a>
            <a href="/sports#top">Sports</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )

        # Should normalize by removing query/fragment (adds trailing slash)
        assert "https://example.com/news/" in sections
        assert "https://example.com/sports/" in sections
        # Should not include query params or fragments
        for section in sections:
            assert "?" not in section
            assert "#" not in section

    def test_discover_section_urls_real_world_example(self):
        """Test section discovery with realistic news site HTML and fuzzy matching."""
        html = """
        <html>
            <header>
                <nav class="main-navigation">
                    <ul>
                        <li><a href="/">Home</a></li>
                        <li><a href="/local-news">Local News</a></li>
                        <li><a href="/sports">Sports</a></li>
                        <li><a href="/weather">Weather</a></li>
                        <li><a href="/obituaries">Obituaries</a></li>
                        <li><a href="/business">Business</a></li>
                        <li><a href="/contact">Contact Us</a></li>
                    </ul>
                </nav>
            </header>
            <div class="content">
                <a href="/article/123">Some Article</a>
            </div>
        </html>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://localnews.example.com",
            html,
        )

        # Fuzzy matching finds sections via keywords in path or link text
        # /local-news matches "local" keyword (in path) and link text "Local News"
        # /sports, /weather, /business all match keywords
        # /contact does not match any keyword
        assert len(sections) >= 4
        assert any("local-news" in s for s in sections)
        assert any("sports/" in s for s in sections)
        assert any("weather/" in s for s in sections)
        assert any("business/" in s for s in sections)
        assert not any("contact" in s for s in sections)
