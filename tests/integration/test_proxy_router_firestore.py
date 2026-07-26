"""Integration tests for proxy_router against a real Firestore instance.

Unlike tests/crawler/test_proxy_router.py (which mocks the client factory
entirely), these exercise genuine Firestore read/write/query semantics --
timestamp comparisons, merge writes, Increment() -- via the Firestore
emulator. Point FIRESTORE_EMULATOR_HOST at a running emulator before running
these, e.g.:

    docker run -d --name firestore-emulator-test -p 8080:8080 \\
        -e FIRESTORE_PROJECT_ID=mizzou-news-crawler-test \\
        mtlynch/firestore-emulator-docker
    FIRESTORE_EMULATOR_HOST=localhost:8080 pytest -m integration \\
        tests/integration/test_proxy_router_firestore.py

The google-cloud-firestore client talks to the emulator automatically once
FIRESTORE_EMULATOR_HOST is set -- no code changes, no credentials needed.
Skipped automatically if that env var isn't set (e.g. plain `pytest -m
integration` in CI without the emulator wired up yet).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.crawler import proxy_router
from src.crawler.proxy_router import RouterProxy, get_proxy_for, report_result

pytestmark = [
    pytest.mark.integration,
    pytest.mark.proxy,
    pytest.mark.skipif(
        not os.getenv("FIRESTORE_EMULATOR_HOST"),
        reason="requires a running Firestore emulator (FIRESTORE_EMULATOR_HOST unset)",
    ),
]


@pytest.fixture(autouse=True)
def _clean_client_cache():
    proxy_router.reset_client_cache()
    yield
    proxy_router.reset_client_cache()


@pytest.fixture
def domain():
    """A unique domain per test so parallel/rerun tests never collide on
    the same emulator document."""
    return f"integration-test-{uuid.uuid4().hex}.example.com"


class TestRealFirestoreRoundTrip:
    def test_no_history_uses_sticky_assignment(self, domain):
        choice = get_proxy_for(domain, service="test")

        assert choice.proxy == proxy_router.assigned_proxy(domain)
        assert choice.method == "http"
        assert choice.all_blocked is False

    def test_success_then_read_reflects_clear_state(self, domain):
        sticky = proxy_router.assigned_proxy(domain)
        report_result(domain, sticky, success=True, service="test")

        choice = get_proxy_for(domain, service="test")

        assert choice.proxy == sticky
        assert choice.all_blocked is False

    def test_failure_backs_off_assigned_proxy_and_fails_over(self, domain):
        sticky = proxy_router.assigned_proxy(domain)
        other = (
            RouterProxy.MIZZOU_SQUID
            if sticky == RouterProxy.HOME_SQUID
            else RouterProxy.HOME_SQUID
        )
        report_result(
            domain,
            sticky,
            success=False,
            reason="403",
            service="test",
        )

        choice = get_proxy_for(domain, service="test")

        assert choice.proxy == other
        assert choice.all_blocked is False
        assert choice.reason.startswith(f"failover from {sticky.value}")

    def test_repeated_failures_double_backoff_and_persist(self, domain):
        for _ in range(3):
            report_result(
                domain,
                RouterProxy.HOME_SQUID,
                success=False,
                reason="captcha",
                service="test",
            )

        client = proxy_router._get_client()
        doc = (
            client.collection(proxy_router._FIRESTORE_COLLECTION)
            .document(proxy_router._doc_id(RouterProxy.HOME_SQUID, domain))
            .get()
        )
        data = doc.to_dict()

        assert data["consecutive_failures"] == 3
        expected_backoff = proxy_router._BACKOFF_BASE_SECONDS * (2**2)
        blocked_until = data["blocked_until"]
        now = datetime.now(timezone.utc)
        assert blocked_until > now + timedelta(seconds=expected_backoff - 30)
        assert blocked_until < now + timedelta(seconds=expected_backoff + 30)

    def test_success_resets_failure_streak_after_failures(self, domain):
        sticky = proxy_router.assigned_proxy(domain)
        report_result(domain, sticky, success=False, reason="timeout")
        report_result(domain, sticky, success=False, reason="timeout")
        report_result(domain, sticky, success=True)

        choice = get_proxy_for(domain, service="test")

        assert choice.proxy == sticky
        assert choice.reason == "sticky assignment, 0 recent failures"

    def test_all_proxies_blocked_flags_all_blocked_and_picks_soonest(self, domain):
        now = datetime.now(timezone.utc)
        client = proxy_router._get_client()
        collection = client.collection(proxy_router._FIRESTORE_COLLECTION)

        collection.document(proxy_router._doc_id(RouterProxy.HOME_SQUID, domain)).set(
            {"blocked_until": now + timedelta(minutes=30)}
        )
        collection.document(proxy_router._doc_id(RouterProxy.MIZZOU_SQUID, domain)).set(
            {"blocked_until": now + timedelta(minutes=5)}
        )

        choice = get_proxy_for(domain, service="test")

        assert choice.all_blocked is True
        assert choice.proxy == RouterProxy.MIZZOU_SQUID

    def test_domains_are_isolated_in_real_firestore(self, domain):
        other_domain = f"other-{domain}"
        report_result(
            domain,
            proxy_router.assigned_proxy(domain),
            success=False,
            reason="403",
        )

        choice = get_proxy_for(other_domain, service="test")

        assert choice.proxy == proxy_router.assigned_proxy(other_domain)
        assert choice.reason.startswith("sticky assignment")
        assert choice.all_blocked is False

    def test_escalation_and_protection_type_persist_across_reads(self, domain):
        sticky = proxy_router.assigned_proxy(domain)
        report_result(
            domain,
            sticky,
            success=False,
            protection_type="perimeterx",
            escalate_to_selenium=True,
            service="test",
        )

        choice = get_proxy_for(domain, service="test")

        assert choice.proxy != sticky  # backed off -> failed over
        client = proxy_router._get_client()
        doc = (
            client.collection(proxy_router._FIRESTORE_COLLECTION)
            .document(proxy_router._doc_id(sticky, domain))
            .get()
        )
        data = doc.to_dict()
        assert data["last_protection_type"] == "perimeterx"
        assert data["preferred_method"] == "selenium"

    def test_client_connects_successfully_against_emulator(self):
        client = proxy_router._get_client()

        assert client is not None
