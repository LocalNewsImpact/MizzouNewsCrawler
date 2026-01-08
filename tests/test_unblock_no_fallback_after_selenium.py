import pytest
from unittest.mock import patch, Mock

from src.crawler import ContentExtractor, ProxyChallengeError


@patch.object(ContentExtractor, "_get_domain_extraction_method")
@patch.object(ContentExtractor, "_run_selenium_extraction")
@patch.object(ContentExtractor, "_extract_with_unblock_proxy")
def test_unblock_domain_no_http_fallback_after_selenium(
    mock_unblock, mock_selenium_run, mock_get_method, monkeypatch
):
    import src.crawler as crawler_module

    # Ensure Selenium is considered available for this test
    monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)

    # Setup: domain requires unblock extraction (PerimeterX)
    mock_get_method.return_value = ("unblock", "perimeterx")

    # Simulate Selenium attempted and failed
    mock_selenium_run.return_value = (True, False)

    extractor = ContentExtractor()

    # Ensure _extract_with_unblock_proxy is not called when Selenium already failed
    mock_unblock.side_effect = AssertionError("_extract_with_unblock_proxy should not be called")

    with pytest.raises(ProxyChallengeError) as exc_info:
        extractor.extract_content("https://example.com/test-article")

    assert "selenium_failed_no_fallback" in str(exc_info.value)
    mock_unblock.assert_not_called()
