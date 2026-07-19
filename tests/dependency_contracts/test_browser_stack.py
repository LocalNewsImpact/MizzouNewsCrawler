"""Contracts for the browser-automation stack: selenium,
undetected-chromedriver, selenium-stealth, cloudscraper.

The real-Chrome test runs only where a Chrome binary exists (the crawler
image in Image Build Check); elsewhere it skips. API-surface tests run
everywhere the libraries import.
"""

from __future__ import annotations

import pytest

from .conftest import chrome_binary_present


class TestSeleniumSurface:
    """Call sites: src/crawler/__init__.py Selenium fallback — Options flags,
    driver.get, page_source, quit."""

    def test_chrome_options_flags_surface(self):
        options_mod = pytest.importorskip("selenium.webdriver.chrome.options")

        opts = options_mod.Options()
        # The exact flags the crawler sets — add_argument must accept them.
        for flag in (
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ):
            opts.add_argument(flag)
        assert "--no-sandbox" in opts.arguments

    def test_undetected_chromedriver_real_boot(self):
        """Boot real Chrome via undetected_chromedriver EXACTLY as extraction
        does (src/crawler/__init__.py:4778-4799): the baked, version-matched
        driver from CHROMEDRIVER_PATH and browser from CHROME_BIN. A bare
        uc.Chrome() would download the latest chromedriver and fail on any
        Chrome-version mismatch prod never sees. Crawler-image venue only."""
        import os

        if not chrome_binary_present():
            pytest.skip("no Chrome binary in this venue")
        uc = pytest.importorskip("undetected_chromedriver")

        opts = uc.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")

        uc_kwargs = {}
        driver_path = os.getenv("CHROMEDRIVER_PATH")
        chrome_bin = os.getenv("CHROME_BIN") or os.getenv("GOOGLE_CHROME_BIN")
        if driver_path:
            uc_kwargs["driver_executable_path"] = str(driver_path)
        if chrome_bin:
            uc_kwargs["browser_executable_path"] = str(chrome_bin)

        driver = uc.Chrome(options=opts, **uc_kwargs)
        try:
            driver.get("data:text/html,<html><body><h1>contract</h1></body></html>")
            assert "contract" in driver.page_source
        finally:
            driver.quit()

    def test_selenium_stealth_import_surface(self):
        stealth_mod = pytest.importorskip("selenium_stealth")

        assert callable(stealth_mod.stealth)


class TestCloudscraper:
    """Call site: Cloudflare escalation path in src/crawler/__init__.py —
    create_scraper() must construct without network access."""

    def test_create_scraper(self):
        cloudscraper = pytest.importorskip("cloudscraper")

        scraper = cloudscraper.create_scraper()
        # requests.Session subclass surface the crawler relies on
        assert hasattr(scraper, "get") and hasattr(scraper, "headers")
