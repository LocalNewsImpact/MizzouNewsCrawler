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
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

#: Chrome's resource type for the navigation itself, as opposed to the assets
#: the page then pulls in.
DOCUMENT_TYPE = "Document"

#: The CDP event carrying a status code.
RESPONSE_EVENT = "Network.responseReceived"

#: The CDP event carrying a request -- and, for a redirect, the response that
#: caused it. Chrome does NOT emit `responseReceived` for a 3xx: the redirect's
#: status arrives as `redirectResponse` inside the NEXT request event. So a
#: reader of responses alone is blind to every redirect, which is how
#: `POST /account/etype-login -> 302 -> /account/etype-auth` -- the one signal
#: that proves an eType login worked -- was invisible while the login was
#: reported as succeeding.
REQUEST_EVENT = "Network.requestWillBeSent"

#: Form fields worth reading out of a request body, and the ONLY ones ever read.
#:
#: A login POST carries the subscriber's password. An allowlist is the whole
#: safety property here: never the raw body, never a key not named below. On
#: 2026-09-20 a log level of DEBUG printed a subscriber password into a pod log,
#: and that was with nobody deliberately reading request bodies at all.
#:
#: `realm` is why this exists. Auth0's classic Universal Login posts it to
#: `/usernamepassword/login`, and it is the parameter the password-realm token
#: grant needs -- `Username-Password-Authentication` on the spokesman tenant, a
#: default that cannot be assumed for any other publisher.
BODY_FIELDS_WORTH_READING: tuple[str, ...] = (
    "realm",
    "connection",
    "client_id",
    "grant_type",
    "scope",
    "response_type",
    "tenant",
)


def _events(entries: list[dict], method: str = RESPONSE_EVENT) -> Any:
    """Yield the decoded CDP params for one event type from a performance log."""
    for entry in entries or []:
        raw = entry.get("message")
        if not raw:
            continue
        try:
            message = json.loads(raw).get("message") or {}
        except (ValueError, TypeError):
            continue
        if message.get("method") == method:
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


def network_redirects(entries: list[dict]) -> list[tuple[int, str]]:
    """Every (status, url) of a REDIRECT, which responses alone never show.

    Chrome reports a 3xx as `redirectResponse` inside the next
    `requestWillBeSent`, not as a `responseReceived`. So this is the only way to
    see the status that proves an eType login: `POST /account/etype-login` answers
    302 with `location: /account/etype-auth`, and the browser follows it before
    any response event names the 302.

    The url is the one that was REDIRECTED (the redirectResponse's own url), not
    the destination, because that is the request whose status is being reported.
    """
    out: list[tuple[int, str]] = []
    for params in _events(entries, REQUEST_EVENT):
        redirect = params.get("redirectResponse") or {}
        code = redirect.get("status")
        url = redirect.get("url")
        if isinstance(code, int) and url:
            out.append((code, str(url)))
    return out


def request_body_fields(entries: list[dict]) -> list[tuple[str, dict[str, str]]]:
    """Allowlisted form fields per request url. NEVER a password, never a body.

    Only the keys in `BODY_FIELDS_WORTH_READING` are read, and everything else in
    the body -- `username`, `password`, tokens, anything a vendor invents -- is
    discarded without being copied anywhere. That is deliberate and is the whole
    safety property: a login POST carries the subscriber's password, so the
    allowlist has to be the mechanism rather than a filter applied afterwards.

    The realm is the reason this exists. It cannot be guessed per tenant, and it
    is in the POST body rather than the URL, so harvesting it requires reading
    requests -- see `BODY_FIELDS_WORTH_READING`.
    """
    out: list[tuple[str, dict[str, str]]] = []
    for params in _events(entries, REQUEST_EVENT):
        request = params.get("request") or {}
        body = request.get("postData")
        url = request.get("url")
        if not body or not url or not isinstance(body, str):
            continue
        found: dict[str, str] = {}
        for pair in body.replace("&amp;", "&").split("&"):
            if "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            key = urllib.parse.unquote_plus(key.strip())
            if key in BODY_FIELDS_WORTH_READING:
                found[key] = urllib.parse.unquote_plus(value.strip())[:120]
        if found:
            out.append((str(url), found))
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
