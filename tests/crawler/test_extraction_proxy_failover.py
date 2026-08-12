"""Extraction must act on the router's decision, not just report to it.

Two defects observed on the VTCNI extraction run, 2026-08-12.

**The proxy was chosen once per domain and then cached.** The router is
consulted only when a domain's session is built, and the choice is baked into
``session.proxies``; every later request reuses that session. So when a
challenge made the router back the proxy off for that domain, the router had
learned and extraction had not -- it kept egressing through the refused address
until an unrelated user-agent rotation happened to rebuild the session.

**A challenge fell straight through to Selenium.** The same failure also puts
the domain into CAPTCHA backoff, and that backoff makes the Selenium rung skip
the browser. So one block cost the article twice: the HTTP fetch and the
fallback meant to rescue it. Measured in the run's own log: Selenium was
*skipped* 16 times against 14 actual attempts.

A challenge is a statement about the address a request came from, not about the
page -- the same URL routinely returns 200 from the second Squid.
"""

from __future__ import annotations

import contextlib
from typing import Any, Optional

from src.crawler import ContentExtractor, ProxyChallengeError
from src.crawler.proxy_config import ProxyManager
from src.crawler.proxy_router import RouterProxy

HOME = {"http": "http://home:3128", "https": "http://home:3128"}
MIZZOU = {"http": "http://mizzou:3128", "https": "http://mizzou:3128"}
DOMAIN = "example.com"
URL = "https://example.com/story"


class _ProxyManager:
    """Stubs config lookup; the alternate-selection logic is production's."""

    get_alternate_proxies = ProxyManager.get_alternate_proxies

    def __init__(self, resolvable=None):
        self._resolvable = (
            resolvable
            if resolvable is not None
            else {RouterProxy.HOME_SQUID: HOME, RouterProxy.MIZZOU_SQUID: MIZZOU}
        )
        self.reported: list[tuple] = []
        self.failures = 0

    def get_requests_proxies_for_router_proxy(self, router_proxy):
        return self._resolvable.get(router_proxy)

    def get_requests_proxies_for_domain(self, domain, service="newscrawler"):
        return HOME, RouterProxy.HOME_SQUID, "http"

    def report_domain_result(self, domain, router_proxy, success, reason=None, **kw):
        self.reported.append((router_proxy, success, reason))

    def record_failure(self):
        self.failures += 1


def _extractor(manager: Optional[_ProxyManager] = None) -> ContentExtractor:
    e = ContentExtractor.__new__(ContentExtractor)
    e.proxy_manager = manager or _ProxyManager()
    e.domain_sessions = {}
    e.domain_router_proxy = {}
    e.domain_user_agents = {}
    e.request_counts = {}
    e.last_request_times = {}
    return e


class TestBlockedProxyDropsTheCachedSession:
    def test_session_is_forgotten_so_the_router_gets_asked_again(self):
        e = _extractor()
        e.domain_sessions[DOMAIN] = object()
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID

        e._create_error_result(URL, "Cloudflare 403 bot protection")

        assert DOMAIN not in e.domain_sessions
        assert DOMAIN not in e.domain_router_proxy

    def test_the_failure_is_still_reported_to_the_router(self):
        manager = _ProxyManager()
        e = _extractor(manager)
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID

        e._create_error_result(URL, "captcha challenge")

        assert manager.reported[-1][0] is RouterProxy.HOME_SQUID
        assert manager.reported[-1][1] is False

    def test_an_ordinary_error_leaves_the_session_alone(self):
        """Only proxy-shaped failures should cost a warm session."""
        e = _extractor()
        sentinel = object()
        e.domain_sessions[DOMAIN] = sentinel

        e._create_error_result(URL, "parse error: no article body found")

        assert e.domain_sessions[DOMAIN] is sentinel


class TestRetryThroughTheAlternateProxy:
    def test_retry_uses_the_other_squid(self):
        e = _extractor()
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID
        seen: dict[str, Any] = {}

        def fake_unblock(
            url, actions=None, metrics=None, domain=None, proxy_override=None
        ):
            seen["override"] = proxy_override
            return {"content": "real body"}

        e._extract_with_unblock_proxy = fake_unblock

        result = e._retry_unblock_via_alternate_proxy(URL, DOMAIN, None)

        assert seen["override"] == MIZZOU
        assert result["content"] == "real body"

    def test_success_is_credited_to_the_proxy_that_worked(self):
        manager = _ProxyManager()
        e = _extractor(manager)
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID
        e._extract_with_unblock_proxy = lambda *a, **k: {"content": "body"}

        e._retry_unblock_via_alternate_proxy(URL, DOMAIN, None)

        assert (RouterProxy.MIZZOU_SQUID, True, None) in manager.reported

    def test_a_second_challenge_returns_none_rather_than_raising(self):
        """Both addresses refused is the caller's fall-through-to-Selenium
        case, not a new exception for it to handle."""
        manager = _ProxyManager()
        e = _extractor(manager)
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID

        def refuse(*a, **k):
            raise ProxyChallengeError("challenge_page")

        e._extract_with_unblock_proxy = refuse

        assert e._retry_unblock_via_alternate_proxy(URL, DOMAIN, None) is None
        assert manager.reported[-1][:2] == (RouterProxy.MIZZOU_SQUID, False)

    def test_no_retry_when_the_alternate_is_the_same_box(self):
        """An unconfigured MIZZOU_SQUID resolves back onto home Squid."""
        manager = _ProxyManager(
            {RouterProxy.HOME_SQUID: HOME, RouterProxy.MIZZOU_SQUID: HOME}
        )
        e = _extractor(manager)
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID
        called = []
        e._extract_with_unblock_proxy = lambda *a, **k: called.append(1)

        assert e._retry_unblock_via_alternate_proxy(URL, DOMAIN, None) is None
        assert called == []

    def test_no_retry_when_the_current_proxy_cannot_be_resolved(self):
        """Without the current proxy's URL, "somewhere else" is unprovable --
        so spending a request on it would be guesswork."""
        manager = _ProxyManager({RouterProxy.MIZZOU_SQUID: MIZZOU})
        e = _extractor(manager)
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID
        called = []
        e._extract_with_unblock_proxy = lambda *a, **k: called.append(1)

        assert e._retry_unblock_via_alternate_proxy(URL, DOMAIN, None) is None
        assert called == []

    def test_no_domain_means_no_retry(self):
        e = _extractor()
        assert e._retry_unblock_via_alternate_proxy(URL, None, None) is None

    def test_a_successful_retry_also_drops_the_stale_session(self):
        e = _extractor()
        e.domain_router_proxy[DOMAIN] = RouterProxy.HOME_SQUID
        e.domain_sessions[DOMAIN] = object()
        e._extract_with_unblock_proxy = lambda *a, **k: {"content": "body"}

        e._retry_unblock_via_alternate_proxy(URL, DOMAIN, None)

        assert DOMAIN not in e.domain_sessions


class TestOverrideBypassesTheRouter:
    def test_router_is_not_consulted_when_an_override_is_given(self, monkeypatch):
        """Asking the router again would return the refused box, since backoff
        is not instantaneous."""
        manager = _ProxyManager()
        asked = []
        manager.get_requests_proxies_for_domain = lambda d, service=None: (
            asked.append(d) or (HOME, RouterProxy.HOME_SQUID, "http")
        )
        e = _extractor(manager)

        # The request itself cannot succeed (no network in tests); all this
        # asserts is that routing was skipped before it was attempted.
        with contextlib.suppress(Exception):
            e._extract_with_unblock_proxy(
                URL, None, None, domain=DOMAIN, proxy_override=MIZZOU
            )

        assert asked == []


class TestNoRecordedProxy:
    def test_domain_with_no_routed_proxy_skips_the_retry(self):
        """domain_router_proxy has no entry until a session is built, so the
        current proxy can be None -- there is nothing to be the alternate of."""
        manager = _ProxyManager()
        e = _extractor(manager)
        called = []
        e._extract_with_unblock_proxy = lambda *a, **k: called.append(1)

        assert e._retry_unblock_via_alternate_proxy(URL, DOMAIN, None) is None
        assert called == []


class TestRetryIsNeverFatal:
    def test_extractor_without_routing_state_returns_none(self):
        """The regression the pre-push hook caught.

        Test doubles (and any ContentExtractor built via __new__) have neither
        domain_router_proxy nor proxy_manager. Reading them unguarded turned a
        stubbed ProxyChallengeError into an AttributeError and aborted the
        whole extraction, breaking the flagged/unflagged challenge contract in
        test_tls_capture_rung.
        """
        bare = ContentExtractor.__new__(ContentExtractor)

        assert bare._retry_unblock_via_alternate_proxy(URL, DOMAIN, None) is None
