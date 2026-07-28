"""Every capture path must report the proxy it used, not just the HTTP one.

Extraction captures a page one of three ways: the plain proxied HTTP fetch
(`_fetch_page_html`), the tls_client/unblock rung
(`_extract_with_unblock_proxy`), or a Selenium render. Only the first ever
called `set_proxy_metrics`, so an extraction captured by either of the other
two recorded `proxy_used=0`, `proxy_url` NULL and `router_proxy` NULL -- while
its traffic went through Squid exactly like everything else.

Measured in production 2026-07-28 over 250 CIN-labelled rows: **all 47 rows
missing proxy data were captured by Selenium or the unblock rung, and every one
of the 203 http_fetch rows had it**. A perfect split, which is what a
per-path instrumentation gap looks like rather than a data problem.

This was invisible until it wasn't: Selenium produced no rows at all from
2026-07-25 to 07-27 (the Manifest V2 proxy-auth outage), so there were no
Selenium-captured extractions to under-report. Fixing Selenium exposed the gap.

It is the same defect class as the fetch-path bug fixed the day before -- the
proxy was never bypassed, only the evidence was -- and these tests exist so the
next capture path added cannot repeat it silently.
"""

import os
from unittest.mock import Mock

import pytest

from src.crawler import ContentExtractor
from src.crawler.proxy_config import RouterProxy
from src.utils.comprehensive_telemetry import PROXY_STATUS_SUCCESS, ExtractionMetrics


def _metrics():
    return ExtractionMetrics("op", "art", "https://example.com/s", "example.com")


class TestSeleniumProxyResolution:
    """One definition, so telemetry cannot report a proxy the driver isn't using."""

    def test_prefers_selenium_proxy(self, monkeypatch):
        monkeypatch.setenv("SELENIUM_PROXY", "http://u:p@sel.example:3128")
        monkeypatch.setenv("SQUID_PROXY_URL", "http://u:p@squid.example:3128")
        assert (
            ContentExtractor._resolve_selenium_proxy() == "http://u:p@sel.example:3128"
        )

    def test_falls_back_to_squid_proxy_url(self, monkeypatch):
        monkeypatch.delenv("SELENIUM_PROXY", raising=False)
        monkeypatch.setenv("SQUID_PROXY_URL", "http://u:p@squid.example:3128")
        assert (
            ContentExtractor._resolve_selenium_proxy()
            == "http://u:p@squid.example:3128"
        )

    def test_never_resolves_to_empty(self, monkeypatch):
        """An empty proxy would mean an unproxied browser egressing the pod IP."""
        monkeypatch.delenv("SELENIUM_PROXY", raising=False)
        monkeypatch.delenv("SQUID_PROXY_URL", raising=False)
        assert ContentExtractor._resolve_selenium_proxy()

    def test_the_driver_sites_use_this_helper(self):
        """The value must not be re-derived inline anywhere.

        Three driver-creation sites each inlined the same os.getenv chain. A
        divergence between them and what telemetry reported would be invisible,
        so the lookup lives in one place and this pins it there.
        """
        import inspect

        import src.crawler as crawler_module

        src = inspect.getsource(crawler_module)
        # Only the helper body itself may name the variable.
        assert src.count('"SELENIUM_PROXY"') == 1


class TestSeleniumRecordsItsProxy:
    def test_selenium_start_records_proxy_used(self, monkeypatch):
        monkeypatch.setenv("SELENIUM_PROXY", "http://user:pw@squid.example:3128")
        metrics = _metrics()

        # conftest's autouse fixture forces SELENIUM_AVAILABLE False so no test
        # spawns real Chrome. Without re-enabling it here _run_selenium_extraction
        # returns on its first line and these assertions pass vacuously -- which
        # is exactly what test_router_proxy_stays_unset_for_selenium did before
        # this was noticed. Chrome is still never launched: _check_rate_limit
        # below short-circuits the method well before any driver is created.
        monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True)

        ex = ContentExtractor.__new__(ContentExtractor)
        ex._check_rate_limit = lambda d: True  # bail immediately after recording
        ex.domain_router_proxy = {}
        ex._selenium_failure_counts = {}
        ex._disable_selenium_for_diagnostics = False

        try:
            ex._run_selenium_extraction(
                "https://example.com/story",
                {},
                metrics,
                reason="test",
                missing_fields=["content"],
            )
        except Exception:
            pass  # the extraction itself is not under test; the recording is

        assert metrics.proxy_used is True, "a Selenium capture is proxied"
        assert "squid.example" in (metrics.proxy_url or "")
        assert metrics.proxy_status == PROXY_STATUS_SUCCESS

    def test_selenium_masks_its_credentials(self, monkeypatch):
        monkeypatch.setenv("SELENIUM_PROXY", "http://user:sekret@squid.example:3128")
        metrics = _metrics()
        # conftest's autouse fixture forces SELENIUM_AVAILABLE False so no test
        # spawns real Chrome. Without re-enabling it here _run_selenium_extraction
        # returns on its first line and these assertions pass vacuously -- which
        # is exactly what test_router_proxy_stays_unset_for_selenium did before
        # this was noticed. Chrome is still never launched: _check_rate_limit
        # below short-circuits the method well before any driver is created.
        monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True)

        monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True)
        ex = ContentExtractor.__new__(ContentExtractor)
        ex._check_rate_limit = lambda d: True
        ex.domain_router_proxy = {}
        ex._selenium_failure_counts = {}
        ex._disable_selenium_for_diagnostics = False
        try:
            ex._run_selenium_extraction(
                "https://example.com/s", {}, metrics, "test", ["content"]
            )
        except Exception:
            pass
        assert "sekret" not in (metrics.proxy_url or "")
        assert metrics.proxy_authenticated is True

    def test_router_proxy_stays_unset_for_selenium(self, monkeypatch):
        """Honest absence, not a guess.

        Selenium reads a static SELENIUM_PROXY and never consults the shared
        router, so there is no home/mizzou decision to report. Recording one
        would invent a routing choice that never happened -- and would hide
        that browser traffic is exempt from #413's health-based failover.
        """
        monkeypatch.setenv("SELENIUM_PROXY", "http://user:pw@squid.example:3128")
        metrics = _metrics()
        # conftest's autouse fixture forces SELENIUM_AVAILABLE False so no test
        # spawns real Chrome. Without re-enabling it here _run_selenium_extraction
        # returns on its first line and these assertions pass vacuously -- which
        # is exactly what test_router_proxy_stays_unset_for_selenium did before
        # this was noticed. Chrome is still never launched: _check_rate_limit
        # below short-circuits the method well before any driver is created.
        monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True)

        monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True)
        ex = ContentExtractor.__new__(ContentExtractor)
        ex._check_rate_limit = lambda d: True
        ex.domain_router_proxy = {"example.com": RouterProxy.MIZZOU_SQUID}
        ex._selenium_failure_counts = {}
        ex._disable_selenium_for_diagnostics = False
        try:
            ex._run_selenium_extraction(
                "https://example.com/s", {}, metrics, "test", ["content"]
            )
        except Exception:
            pass
        assert metrics.router_proxy is None


class TestTelemetryIsRecordedPerPath:
    """Guard the shape of the bug rather than one instance of it."""

    def test_every_capture_path_records_proxy_metrics(self):
        """A capture path that never calls set_proxy_metrics under-reports.

        Pins the three known paths. A fourth added without recording will not
        trip this, but the assertion documents the requirement at the point
        someone would look.
        """
        import inspect

        import src.crawler as crawler_module

        for fn in (
            crawler_module.ContentExtractor._fetch_page_html,
            crawler_module.ContentExtractor._extract_with_unblock_proxy,
            crawler_module.ContentExtractor._run_selenium_extraction,
        ):
            src = inspect.getsource(fn)
            assert "set_proxy_metrics" in src, (
                f"{fn.__name__} captures pages but never records which proxy "
                "served them -- the gap that made proxy_used=0 on 47 of 250 rows"
            )

    def test_recording_failure_cannot_break_a_capture(self):
        """Telemetry must never be able to discard a capture we already hold."""
        import inspect

        import src.crawler as crawler_module

        for fn in (
            crawler_module.ContentExtractor._fetch_page_html,
            crawler_module.ContentExtractor._extract_with_unblock_proxy,
            crawler_module.ContentExtractor._run_selenium_extraction,
        ):
            src = inspect.getsource(fn)
            # rindex on the CALL: the name also appears in explanatory
            # comments, and matching those would pass on unguarded code.
            idx = src.rindex("set_proxy_metrics(")
            window = src[max(0, idx - 400) : idx]
            assert "try:" in window, f"{fn.__name__} must guard the recording"
