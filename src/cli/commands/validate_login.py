"""news-crawler validate-login -- run a publisher login and show what happened.

The entry-time half of docs/A_LOGIN_IS_WITNESSED_AT_ENTRY.md. There is no
site-independent runtime signal that a login worked; the affirmative signal is a
person watching it succeed once, with the evidence recorded. This is that step,
runnable by hand today and callable from the source form later.

    news-crawler validate-login --host www.yakimaherald.com
    news-crawler validate-login --host www.yakimaherald.com --record --path modal

It logs in through the crawler's own driver and login mechanism -- the same
code the run uses, so a pass here means the run will pass -- and reports:

  * which network responses arrived during the submit. The vendor's auth call
    is the one that matters: on www.yakimaherald.com it is Connext's
    /api/user answering 200.
  * whether the login control went hidden. The site ships a logged-out control
    and a logged-in one and toggles VISIBILITY; the strings themselves are in
    the page source in both states, which is why `success_text` was worthless.
  * which FIRST-PARTY, NON-ANALYTICS cookies were added or changed. Names only,
    never values: a value is the session, and the point is which cookie
    carries it, not what it says. On this host the filter takes 49 first-party
    cookies down to 15, of which exactly one changes: Connext's.

`--record` writes that evidence into `auth_config.witnessed` (names, URLs and
statuses -- nothing secret), stores `login_path` if given, and clears
`auth_last_failed_at` so /stats stops reporting the host as needing
re-validation. Without it, nothing is written.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

#: Analytics, consent and bot-vendor cookies, by product prefix. Generic across
#: the web -- these are products, not publishers, so the list does not grow
#: per host.
NOISE = re.compile(
    r"^(_ga|_gid|_gat|_gcl|_fbp|_chartbeat|_cb_|_cb$|_li_|_lc2_|_lr_|_px|px|"
    r"_ml_|_mather|ajs_|amplitude|compass_|flipp|loggly|mcforms|ai_|csparkW|"
    r"anonDeviceId|_iiq|_scor|_uet|OptanonConsent|euconsent|__gads|__qca|"
    r"__eoi|__gpi|FCCDCF|FCNEC|___nrbi)",
    re.I,
)

#: Set for every visitor by a load balancer, CDN or WAF, so never evidence of a
#: session. Named from what the four 2026-09-20 witness runs actually returned.
INFRA = re.compile(
    r"^(AWSALB|AWSALBCORS|AWSELB|ELB|incap_ses|nlbi_|visid_incap|reese84|"
    r"__cf_bm|__cfruid|cf_clearance|_abck|bm_sz|bm_sv|ak_bmsc|datadome|"
    r"BIGipServer|TS[0-9a-f]{6,}|JSESSIONID_LB|x-ms-routing-name)",
    re.I,
)

#: A response worth showing: the vendor's auth exchange, not the page's assets.
AUTH_LIKE = re.compile(
    r"login|auth|session|account|user|token|connext|mg2|newzware|etype|simplecirc",
    re.I,
)
ASSET = re.compile(r"\.(js|css|png|gif|jpe?g|svg|woff2?|ico|mp4)(\?|$)", re.I)


def add_validate_login_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "validate-login",
        help="Run a publisher login through the crawler and show the evidence",
    )
    parser.add_argument("--host", required=True, help="sources.host_norm")
    parser.add_argument(
        "--record",
        action="store_true",
        help="write the evidence to auth_config.witnessed and clear the failure",
    )
    parser.add_argument(
        "--path",
        choices=("page", "modal", "sso"),
        default=None,
        help="how the login is reached; stored with --record",
    )


def bare_host(host: str) -> str:
    host = host.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def first_party_cookies(cookies: list[dict], site: str) -> dict[str, str]:
    """name@domain -> a length-only fingerprint. Never a value."""
    out: dict[str, str] = {}
    for c in cookies or []:
        name = c.get("name", "")
        domain = (c.get("domain") or "").lstrip(".")
        if site not in domain or NOISE.match(name):
            continue
        out[f"{name}@{domain}"] = f"len={len(c.get('value', ''))}"
    return out


def partition_evidence(names: list[str]) -> tuple[list[str], list[str]]:
    """Split cookie keys into (session evidence, infrastructure).

    A load balancer's affinity cookie and a WAF's device cookie are set for
    everyone who loads the page, logged in or not, so they are not evidence of
    a session -- but they LOOK like evidence in a diff, because they are
    first-party, non-analytics, and appear during the login.

    `www.spokesman.com` is the case that named this: its only new cookies were
    `AWSALB`, `AWSALBCORS` (an AWS load balancer) and `incap_ses_*`, `nlbi_*`,
    `visid_incap_*` (Imperva Incapsula). A person reads that list and knows it
    proves nothing. Nothing in the code knew, and a verifier that judges
    unattended has to.

    Returned rather than dropped: the infrastructure list says which vendor
    fronts the site, which is worth seeing when a login misbehaves.
    """
    session, infra = [], []
    for name in names:
        (infra if INFRA.match(name) else session).append(name)
    return sorted(session), sorted(infra)


def auth_responses(responses: list[tuple[int, str]]) -> list[tuple[int, str]]:
    return [
        (code, url[:140])
        for code, url in responses
        if AUTH_LIKE.search(url) and not ASSET.search(url)
    ][:20]


def _visible(driver, selector: str | None) -> bool | None:
    if not selector:
        return None
    try:
        from selenium.webdriver.common.by import By

        return any(
            el.is_displayed() for el in driver.find_elements(By.CSS_SELECTOR, selector)
        )
    except Exception:
        return None


def witness(extractor, host: str) -> dict:
    """Run the login and return the evidence. Writes nothing."""
    from src.crawler.authenticated_login import (
        perform_login,
        resolve_auth_credentials,
    )
    from src.crawler.browser_status import network_responses

    bare = bare_host(host)
    auth = extractor._get_domain_auth_config(bare)
    if not auth:
        return {"ok": False, "why": f"{host} has no auth config (requires_login?)"}
    cfg = auth.get("auth_config") or {}
    creds = resolve_auth_credentials(auth.get("auth_secret_name"))
    if not creds.get("username") and not creds.get("account_id"):
        return {"ok": False, "why": "credentials could not be resolved"}

    driver = extractor.get_persistent_driver()
    trigger = cfg.get("login_trigger_selector")

    # BOTH cookie snapshots are taken standing on the publisher's own origin.
    #
    # `driver.get_cookies()` returns only what the CURRENT document's origin can
    # read. Taking `before` on the login page and `after` wherever the login
    # left the browser compares two different origins, so the diff means
    # nothing for any login that navigates away -- which is every url and SSO
    # path, i.e. all of them except a modal on the article page.
    #
    # Measured 2026-09-20, four hosts, one run each: yakimaherald and
    # union-bulletin log in through a modal on the publisher's page, stay on
    # that origin, and showed real session cookies. tdn (form, url) and
    # pendoreillerivervalley (etype) ended elsewhere and showed NONE.
    # www.spokesman.com (auth0) showed `AWSALB@myaccount.spokesman.com` -- a
    # cookie only a document on `myaccount.spokesman.com` can read, which is
    # the proof that the snapshot origin, not the site, was the variable.
    origin = f"https://{host}/" if "." in host else f"https://{bare}/"
    try:
        driver.get(origin)
    except Exception as exc:
        return {"ok": False, "why": f"could not open {origin}: {exc}"}
    cookies_before = first_party_cookies(_cookies(driver), bare)
    # The login control is read on the origin BOTH times too, for the same
    # reason: "the Log in link is gone" is only a signal if the two
    # observations are of the same page.
    trigger_before = _visible(driver, trigger)

    login_url = cfg.get("login_url")
    if login_url:
        try:
            driver.get(login_url)
        except Exception as exc:
            return {"ok": False, "why": f"could not open {login_url}: {exc}"}
    time.sleep(float(cfg.get("modal_delay", 5)))
    try:
        driver.get_log("performance")  # drain what the page load produced
    except Exception:
        pass

    started = time.time()
    ok = perform_login(
        driver, auth_type=auth.get("auth_type"), auth_config=cfg, credentials=creds
    )
    elapsed = round(time.time() - started, 1)
    time.sleep(3)

    # Drained BEFORE navigating back: get_log() consumes the buffer, and the
    # return trip's own requests would otherwise be all that is left of it.
    try:
        responses = network_responses(driver.get_log("performance"))
    except Exception:
        responses = []

    # Back to the origin the `before` snapshot was taken on.
    returned_to_origin = True
    try:
        driver.get(origin)
    except Exception:
        # Not fatal: report the evidence that was gathered and say the return
        # trip failed, rather than throwing away a login that may have worked.
        returned_to_origin = False
    cookies_after = first_party_cookies(_cookies(driver), bare)

    added = [k for k in cookies_after if k not in cookies_before]
    changed = [
        k
        for k in cookies_after
        if k in cookies_before and cookies_after[k] != cookies_before[k]
    ]
    added_session, added_infra = partition_evidence(added)
    changed_session, changed_infra = partition_evidence(changed)

    return {
        "ok": bool(ok),
        "host": host,
        "auth_type": auth.get("auth_type"),
        "seconds": elapsed,
        "origin": origin,
        "returned_to_origin": returned_to_origin,
        "trigger_visible_before": trigger_before,
        "trigger_visible_after": _visible(driver, trigger),
        "auth_responses": auth_responses(responses),
        "first_party_cookies_added": added_session,
        "first_party_cookies_changed": changed_session,
        "infrastructure_cookies": sorted(set(added_infra) | set(changed_infra)),
    }


def _cookies(driver) -> list[dict]:
    try:
        return driver.get_cookies() or []
    except Exception:
        return []


RECORD_SQL = (
    "UPDATE sources SET "
    "auth_config = (coalesce(auth_config::jsonb, '{}'::jsonb) "
    "  || jsonb_build_object('witnessed', CAST(:witnessed AS jsonb)))::json, "
    "login_path = coalesce(:path, login_path), "
    "auth_last_failed_at = NULL, auth_failure_reason = NULL "
    "WHERE requires_login AND host_norm IN (:host, :www_host, :bare_host)"
)


def record(session, host: str, evidence: dict, path: str | None) -> None:
    """Store the witnessed login. Names, URLs and statuses only."""
    from sqlalchemy import text

    witnessed = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "auth_responses": evidence.get("auth_responses"),
        "trigger_visible_before": evidence.get("trigger_visible_before"),
        "trigger_visible_after": evidence.get("trigger_visible_after"),
        "first_party_cookies_added": evidence.get("first_party_cookies_added"),
        "first_party_cookies_changed": evidence.get("first_party_cookies_changed"),
        "infrastructure_cookies": evidence.get("infrastructure_cookies"),
        # Which origin the cookie diff was taken on, so a stored witness can be
        # read later without assuming it was same-origin. The 2026-09-20 records
        # predate the fix and carry neither key.
        "origin": evidence.get("origin"),
        "seconds": evidence.get("seconds"),
    }
    session.execute(
        text(RECORD_SQL),
        {
            "witnessed": json.dumps(witnessed),
            "path": path,
            "host": host,
            "www_host": f"www.{bare_host(host)}",
            "bare_host": bare_host(host),
        },
    )
    session.commit()


def handle_validate_login_command(args: argparse.Namespace) -> int:
    from src.crawler import ContentExtractor
    from src.models.database import DatabaseManager

    extractor = ContentExtractor()
    try:
        evidence = witness(extractor, args.host)
    finally:
        try:
            extractor.close_persistent_driver()
        except Exception:
            pass

    if not evidence.get("ok"):
        print(f"NOT LOGGED IN  {args.host}")
        print(f"  {evidence.get('why', 'the mechanism did not confirm a session')}")
        for k in (
            "auth_responses",
            "trigger_visible_before",
            "trigger_visible_after",
            "first_party_cookies_added",
            "first_party_cookies_changed",
        ):
            if k in evidence:
                print(f"  {k}: {evidence[k]}")
        return 1

    print(f"LOGGED IN  {args.host}  ({evidence['auth_type']}, {evidence['seconds']}s)")
    for code, url in evidence["auth_responses"]:
        print(f"  {code}  {url}")
    print(
        f"  login control visible: {evidence['trigger_visible_before']} -> "
        f"{evidence['trigger_visible_after']}"
    )
    print(f"  session cookies added:   {evidence['first_party_cookies_added']}")
    print(f"  session cookies changed: {evidence['first_party_cookies_changed']}")
    if evidence.get("infrastructure_cookies"):
        print(f"  infrastructure (NOT evidence): {evidence['infrastructure_cookies']}")
    if not evidence.get("returned_to_origin", True):
        print(
            f"  WARNING: could not return to {evidence.get('origin')} -- the cookie "
            "diff compares two origins and proves nothing"
        )
    if not (
        evidence["first_party_cookies_added"]
        or evidence["first_party_cookies_changed"]
        or evidence["trigger_visible_after"] is False
    ):
        # The mechanism said yes and nothing observable changed on the
        # publisher's own origin. That is the case a verifier must not pass:
        # `etype` returns True having confirmed only that a form submitted.
        print(
            "  NOTE: the mechanism confirmed a session but nothing changed on "
            f"{evidence.get('origin')} -- no session cookie, no control flip. "
            "Do not record this as witnessed without a second signal."
        )

    if args.record:
        with DatabaseManager().get_session() as session:
            record(session, args.host, evidence, args.path)
        print("  recorded to auth_config.witnessed; auth_last_failed_at cleared")
    else:
        print("  (not recorded -- pass --record to store this as the witnessed login)")
    return 0
