"""The HTTP status a browser navigation got, which Selenium does not tell you.

`driver.get()` returns None. A page that answered 404, 403 or 410 renders like
any other, so the browser path has no idea what status it received: on
2026-09-18 every one of 30 Port Townsend Leader links carried
`candidate_links.http_status = NULL`, and a fetch that landed on a fallback page
was stored as an article because nothing contradicted it.

Chrome does report it, over the DevTools Protocol, and the driver is already
built to collect those events -- `goog:loggingPrefs {"performance": "ALL"}` is
set at creation and `driver.get_log("performance")` is already called in the
diagnostic path and written to /tmp. This reads the same log for the one fact
that decides whether the page is worth keeping.

Only the MAIN DOCUMENT counts. A page fires `Network.responseReceived` for every
image, script and beacon it loads, and a 404 on a tracking pixel says nothing
about the article. Chrome labels the document request `type: "Document"`, and
the last one wins so that a redirect chain reports where it ended.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Chrome's resource type for the navigation itself, as opposed to the assets
#: the page then pulls in.
DOCUMENT_TYPE = "Document"

#: The CDP event carrying a status code.
RESPONSE_EVENT = "Network.responseReceived"


def _events(entries: list[dict]) -> Any:
    """Yield the decoded CDP messages from a performance log."""
    for entry in entries or []:
        raw = entry.get("message")
        if not raw:
            continue
        try:
            message = json.loads(raw).get("message") or {}
        except (ValueError, TypeError):
            continue
        if message.get("method") == RESPONSE_EVENT:
            yield message.get("params") or {}


def document_status(entries: list[dict]) -> tuple[int | None, str | None]:
    """Return (status, final_url) for the navigation, or (None, None).

    The LAST document response wins. A 301 to the article reports 200 and the
    article's URL, which is what a caller wants to record -- and a 301 to a
    fallback page reports that page, which is what a caller needs to refuse.
    """
    status: int | None = None
    final_url: str | None = None
    for params in _events(entries):
        response = params.get("response") or {}
        if params.get("type") != DOCUMENT_TYPE:
            continue
        code = response.get("status")
        if not isinstance(code, int):
            continue
        status, final_url = code, response.get("url")
    return status, final_url


def network_responses(entries: list[dict]) -> list[tuple[int, str]]:
    """Every (status, url) the browser received, in order.

    `document_status` keeps only the navigation. A login is confirmed by a
    different request -- the vendor's auth call, which is an XHR -- so the
    entry-time validation reads all of them and shows which one answered. On
    www.yakimaherald.com that is
    `prod-amg-proxy-connext.azurewebsites.net/api/user -> 200`.
    """
    out: list[tuple[int, str]] = []
    for params in _events(entries):
        response = params.get("response") or {}
        code = response.get("status")
        url = response.get("url")
        if isinstance(code, int) and url:
            out.append((code, str(url)))
    return out


def read_navigation_status(driver) -> tuple[int | None, str | None]:
    """The status and final URL of the page currently loaded, best effort.

    Never raises. A driver without performance logging, or a Chrome that did not
    emit the event, yields (None, None) -- the same answer the browser path gave
    before this existed, so a caller is no worse off than it was.

    Reading the log CONSUMES it, which is why this is called once per
    navigation: a second call returns only what has accumulated since.
    """
    try:
        entries = driver.get_log("performance")
    except Exception as exc:  # noqa: BLE001 - any driver may refuse the log
        logger.debug("no performance log available: %s", exc)
        return None, None
    try:
        return document_status(entries)
    except Exception as exc:  # noqa: BLE001 - malformed log is not a failure
        logger.debug("could not read a document status: %s", exc)
        return None, None
