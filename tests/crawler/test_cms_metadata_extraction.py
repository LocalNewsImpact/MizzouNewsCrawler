"""Unit tests for CMS metadata extraction from JavaScript data objects.

Tests the _extract_cms_metadata_from_html method that captures title,
author, and other fields from CMS-specific JavaScript objects like
NXSTdata.content (Nexstar), dataLayer (Gray TV), and JSON-LD.
"""

import pytest

from src.crawler import ContentExtractor


@pytest.fixture
def extractor():
    """Create ContentExtractor instance for testing."""
    return ContentExtractor(timeout=5)


class TestNexstarMetadataExtraction:
    """Test extraction from Nexstar NXSTdata.content patterns."""

    def test_extracts_title_and_author(self, extractor):
        """Test extraction of title and authorName from NXSTdata.content."""
        html = """
        <script>
            window.NXSTdata = window.NXSTdata || {};
            window.NXSTdata.content = Object.assign( window.NXSTdata.content, {
                "title":"Fire District warns public not to burn",
                "authorName":"John Smith",
                "description":"Local fire warning issued",
                "publicationDate":"2025-12-09T12:17:04-06:00",
                "primaryCategory":"Local News"
            } )
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert (
            extractor._latest_cms_metadata.get("title")
            == "Fire District warns public not to burn"
        )
        assert extractor._latest_cms_metadata.get("author") == "John Smith"
        assert (
            extractor._latest_cms_metadata.get("publish_date")
            == "2025-12-09T12:17:04-06:00"
        )
        assert extractor._latest_cms_metadata.get("category") == "Local News"
        assert extractor._latest_cms_metadata.get("cms_source") == "nexstar"

    def test_handles_unicode_in_title(self, extractor):
        """Test handling of unicode characters in title."""
        html = """
        <script>
            window.NXSTdata.content = Object.assign( window.NXSTdata.content, {
                "title":"Fire District warns public about burning\\u00a0",
                "authorName":"Jane Doe"
            } )
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        # Unicode \u00a0 is non-breaking space
        assert (
            "Fire District warns public about burning"
            in extractor._latest_cms_metadata.get("title", "")
        )

    def test_ignores_empty_fields(self, extractor):
        """Test that empty fields are not stored."""
        html = """
        <script>
            window.NXSTdata.content = Object.assign( window.NXSTdata.content, {
                "title":"",
                "authorName":"John Smith",
                "description":""
            } )
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        # Should have author but not empty title
        if extractor._latest_cms_metadata:
            assert not extractor._latest_cms_metadata.get("title")
            assert extractor._latest_cms_metadata.get("author") == "John Smith"


class TestJsonLdMetadataExtraction:
    """Test extraction from JSON-LD when CMS patterns don't match."""

    def test_extracts_from_jsonld_newsarticle(self, extractor):
        """Test fallback to JSON-LD NewsArticle schema."""
        html = """
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Breaking News Story",
            "author": {"@type": "Person", "name": "Reporter Name"},
            "datePublished": "2025-12-09T10:00:00Z"
        }
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("title") == "Breaking News Story"
        assert extractor._latest_cms_metadata.get("author") == "Reporter Name"
        assert (
            extractor._latest_cms_metadata.get("publish_date") == "2025-12-09T10:00:00Z"
        )
        assert extractor._latest_cms_metadata.get("cms_source") == "json_ld"

    def test_extracts_author_from_array(self, extractor):
        """Test extraction when author is an array."""
        html = """
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Multi-author Story",
            "author": [
                {"@type": "Person", "name": "First Author"},
                {"@type": "Person", "name": "Second Author"}
            ]
        }
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("author") == "First Author"

    def test_extracts_author_as_string(self, extractor):
        """Test extraction when author is a simple string."""
        html = """
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Simple Author Story",
            "author": "Staff Reporter"
        }
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("author") == "Staff Reporter"


class TestCmsMetadataPriority:
    """Test that JSON-LD (standardized) takes priority over CMS-specific patterns."""

    def test_jsonld_takes_priority_over_cms_specific(self, extractor):
        """Test that JSON-LD data takes priority over CMS-specific patterns.

        JSON-LD is a W3C/schema.org standard used across all CMSes, so it should
        be preferred over CMS-specific JavaScript patterns.
        """
        html = """
        <script>
            window.NXSTdata.content = Object.assign( window.NXSTdata.content, {
                "title":"Nexstar Title",
                "authorName":"Nexstar Author"
            } )
        </script>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "JSON-LD Title",
            "author": "JSON-LD Author"
        }
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        # JSON-LD should take priority (standardized format)
        assert extractor._latest_cms_metadata.get("title") == "JSON-LD Title"
        assert extractor._latest_cms_metadata.get("author") == "JSON-LD Author"
        assert extractor._latest_cms_metadata.get("cms_source") == "json_ld"

    def test_cms_specific_used_when_jsonld_missing(self, extractor):
        """Test that CMS-specific patterns are used when JSON-LD is missing."""
        html = """
        <script>
            window.NXSTdata.content = Object.assign( window.NXSTdata.content, {
                "title":"Nexstar Title",
                "authorName":"Nexstar Author"
            } )
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("title") == "Nexstar Title"
        assert extractor._latest_cms_metadata.get("author") == "Nexstar Author"
        assert extractor._latest_cms_metadata.get("cms_source") == "nexstar"


class TestNoMetadataFound:
    """Test behavior when no CMS metadata is found."""

    def test_no_metadata_returns_none(self, extractor):
        """Test that missing metadata doesn't create empty dict."""
        html = """
        <html>
        <head><title>Simple Page</title></head>
        <body><p>Content</p></body>
        </html>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        # Should remain None when no CMS data found
        assert extractor._latest_cms_metadata is None

    def test_malformed_json_handled(self, extractor):
        """Test that malformed JSON doesn't cause errors."""
        html = """
        <script>
            window.NXSTdata.content = Object.assign( window.NXSTdata.content, {
                "title": "Test",
                "broken":
            } )
        </script>
        """
        extractor._latest_cms_metadata = None
        # Should not raise exception
        extractor._extract_cms_metadata_from_html(html)


class TestMetaTagExtraction:
    """Test extraction from OpenGraph and standard meta tags."""

    def test_extracts_og_title(self, extractor):
        """Test extraction of og:title from meta tags."""
        html = """
        <html>
        <head>
            <meta property="og:title" content="OpenGraph Title"/>
            <meta name="author" content="Meta Author"/>
        </head>
        <body></body>
        </html>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("title") == "OpenGraph Title"
        assert extractor._latest_cms_metadata.get("author") == "Meta Author"
        assert extractor._latest_cms_metadata.get("cms_source") == "meta_tags"

    def test_extracts_article_author(self, extractor):
        """Test extraction of article:author meta tag."""
        html = """
        <html>
        <head>
            <meta property="article:author" content="Jane Reporter"/>
            <meta property="article:published_time" content="2025-12-09T12:00:00Z"/>
        </head>
        <body></body>
        </html>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("author") == "Jane Reporter"
        assert (
            extractor._latest_cms_metadata.get("publish_date") == "2025-12-09T12:00:00Z"
        )

    def test_handles_alternate_meta_order(self, extractor):
        """Test meta tags with content before property."""
        html = """
        <html>
        <head>
            <meta content="Alternate Title" property="og:title"/>
        </head>
        <body></body>
        </html>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("title") == "Alternate Title"


class TestDataLayerExtraction:
    """Test extraction from generic dataLayer patterns."""

    def test_extracts_from_datalayer_push(self, extractor):
        """Test extraction from dataLayer.push with common field names."""
        html = """
        <script>
            dataLayer.push({
                "articleTitle": "DataLayer Article Title",
                "articleAuthor": "DataLayer Author"
            });
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert extractor._latest_cms_metadata.get("title") == "DataLayer Article Title"
        assert extractor._latest_cms_metadata.get("author") == "DataLayer Author"
        assert extractor._latest_cms_metadata.get("cms_source") == "datalayer"

    def test_extracts_alternate_datalayer_fields(self, extractor):
        """Test extraction from dataLayer with alternate field names."""
        html = """
        <script>
            dataLayer.push({
                "pageTitle": "Page Title from DataLayer",
                "byline": "Byline Author"
            });
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        assert (
            extractor._latest_cms_metadata.get("title") == "Page Title from DataLayer"
        )
        assert extractor._latest_cms_metadata.get("author") == "Byline Author"

    def test_jsonld_preferred_over_datalayer(self, extractor):
        """Test that JSON-LD is preferred over dataLayer."""
        html = """
        <script type="application/ld+json">
        {"@type": "NewsArticle", "headline": "JSON-LD Headline", "author": "JSON Author"}
        </script>
        <script>
            dataLayer.push({"articleTitle": "DataLayer Title", "articleAuthor": "DL Author"});
        </script>
        """
        extractor._latest_cms_metadata = None
        extractor._extract_cms_metadata_from_html(html)

        assert extractor._latest_cms_metadata is not None
        # JSON-LD should win
        assert extractor._latest_cms_metadata.get("title") == "JSON-LD Headline"
        assert extractor._latest_cms_metadata.get("author") == "JSON Author"
        assert extractor._latest_cms_metadata.get("cms_source") == "json_ld"
