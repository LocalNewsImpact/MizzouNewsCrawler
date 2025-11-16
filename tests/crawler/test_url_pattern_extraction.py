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


class TestRealisticURLPatterns:
    """
    Tests for identifying section fronts from realistic article URL patterns.

    These tests simulate real-world news site URL structures to verify the
    extraction method can identify section landing pages from article URLs.
    """

    def test_columbian_missourian_structure(self):
        """Test extraction with Columbia Missourian URL structure."""
        # Real pattern: /news/local/article_uuid.html
        articles = [
            "https://www.columbiamissourian.com/news/local/boone-county-begins-budget-planning/article_123.html",
            "https://www.columbiamissourian.com/news/local/city-council-approves-plan/article_456.html",
            "https://www.columbiamissourian.com/news/local/new-school-opens/article_789.html",
            "https://www.columbiamissourian.com/news/state/missouri-legislature-votes/article_abc.html",
            "https://www.columbiamissourian.com/news/state/governor-announces-plan/article_def.html",
            "https://www.columbiamissourian.com/sports/mizzou-football-wins/article_ghi.html",
            "https://www.columbiamissourian.com/sports/tigers-basketball-game/article_jkl.html",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://www.columbiamissourian.com",
        )

        # Should identify section fronts
        assert "https://www.columbiamissourian.com/news/" in sections
        assert "https://www.columbiamissourian.com/news/local/" in sections
        assert "https://www.columbiamissourian.com/news/state/" in sections
        assert "https://www.columbiamissourian.com/sports/" in sections

    def test_wordpress_date_based_structure(self):
        """Test extraction with WordPress date-based URL structure."""
        # Pattern: /YYYY/MM/DD/article-slug/
        articles = [
            "https://example.com/2024/11/15/local-news-story/",
            "https://example.com/2024/11/14/another-local-story/",
            "https://example.com/2024/11/13/more-local-news/",
            "https://example.com/2024/10/20/sports-update/",
            "https://example.com/2024/10/19/game-recap/",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
            min_occurrences=2,
        )

        # Date-based URLs will extract year and year/month patterns
        # since extraction only goes 1-2 segments deep
        # Should find /2024/ (5 occurrences) and /2024/11/ (3), /2024/10/ (2)
        assert "https://example.com/2024/" in sections
        assert "https://example.com/2024/11/" in sections
        assert "https://example.com/2024/10/" in sections
        # These are date patterns, not semantic sections, but that's what
        # extraction finds (Strategy 1 fuzzy matching would filter these)

    def test_shallow_single_segment_structure(self):
        """Test extraction with single-level category structure."""
        # Pattern: /category/article-slug.html
        articles = [
            "https://example.com/news/story-1.html",
            "https://example.com/news/story-2.html",
            "https://example.com/news/story-3.html",
            "https://example.com/sports/game-1.html",
            "https://example.com/sports/game-2.html",
            "https://example.com/business/company-news-1.html",
            "https://example.com/business/company-news-2.html",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should identify top-level sections
        assert "https://example.com/news/" in sections
        assert "https://example.com/sports/" in sections
        assert "https://example.com/business/" in sections
        assert len(sections) == 3

    def test_deep_hierarchical_structure(self):
        """Test extraction with deep category hierarchy."""
        # Pattern: /section/subsection/category/article
        articles = [
            "https://example.com/news/local/crime/robbery-report.html",
            "https://example.com/news/local/crime/arrest-made.html",
            "https://example.com/news/local/crime/investigation-ongoing.html",
            "https://example.com/news/local/politics/mayor-speech.html",
            "https://example.com/news/local/politics/council-vote.html",
            "https://example.com/news/state/legislation/new-bill.html",
            "https://example.com/news/state/legislation/vote-result.html",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Extraction only goes 1-2 segments deep (intentionally limited)
        # Should identify first two depth levels
        assert "https://example.com/news/" in sections
        assert "https://example.com/news/local/" in sections
        assert "https://example.com/news/state/" in sections
        # Third level paths like /news/local/crime/ are NOT extracted
        # (too specific, would need min 3 segments depth)
        assert len(sections) == 3

    def test_mixed_depth_patterns(self):
        """Test extraction with inconsistent URL depth patterns."""
        articles = [
            # Some shallow
            "https://example.com/news/article-1.html",
            "https://example.com/news/article-2.html",
            "https://example.com/news/article-3.html",
            # Some deep
            "https://example.com/news/local/city/article-4.html",
            "https://example.com/news/local/county/article-5.html",
            # Some medium
            "https://example.com/sports/football/article-6.html",
            "https://example.com/sports/football/article-7.html",
            "https://example.com/sports/basketball/article-8.html",
            "https://example.com/sports/basketball/article-9.html",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should identify sections at multiple levels
        assert "https://example.com/news/" in sections  # 3 shallow
        assert "https://example.com/sports/" in sections  # 4 total
        assert "https://example.com/sports/football/" in sections  # 2
        assert "https://example.com/sports/basketball/" in sections  # 2
        # Deep paths with only 1 occurrence should not appear
        assert not any("news/local/city" in s for s in sections)  # Only 1 occurrence
        assert not any("news/local/county" in s for s in sections)  # Only 1

    def test_trailing_slash_vs_extension_normalization(self):
        """Test that URLs with different endings normalize correctly."""
        articles = [
            "https://example.com/news/story-1.html",
            "https://example.com/news/story-2.htm",
            "https://example.com/news/story-3.php",
            "https://example.com/news/story-4/",
            "https://example.com/news/story-5",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
            min_occurrences=2,
        )

        # All should normalize to /news/ as the parent
        assert "https://example.com/news/" in sections
        # Should only have one section (all normalize to same parent)
        assert len(sections) == 1

    def test_subdomain_handling(self):
        """Test that subdomains are treated as different sources."""
        articles = [
            "https://www.example.com/news/article-1.html",
            "https://www.example.com/news/article-2.html",
            "https://sports.example.com/news/article-3.html",
            "https://sports.example.com/news/article-4.html",
        ]

        # Test www subdomain
        sections_www = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://www.example.com",
        )
        assert "https://www.example.com/news/" in sections_www
        assert not any("sports.example.com" in s for s in sections_www)

        # Test sports subdomain
        sections_sports = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://sports.example.com",
        )
        assert "https://sports.example.com/news/" in sections_sports
        assert not any("www.example.com" in s for s in sections_sports)

    def test_article_id_patterns(self):
        """Test extraction with various article ID patterns."""
        articles = [
            # Numeric IDs
            "https://example.com/news/123456",
            "https://example.com/news/789012",
            "https://example.com/news/345678",
            # UUID-style
            "https://example.com/sports/abc-def-ghi-jkl-mno",
            "https://example.com/sports/pqr-stu-vwx-yz1-234",
            # Date + ID
            "https://example.com/business/20241115-article-1",
            "https://example.com/business/20241114-article-2",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://example.com",
        )

        # Should identify section fronts regardless of ID format
        assert "https://example.com/news/" in sections
        assert "https://example.com/sports/" in sections
        assert "https://example.com/business/" in sections

    def test_real_world_mixed_scenario(self):
        """
        Test with realistic mixed URL patterns from actual news site.

        Simulates what we'd see from a typical local news source with
        inconsistent URL structures.
        """
        articles = [
            # Local news section (consistent deep structure)
            "https://localsite.com/news/local/town-meeting-held.html",
            "https://localsite.com/news/local/new-business-opens.html",
            "https://localsite.com/news/local/school-event-success.html",
            "https://localsite.com/news/local/traffic-update.html",
            # State news (medium structure)
            "https://localsite.com/news/state/legislature-update.html",
            "https://localsite.com/news/state/governor-visit.html",
            # Sports (shallow structure)
            "https://localsite.com/sports/friday-night-game.html",
            "https://localsite.com/sports/playoff-preview.html",
            "https://localsite.com/sports/athlete-spotlight.html",
            # Opinion (shallow)
            "https://localsite.com/opinion/editorial-taxes.html",
            "https://localsite.com/opinion/letter-to-editor.html",
            # Weather (root level)
            "https://localsite.com/weather",
            "https://localsite.com/weather-forecast",
            # Obits (varied)
            "https://localsite.com/obituaries/john-doe.html",
            "https://localsite.com/obituaries/jane-smith.html",
        ]

        sections = NewsDiscovery._extract_sections_from_article_urls(
            articles,
            "https://localsite.com",
            min_occurrences=2,
        )

        # Should identify all major sections
        assert "https://localsite.com/news/" in sections
        assert "https://localsite.com/news/local/" in sections  # 4 occurrences
        assert "https://localsite.com/news/state/" in sections  # 2 occurrences
        assert "https://localsite.com/sports/" in sections  # 3 occurrences
        assert "https://localsite.com/opinion/" in sections  # 2 occurrences
        assert "https://localsite.com/obituaries/" in sections  # 2 occurrences

        # Should have good coverage (6+ sections identified)
        assert len(sections) >= 6
