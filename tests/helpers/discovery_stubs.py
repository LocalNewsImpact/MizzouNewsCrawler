"""Helpers to keep NewsDiscovery tests hermetic (no real network).

``process_source`` (via ``SourceProcessor.process``) runs every discovery
method — ``rss_feeds``, ``newspaper4k``, ``storysniffer`` and
``proxy_scraping`` — regardless of whether an earlier method succeeded. Tests
that exercise the RSS failure-tracking logic script ``discover_with_rss_feeds``
to control feed outcomes, but must also neutralize the other methods; otherwise
they make real HTTP calls (e.g. newspaper4k fetching ``example.org``), which is
slow and can hang CI.

Section discovery is the sneakiest offender: ``_discover_and_store_sections``
fetches the source homepage via ``NewsDiscovery._fetch_with_ssl_fallback``
(30s default timeout) on EVERY ``process_source`` call, regardless of which
discovery methods a test has patched. Against the fabricated hosts tests use,
that is a guaranteed ~30s connect timeout per call — measured at ~12 of the
~17 minutes of the PostgreSQL CI job. The stubs below make that fetch fail
immediately instead (section discovery catches the error and moves on, same
as a timeout, just without the wait).
"""

from __future__ import annotations

import requests

# Network-reaching discovery methods other than RSS (which tests script
# explicitly). Keep in sync with the methods invoked in
# ``src/crawler/source_processing.py``.
NON_RSS_DISCOVERY_METHODS = (
    "discover_with_newspaper4k",
    "discover_with_storysniffer",
    "discover_with_proxy_scraping",
)

# Low-level fetch helpers that reach the network outside the discovery
# methods above (section discovery fetches the homepage through this).
NETWORK_FETCH_HELPERS = ("_fetch_with_ssl_fallback",)


def _raise_connection_error(*_a, **_k):
    raise requests.exceptions.ConnectionError(
        "network fetch disabled by tests.helpers.discovery_stubs"
    )


def stub_nonrss_discovery(monkeypatch, discovery):
    """Stub every non-RSS discovery method on ``discovery`` to return no articles.

    Leaves ``discover_with_rss_feeds`` untouched so the test can script feed
    outcomes. Also makes the low-level homepage fetch (used by section
    discovery) fail fast instead of timing out against fabricated hosts.
    ``raising=False`` keeps this resilient if a method is renamed.
    """
    for name in NON_RSS_DISCOVERY_METHODS:
        monkeypatch.setattr(discovery, name, lambda *a, **k: [], raising=False)
    for name in NETWORK_FETCH_HELPERS:
        monkeypatch.setattr(discovery, name, _raise_connection_error, raising=False)


def stub_nonrss_discovery_class(monkeypatch):
    """Class-level variant of :func:`stub_nonrss_discovery`.

    Use when the ``NewsDiscovery`` instance is constructed inside the code
    under test (so the test has no handle to pass to the instance-level
    helper). Patches the methods on the class, covering every instance.
    Tests can still override individual methods afterwards — a later
    ``monkeypatch.setattr``/``patch.object`` wins over these stubs.
    """
    from src.crawler.discovery import NewsDiscovery

    for name in NON_RSS_DISCOVERY_METHODS:
        monkeypatch.setattr(NewsDiscovery, name, lambda *a, **k: [], raising=False)
    for name in NETWORK_FETCH_HELPERS:
        monkeypatch.setattr(NewsDiscovery, name, _raise_connection_error, raising=False)
