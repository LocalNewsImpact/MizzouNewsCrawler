"""Unit tests for structured metadata wire detection.

Tests the generic _detect_structured_metadata_wire_from_html method that looks
for CMS-agnostic metadata signals (OpenGraph distributor tags, canonical URLs,
JSON-LD author fields, dataLayer syndication fields).
"""

import pytest

from src.crawler import ContentExtractor


@pytest.fixture
def extractor():
    """Create a ContentExtractor instance for testing."""
    return ContentExtractor(timeout=5)


class TestOpenGraphDistributorDetection:
    """Test detection via article:distributor_category and distributor_name meta tags."""

    def test_distributor_category_wires(self, extractor):
        """Test detection when distributor_category=wires (Gray TV pattern)."""
        html = """
        <html>
        <head>
            <meta property="article:distributor_category" content="wires"/>
            <meta property="article:distributor_name" content="AP National"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "og_distributor_category" in result["detected_by"]
        assert "The Associated Press" in result["wire_services"]
        assert any("distributor_category=wires" in e for e in result["evidence"])
        assert any("distributor_name=AP National" in e for e in result["evidence"])

    def test_distributor_category_alternate_order(self, extractor):
        """Test detection when content comes before property in meta tag."""
        html = """
        <html>
        <head>
            <meta content="wires" property="article:distributor_category"/>
            <meta content="Reuters" property="article:distributor_name"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "Reuters" in result["wire_services"]

    def test_distributor_category_not_wires(self, extractor):
        """Test that non-wire distributor categories don't trigger detection."""
        html = """
        <html>
        <head>
            <meta property="article:distributor_category" content="local"/>
            <meta property="article:distributor_name" content="KCTV5"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        # Should not detect as wire since category is 'local'
        assert result is None


class TestCanonicalUrlCrossDomainDetection:
    """Test detection via canonical URL pointing to wire service domain."""

    def test_canonical_to_healthday(self, extractor):
        """Test detection when canonical points to healthday.com."""
        html = """
        <html>
        <head>
            <link rel="canonical" href="https://consumer.healthday.com/article/123"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html, article_url="https://maryvilleforum.com/news/health/article/123"
        )

        assert result is not None
        assert "canonical_cross_domain" in result["detected_by"]
        assert "HealthDay" in result["wire_services"]

    def test_canonical_to_ap(self, extractor):
        """Test detection when canonical points to apnews.com."""
        html = """
        <html>
        <head>
            <link href="https://apnews.com/article/xyz" rel="canonical"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html, article_url="https://local-news.com/story/xyz"
        )

        assert result is not None
        assert "The Associated Press" in result["wire_services"]

    def test_canonical_same_domain_no_detection(self, extractor):
        """Test that canonical to same domain doesn't trigger detection."""
        html = """
        <html>
        <head>
            <link rel="canonical" href="https://example.com/article/123"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html, article_url="https://example.com/article/123"
        )

        # Same domain, not a wire service signal
        assert result is None

    def test_canonical_cross_domain_unknown_service(self, extractor):
        """Test that cross-domain canonical to unknown domain is detected as syndication."""
        html = """
        <html>
        <head>
            <link rel="canonical" href="https://www.wcvb.com/article/mit-professor-shot-brookline-brown-university-shooting-possible-link/69811151"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html,
            article_url="https://www.kmbc.com/article/mit-professor-shot-brookline-brown-university-shooting-possible-link/69811635",
        )

        # Different domain should trigger syndication detection
        assert result is not None
        assert "canonical_cross_domain" in result["detected_by"]
        # wcvb.com should be in wire_services even though it's not in _WIRE_SERVICE_DOMAINS
        assert any("wcvb.com" in svc.lower() for svc in result["wire_services"])


class TestCanonicalCrossDomainSameSiteAlias:
    """An unknown-domain cross-domain canonical is not automatically wire.

    Found 2026-07-28: emissourian.com's canonical points to missourian.com with
    an IDENTICAL slug, and the page's own TownNews CDN path is
    bloximages.chicago2.vip.townnews.com/missourian.com/shared-content/... --
    missourian.com is this paper's own CMS site-key, not a wire source. Two
    hyper-local prep-sports recaps (real reporting, no byline, box scores) were
    filed `wire` because of it and dropped out of CIN classification entirely.

    Validated against all 549 distinct (article_domain, wire_service) pairs
    carrying status='wire' in production: suppresses exactly 5, all confirmed
    same-site, and preserves all 544 genuine cross-organization pairs.
    """

    def test_emissourian_missourian_is_not_wire(self, extractor):
        """The exact case that surfaced this."""
        html = """
        <html><head>
        <link rel="canonical" href="https://www.missourian.com/sports/bulldogs-fall-to-north-county-in-thursday-tilt/article_8b5f4600.html"/>
        </head><body></body></html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html,
            article_url="https://www.emissourian.com/sports/bulldogs-fall-to-north-county-in-thursday-tilt/article_8b5f4600.html",
        )
        assert result is None

    def test_nwaonline_subdomain_variant_is_not_wire(self, extractor):
        """Same registrable domain, different subdomain -- same publisher."""
        html = """
        <html><head>
        <link rel="canonical" href="https://bvwv.nwaonline.com/news/2026/story"/>
        </head><body></body></html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html, article_url="https://mdcp.nwaonline.com/news/2026/story"
        )
        assert result is None

    def test_kmbc_storystudio_subdomain_is_not_wire(self, extractor):
        html = """
        <html><head>
        <link rel="canonical" href="https://storystudio.kmbc.com/feature/123"/>
        </head><body></body></html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html, article_url="https://www.kmbc.com/feature/123"
        )
        assert result is None

    def test_kansascity_kansas_is_still_real_syndication(self, extractor):
        """The case that killed a broader substring-based first draft.

        kansascity.com and kansas.com are genuinely different newsrooms in
        different cities -- the Kansas City Star and the Wichita Eagle. A raw
        substring check (`"kansas" in "kansascity.com"`) wrongly caught this
        as a same-site alias; it is real syndication and must stay detected.
        """
        html = """
        <html><head>
        <link rel="canonical" href="https://www.kansas.com/news/state/article123.html"/>
        </head><body></body></html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html, article_url="https://www.kansascity.com/news/state/article123.html"
        )
        assert result is not None
        assert "canonical_cross_domain" in result["detected_by"]
        assert any("kansas.com" in svc.lower() for svc in result["wire_services"])

    def test_unrelated_cross_affiliate_syndication_still_detected(self, extractor):
        """Guard against over-correcting: genuinely different domains stay wire.

        Same fixture as test_canonical_cross_domain_unknown_service above --
        kmbc.com and wcvb.com share no name or registrable domain at all, the
        real Hearst-TV-affiliate case the original fallback was written for.
        """
        html = """
        <html><head>
        <link rel="canonical" href="https://www.wcvb.com/article/xyz/123"/>
        </head><body></body></html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(
            html, article_url="https://www.kmbc.com/article/xyz/123"
        )
        assert result is not None
        assert any("wcvb.com" in svc.lower() for svc in result["wire_services"])


class TestJsonLdAuthorDetection:
    """Test detection via JSON-LD author field containing wire service names."""

    def test_author_array_with_ap(self, extractor):
        """Test detection when JSON-LD author array contains AP."""
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "NewsArticle",
                "author": [
                    {"@type": "Person", "name": "John Smith"},
                    {"@type": "Organization", "name": "Associated Press"}
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "jsonld_author" in result["detected_by"]
        assert "The Associated Press" in result["wire_services"]

    def test_author_string_cnn(self, extractor):
        """Test detection when JSON-LD author is a string mentioning CNN."""
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {"@type": "NewsArticle", "author": "CNN"}
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "CNN" in result["wire_services"]

    def test_author_with_outlet_suffix(self, extractor):
        """Test detection with author format 'Name, CNN' in meta tag."""
        html = """
        <html>
        <head>
            <meta name="author" content="Rob Kuznia, CNN"/>
        </head>
        <body></body>
        </html>
        """
        # Meta author with wire service suffix should be detected
        result = extractor._detect_structured_metadata_wire_from_html(html)
        assert result is not None
        assert "meta_author" in result["detected_by"]
        assert "CNN" in result["wire_services"]


class TestMetaAuthorDetection:
    """Test detection via HTML meta author tag."""

    def test_meta_author_with_ap_suffix(self, extractor):
        """Test detection with 'Name, Associated Press' pattern."""
        html = """
        <html>
        <head>
            <meta name="author" content="TERESA CEROJANO, Associated Press"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "meta_author" in result["detected_by"]
        assert any("Associated Press" in s for s in result["wire_services"])

    def test_meta_author_multiple_with_wire(self, extractor):
        """Test detection with multiple authors including wire service."""
        html = """
        <html>
        <head>
            <meta name="author" content="Hanna Park, Betsy Klein, CNN"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "CNN" in result["wire_services"]

    def test_meta_author_local_reporter(self, extractor):
        """Test that local reporter byline doesn't trigger detection."""
        html = """
        <html>
        <head>
            <meta name="author" content="John Smith, Staff Writer"/>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        # Should not detect - "Staff Writer" is not a wire service
        assert result is None


class TestDataLayerSyndicationDetection:
    """Test detection via CMS dataLayer syndication fields."""

    def test_tncms_syndication_source(self, extractor):
        """Test detection via tncms.syndication.source field."""
        html = """
        <html>
        <head>
            <script>
                dataLayer = [{
                    "tncms.syndication.source": "healthday.com",
                    "tncms.syndication.channel": "Health"
                }];
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "datalayer_syndication" in result["detected_by"]

    def test_townnews_content_source(self, extractor):
        """Test detection via townnews.content.source field."""
        html = """
        <html>
        <head>
            <script>
                window.dataLayer = [{"townnews.content.source": "AP Wire"}];
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "datalayer_syndication" in result["detected_by"]


class TestJsonLdSyndicationSignals:
    """Test detection via JSON-LD syndication signals (formerly Gannett-specific)."""

    def test_is_based_on_usatoday(self, extractor):
        """Test detection via isBasedOn pointing to USA Today."""
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "NewsArticle",
                "headline": "Test Article",
                "isBasedOn": "https://www.usatoday.com/story/news/2024/article"
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "jsonld_isBasedOn" in result["detected_by"]
        assert "USA Today" in result["wire_services"]

    def test_main_entity_of_page_ap(self, extractor):
        """Test detection via mainEntityOfPage pointing to AP."""
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "NewsArticle",
                "headline": "Test Article",
                "mainEntityOfPage": {
                    "@type": "WebPage",
                    "@id": "https://apnews.com/article/some-story"
                }
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "jsonld_mainEntity" in result["detected_by"]
        assert "The Associated Press" in result["wire_services"]

    def test_content_source_code_usat(self, extractor):
        """Test detection via Gannett contentSourceCode = USAT."""
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "NewsArticle",
                "headline": "Test Article",
                "metadata": "{\\"contentSourceCode\\": \\"USAT\\"}"
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "jsonld_contentSourceCode" in result["detected_by"]
        assert "USA Today" in result["wire_services"]

    def test_is_based_on_reuters(self, extractor):
        """Test detection via isBasedOn pointing to Reuters."""
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "NewsArticle",
                "isBasedOn": "https://www.reuters.com/world/some-story"
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        assert "jsonld_isBasedOn" in result["detected_by"]
        assert "Reuters" in result["wire_services"]


class TestCombinedSignalsDetection:
    """Test detection with multiple signals present."""

    def test_multiple_signals_combined(self, extractor):
        """Test that multiple signals are merged correctly."""
        html = """
        <html>
        <head>
            <meta property="article:distributor_category" content="wires"/>
            <meta property="article:distributor_name" content="AP National"/>
            <script type="application/ld+json">
            {"@type": "NewsArticle", "author": "Reuters"}
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        # Should have both detection methods (different services)
        assert "og_distributor_category" in result["detected_by"]
        assert "jsonld_author" in result["detected_by"]
        # Should have both wire services
        assert "The Associated Press" in result["wire_services"]
        assert "Reuters" in result["wire_services"]

    def test_same_service_multiple_signals(self, extractor):
        """Test that same service from multiple signals only appears once."""
        html = """
        <html>
        <head>
            <meta property="article:distributor_category" content="wires"/>
            <meta property="article:distributor_name" content="AP National"/>
            <script type="application/ld+json">
            {"@type": "NewsArticle", "author": "The Associated Press"}
            </script>
        </head>
        <body></body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)

        assert result is not None
        # First detection method wins when same service is found
        assert "og_distributor_category" in result["detected_by"]
        # Should deduplicate wire services
        assert result["wire_services"].count("The Associated Press") == 1


class TestNoSignalsReturnsNone:
    """Test that pages without wire signals return None."""

    def test_empty_html(self, extractor):
        """Test that empty HTML returns None."""
        result = extractor._detect_structured_metadata_wire_from_html("")
        assert result is None

    def test_regular_article_no_wire_signals(self, extractor):
        """Test that regular article without wire signals returns None."""
        html = """
        <html>
        <head>
            <title>Local News Story</title>
            <meta name="author" content="Jane Reporter"/>
            <script type="application/ld+json">
            {"@type": "NewsArticle", "author": {"name": "Jane Reporter"}}
            </script>
        </head>
        <body>
            <p>This is a local news story written by our staff.</p>
        </body>
        </html>
        """
        result = extractor._detect_structured_metadata_wire_from_html(html)
        assert result is None
