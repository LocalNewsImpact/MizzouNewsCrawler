"""The browser's own error page is a fetch failure, not an article.

thebannerpress.com let its certificate expire on 2024-07-15. Chrome showed
its SSL interstitial, Selenium read that page with `driver.page_source`,
and the extractor stored it: 22 articles whose body is a PEM certificate
chain and whose headline is "Privacy error". Twenty of them were
CIN-classified on that basis.

Nothing was wrong with the crawl except that nobody asked whether the page
had loaded. There is no interstitial check anywhere in this project --
`net::ERR`, `chrome-error` and `main-frame-error` appear nowhere -- so
every browser-level failure since the beginning has been stored as
content: an expired certificate, a DNS failure, a refused connection,
all of them "articles".

WHAT IT MATCHES ON, AND WHY NOT THE TITLE
-----------------------------------------
The `net::ERR_*` code, which is locale-independent, AND one of Chrome's
interstitial scaffolding ids. Both, because either alone is wrong:

- The code alone would condemn a real story about a certificate outage
  that quotes the error it saw.
- The scaffolding alone drifts with Chrome's markup between versions.

Not the document title. "Privacy error" and "This site can't be reached"
are translated strings, so a check on them silently stops working the
first time a driver runs under another locale -- which is the same class
of bug as matching a marker list against a publisher's curly apostrophes.
"""

from __future__ import annotations

import re

#: Locale-independent, and the part that says WHICH failure. Returned as the
#: evidence rather than a bool, so telemetry records an expired certificate
#: and a DNS failure as different things and a fix can be aimed.
_ERROR_CODE = re.compile(r"net::(ERR_[A-Z0-9_]+)")

#: Chrome's interstitial scaffolding. Several spellings because the markup
#: differs between the network-error page and the SSL page, and between
#: versions -- any one of them is enough when it appears beside a code.
_SCAFFOLDING = (
    'id="main-frame-error"',
    'id="proceed-link"',
    'id="details-button"',
    'id="primary-button"',
    "interstitial-wrapper",
    "neterror",
    "ssl-blocking-page",
    "chrome-error://chromewebdata",
)

#: A page the browser served instead of the site. `driver.current_url` is
#: this for a network-level failure, which settles the question on its own
#: -- no document from the site was loaded at all.
BROWSER_ERROR_SCHEME = "chrome-error://"


def interstitial_error(html: str | None, current_url: str | None = None) -> str | None:
    """The browser error code this page reports, or None if it is a page.

    Returns e.g. "ERR_CERT_DATE_INVALID" so the caller can record which
    failure it was.
    """
    # isinstance, not truthiness. `driver.current_url` is whatever the driver
    # hands back, and anything non-string answers `.startswith()` with
    # something truthy of its own -- a Mock does exactly that -- which
    # condemned every page as a browser error. A current_url that is not a
    # string is not evidence of anything, so it is ignored and the HTML
    # decides.
    if isinstance(current_url, str) and current_url.startswith(BROWSER_ERROR_SCHEME):
        # No document from the site was loaded. Whatever the body holds, it
        # did not come from the publisher.
        found = _ERROR_CODE.search(html or "")
        return found.group(1) if found else "ERR_BROWSER_ERROR_PAGE"

    if not html:
        return None
    found = _ERROR_CODE.search(html)
    if not found:
        return None
    lowered = html.lower()
    if not any(marker in lowered for marker in _SCAFFOLDING):
        # A code with no interstitial around it is a page that mentions an
        # error, which is a real article about an outage.
        return None
    return found.group(1)
