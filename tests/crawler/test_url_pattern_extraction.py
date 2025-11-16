"""Unit tests for URL pattern extraction from article URLs."""

from src.crawler.discovery import NewsDiscovery


class TestSectionExtractionFromArticles:
    """Tests for _extract_sections_from_article_urls method."""

    def test_extract_sections_empty_list(self):
        """Test extraction with empty article list returns empty."""
        sections = NewsDiscovery._extract_sections_from_article_urls(
            [],
            "https://example.com",
        )
        assert sections == []

    def test_extract_sections_single_article(self):
        """Test extraction with single article returns empty (below min)."""
        articles = ["https://example.com/news/article-123.html"]
        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )
        # Below min_occurrences=2, so no sections
        assert sections == []

    def test_extract_sections_common_pattern(self):
        """Test extraction finds common parent paths."""
        articles = [
            "https://example.com/news/local/article-1.html",
            "https://example.com/news/local/article-2.html",
            "https://example.com/news/local/article-3.html",
            "https://example.com/sports/article-4.html",
            "https://example.com/sports/article-5.html",
        ]
        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should find /news/local/ (3 occurrences), /news/ (3), /sports/ (2)
        assert "https://example.com/news/local/" in sections
        assert "https://example.com/news/" in sections
        assert "https://example.com/sports/" in sections
        assert len(sections) == 3

    def test_extract_sections_different_depths(self):
        """Test extraction handles different URL depths."""
        articles = [
            "https://example.com/news/article-1.html",
            "https://example.com/news/article-2.html",
            "https://example.com/news/local/city/deep-article.html",
            "https://example.com/news/local/county/deep-article2.html",
        ]
        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should find /news/ (shallow pattern, 2+ occurrences)
        # /news/local/ might be found if we extract parent paths
        assert "https://example.com/news/" in sections
        # Should not find deep paths like /news/local/city/ (only 1 each)

    def test_extract_sections_strips_query_params(self):
        """Test extraction strips query params and fragments."""
        articles = [
            "https://example.com/news/article-1.html?ref=homepage",
            "https://example.com/news/article-2.html#section",
            "https://example.com/news/article-3.html",
        ]
        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should normalize to /news/ (3 occurrences)
        assert "https://example.com/news/" in sections
        # No query params in results
        for section in sections:
            assert "?" not in section
            assert "#" not in section

    def test_extract_sections_limits_results(self):
        """Test extraction limits to top 15 sections."""
        # Create 20 different section patterns with 2 articles each
        articles = []
        for i in range(20):
            articles.extend(
                [
                    f"https://example.com/section-{i}/article-1.html",
                    f"https://example.com/section-{i}/article-2.html",
                ]
            )

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should limit to 15 most common
        assert len(sections) == 15

    def test_extract_sections_min_occurrences(self):
        """Test extraction respects min_occurrences parameter."""
        articles = [
            "https://example.com/news/article-1.html",
            "https://example.com/sports/article-2.html",
            "https://example.com/weather/article-3.html",
        ]

        # With min_occurrences=1, should find all
        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
            min_occurrences=1,
        )
        assert len(sections) == 3

        # With min_occurrences=2, should find none
        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
            min_occurrences=2,
        )
        assert len(sections) == 0

    def test_extract_sections_same_domain_only(self):
        """Test extraction ignores different domains."""
        articles = [
            "https://example.com/news/article-1.html",
            "https://example.com/news/article-2.html",
            "https://external.com/news/article-3.html",
            "https://external.com/news/article-4.html",
        ]
        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should only count example.com articles
        assert "https://example.com/news/" in sections
        assert not any("external.com" in s for s in sections)
