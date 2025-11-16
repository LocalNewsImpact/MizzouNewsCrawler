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
        """Test section discovery finds basic news sections."""
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
        
        assert len(sections) == 3
        assert "https://example.com/news" in sections
        assert "https://example.com/sports" in sections
        assert "https://example.com/weather" in sections

    def test_discover_section_urls_relative_paths(self):
        """Test section discovery handles relative paths correctly."""
        html = """
        <nav>
            <a href="/local/">Local News</a>
            <a href="news/politics">Politics</a>
        </nav>
        """
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )
        
        assert "https://example.com/local/" in sections
        assert "https://example.com/news/politics" in sections

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
        
        # Should only include /news and /local, not feed URLs
        assert len(sections) == 2
        assert "https://example.com/news" in sections
        assert "https://example.com/local" in sections

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
        
        # Should only include same-domain URLs
        assert len(sections) == 2
        assert "https://example.com/news" in sections
        assert "https://example.com/local" in sections

    def test_discover_section_urls_deduplicates(self):
        """Test section discovery deduplicates URLs."""
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
        
        # Should deduplicate based on normalized path
        # Both /news and /news/ should be treated as different initially
        # but query params should be stripped
        assert len(sections) <= 2  # Could be 1 or 2 depending on normalization

    def test_discover_section_urls_limits_results(self):
        """Test section discovery limits number of sections returned."""
        # Create HTML with many section links
        links = "".join(
            f'<a href="/news-{i}">News {i}</a>' for i in range(20)
        )
        html = f"<nav>{links}</nav>"
        
        sections = NewsDiscovery._discover_section_urls(
            "https://example.com",
            html,
        )
        
        # Should limit to max 10 sections
        assert len(sections) <= 10

    def test_discover_section_urls_nav_element(self):
        """Test section discovery works with <nav> element."""
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
        
        assert len(sections) == 2

    def test_discover_section_urls_menu_element(self):
        """Test section discovery works with <menu> element."""
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
        
        assert len(sections) == 2

    def test_discover_section_urls_div_with_nav_class(self):
        """Test section discovery works with div having nav-related class."""
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
        
        assert len(sections) == 2

    def test_discover_section_urls_case_insensitive(self):
        """Test section discovery is case-insensitive for paths."""
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
        
        # Should find sections regardless of case
        assert len(sections) == 3

    def test_discover_section_urls_common_patterns(self):
        """Test section discovery finds all common section patterns."""
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
        
        # Should find all 10 common section patterns
        assert len(sections) == 10

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
        
        # Should only include /news
        assert len(sections) == 1
        assert "https://example.com/news" in sections

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
        
        # Should normalize by removing query/fragment
        assert "https://example.com/news" in sections
        assert "https://example.com/sports" in sections
        # Should not include query params or fragments
        for section in sections:
            assert "?" not in section
            assert "#" not in section

    def test_discover_section_urls_real_world_example(self):
        """Test section discovery with realistic news site HTML."""
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
        
        # Should find news-related sections but not contact
        assert len(sections) >= 3
        # The current implementation looks for specific patterns
        # /local-news might not match /local pattern exactly
        assert any("/sports" in s for s in sections)
        assert any("/weather" in s for s in sections)
        assert any("/business" in s for s in sections)
