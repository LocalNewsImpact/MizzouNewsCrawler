"""Byline provenance -- track whether an author came from body text,
metadata, or JSON-LD.

`extraction_methods["author"]` (which becomes `final_field_attribution` in
telemetry) was left with almost no real information for the byline field.
Three gaps, found 2026-07-29 investigating the user's request to track this:

1. mcmetadata already computes `author_extraction_method` internally
   ("structured_json_ld", "structured_meta_tags", "content_extraction") but it
   was read into a local variable and then discarded -- never copied into
   `extraction_methods["author"]`. mcmetadata is the DOMINANT successful path
   in production (the fallback cascade below only runs when it comes back
   empty), so this left the common case with no attribution at all.

2. `_apply_cms_metadata_fallback`'s `cms_source` was ONE shared variable
   across title/author/publish_date, set once and never revisited. A page
   whose JSON-LD supplied a title but no author, filled in afterward by a
   meta tag, stamped BOTH `extraction_methods["title"]` and
   `extraction_methods["author"]` with the SAME label -- so the author's
   attribution could read "cms_json_ld" when it actually came from a meta tag.

3. `_extract_author`'s three-strategy DOM fallback (meta tag -> CSS byline
   selector -> "By {Name}" text-pattern search) recorded nothing at all. Both
   its callers (`extract_article_data` / beautifulsoup, and the Selenium path)
   stamped every field with one flat method label ("beautifulsoup" /
   "selenium"), with no way to tell a structured meta tag apart from a raw
   body-text match.
"""

from bs4 import BeautifulSoup

from src.crawler import ContentExtractor


class TestExtractAuthorWithSource:
    """The new method _extract_author gained a companion for."""

    def _extractor(self):
        return ContentExtractor.__new__(ContentExtractor)

    def test_meta_tag_reports_meta_tag_source(self):
        soup = BeautifulSoup(
            '<html><head><meta name="author" content="Jane Smith"></head>'
            "<body></body></html>",
            "html.parser",
        )
        author, source = self._extractor()._extract_author_with_source(soup)
        assert author == "Jane Smith"
        assert source == "meta_tag"

    def test_css_selector_reports_css_selector_source(self):
        soup = BeautifulSoup(
            '<html><body><div class="byline">By John Doe</div></body></html>',
            "html.parser",
        )
        author, source = self._extractor()._extract_author_with_source(soup)
        assert author is not None
        assert source == "css_selector"

    def test_body_text_pattern_reports_body_text_pattern_source(self):
        soup = BeautifulSoup(
            "<html><body><p>By Maria Garcia</p>"
            "<p>Some article content follows here.</p></body></html>",
            "html.parser",
        )
        author, source = self._extractor()._extract_author_with_source(soup)
        assert author is not None
        assert source == "body_text_pattern"

    def test_no_byline_anywhere_reports_no_source(self):
        soup = BeautifulSoup(
            "<html><body><p>Nothing byline-shaped here.</p></body></html>",
            "html.parser",
        )
        author, source = self._extractor()._extract_author_with_source(soup)
        assert author is None
        assert source is None

    def test_old_extract_author_still_returns_just_the_string(self):
        """Backward compatibility: existing callers must not break."""
        soup = BeautifulSoup(
            '<html><head><meta name="author" content="Jane Smith"></head>'
            "<body></body></html>",
            "html.parser",
        )
        assert self._extractor()._extract_author(soup) == "Jane Smith"

    def test_meta_tag_wins_over_css_selector_when_both_present(self):
        """Priority order is unchanged: meta tag is tried first."""
        soup = BeautifulSoup(
            '<html><head><meta name="author" content="Meta Author"></head>'
            '<body><div class="byline">By CSS Author</div></body></html>',
            "html.parser",
        )
        author, source = self._extractor()._extract_author_with_source(soup)
        assert author == "Meta Author"
        assert source == "meta_tag"


class TestCmsMetadataPerFieldSource:
    """The cms_source sharing bug: title/author/date must not share a label."""

    def _extractor(self):
        return ContentExtractor.__new__(ContentExtractor)

    def test_title_from_jsonld_and_author_from_meta_tag_get_different_sources(self):
        """The exact bug: JSON-LD supplies title only, a meta tag supplies
        author. Both used to be stamped identically."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "NewsArticle", "headline": "A Real Headline"}
        </script>
        <meta name="author" content="Jane Smith">
        </head><body></body></html>
        """
        ex = self._extractor()
        ex._latest_cms_metadata = None
        ex._extract_cms_metadata_from_html(html)
        meta = ex._latest_cms_metadata
        assert meta.get("title") == "A Real Headline"
        assert meta.get("author") == "Jane Smith"
        assert meta.get("title_source") == "json_ld"
        assert meta.get("author_source") == "meta_tags"
        # The two must NOT be equal -- that was the bug.
        assert meta["title_source"] != meta["author_source"]

    def test_apply_cms_metadata_fallback_uses_the_per_field_source(self):
        ex = self._extractor()
        ex._latest_cms_metadata = {
            "title": "A Real Headline",
            "title_source": "json_ld",
            "author": "Jane Smith",
            "author_source": "meta_tags",
            "cms_source": "json_ld",  # whichever stage ran first
        }
        result = {"extraction_methods": {}, "metadata": {}}
        ex._apply_cms_metadata_fallback(result)
        assert result["extraction_methods"]["title"] == "cms_json_ld"
        # Must reflect the AUTHOR's own source, not the shared/first one.
        assert result["extraction_methods"]["author"] == "cms_meta_tags"

    def test_apply_cms_metadata_fallback_falls_back_to_cms_source_if_missing(self):
        """Backward compatibility for any metadata dict without the new keys."""
        ex = self._extractor()
        ex._latest_cms_metadata = {
            "title": "A Real Headline",
            "author": "Jane Smith",
            "cms_source": "nexstar",
        }
        result = {"extraction_methods": {}, "metadata": {}}
        ex._apply_cms_metadata_fallback(result)
        assert result["extraction_methods"]["title"] == "cms_nexstar"
        assert result["extraction_methods"]["author"] == "cms_nexstar"

    def test_existing_cms_source_field_is_unchanged(self):
        """The old shared field must still be set exactly as before -- pins
        backward compatibility with tests/crawler/test_cms_metadata_extraction.py."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "NewsArticle", "headline": "Title", "author": {"name": "Jane Smith"}}
        </script>
        </head><body></body></html>
        """
        ex = self._extractor()
        ex._latest_cms_metadata = None
        ex._extract_cms_metadata_from_html(html)
        assert ex._latest_cms_metadata.get("cms_source") == "json_ld"


class TestMergeExtractionResultsFieldMethods:
    """The plumbing that lets mcmetadata/beautifulsoup/selenium override the
    per-field label with something more specific than the whole-source name."""

    def _extractor(self):
        return ContentExtractor.__new__(ContentExtractor)

    def test_field_methods_overrides_the_generic_label(self):
        ex = self._extractor()
        target = {"extraction_methods": {}}
        source = {"author": "Jane Smith", "title": "A Sufficiently Long Test Title"}
        ex._merge_extraction_results(
            target,
            source,
            "mcmetadata",
            field_methods={"author": "structured_json_ld"},
        )
        assert target["extraction_methods"]["author"] == "structured_json_ld"
        # title had no override, so it keeps the plain method name.
        assert target["extraction_methods"]["title"] == "mcmetadata"

    def test_no_field_methods_behaves_exactly_as_before(self):
        ex = self._extractor()
        target = {"extraction_methods": {}}
        source = {"author": "Jane Smith"}
        ex._merge_extraction_results(target, source, "selenium")
        assert target["extraction_methods"]["author"] == "selenium"
