"""Helpers to keep NewsDiscovery tests hermetic (no real network).

``process_source`` (via ``SourceProcessor.process``) runs every discovery
method — ``rss_feeds``, ``newspaper4k``, ``storysniffer`` and
``proxy_scraping`` — regardless of whether an earlier method succeeded. Tests
that exercise the RSS failure-tracking logic script ``discover_with_rss_feeds``
to control feed outcomes, but must also neutralize the other methods; otherwise
they make real HTTP calls (e.g. newspaper4k fetching ``example.org``), which is
slow and can hang CI.
"""

from __future__ import annotations

# Network-reaching discovery methods other than RSS (which tests script
# explicitly). Keep in sync with the methods invoked in
# ``src/crawler/source_processing.py``.
NON_RSS_DISCOVERY_METHODS = (
    "discover_with_newspaper4k",
    "discover_with_storysniffer",
    "discover_with_proxy_scraping",
)


def stub_nonrss_discovery(monkeypatch, discovery):
    """Stub every non-RSS discovery method on ``discovery`` to return no articles.

    Leaves ``discover_with_rss_feeds`` untouched so the test can script feed
    outcomes. ``raising=False`` keeps this resilient if a method is renamed.
    """
    for name in NON_RSS_DISCOVERY_METHODS:
        monkeypatch.setattr(discovery, name, lambda *a, **k: [], raising=False)
