"""What a row owed rework actually needs: a fresh capture, or a fresh reading.

Rework is one queue with two dispositions, and which one a row gets is decided by
what is in the capture rather than by which rule condemned it.

Reparsing a paywall stub does nothing. The stored body IS the wall, so re-running
a corrected classifier over it re-derives the same verdict and reports success.
Refetching a good capture is the opposite waste: it spends a publisher request to
collect bytes we already hold, and on a credentialed host it spends a login too.
`articles.raw` is the capture as taken and is never edited after capture, so the
question is answerable from the row.

The signals this reads exist as of 2026-09-20 and did not before:
`authenticated_session` says whether a fetch ran as a subscriber, and it is the
only way to know that a credentialed host's capture is trustworthy -- body length
proves nothing on a metered site. NULL is a third answer and is treated as one: a
capture taken before that field existed is UNKNOWN, not anonymous, and unknown on
a credentialed host means refetch.
"""

from __future__ import annotations

from typing import NamedTuple

from src.utils.boilerplate import PAYWALL, classify_furniture, document_is_furniture

#: Below this a body cannot be reparsed into anything, whatever it says.
MIN_CAPTURE_CHARS = 400

#: Hosts that must never be fetched again, for reasons outside the pipeline.
#: `lynnwoodtoday.com` left publisher control and serves gambling spam;
#: `mltnews.com` does not resolve. A rework plan that queues either produces a
#: failure that looks like a bug.
NEVER_REFETCH: frozenset[str] = frozenset({"lynnwoodtoday.com", "mltnews.com"})

REPARSE = "reparse"
REFETCH = "refetch"
HOLD = "hold"
LEAVE = "leave"


class Disposition(NamedTuple):
    """What to do with one row, and the reason, which is the auditable part."""

    action: str
    reason: str

    @property
    def touches_the_publisher(self) -> bool:
        return self.action == REFETCH


def _bare(host: str | None) -> str:
    h = (host or "").lower().strip()
    return h[4:] if h.startswith("www.") else h


def decide(
    *,
    status: str | None = None,
    raw: str | None,
    host: str | None,
    requires_login: bool,
    has_credentials: bool,
    authenticated_session: str | bool | None,
    min_prose_chars: int,
) -> Disposition:
    """Which kind of rework this row owes.

    Order is precedence. A host we must not fetch is decided before anything
    about the capture, because no capture question can change the answer.
    """
    if _bare(host) in NEVER_REFETCH:
        return Disposition(HOLD, f"{host} must never be fetched again")

    # A credentialed host with no credentials cannot be refetched successfully.
    # Queueing it produces a failure by construction, so it is held with the
    # reason on the row instead -- chinookobserver and wenatcheeworld are here,
    # their subscriber credentials having been confirmed dead.
    if requires_login and not has_credentials:
        return Disposition(HOLD, f"{host} needs a login and has no credentials")

    # The wall is checked BEFORE the length floor, because a wall stub is usually
    # short and "stored capture is a wall" is the more useful reason than "no
    # usable capture" -- both refetch, but only one tells an operator that the
    # login is the thing to look at.
    # A wall is recorded in the STATUS, not only in the body. When a row is filed
    # `paywall` the body is emptied on purpose -- "a refused capture must never be
    # readable as a body" -- so `raw` is length 0 and a body-only test cannot see
    # the wall it is looking for. All six chinookobserver rows and the one
    # wenatcheeworld row are exactly this: status `paywall`, raw empty.
    walled = (status or "").strip().lower() == PAYWALL
    verdict = classify_furniture(raw) if raw else None
    if walled or (verdict is not None and verdict.kind == PAYWALL):
        # The capture IS the wall, so reparsing re-derives it. But refetching only
        # helps if we can get PAST the wall, and a host with no credentials cannot
        # be: chinookobserver and wenatcheeworld both carry `requires_login=false`
        # because the login was switched off when their subscriber credential was
        # confirmed dead, so they look like ordinary anonymous hosts and would be
        # refetched forever, collecting the same wall each time.
        #
        # Held rather than refetched even though a SOFT meter might yield to a
        # fresh anonymous fetch. That is the deliberate trade: holding is
        # reversible and reports its reason, while refetching a wall we cannot
        # pass is silent, endless, and spends a publisher request every time.
        if not has_credentials:
            return Disposition(
                HOLD,
                f"stored capture is a wall and {host} has no login to get past it",
            )
        evidence = verdict.evidence if verdict is not None else "filed as a wall"
        return Disposition(REFETCH, f"stored capture is a wall ({evidence})")

    if not raw or len(raw.strip()) < MIN_CAPTURE_CHARS:
        return Disposition(REFETCH, "no usable capture to reparse")

    # `authenticated_session` arrives from JSON, so `true` may be a string.
    authed = authenticated_session in (True, "true")
    if requires_login and not authed:
        known = authenticated_session is not None
        return Disposition(
            REFETCH,
            (
                "credentialed host, capture was not a subscriber fetch"
                if known
                else "credentialed host, capture predates the subscriber marker"
            ),
        )

    if document_is_furniture(raw, min_prose_chars) is None:
        return Disposition(REPARSE, "capture is a story; the verdict was wrong")

    return Disposition(LEAVE, "still furniture on a good capture")
