"""Which fetch paths an article may use, decided once and in one place.

`extract_content` used to make this decision inline across three branches, and
two of them cleared a flag the first had set. The Cloudflare branch does it
deliberately, so cloudscraper can try before Selenium. The AMP branch was not
even aware of the flag: it fetched the AMP copy, assigned it as the body and
re-enabled the anonymous parsers.

That is survivable while every path is anonymous, because they are all trying to
get the same public page. It stops being survivable once one host must be
fetched through a subscriber session, since each of those branches fetches
anonymously and an anonymous fetch of a paywalled article returns the wall --
a 200 with content, which extraction then accepts as the body.

On 2026-09-18 that filed 13 of 19 Port Townsend Leader articles as `paywall`
against a credential known to work, off a page whose own text read
"access this content ... login".

So the decision is a value, computed from the facts and then read. A branch can
consult it; nothing can quietly reverse it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Extraction methods whose HTTP paths cannot work at all, so the browser is the
#: only option regardless of credentials.
BROWSER_ONLY_METHODS = frozenset({"selenium", "unblock"})


@dataclass(frozen=True)
class FetchPlan:
    """What `extract_content` is permitted to try, and why."""

    #: Skip the HTTP fetch and the parsers that read its HTML (mcmetadata,
    #: newspaper4k), leaving the browser.
    skip_http_methods: bool
    #: Try cloudscraper before Selenium for a Cloudflare-walled host.
    allow_cloudflare_escalation: bool
    #: Preemptively fetch the AMP copy, which is served unauthenticated.
    allow_amp: bool
    #: Use the tls_client rung -- same Squid egress, Chrome-like TLS
    #: fingerprint. Anonymous, and enabled for every host by default, not only
    #: the ones flagged `unblock`.
    allow_tls_capture: bool
    #: True when this host's articles are behind a subscriber login.
    credentialed: bool
    #: Short phrase naming why, for the log line.
    reason: str

    @property
    def browser_only(self) -> bool:
        return self.skip_http_methods and not self.allow_cloudflare_escalation


def plan_fetch(
    *,
    credentialed: bool,
    extraction_method: str | None,
    protection_type: str | None,
    cloudscraper_available: bool,
    amp_supported: bool | None,
    selenium_only: bool = False,
) -> FetchPlan:
    """Decide the permitted fetch paths for one host.

    `credentialed` wins over everything. A subscriber session is how the host
    stops refusing us, so the anonymous escapes are not alternatives to it --
    they are ways of being refused more expensively. Trying them first and
    escalating on detection reaches the same article and pays for a fetch known
    in advance to fail, on every article of every login-gated publisher.
    """
    if credentialed:
        return FetchPlan(
            skip_http_methods=True,
            allow_cloudflare_escalation=False,
            allow_amp=False,
            # The tls_client rung fires for every host, not only those flagged
            # `unblock`, and it is an anonymous fetch. On 2026-09-18 it knocked
            # on ptleader twice before the browser opened, read the 301 as a
            # proxy challenge, and had the router back off BOTH proxies for the
            # host for 600s. The browser then arrived from the same egress and
            # met a CAPTCHA.
            #
            # An anonymous knock does not merely waste a request on a host we
            # hold a subscription to: it spends that host's patience, and the
            # authenticated attempt is what pays for it.
            allow_tls_capture=False,
            credentialed=True,
            reason="subscriber login: authenticated browser only",
        )

    # `sources.selenium_only`: someone has said this host answers HTTP with a
    # challenge and only the browser gets through. The column existed and the
    # auto-flagger wrote it, but nothing read it, so a host marked `selenium`
    # AND `cloudflare` still got cloudscraper first -- an HTTP knock the label
    # said not to make. My Edmonds News, 2026-09-21: both proxies refused every
    # HTTP capture (403, a 2.6 KB challenge page) and its home proxy's failure
    # count for the host stood at 180.
    #
    # `unblock` hosts are left as they are. Their whole method is a proxied HTTP
    # fetch, and refusing them the tls_client rung would remove it.
    only_browser = selenium_only and extraction_method != "unblock"

    browser_only = only_browser or (extraction_method or "") in BROWSER_ONLY_METHODS
    escalate = (
        extraction_method == "selenium"
        and protection_type == "cloudflare"
        and cloudscraper_available
        and not only_browser
    )
    return FetchPlan(
        # The escalation exists to let cloudscraper try first, so it reopens the
        # HTTP paths for a host that would otherwise be browser-only.
        skip_http_methods=browser_only and not escalate,
        allow_cloudflare_escalation=escalate,
        # `bool | None` because the source record may simply not say. Unknown
        # is "do not preemptively fetch": the AMP copy is a guess about a URL
        # that may not exist, and guessing wrong costs a request.
        # The AMP copy and the tls_client capture are anonymous HTTP fetches too.
        allow_amp=bool(amp_supported) and not only_browser,
        allow_tls_capture=not only_browser,
        credentialed=False,
        reason=(
            "cloudflare: cloudscraper before selenium"
            if escalate
            else (
                "selenium only: browser, no HTTP of any kind"
                if only_browser
                else "browser only" if browser_only else "http first"
            )
        ),
    )
