"""Shared, real-time proxy/domain routing backed by Firestore.

Tracks per-(proxy, domain) health across every service that touches the
web -- today that's this crawler package and the isolated `newsgrabs`
screenshot pipeline (a separate GKE Job/pod, no shared runtime). Firestore
is the *only* thing shared between those two services; each still runs in
its own process, this module is just a client against common state.

This is layered ABOVE proxy_config.py, not a replacement for it:
proxy_config.py builds the actual proxy URL/credentials for a given
provider; this module decides *which* proxy and extraction method a
caller should use for a specific domain right now, based on live health,
and records the outcome so the next caller (in this pod or any other)
benefits from what was just learned.

Backoff math mirrors _handle_captcha_backoff() in src/crawler/__init__.py
so a domain's cooldown behaves consistently regardless of which system
tripped it.

Every failure path is soft, same contract as raw_html_archive.py: routing
is an optimization, not a dependency, so a Firestore outage must never
block or crash a capture/extraction attempt. get_proxy_for() falls back to
a static default and report_result() silently no-ops.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

_FIRESTORE_COLLECTION = "proxy_domain_status"

_BACKOFF_BASE_SECONDS = int(os.getenv("PROXY_ROUTER_BACKOFF_BASE", "600"))
_BACKOFF_MAX_SECONDS = int(os.getenv("PROXY_ROUTER_BACKOFF_MAX", "5400"))

_client = None
_client_failed = False
_lock = threading.Lock()


class RouterProxy(Enum):
    """Proxies the router is allowed to choose between.

    Deliberately small and static -- unlike proxy_config.py's
    ProxyProvider (which enumerates paid third-party services that may or
    may not be configured), this is exactly what physically exists today:
    two Squid boxes. Extend this enum, not around it, if a new proxy comes
    online.

    No DIRECT option: every caller of this router (the crawler today,
    the isolated newsgrabs pipeline later) must always egress through a
    proxy -- direct connections are never a valid routing decision here.
    """

    HOME_SQUID = "home_squid"  # SQUID_PROXY_URL (t9880447.eero.online)
    MIZZOU_SQUID = "mizzou_squid"  # MIZZOU_SQUID_PROXY_URL (10.128.0.46 tunnel VM)


# The pool the load balancer spreads domains across. Order matters only
# for index stability of the hash assignment below -- append new proxies,
# never reorder, or every domain's sticky assignment shifts at once.
_PROXY_POOL = [
    RouterProxy.HOME_SQUID,
    RouterProxy.MIZZOU_SQUID,
]

# Kept for callers/tests that referenced the old name.
_DEFAULT_PREFERENCE = _PROXY_POOL

# Returned by get_proxy_for() when Firestore itself is unreachable. The
# hash-sticky assignment still applies (it needs no health data), so a
# Firestore outage costs only the health-based failover, not the load
# balancing.
_FALLBACK_CHOICE_REASON = "firestore unavailable, using sticky assignment"


def assigned_proxy(domain: str) -> RouterProxy:
    """The domain's sticky home in the pool: a stable md5-based hash.

    This IS the load balancer: domains split ~evenly across the pool, and
    a given domain always prefers the same proxy -- so each publisher sees
    one consistent egress IP (which also reads as normal traffic to bot
    defenses) while total load spreads across both Squids. Health-based
    failover in get_proxy_for() overrides this only while the assigned
    proxy is backed off for that domain.

    md5 rather than hash(): Python salts hash() per process, and this
    assignment must agree across every pod and service.
    """
    digest = hashlib.md5(domain.lower().encode("utf-8")).digest()
    return _PROXY_POOL[digest[0] % len(_PROXY_POOL)]


@dataclass
class ProxyChoice:
    """A routing decision returned by get_proxy_for()."""

    proxy: RouterProxy
    method: str  # "http" or "selenium" -- mirrors sources.extraction_method
    reason: str  # why this was picked, for logging
    # True if every proxy is currently backed off for this domain.
    all_blocked: bool = False


def _get_client():
    """Return a cached Firestore client, or None if unavailable.

    A failed init is remembered so environments without credentials (local
    dev, CI, tests) log once instead of on every call.
    """
    global _client, _client_failed

    if _client is not None or _client_failed:
        return _client

    with _lock:
        if _client is not None or _client_failed:
            return _client
        try:
            from google.cloud import firestore

            _client = firestore.Client()
        except Exception as exc:
            _client_failed = True
            logger.warning(
                "proxy_router: Firestore unavailable -- falling back to static "
                "proxy defaults (%s: %s)",
                type(exc).__name__,
                exc,
            )
    return _client


def reset_client_cache() -> None:
    """Clear the cached client/failure flag. Test isolation only."""
    global _client, _client_failed
    with _lock:
        _client = None
        _client_failed = False


def _doc_id(proxy: RouterProxy, domain: str) -> str:
    return f"{proxy.value}__{domain}"


def get_proxy_for(domain: str, service: str = "unknown") -> ProxyChoice:
    """Return the best available (proxy, method) for `domain` right now.

    Load-balancing policy: the domain's hash-sticky assigned_proxy() wins
    whenever it is healthy; if it's backed off for this domain, fail over
    to the healthiest other proxy in the pool; if everything is backed
    off, return whichever frees up soonest with all_blocked=True.

    `service` is an attribution label ("newscrawler" / "newsgrabs") -- it's
    written into telemetry for debugging only, it never affects the
    decision itself.
    """
    sticky = assigned_proxy(domain)

    client = _get_client()
    if client is None:
        # No health data, but the sticky assignment needs none -- load
        # balancing survives a Firestore outage; only failover is lost.
        return ProxyChoice(
            proxy=sticky,
            method="http",
            reason=_FALLBACK_CHOICE_REASON,
        )

    now = datetime.now(timezone.utc)

    try:
        collection = client.collection(_FIRESTORE_COLLECTION)
        candidates = []
        for proxy in _PROXY_POOL:
            doc = collection.document(_doc_id(proxy, domain)).get()
            data = doc.to_dict() if doc.exists else {}
            blocked_until = data.get("blocked_until")
            candidates.append(
                {
                    "proxy": proxy,
                    "blocked": bool(blocked_until and blocked_until > now),
                    "blocked_until": blocked_until,
                    "consecutive_failures": data.get("consecutive_failures", 0),
                    "preferred_method": data.get("preferred_method", "http"),
                }
            )
    except Exception as exc:
        logger.warning(
            "proxy_router: read failed for %s, using sticky assignment (%s: %s)",
            domain,
            type(exc).__name__,
            exc,
        )
        return ProxyChoice(
            proxy=sticky,
            method="http",
            reason=_FALLBACK_CHOICE_REASON,
        )

    available = [c for c in candidates if not c["blocked"]]
    if available:
        for candidate in available:
            if candidate["proxy"] is sticky:
                return ProxyChoice(
                    proxy=sticky,
                    method=candidate["preferred_method"],
                    reason=(
                        "sticky assignment, "
                        f"{candidate['consecutive_failures']} recent failures"
                    ),
                )
        # Assigned proxy is backed off for this domain: fail over to the
        # healthiest remaining proxy.
        best = min(available, key=lambda c: c["consecutive_failures"])
        return ProxyChoice(
            proxy=best["proxy"],
            method=best["preferred_method"],
            reason=(
                f"failover from {sticky.value}, "
                f"{best['consecutive_failures']} recent failures"
            ),
        )

    # Every proxy is currently backed off for this domain. Return whichever
    # frees up soonest, but flag it -- callers should generally skip the
    # domain this round rather than burn another attempt into a wall.
    soonest = min(candidates, key=lambda c: c["blocked_until"] or now)
    return ProxyChoice(
        proxy=soonest["proxy"],
        method=soonest["preferred_method"],
        reason="all proxies currently backed off for this domain",
        all_blocked=True,
    )


def report_result(
    domain: str,
    proxy: RouterProxy,
    success: bool,
    reason: Optional[str] = None,
    protection_type: Optional[str] = None,
    escalate_to_selenium: bool = False,
    service: str = "unknown",
) -> None:
    """Record the outcome of an attempt so future get_proxy_for() calls
    reflect it. Call this after every capture/extraction attempt, from
    either service. Never raises -- a Firestore outage means this
    optimization silently stops updating, not that the caller's real
    work (the capture/extraction itself) fails too.

    Args:
        domain: bare domain the attempt targeted (not the full URL).
        proxy: which RouterProxy the attempt actually used.
        success: whether the attempt succeeded.
        reason: short failure reason ("403", "captcha", "timeout", ...) --
            reuses the vocabulary already in extraction_telemetry_v2.
        protection_type: "perimeterx" / "cloudflare" / "datadome" / "akamai"
            if detected, else None.
        escalate_to_selenium: set True if this failure indicates the
            domain needs a full browser next time (e.g. a JS challenge),
            not just a different proxy.
        service: attribution label, "newscrawler" or "newsgrabs".
    """
    client = _get_client()
    if client is None:
        return

    try:
        doc_ref = client.collection(_FIRESTORE_COLLECTION).document(
            _doc_id(proxy, domain)
        )
        now = datetime.now(timezone.utc)

        if success:
            from google.cloud.firestore import Increment

            doc_ref.set(
                {
                    "proxy_id": proxy.value,
                    "domain": domain,
                    "last_success_at": now,
                    "consecutive_failures": 0,
                    "consecutive_successes": Increment(1),
                    "blocked_until": None,
                    "updated_at": now,
                    "updated_by": service,
                },
                merge=True,
            )
            return

        doc = doc_ref.get()
        prior_failures = (
            (doc.to_dict() or {}).get("consecutive_failures", 0) if doc.exists else 0
        )
        consecutive_failures = prior_failures + 1
        backoff_seconds = min(
            _BACKOFF_BASE_SECONDS * (2 ** (consecutive_failures - 1)),
            _BACKOFF_MAX_SECONDS,
        )

        update = {
            "proxy_id": proxy.value,
            "domain": domain,
            "last_failure_at": now,
            "consecutive_failures": consecutive_failures,
            "consecutive_successes": 0,
            "blocked_until": now + timedelta(seconds=backoff_seconds),
            "last_failure_reason": reason or "unknown",
            "updated_at": now,
            "updated_by": service,
        }
        if protection_type:
            update["last_protection_type"] = protection_type
        if escalate_to_selenium:
            update["preferred_method"] = "selenium"

        doc_ref.set(update, merge=True)
        logger.warning(
            "🚫 proxy_router: %s backed off for %s (%d failures, %ds) -- reported by %s",
            proxy.value,
            domain,
            consecutive_failures,
            backoff_seconds,
            service,
        )
    except Exception as exc:
        logger.warning(
            "proxy_router: report_result failed for %s/%s (%s: %s)",
            proxy.value,
            domain,
            type(exc).__name__,
            exc,
        )
