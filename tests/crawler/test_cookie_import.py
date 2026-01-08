import json
import os
from pathlib import Path

import pytest

from src.crawler.__init__ import ContentExtractor


class MockCDPDriver:
    def __init__(self):
        self.calls = []

    def execute_cdp_cmd(self, cmd, payload):
        self.calls.append((cmd, payload))
        if cmd == "Network.setCookie":
            return {"success": True}
        return None


class MockAddCookieDriver:
    def __init__(self):
        self.added = []
        self.load_attempted = False

    def set_page_load_timeout(self, t):
        pass

    def get(self, url):
        # simulate a simple load
        self.load_attempted = True

    def add_cookie(self, cookie):
        self.added.append(cookie)


def test_maybe_import_selenium_cookies_uses_cdp(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookies = [
        {"name": "_pxvid", "value": "abc", "domain": ".fox4kc.com", "path": "/"},
        {"name": "other", "value": "x", "domain": "example.com", "path": "/"},
    ]
    cookie_file.write_text(json.dumps(cookies))

    # Set env var to point to cookie file
    os.environ["SELENIUM_IMPORT_COOKIES_FILE"] = str(cookie_file)

    extractor = ContentExtractor()
    driver = MockCDPDriver()

    ok = extractor._maybe_import_selenium_cookies(driver, "fox4kc.com")
    assert ok is True
    # Should have one Network.setCookie call for the _pxvid cookie
    set_calls = [c for c in driver.calls if c[0] == "Network.setCookie"]
    assert len(set_calls) == 1
    assert set_calls[0][1]["name"] == "_pxvid"


def test_maybe_import_selenium_cookies_fallback_add_cookie(tmp_path):
    cookie_file = tmp_path / "cookies2.json"
    cookies = [
        {"name": "_px2", "value": "abc", "domain": ".fox4kc.com", "path": "/"},
    ]
    cookie_file.write_text(json.dumps(cookies))

    os.environ["SELENIUM_IMPORT_COOKIES_FILE"] = str(cookie_file)

    extractor = ContentExtractor()
    driver = MockAddCookieDriver()

    ok = extractor._maybe_import_selenium_cookies(driver, "fox4kc.com")
    assert ok is True
    assert driver.load_attempted is True
    assert len(driver.added) == 1
    assert driver.added[0]["name"] == "_px2"
