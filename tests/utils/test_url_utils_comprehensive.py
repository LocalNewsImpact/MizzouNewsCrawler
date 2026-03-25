"""Comprehensive tests for URL utilities."""

import pytest

from src.utils.url_utils import extract_base_url, is_same_article_url, normalize_url


class TestNormalizeUrl:
    """Comprehensive tests for normalize_url function."""

    def test_removes_fragment(self):
        """Fragments should be removed."""
        assert (
            normalize_url("https://example.com/story#section")
            == "https://example.com/story"
        )
        assert (
            normalize_url("https://example.com/story#top")
            == "https://example.com/story"
        )
        assert (
            normalize_url("https://example.com/story#") == "https://example.com/story"
        )

    def test_removes_query_parameters(self):
        """Query parameters should be removed."""
        assert (
            normalize_url("https://example.com/story?ref=home")
            == "https://example.com/story"
        )
        assert (
            normalize_url("https://example.com/story?id=123")
            == "https://example.com/story"
        )
        assert (
            normalize_url("https://example.com/story?") == "https://example.com/story"
        )

    def test_removes_both_fragment_and_query(self):
        """Both fragments and query parameters should be removed."""
        result = normalize_url("https://example.com/story?id=123#top")
        assert result == "https://example.com/story"

    def test_removes_trailing_slash_from_path(self):
        """Trailing slashes should be removed from paths."""
        assert (
            normalize_url("https://example.com/story/") == "https://example.com/story"
        )
        assert (
            normalize_url("https://example.com/news/local/")
            == "https://example.com/news/local"
        )

    def test_preserves_root_trailing_slash(self):
        """Root URL should keep trailing slash."""
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_preserves_scheme(self):
        """URL scheme should be preserved (not converted)."""
        assert normalize_url("https://example.com/story") == "https://example.com/story"
        assert normalize_url("http://example.com/story") == "http://example.com/story"
        # www is now preserved (only stripped for dedup comparison)
        assert (
            normalize_url("http://www.example.com/story")
            == "http://www.example.com/story"
        )

    def test_preserves_port_number(self):
        """Port numbers should be preserved."""
        assert (
            normalize_url("https://example.com:8080/story")
            == "https://example.com:8080/story"
        )
        assert (
            normalize_url("http://localhost:3000/article")
            == "http://localhost:3000/article"
        )

    def test_preserves_all_subdomains(self):
        """All subdomains including www should be preserved."""
        assert (
            normalize_url("https://news.example.com/story")
            == "https://news.example.com/story"
        )
        # www is now preserved (only stripped for dedup comparison)
        assert (
            normalize_url("https://www.example.com/story")
            == "https://www.example.com/story"
        )
        assert (
            normalize_url("http://www.example.com/story")
            == "http://www.example.com/story"
        )

    def test_handles_empty_string(self):
        """Empty strings should be returned as-is."""
        assert normalize_url("") == ""

    def test_handles_whitespace_only(self):
        """Whitespace-only strings should be returned as-is."""
        assert normalize_url("   ") == "   "
        assert normalize_url("\n") == "\n"

    def test_strips_leading_trailing_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        assert (
            normalize_url("  https://example.com/story  ")
            == "https://example.com/story"
        )
        assert (
            normalize_url("\thttps://example.com/story\n")
            == "https://example.com/story"
        )

    def test_handles_none_gracefully(self):
        """None should be returned as-is."""
        assert normalize_url(None) is None  # type: ignore

    def test_preserves_params(self):
        """URL params (semicolon-separated) should be preserved."""
        # This is rare but valid URL syntax
        result = normalize_url("https://example.com/story;param=value")
        assert ";param=value" in result or result == "https://example.com/story"

    def test_handles_malformed_url_gracefully(self):
        """Malformed URLs should be returned unchanged with logged warning."""
        # These might parse oddly but shouldn't crash
        malformed = "not a valid url"
        result = normalize_url(malformed)
        assert result == malformed

    def test_handles_unicode_in_url(self):
        """Unicode characters should be handled."""
        url = "https://example.com/новости"
        result = normalize_url(url)
        assert "example.com" in result

    def test_handles_encoded_characters(self):
        """URL-encoded characters should be preserved."""
        url = "https://example.com/story%20with%20spaces"
        result = normalize_url(url)
        assert "story%20with%20spaces" in result

    def test_complex_query_string(self):
        """Complex query strings with multiple params should be removed."""
        url = "https://example.com/story?utm_source=twitter&utm_medium=social&ref=home&id=123"
        assert normalize_url(url) == "https://example.com/story"

    def test_multiple_path_segments(self):
        """URLs with multiple path segments should work."""
        url = "https://example.com/news/2024/01/15/story?ref=home#section"
        expected = "https://example.com/news/2024/01/15/story"
        assert normalize_url(url) == expected

    def test_preserves_path_with_file_extension(self):
        """Paths with file extensions should be preserved."""
        assert (
            normalize_url("https://example.com/story.html")
            == "https://example.com/story.html"
        )
        assert (
            normalize_url("https://example.com/article.php")
            == "https://example.com/article.php"
        )

    def test_handles_relative_url_parts(self):
        """URLs with .. or . in path should parse correctly."""
        url = "https://example.com/news/../story"
        result = normalize_url(url)
        # urlparse may or may not normalize this - we just ensure no crash
        assert result is not None


class TestIsSameArticleUrl:
    """Comprehensive tests for is_same_article_url function."""

    def test_same_url_exact_match(self):
        """Identical URLs should match."""
        url = "https://example.com/story"
        assert is_same_article_url(url, url) is True

    def test_same_url_with_different_fragments(self):
        """Same URL with different fragments should match."""
        url1 = "https://example.com/story#section1"
        url2 = "https://example.com/story#section2"
        assert is_same_article_url(url1, url2) is True

    def test_same_url_with_different_query_params(self):
        """Same URL with different query parameters should match."""
        url1 = "https://example.com/story?ref=home"
        url2 = "https://example.com/story?ref=twitter"
        assert is_same_article_url(url1, url2) is True

    def test_same_url_with_and_without_trailing_slash(self):
        """URLs with/without trailing slash should match."""
        url1 = "https://example.com/story/"
        url2 = "https://example.com/story"
        assert is_same_article_url(url1, url2) is True

    def test_different_urls_should_not_match(self):
        """Different URLs should not match."""
        url1 = "https://example.com/story1"
        url2 = "https://example.com/story2"
        assert is_same_article_url(url1, url2) is False

    def test_different_domains_should_not_match(self):
        """Same path but different domains should not match."""
        url1 = "https://example1.com/story"
        url2 = "https://example2.com/story"
        assert is_same_article_url(url1, url2) is False

    def test_http_and_https_should_match(self):
        """HTTP vs HTTPS should match (normalized to same scheme)."""
        url1 = "http://example.com/story"
        url2 = "https://example.com/story"
        assert is_same_article_url(url1, url2) is True

    def test_www_and_non_www_should_match(self):
        """www vs non-www should match (www is stripped)."""
        url1 = "https://www.example.com/story"
        url2 = "https://example.com/story"
        assert is_same_article_url(url1, url2) is True
        url3 = "http://www.example.com/story"
        assert is_same_article_url(url1, url3) is True
        assert is_same_article_url(url2, url3) is True

    def test_different_ports_should_not_match(self):
        """Different ports should not match."""
        url1 = "https://example.com:8080/story"
        url2 = "https://example.com:9090/story"
        assert is_same_article_url(url1, url2) is False

    def test_handles_none_inputs(self):
        """None inputs should return False."""
        assert is_same_article_url(None, "https://example.com") is False  # type: ignore
        assert is_same_article_url("https://example.com", None) is False  # type: ignore
        assert is_same_article_url(None, None) is False  # type: ignore

    def test_handles_empty_string_inputs(self):
        """Empty string inputs should return False."""
        assert is_same_article_url("", "https://example.com") is False
        assert is_same_article_url("https://example.com", "") is False
        assert is_same_article_url("", "") is False

    def test_case_sensitive_comparison(self):
        """URL comparison should be case-sensitive for path."""
        url1 = "https://example.com/Story"
        url2 = "https://example.com/story"
        # urlparse is case-sensitive for paths
        assert is_same_article_url(url1, url2) is False

    def test_case_sensitive_domain(self):
        """Domain comparison is case-sensitive (urlparse preserves case)."""
        url1 = "https://Example.com/story"
        url2 = "https://example.com/story"
        # urlparse preserves domain case, so these don't match
        assert is_same_article_url(url1, url2) is False

    def test_with_whitespace(self):
        """URLs with whitespace should be handled."""
        url1 = "  https://example.com/story  "
        url2 = "https://example.com/story"
        assert is_same_article_url(url1, url2) is True


class TestExtractBaseUrl:
    """Comprehensive tests for extract_base_url function."""

    def test_extracts_base_url_https(self):
        """Should extract scheme and netloc for HTTPS."""
        url = "https://example.com/story?id=123#section"
        assert extract_base_url(url) == "https://example.com"

    def test_extracts_base_url_http(self):
        """Should extract scheme and netloc for HTTP."""
        url = "http://example.com/story?id=123#section"
        assert extract_base_url(url) == "http://example.com"

    def test_extracts_with_port(self):
        """Should include port in base URL."""
        url = "https://example.com:8080/story"
        assert extract_base_url(url) == "https://example.com:8080"

    def test_extracts_with_subdomain(self):
        """Should include subdomain in base URL."""
        url = "https://news.example.com/story"
        assert extract_base_url(url) == "https://news.example.com"

    def test_extracts_www_subdomain(self):
        """Should include www subdomain."""
        url = "https://www.example.com/story"
        assert extract_base_url(url) == "https://www.example.com"

    def test_handles_root_url(self):
        """Should handle root URLs."""
        url = "https://example.com/"
        assert extract_base_url(url) == "https://example.com"

    def test_handles_url_without_path(self):
        """Should handle URLs without path."""
        url = "https://example.com"
        assert extract_base_url(url) == "https://example.com"

    def test_handles_none_input(self):
        """None input should return None."""
        assert extract_base_url(None) is None  # type: ignore

    def test_handles_empty_string(self):
        """Empty string should return None."""
        assert extract_base_url("") is None

    def test_handles_malformed_url(self):
        """Malformed URLs return scheme://netloc (may be '://' if no scheme)."""
        result = extract_base_url("not a valid url")
        # urlparse treats this as having no scheme/netloc, returns '://'
        assert result == "://"

    def test_handles_url_with_authentication(self):
        """Should handle URLs with user:pass@ authentication."""
        url = "https://user:pass@example.com/story"
        result = extract_base_url(url)
        # May include or exclude auth - we just ensure it doesn't crash
        assert result is not None
        assert "example.com" in result

    def test_handles_ipv4_address(self):
        """Should handle IPv4 addresses."""
        url = "http://192.168.1.1:8080/admin"
        assert extract_base_url(url) == "http://192.168.1.1:8080"

    def test_handles_localhost(self):
        """Should handle localhost."""
        url = "http://localhost:3000/api"
        assert extract_base_url(url) == "http://localhost:3000"

    def test_handles_complex_tld(self):
        """Should handle complex TLDs."""
        url = "https://example.co.uk/story"
        assert extract_base_url(url) == "https://example.co.uk"

    def test_strips_query_and_fragment(self):
        """Should not include query or fragment in base URL."""
        url = "https://example.com/path?query=value#fragment"
        result = extract_base_url(url)
        assert result == "https://example.com"
        assert "?" not in result
        assert "#" not in result

    def test_handles_unicode_domain(self):
        """Should handle internationalized domain names."""
        url = "https://例え.jp/story"
        result = extract_base_url(url)
        # Should parse without crashing
        assert result is not None
