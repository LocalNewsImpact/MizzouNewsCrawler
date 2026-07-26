"""Unit tests for the shared Firestore-backed proxy router.

Mirrors the mocking pattern in tests/utils/test_raw_html_archive.py: the
client factory is patched, never real Firestore. Integration tests that
exercise a real (emulated) Firestore instance live in
tests/integration/test_proxy_router_firestore.py.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from src.crawler import proxy_router
from src.crawler.proxy_router import (
    ProxyChoice,
    RouterProxy,
    get_proxy_for,
    report_result,
    reset_client_cache,
)

pytestmark = pytest.mark.proxy


@pytest.fixture(autouse=True)
def _clean_client_cache():
    reset_client_cache()
    yield
    reset_client_cache()


def _mock_doc(exists: bool, data: dict | None = None):
    doc = Mock()
    doc.exists = exists
    doc.to_dict.return_value = data or {}
    return doc


@pytest.fixture
def mock_firestore(monkeypatch):
    """Patch the module's client factory. Returns (client, docs_by_id) where
    docs_by_id maps a "{proxy}__{domain}" doc id -> the Mock doc .get()
    should return for it. Missing ids default to a non-existent doc.
    """
    docs_by_id: dict = {}
    doc_refs_by_id: dict = {}

    def _document(doc_id):
        # Memoized: repeated .document(same_id) calls -- one from the code
        # under test, one from a test's own assertion -- must return the
        # SAME Mock so .set() calls made by the former are visible to the
        # latter. A fresh Mock() per call would silently desync them.
        if doc_id not in doc_refs_by_id:
            doc_ref = Mock()
            doc_ref.get.return_value = docs_by_id.get(doc_id, _mock_doc(False))
            doc_refs_by_id[doc_id] = doc_ref
        return doc_refs_by_id[doc_id]

    collection = Mock()
    collection.document.side_effect = _document

    client = Mock()
    client.collection.return_value = collection

    monkeypatch.setattr(proxy_router, "_get_client", lambda: client)
    return client, docs_by_id


def _doc_id(proxy, domain):
    return proxy_router._doc_id(proxy, domain)


# Domains with known md5-sticky assignments (see assigned_proxy):
#   example.com / js-heavy.com / blocked.com / beta.com -> HOME_SQUID
#   wsj.com / unrelated.com / alpha.com                 -> MIZZOU_SQUID
_HOME_DOMAIN = "example.com"
_MIZZOU_DOMAIN = "alpha.com"


class TestLoadBalancing:
    def test_assignment_is_stable_and_covers_both_proxies(self):
        domains = [f"paper-{i}.example.com" for i in range(40)]
        first_pass = [proxy_router.assigned_proxy(d) for d in domains]
        second_pass = [proxy_router.assigned_proxy(d) for d in domains]

        assert first_pass == second_pass  # sticky
        assert set(first_pass) == {
            RouterProxy.HOME_SQUID,
            RouterProxy.MIZZOU_SQUID,
        }  # both proxies actually take load

    def test_assignment_is_case_insensitive(self):
        assert proxy_router.assigned_proxy("Example.COM") == (
            proxy_router.assigned_proxy("example.com")
        )


class TestGetProxyFor:
    def test_no_history_uses_sticky_assignment(self, mock_firestore):
        home_choice = get_proxy_for(_HOME_DOMAIN)
        mizzou_choice = get_proxy_for(_MIZZOU_DOMAIN)

        assert home_choice.proxy == RouterProxy.HOME_SQUID
        assert mizzou_choice.proxy == RouterProxy.MIZZOU_SQUID
        assert home_choice.method == "http"
        assert home_choice.all_blocked is False

    def test_blocked_assigned_proxy_fails_over_to_other(self, mock_firestore):
        _, docs = mock_firestore
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        docs[_doc_id(RouterProxy.HOME_SQUID, _HOME_DOMAIN)] = _mock_doc(
            True, {"blocked_until": future, "consecutive_failures": 3}
        )

        choice = get_proxy_for(_HOME_DOMAIN)

        assert choice.proxy == RouterProxy.MIZZOU_SQUID
        assert choice.all_blocked is False
        assert choice.reason.startswith("failover from home_squid")

    def test_all_proxies_blocked_returns_soonest_and_flags_it(self, mock_firestore):
        _, docs = mock_firestore
        now = datetime.now(timezone.utc)
        docs[_doc_id(RouterProxy.HOME_SQUID, "wsj.com")] = _mock_doc(
            True, {"blocked_until": now + timedelta(minutes=30)}
        )
        docs[_doc_id(RouterProxy.MIZZOU_SQUID, "wsj.com")] = _mock_doc(
            True, {"blocked_until": now + timedelta(minutes=5)}
        )

        choice = get_proxy_for("wsj.com")

        assert choice.all_blocked is True
        assert choice.proxy == RouterProxy.MIZZOU_SQUID  # soonest to free up

    def test_sticky_wins_even_with_more_failures_while_unblocked(self, mock_firestore):
        """Failure count alone must not bounce a domain between egress IPs;
        only an actual backoff (blocked_until) triggers failover."""
        _, docs = mock_firestore
        docs[_doc_id(RouterProxy.HOME_SQUID, _HOME_DOMAIN)] = _mock_doc(
            True, {"consecutive_failures": 2}
        )
        docs[_doc_id(RouterProxy.MIZZOU_SQUID, _HOME_DOMAIN)] = _mock_doc(
            True, {"consecutive_failures": 0}
        )

        choice = get_proxy_for(_HOME_DOMAIN)

        assert choice.proxy == RouterProxy.HOME_SQUID
        assert choice.reason.startswith("sticky assignment")

    def test_honors_stored_preferred_method(self, mock_firestore):
        _, docs = mock_firestore
        docs[_doc_id(RouterProxy.HOME_SQUID, "js-heavy.com")] = _mock_doc(
            True, {"preferred_method": "selenium"}
        )

        choice = get_proxy_for("js-heavy.com")

        assert choice.method == "selenium"

    def test_domains_are_isolated(self, mock_firestore):
        """A block on one domain must not leak into routing for another."""
        _, docs = mock_firestore
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        docs[_doc_id(RouterProxy.HOME_SQUID, "blocked.com")] = _mock_doc(
            True, {"blocked_until": future}
        )

        choice = get_proxy_for("unrelated.com")

        assert choice.proxy == proxy_router.assigned_proxy("unrelated.com")
        assert choice.reason.startswith("sticky assignment")
        assert choice.all_blocked is False

    def test_no_client_still_load_balances(self, monkeypatch):
        """A Firestore outage costs failover, never the load balancing."""
        monkeypatch.setattr(proxy_router, "_get_client", lambda: None)

        assert get_proxy_for(_HOME_DOMAIN) == ProxyChoice(
            proxy=RouterProxy.HOME_SQUID,
            method="http",
            reason=proxy_router._FALLBACK_CHOICE_REASON,
        )
        assert get_proxy_for(_MIZZOU_DOMAIN).proxy == RouterProxy.MIZZOU_SQUID

    def test_read_exception_falls_back_to_sticky(self, mock_firestore):
        client, _ = mock_firestore
        client.collection.side_effect = RuntimeError("firestore on fire")

        choice = get_proxy_for(_HOME_DOMAIN)

        assert choice.proxy == RouterProxy.HOME_SQUID
        assert choice.reason == proxy_router._FALLBACK_CHOICE_REASON


class TestReportResult:
    def test_success_resets_failure_state(self, mock_firestore):
        client, _ = mock_firestore
        collection = client.collection.return_value

        report_result(
            "example.com", RouterProxy.HOME_SQUID, success=True, service="test"
        )

        doc_ref = collection.document(_doc_id(RouterProxy.HOME_SQUID, "example.com"))
        payload = doc_ref.set.call_args[0][0]
        assert payload["consecutive_failures"] == 0
        assert payload["blocked_until"] is None
        assert payload["updated_by"] == "test"

    def test_first_failure_uses_base_backoff(self, mock_firestore):
        client, docs = mock_firestore
        docs[_doc_id(RouterProxy.HOME_SQUID, "example.com")] = _mock_doc(False)

        before = datetime.now(timezone.utc)
        report_result(
            "example.com", RouterProxy.HOME_SQUID, success=False, reason="403"
        )
        after = datetime.now(timezone.utc)

        collection = client.collection.return_value
        doc_ref = collection.document(_doc_id(RouterProxy.HOME_SQUID, "example.com"))
        payload = doc_ref.set.call_args[0][0]

        assert payload["consecutive_failures"] == 1
        assert payload["last_failure_reason"] == "403"
        base = proxy_router._BACKOFF_BASE_SECONDS
        expected_min = before + timedelta(seconds=base)
        expected_max = after + timedelta(seconds=base)
        assert expected_min <= payload["blocked_until"] <= expected_max

    def test_backoff_doubles_and_caps_at_max(self, mock_firestore):
        client, docs = mock_firestore
        doc_id = _doc_id(RouterProxy.HOME_SQUID, "example.com")
        # Simulate 10 prior failures -- base*2^9 would blow past the cap.
        docs[doc_id] = _mock_doc(True, {"consecutive_failures": 10})

        report_result("example.com", RouterProxy.HOME_SQUID, success=False)

        doc_ref = client.collection.return_value.document(doc_id)
        payload = doc_ref.set.call_args[0][0]
        delta = (payload["blocked_until"] - datetime.now(timezone.utc)).total_seconds()
        # small clock-skew tolerance
        assert delta <= proxy_router._BACKOFF_MAX_SECONDS + 5

    def test_protection_type_and_escalation_are_recorded(self, mock_firestore):
        client, _ = mock_firestore

        report_result(
            "wsj.com",
            RouterProxy.HOME_SQUID,
            success=False,
            protection_type="perimeterx",
            escalate_to_selenium=True,
        )

        collection = client.collection.return_value
        doc_ref = collection.document(_doc_id(RouterProxy.HOME_SQUID, "wsj.com"))
        payload = doc_ref.set.call_args[0][0]
        assert payload["last_protection_type"] == "perimeterx"
        assert payload["preferred_method"] == "selenium"

    def test_no_client_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(proxy_router, "_get_client", lambda: None)

        # must not raise
        report_result("example.com", RouterProxy.HOME_SQUID, success=True)

    def test_write_exception_does_not_raise(self, mock_firestore):
        client, _ = mock_firestore
        client.collection.return_value.document.side_effect = RuntimeError("boom")

        # must not raise
        report_result("example.com", RouterProxy.HOME_SQUID, success=False)


class TestClientCaching:
    def test_client_init_failure_is_cached(self):
        """A credential-less environment (local dev, CI) should log once,
        not once per call. google-cloud-firestore is a hard dependency
        (requirements-base.txt) so this patches the real Client
        constructor directly rather than stubbing the module -- a
        sys.modules stub would collide with the module already being
        genuinely imported by other tests in this file.
        """
        with patch(
            "google.cloud.firestore.Client",
            side_effect=RuntimeError("no credentials"),
        ) as mock_ctor:
            assert proxy_router._get_client() is None
            assert proxy_router._get_client() is None

        assert mock_ctor.call_count == 1

    def test_reset_client_cache_clears_failure_flag(self):
        proxy_router._client_failed = True
        reset_client_cache()
        assert proxy_router._client_failed is False
