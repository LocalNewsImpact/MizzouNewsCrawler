"""The HTTP status a browser navigation got, which Selenium does not report.

`driver.get()` returns None, and a 404 renders like any other page. On
2026-09-18 all 30 Port Townsend Leader links carried
`candidate_links.http_status = NULL`, and a fetch that landed on a fallback page
was stored as an article because nothing contradicted it.

Chrome reports it over the DevTools Protocol and the driver already collects
those events -- the log was being written to /tmp for diagnostics and otherwise
thrown away.
"""

from __future__ import annotations

import json

from src.crawler.browser_status import (
    DOCUMENT_TYPE,
    document_status,
    read_navigation_status,
)


def _entry(status, url, rtype=DOCUMENT_TYPE, method="Network.responseReceived"):
    return {
        "message": json.dumps(
            {
                "message": {
                    "method": method,
                    "params": {
                        "type": rtype,
                        "response": {"status": status, "url": url},
                    },
                }
            }
        )
    }


class _Driver:
    def __init__(self, entries):
        self._entries = entries
        self.reads = 0

    def get_log(self, which):
        assert which == "performance"
        self.reads += 1
        # get_log consumes the buffer, as Chrome's does.
        entries, self._entries = self._entries, []
        return entries


class TestReadingTheDocumentStatus:
    def test_a_plain_200(self):
        assert document_status([_entry(200, "https://x.test/a")]) == (
            200,
            "https://x.test/a",
        )

    def test_a_404_is_reported(self):
        assert document_status([_entry(404, "https://x.test/gone")])[0] == 404

    def test_assets_are_ignored(self):
        """A page fires this event for every image and beacon. A 404 on a
        tracking pixel says nothing about the article."""
        entries = [
            _entry(200, "https://x.test/a"),
            _entry(404, "https://x.test/pixel.gif", rtype="Image"),
            _entry(500, "https://x.test/ads.js", rtype="Script"),
        ]
        assert document_status(entries) == (200, "https://x.test/a")

    def test_the_last_document_wins_so_a_redirect_reports_where_it_ended(self):
        """ptleader answers /stories/<slug>,<id> with two 301s to
        /articles/<section>/<slug>/. The useful answer is the destination."""
        entries = [
            _entry(301, "https://x.test/stories/a,1"),
            _entry(301, "https://x.test/mid"),
            _entry(200, "https://x.test/articles/local/a/"),
        ]
        assert document_status(entries) == (200, "https://x.test/articles/local/a/")

    def test_an_empty_log_says_nothing_rather_than_guessing(self):
        assert document_status([]) == (None, None)

    def test_other_cdp_events_are_skipped(self):
        assert document_status(
            [_entry(200, "https://x.test/a", method="Network.requestWillBeSent")]
        ) == (None, None)

    def test_malformed_entries_do_not_break_the_read(self):
        entries = [{"message": "not json"}, {}, _entry(200, "https://x.test/a")]
        assert document_status(entries) == (200, "https://x.test/a")

    def test_a_non_integer_status_is_not_a_status(self):
        entries = [_entry("200", "https://x.test/a")]
        assert document_status(entries) == (None, None)


class TestReadingItFromADriver:
    def test_it_returns_the_status_and_final_url(self):
        driver = _Driver([_entry(200, "https://x.test/a")])
        assert read_navigation_status(driver) == (200, "https://x.test/a")

    def test_a_driver_without_the_log_is_not_an_error(self):
        """The browser path gave no status at all before this existed, so a
        driver that cannot supply one leaves the caller no worse off."""

        class _NoLog:
            def get_log(self, which):
                raise RuntimeError("performance logging not enabled")

        assert read_navigation_status(_NoLog()) == (None, None)

    def test_the_log_is_read_once_because_reading_consumes_it(self):
        driver = _Driver([_entry(404, "https://x.test/gone")])
        assert read_navigation_status(driver)[0] == 404
        assert driver.reads == 1
        # A second read sees only what arrived since -- nothing.
        assert read_navigation_status(driver) == (None, None)


class TestTheCallerRecordsIt:
    def test_the_navigation_status_is_read_and_stored(self):
        from pathlib import Path

        body = Path("src/crawler/__init__.py").read_text()
        block = body.split("success = self._navigate_with_human_behavior(driver, url)")[
            1
        ][:900]
        assert "read_navigation_status(driver)" in block
        assert "self._last_fetch_http_status = nav_status" in block

    def test_a_4xx_is_logged_as_a_warning_not_swallowed(self):
        from pathlib import Path

        body = Path("src/crawler/__init__.py").read_text()
        assert "nav_status >= 400" in body
