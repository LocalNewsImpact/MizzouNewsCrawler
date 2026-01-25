import pytest

import src.crawler as crawler_module
from src.crawler import ContentExtractor


@pytest.fixture
def extractor(monkeypatch):
    # Create minimal extractor fixture (reuse existing helper logic from other tests)
    monkeypatch.setattr(crawler_module, "CLOUDSCRAPER_AVAILABLE", False)
    monkeypatch.setattr(crawler_module, "cloudscraper", None)
    extractor = ContentExtractor()
    extractor.user_agent_pool = ["ua1"]
    extractor.proxy_pool = ["http://proxy.local:3128"]
    return extractor


def test_selenium_first_blocks_http_session(extractor):
    domain_url = "https://example.com/path"
    extractor._enforce_selenium_first_domain = "example.com"

    with pytest.raises(Exception) as exc:
        extractor._get_domain_session(domain_url)

    assert "Selenium-first enforced" in str(exc.value)

    # Clear the enforcement and try again - should not raise
    extractor._enforce_selenium_first_domain = None
    sess = extractor._get_domain_session(domain_url)
    assert sess is not None
