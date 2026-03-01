"""Tests for canonical URL adoption in extraction.

Tests the _get_canonical_url function that prefers canonical URLs over
discovered URLs when they are on the same domain.
"""

from __future__ import annotations

import pytest

from src.cli.commands.extraction import _get_canonical_url


class TestGetCanonicalUrl:
    """Tests for _get_canonical_url function."""

    def test_same_domain_canonical_url_adopted(self):
        """When canonical URL is on same domain, it should be adopted."""
        original_url = (
            "https://abc17news.com/news/2026/02/28/"
            "the-1700-year-old-megastructure-history-almost-forgot"
        )
        metadata = {
            "mcmetadata": {
                "canonical_url": (
                    "https://abc17news.com/entertainment/cnn-style/2026/02/28/"
                    "the-1700-year-old-megastructure-history-almost-forgot/"
                )
            }
        }

        result = _get_canonical_url(original_url, metadata)

        assert result == metadata["mcmetadata"]["canonical_url"]
        assert "/cnn-style/" in result

    def test_different_domain_canonical_url_rejected(self):
        """When canonical URL is on different domain, keep original."""
        original_url = "https://localstation.com/news/story"
        metadata = {
            "mcmetadata": {
                "canonical_url": "https://apnews.com/article/original-ap-story"
            }
        }

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url
        assert "apnews.com" not in result

    def test_no_canonical_url_in_metadata(self):
        """When no canonical URL exists, return original."""
        original_url = "https://example.com/news/story"
        metadata = {"mcmetadata": {"language": "en"}}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_empty_canonical_url(self):
        """When canonical URL is empty string, return original."""
        original_url = "https://example.com/news/story"
        metadata = {"mcmetadata": {"canonical_url": ""}}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_none_canonical_url(self):
        """When canonical URL is None, return original."""
        original_url = "https://example.com/news/story"
        metadata = {"mcmetadata": {"canonical_url": None}}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_whitespace_only_canonical_url(self):
        """When canonical URL is whitespace only, return original."""
        original_url = "https://example.com/news/story"
        metadata = {"mcmetadata": {"canonical_url": "   "}}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_no_mcmetadata_key(self):
        """When mcmetadata key missing, return original."""
        original_url = "https://example.com/news/story"
        metadata = {"other_key": "value"}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_empty_metadata(self):
        """When metadata is empty dict, return original."""
        original_url = "https://example.com/news/story"
        metadata = {}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_none_metadata(self):
        """When metadata is None, return original."""
        original_url = "https://example.com/news/story"
        metadata = None

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_non_dict_metadata(self):
        """When metadata is not a dict, return original."""
        original_url = "https://example.com/news/story"

        result = _get_canonical_url(original_url, "not a dict")

        assert result == original_url

    def test_www_prefix_handling_same_domain(self):
        """www. prefix should be stripped for domain comparison."""
        original_url = "https://www.example.com/news/story"
        metadata = {
            "mcmetadata": {"canonical_url": "https://example.com/news/canonical-story"}
        }

        result = _get_canonical_url(original_url, metadata)

        assert result == metadata["mcmetadata"]["canonical_url"]

    def test_www_prefix_handling_reversed(self):
        """www. prefix on canonical should also be handled."""
        original_url = "https://example.com/news/story"
        metadata = {
            "mcmetadata": {
                "canonical_url": "https://www.example.com/news/canonical-story"
            }
        }

        result = _get_canonical_url(original_url, metadata)

        assert result == metadata["mcmetadata"]["canonical_url"]

    def test_www_prefix_different_domain(self):
        """www. stripping shouldn't make different domains seem same."""
        original_url = "https://www.localstation.com/news/story"
        metadata = {"mcmetadata": {"canonical_url": "https://www.cnn.com/news/story"}}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_preserves_wire_path_markers(self):
        """Real-world case: canonical URL has wire path markers."""
        # This is the actual abc17news.com case that prompted this feature
        original_url = (
            "https://abc17news.com/news/2026/02/28/"
            "louisiana-judge-temporarily-blocks-state"
        )
        metadata = {
            "mcmetadata": {
                "canonical_url": (
                    "https://abc17news.com/politics/national-politics/"
                    "cnn-us-politics/2026/02/28/"
                    "louisiana-judge-temporarily-blocks-state"
                )
            }
        }

        result = _get_canonical_url(original_url, metadata)

        assert "/cnn-us-politics/" in result
        assert "/politics/national-politics/" in result

    def test_case_insensitive_domain_comparison(self):
        """Domain comparison should be case-insensitive."""
        original_url = "https://EXAMPLE.COM/news/story"
        metadata = {
            "mcmetadata": {"canonical_url": "https://example.com/news/canonical-story"}
        }

        result = _get_canonical_url(original_url, metadata)

        assert result == metadata["mcmetadata"]["canonical_url"]

    def test_subdomain_treated_as_different(self):
        """Subdomains should be treated as different domains."""
        original_url = "https://news.example.com/story"
        metadata = {"mcmetadata": {"canonical_url": "https://example.com/story"}}

        result = _get_canonical_url(original_url, metadata)

        # Should keep original since news.example.com != example.com
        assert result == original_url

    def test_trailing_slash_handling(self):
        """Canonical URL with trailing slash should still work."""
        original_url = "https://example.com/news/story"
        metadata = {"mcmetadata": {"canonical_url": "https://example.com/news/story/"}}

        result = _get_canonical_url(original_url, metadata)

        # Should adopt canonical (same domain, just has trailing slash)
        assert result == metadata["mcmetadata"]["canonical_url"]

    def test_non_string_canonical_url(self):
        """When canonical URL is not a string, return original."""
        original_url = "https://example.com/news/story"
        metadata = {"mcmetadata": {"canonical_url": 12345}}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url


class TestCanonicalUrlImpactAnalysis:
    """Tests to verify canonical URL adoption doesn't break expected behavior.

    These tests document expected behavior for various real-world scenarios
    to ensure the change doesn't negatively impact other sites.
    """

    def test_local_news_site_no_canonical_unchanged(self):
        """Local news sites without canonical URLs are unaffected."""
        original_url = "https://joplinglobe.com/news/local-story"
        metadata = {"mcmetadata": {"language": "en", "title": "Local Story"}}

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url

    def test_local_news_site_same_canonical_path(self):
        """Local news with canonical = original should return canonical."""
        original_url = "https://joplinglobe.com/news/local-story"
        metadata = {
            "mcmetadata": {"canonical_url": "https://joplinglobe.com/news/local-story"}
        }

        result = _get_canonical_url(original_url, metadata)

        # Same URL, so result is the canonical (which equals original)
        assert result == original_url

    def test_gray_tv_affiliate_wire_detection(self):
        """Gray TV affiliates (abc17, komu, etc.) with CNN content."""
        original_url = "https://komu.com/news/2026/03/01/breaking-story"
        metadata = {
            "mcmetadata": {
                "canonical_url": (
                    "https://komu.com/cnn/business/2026/03/01/breaking-story"
                )
            }
        }

        result = _get_canonical_url(original_url, metadata)

        assert "/cnn/" in result

    def test_hearst_tv_affiliate_ap_content(self):
        """Hearst TV affiliates syndicating AP content."""
        original_url = "https://kctv5.com/news/national/story"
        metadata = {
            "mcmetadata": {
                # Hearst canonical URLs typically stay on same domain
                "canonical_url": "https://kctv5.com/news/ap-wire/story"
            }
        }

        result = _get_canonical_url(original_url, metadata)

        # Should adopt since same domain
        assert result == metadata["mcmetadata"]["canonical_url"]
        assert "/ap-wire/" in result

    def test_print_newspaper_no_wire_paths(self):
        """Traditional print newspapers without wire path structure."""
        original_url = "https://columbiatribune.com/story/news/local/2026/03/01/story"
        metadata = {
            "mcmetadata": {
                "canonical_url": (
                    "https://columbiatribune.com/story/news/local/2026/03/01/story"
                )
            }
        }

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url  # Canonical equals original

    def test_cross_domain_canonical_to_ap_rejected(self):
        """Cross-domain canonical pointing to AP should be rejected."""
        original_url = "https://localnews.com/news/breaking"
        metadata = {
            "mcmetadata": {"canonical_url": "https://apnews.com/article/breaking"}
        }

        result = _get_canonical_url(original_url, metadata)

        # Should reject cross-domain to preserve local copy
        assert result == original_url
        assert "apnews.com" not in result

    def test_cross_domain_canonical_to_reuters_rejected(self):
        """Cross-domain canonical pointing to Reuters should be rejected."""
        original_url = "https://localnews.com/business/markets"
        metadata = {
            "mcmetadata": {"canonical_url": "https://reuters.com/business/markets"}
        }

        result = _get_canonical_url(original_url, metadata)

        assert result == original_url
