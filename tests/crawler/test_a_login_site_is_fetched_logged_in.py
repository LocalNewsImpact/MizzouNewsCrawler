"""A publisher with a login is fetched logged in, from the first request.

The anonymous HTTP paths return the wall, and a wall is a 200 with content:
extraction accepts it, stores the stub, and the browser -- the only place
`_ensure_authenticated` runs -- is never reached. On 2026-09-18 that filed 13
of 19 Port Townsend Leader articles as `paywall` against a credential known to
work, off a page whose own text read "access this content ... login".
"""

from __future__ import annotations

import inspect

from src.crawler import ContentExtractor


class TestTheHostIsNormalisedTheWaySourcesStoresIt:
    def test_www_userinfo_and_port_are_stripped(self):
        for given, want in [
            ("www.ptleader.com", "ptleader.com"),
            ("ptleader.com:443", "ptleader.com"),
            ("user@www.ptleader.com:8080", "ptleader.com"),
            ("PTLeader.com", "ptleader.com"),
        ]:
            assert ContentExtractor._bare_host(given) == want

    def test_an_empty_domain_is_not_an_error(self):
        assert ContentExtractor._bare_host("") == ""
        assert ContentExtractor._bare_host(None) == ""


class TestRequiresLogin:
    def _extractor(self, monkeypatch, answer):
        obj = ContentExtractor.__new__(ContentExtractor)
        monkeypatch.setattr(
            ContentExtractor, "_get_domain_auth_config", lambda self, host: answer
        )
        return obj

    def test_a_configured_publisher_requires_login(self, monkeypatch):
        obj = self._extractor(monkeypatch, {"auth_type": "simplecirc"})
        assert obj._requires_login("www.ptleader.com") is True

    def test_a_publisher_without_a_config_does_not(self, monkeypatch):
        """`_get_domain_auth_config` returns None unless sources.requires_login
        is set, so the two callers cannot disagree about who needs a login."""
        obj = self._extractor(monkeypatch, None)
        assert obj._requires_login("www.kitsapsun.com") is False

    def test_a_lookup_failure_does_not_block_extraction(self, monkeypatch):
        """A database hiccup must not turn every host into a browser fetch."""
        obj = ContentExtractor.__new__(ContentExtractor)

        def boom(self, host):
            raise RuntimeError("no database")

        monkeypatch.setattr(ContentExtractor, "_get_domain_auth_config", boom)
        assert obj._requires_login("ptleader.com") is False


class TestNothingCanUndoTheDecision:
    """`credentialed` is read once and two later branches clear
    `skip_http_methods`. Either one re-enables the anonymous path, and the
    anonymous path is what returns the wall."""

    def _body(self) -> str:
        from pathlib import Path

        return Path("src/crawler/__init__.py").read_text()

    def test_being_credentialed_skips_the_http_methods(self):
        body = self._body()
        assert "credentialed = self._requires_login(domain)" in body
        assert "skip_http_methods = credentialed or extraction_method in {" in body

    def test_cloudflare_escalation_is_off_for_a_credentialed_host(self):
        """cloudscraper solves a JS challenge anonymously, which on a
        credentialed host buys a wall instead of an article."""
        body = self._body()
        block = body.split("cloudflare_escalation_enabled = (")[1].split(")")[0]
        assert "not credentialed" in block

    def test_amp_preemption_is_off_for_a_credentialed_host(self):
        """The AMP copy is served unauthenticated, and the AMP branch assigns
        it as the body AND clears skip_http_methods -- so leaving it on undoes
        the decision and hands the parsers a paywall notice."""
        body = self._body()
        amp = body.split("Check for preemptive AMP fetch")[1][:600]
        assert "not credentialed" in amp
        assert "and self._get_domain_amp_support(domain)" in amp

    def test_the_decision_precedes_both_branches_that_clear_the_flag(self):
        body = self._body()
        decided = body.index("credentialed = self._requires_login(domain)")
        cloudflare = body.index("skip_http_methods = False  # Allow HTTP methods")
        amp = body.index("Check for preemptive AMP fetch")
        assert decided < cloudflare
        assert decided < amp


class TestOneSessionPerRun:
    def test_the_driver_is_shared_and_reused_not_rebuilt_per_article(self):
        """One browser session for the run: the driver is class-level, so the
        login survives between articles."""
        from src.crawler import ContentExtractor

        assert hasattr(ContentExtractor, "_shared_persistent_driver")
        assert hasattr(ContentExtractor, "_authenticated_domains")

    def test_the_login_cache_clears_only_when_the_driver_closes(self):
        """Clearing it any earlier would re-login per article; clearing it later
        would carry a dead session into a fresh browser."""

        from src.crawler import ContentExtractor

        src = inspect.getsource(ContentExtractor.close_persistent_driver)
        assert "_authenticated_domains = set()" in src

    def test_the_session_is_established_before_navigation(self):
        """A login after navigation does not carry cookies into the article."""

        from src.crawler import ContentExtractor

        src = inspect.getsource(ContentExtractor._extract_with_selenium)
        assert src.index("_ensure_authenticated") < src.index(
            "_navigate_with_human_behavior"
        )
