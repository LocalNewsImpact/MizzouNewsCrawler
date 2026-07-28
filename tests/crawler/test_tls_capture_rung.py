"""tls_client capture rung: triggers, flow, and non-regression.

tls_client is a capture rung between a plain HTTP client and a browser — same
Squid egress, Chrome-like TLS/JA3 fingerprint. It used to run only for domains
pre-flagged ``unblock``; it now runs for any domain still missing fields, so
capture no longer jumps straight from a sub-second HTTP fetch to a Selenium
render measured in minutes.

The risk is not the trigger, it is the exception path. The flagged case
re-raises ProxyChallengeError *specifically to prevent Selenium fallback* and
mark the article for retry. Generalising the rung without scoping that would
make any proxy challenge abort extraction on every domain. These tests pin the
old behaviour for flagged domains and the new, advisory behaviour for the rest.

The harness drives the real ``extract_content`` with only the network-touching
methods stubbed, so ordering and trigger conditions are genuinely exercised.
"""

import pytest

from src.crawler import ContentExtractor, ProxyChallengeError

ARTICLE_BODY = "Council approved the measure on Tuesday evening. " * 6


def _full_result(method: str) -> dict:
    return {
        "title": f"Headline via {method}",
        "author": "Jane Reporter",
        "publish_date": "2026-07-20",
        "content": ARTICLE_BODY,
        # Two+ keys on purpose: _get_missing_fields treats a metadata dict with
        # <=1 key as missing, which would otherwise escalate every case here.
        "metadata": {"extraction_method": method, "meta_description": "a summary"},
    }


def _partial_result(method: str) -> dict:
    """Enough to be 'successful' but leaving the byline missing."""
    return {
        "title": f"Headline via {method}",
        "author": None,
        "publish_date": "2026-07-20",
        "content": ARTICLE_BODY,
        # Two+ keys on purpose: _get_missing_fields treats a metadata dict with
        # <=1 key as missing, which would otherwise escalate every case here.
        "metadata": {"extraction_method": method, "meta_description": "a summary"},
    }


class Harness:
    """Records which capture rungs ran, in order."""

    def __init__(self, extractor, calls):
        self.ex = extractor
        self.calls = calls


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True, raising=False)
    monkeypatch.setattr("src.crawler.NEWSPAPER_AVAILABLE", True, raising=False)

    ex = ContentExtractor.__new__(ContentExtractor)
    calls: list[str] = []

    # Per-extraction state extract_content resets/reads.
    ex._raw_html_by_method = {}
    ex._latest_raw_html = None
    ex._latest_raw_html_method = None
    ex._last_bot_protection_detection = None
    ex._latest_wire_hints = None
    ex._latest_cms_metadata = None
    ex._publish_date_details = None
    ex._selenium_failure_counts = {}
    ex._enforce_selenium_first_domain = None
    ex._disable_selenium_for_diagnostics = False
    ex.use_mcmetadata = True
    ex.mcmetadata_include_other_metadata = False

    # Non-network collaborators. _mcmetadata_enabled consults a module-level
    # availability flag, so leaving it real makes these tests depend on whether
    # mcmetadata imported in the running environment — it did locally and did
    # not in CI, which silently changed which rungs ran.
    ex._mcmetadata_enabled = lambda: True
    ex._get_domain_amp_support = lambda d: False
    ex._should_prioritize_selenium = lambda m: False
    ex._check_rate_limit = lambda d: False
    ex._apply_cms_metadata_fallback = lambda r: None

    # The single HTTP capture. Parsers only run when this produced html,
    # so the rung-ordering assertions below need a capture to exist.
    ex._fetch_page_html = lambda url, metrics=None: "<html>capture</html>"

    # Capture rungs — all stubbed, each recording that it ran.
    def mc(url, html=None, include_other_metadata=None):
        calls.append("mcmetadata")
        return _partial_result("mcmetadata")

    def news(url, html=None):
        calls.append("newspaper4k")
        return _partial_result("newspaper4k")

    def bs4(url, html=None):
        calls.append("beautifulsoup")
        return _partial_result("beautifulsoup")

    def tls(url, html=None, metrics=None, domain=None):
        # `domain` mirrors the production signature: 3a06db3c threaded it in so
        # this rung consults the shared proxy_router. A stub missing it raises
        # TypeError, which the caller's broad `except Exception` swallows -- the
        # rung then silently never runs and every assertion here fails with
        # "'tls_client' is not in list" rather than a signature error.
        calls.append("tls_client")
        return _full_result("unblock_proxy")

    def selenium(url, result, metrics, reason, missing_fields=None):
        calls.append("selenium")
        result["author"] = "Jane Reporter"
        result["extraction_methods"]["author"] = "selenium"
        return True, True

    ex._parse_with_mcmetadata = mc
    ex._parse_with_newspaper = news
    ex._parse_with_beautifulsoup = bs4
    ex._extract_with_unblock_proxy = tls
    ex._run_selenium_extraction = selenium

    return Harness(ex, calls)


def _run(h, extraction_method="http"):
    h.ex._get_domain_extraction_method = lambda d: (extraction_method, None)
    return h.ex.extract_content("https://example.com/news/story.html")


# --------------------------------------------------------------------------
# Triggers
# --------------------------------------------------------------------------


def test_unflagged_domain_now_tries_tls(harness):
    """The change itself: capture no longer jumps straight from HTTP to browser.

    Ordering relative to Selenium is asserted in
    test_tls_failure_still_escalates_to_selenium, where both rungs actually run.
    """
    _run(harness)

    assert "tls_client" in harness.calls
    assert harness.calls.index("tls_client") > harness.calls.index("beautifulsoup")


def test_flagged_unblock_domain_still_tries_tls(harness):
    """Pre-existing behaviour for flagged domains is untouched."""
    _run(harness, extraction_method="unblock")

    assert "tls_client" in harness.calls


def test_tls_is_skipped_when_nothing_is_missing(harness):
    """No gap, no extra capture — this must not add requests gratuitously."""
    harness.ex._parse_with_mcmetadata = lambda url, html=None, **kw: (
        harness.calls.append("mcmetadata") or _full_result("mcmetadata")
    )

    _run(harness)

    assert "tls_client" not in harness.calls
    assert "selenium" not in harness.calls


def test_kill_switch_restores_flagged_only_behaviour(harness, monkeypatch):
    monkeypatch.setenv("TLS_CAPTURE_FALLBACK", "false")

    _run(harness)
    assert "tls_client" not in harness.calls

    harness.calls.clear()
    _run(harness, extraction_method="unblock")
    assert "tls_client" in harness.calls, "flagged domains must be unaffected"


# --------------------------------------------------------------------------
# Flow
# --------------------------------------------------------------------------


def test_successful_tls_capture_prevents_the_selenium_escalation(harness):
    """The saving: a seconds-long rung stops a minutes-long one."""
    _run(harness)

    assert "tls_client" in harness.calls
    assert "selenium" not in harness.calls


def test_tls_failure_still_escalates_to_selenium(harness):
    """A failed rung must not strand the article."""
    harness.ex._extract_with_unblock_proxy = (
        lambda url, html=None, metrics=None, domain=None: (
            harness.calls.append("tls_client") or {}
        )
    )

    _run(harness)

    assert harness.calls.index("tls_client") < harness.calls.index("selenium")


# --------------------------------------------------------------------------
# Regression: the ProxyChallengeError path
# --------------------------------------------------------------------------


def test_challenge_on_flagged_domain_is_still_terminal(harness):
    """Flagged domains mark the article for retry and skip Selenium — as before."""

    def challenged(url, html=None, metrics=None, domain=None):
        harness.calls.append("tls_client")
        raise ProxyChallengeError("blocked")

    harness.ex._extract_with_unblock_proxy = challenged

    with pytest.raises(ProxyChallengeError):
        _run(harness, extraction_method="unblock")

    assert "selenium" not in harness.calls


def test_challenge_on_unflagged_domain_must_not_abort_extraction(harness):
    """The regression this change could have introduced.

    A refused disguise says nothing about whether a real browser would be
    refused, so Selenium must still get its turn rather than the article
    failing outright.
    """

    def challenged(url, html=None, metrics=None, domain=None):
        harness.calls.append("tls_client")
        raise ProxyChallengeError("blocked")

    harness.ex._extract_with_unblock_proxy = challenged

    result = _run(harness)  # must not raise

    assert "selenium" in harness.calls
    assert result["author"] == "Jane Reporter"


def test_unexpected_error_in_the_rung_is_swallowed(harness):
    """A broken rung degrades to the previous escalation path."""

    def boom(url, html=None, metrics=None, domain=None):
        harness.calls.append("tls_client")
        raise RuntimeError("tls_client exploded")

    harness.ex._extract_with_unblock_proxy = boom

    result = _run(harness)

    assert "selenium" in harness.calls
    assert result["content"] == ARTICLE_BODY


def test_selenium_first_failure_skips_the_rung_quietly_when_unflagged(harness):
    """Flagged domains raise here; unflagged ones just skip the rung."""
    harness.ex._should_prioritize_selenium = lambda m: True

    def failed_selenium_first(url, result, metrics, reason, missing_fields=None):
        harness.calls.append("selenium_first")
        return True, False

    harness.ex._run_selenium_extraction = failed_selenium_first
    harness.ex.get_persistent_driver = lambda: None

    _run(harness)  # must not raise

    assert "tls_client" not in harness.calls


def test_selenium_first_failure_on_flagged_domain_still_raises(harness):
    harness.ex._should_prioritize_selenium = lambda m: True

    def failed_selenium_first(url, result, metrics, reason, missing_fields=None):
        harness.calls.append("selenium_first")
        return True, False

    harness.ex._run_selenium_extraction = failed_selenium_first
    harness.ex.get_persistent_driver = lambda: None

    with pytest.raises(ProxyChallengeError):
        _run(harness, extraction_method="unblock")
