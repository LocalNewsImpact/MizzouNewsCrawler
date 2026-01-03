"""Test Selenium prioritization logic for different extraction methods.

This test validates the core extraction strategy:
1. HTTP domains: Try HTTP methods first (mediacloud/newspaper4k), escalate to Selenium if needed
2. Unblock domains: Try Selenium headful first (PerimeterX/Akamai require it)
3. Selenium-only domains: Always use Selenium
"""
import pytest

from src.crawler import ContentExtractor


class TestSeleniumPrioritization:
    """Test _should_prioritize_selenium() method behavior."""

    def test_http_extraction_method_uses_http_first(self):
        """HTTP domains should NOT prioritize Selenium (try HTTP methods first)."""
        extractor = ContentExtractor()
        
        # HTTP extraction method should use HTTP-first strategy
        assert extractor._should_prioritize_selenium("http") is False
        
        # This allows normal escalation: HTTP → Selenium headless → Selenium headful

    def test_unblock_extraction_method_prioritizes_selenium(self):
        """Unblock domains (PerimeterX/Akamai) MUST prioritize Selenium."""
        extractor = ContentExtractor()
        
        # Unblock domains MUST use Selenium first to defeat bot protection
        assert extractor._should_prioritize_selenium("unblock") is True

    def test_selenium_extraction_method_prioritizes_selenium(self):
        """Selenium-only domains MUST prioritize Selenium."""
        extractor = ContentExtractor()
        
        # Domains marked as selenium_only should always use Selenium
        assert extractor._should_prioritize_selenium("selenium") is True

    def test_headful_mode_does_not_override_http_strategy(self):
        """Headful mode should NOT force Selenium-first for HTTP domains.
        
        BUG FIX: Previously, headful mode caused ALL domains to use Selenium first.
        Correct behavior: Headful mode only affects HOW Selenium runs, not WHEN.
        """
        # Explicitly create extractor in headful mode
        extractor = ContentExtractor(selenium_mode="headful")
        
        assert extractor.selenium_mode == "headful"
        
        # Even in headful mode, HTTP domains should use HTTP-first strategy
        assert extractor._should_prioritize_selenium("http") is False
        
        # Unblock domains should still prioritize Selenium in headful mode
        assert extractor._should_prioritize_selenium("unblock") is True

    def test_selenium_primary_strategy_override(self, monkeypatch):
        """SELENIUM_PRIMARY_STRATEGY env var can force selenium-first for all domains."""
        monkeypatch.setenv("SELENIUM_PRIMARY_STRATEGY", "selenium-first")
        
        extractor = ContentExtractor()
        
        # When explicitly configured as selenium-first, even HTTP domains use Selenium first
        assert extractor._should_prioritize_selenium("http") is True
        
        # Unblock domains should always prioritize Selenium regardless
        assert extractor._should_prioritize_selenium("unblock") is True

    def test_http_first_strategy_default(self):
        """Default strategy should be http-first."""
        extractor = ContentExtractor()
        
        # Default strategy should be http-first
        assert extractor._selenium_primary_strategy == "http-first"
        
        # This means HTTP domains don't prioritize Selenium
        assert extractor._should_prioritize_selenium("http") is False

    def test_escalation_logic_for_http_domains(self):
        """HTTP domains should escalate to Selenium only when HTTP methods fail.
        
        This is tested implicitly through the prioritization logic:
        - _should_prioritize_selenium("http") returns False
        - Extraction tries HTTP methods first
        - Selenium is used as fallback for missing fields
        """
        extractor = ContentExtractor()
        
        # HTTP domains don't prioritize Selenium
        selenium_first = extractor._should_prioritize_selenium("http")
        assert selenium_first is False
        
        # The extraction pipeline will:
        # 1. Try mediacloud/newspaper4k/requests first
        # 2. If fields missing, escalate to Selenium (headless → headful)


class TestExtractionMethodIntegration:
    """Test how extraction_method from database affects behavior."""
    
    def test_extraction_method_values(self):
        """Verify expected extraction_method values are handled."""
        extractor = ContentExtractor()
        
        # Standard HTTP extraction
        assert extractor._should_prioritize_selenium("http") is False
        
        # PerimeterX/Akamai/DataDome protection
        assert extractor._should_prioritize_selenium("unblock") is True
        
        # Sites that ONLY work with Selenium
        assert extractor._should_prioritize_selenium("selenium") is True
    
    def test_invalid_extraction_method_defaults_to_http_first(self):
        """Unknown extraction methods should default to http-first behavior."""
        extractor = ContentExtractor()
        
        # Invalid/unknown extraction methods should not prioritize Selenium
        assert extractor._should_prioritize_selenium("unknown") is False
        assert extractor._should_prioritize_selenium("") is False
        assert extractor._should_prioritize_selenium(None) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
