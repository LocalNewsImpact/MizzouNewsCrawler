#!/usr/bin/env python3
"""Spike: validate that we can authenticate (log in) to a subscriber site.

This is a throwaway feasibility probe, NOT production code. It answers one
question: can we log into a subscriber account with the crawler's existing
stealth Selenium + residential-proxy stack and obtain an authenticated session
(cookies) that the fast HTTP path can reuse?

Whether any given story is paywalled is determined dynamically by the site, so
this probe does NOT try to classify articles. The pass/fail signal is simply:
did the login succeed and did we get a logged-in session?

It is intentionally generic so the same probe works for BLOX/TownNews papers
(e.g. Yakima Herald-Republic) and custom systems (e.g. The Spokesman-Review),
and any future password-protected site.

CREDENTIALS ARE READ FROM ENVIRONMENT VARIABLES ONLY. Nothing is hardcoded or
written to disk. Rotate any password that has ever been pasted into chat and
load the real one from GCP Secret Manager in production.

Required env vars
-----------------
  PAYWALL_TEST_LOGIN_URL     URL of the site's login form page
  PAYWALL_TEST_USERNAME      subscriber account email/username
  PAYWALL_TEST_PASSWORD      subscriber account password

Optional env vars
-----------------
  PAYWALL_TEST_ARTICLE_URL        an article to fetch post-login (informational)
  PAYWALL_TEST_EMAIL_SELECTOR     CSS selector for the username/email input
  PAYWALL_TEST_PASSWORD_SELECTOR  CSS selector for the password input
  PAYWALL_TEST_SUBMIT_SELECTOR    CSS selector for the submit button
  PAYWALL_TEST_SUCCESS_TEXT       substring that proves login (e.g. "Log Out")
  SELENIUM_PROXY / SQUID_PROXY_URL   residential proxy (already used by crawler)
  SELENIUM_EXECUTION_MODE         "headful" (default) or "headless"

Run from an extraction pod per the repo's Extraction Site-Access Testing
Protocol. Example:
  kubectl cp scripts/spike_paywall_login.py \
      production/<extraction-pod>:/app/spike_paywall_login.py
  kubectl exec -n production <extraction-pod> -- env \
      PAYWALL_TEST_LOGIN_URL=... PAYWALL_TEST_ARTICLE_URL=... \
      PAYWALL_TEST_USERNAME=... PAYWALL_TEST_PASSWORD=... \
      python /app/spike_paywall_login.py
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import time
import urllib.parse

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from src.crawler import ContentExtractor

# Candidate selectors tried in order when no explicit selector is provided.
EMAIL_CANDIDATES = (
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    'input[name="user[email]"]',
    'input[id*="email" i]',
    'input[name*="email" i]',
    'input[name*="user" i]',
    'input[autocomplete="username"]',
)
PASSWORD_CANDIDATES = (
    'input[type="password"]',
    'input[name="password"]',
    'input[id*="pass" i]',
    'input[autocomplete="current-password"]',
)
SUBMIT_CANDIDATES = (
    'button[type="submit"]',
    'input[type="submit"]',
    'button[name="login"]',
    'button[id*="login" i]',
    'button[id*="signin" i]',
)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"ERROR: required env var {name} is not set")
    return value


def _mask(secret: str) -> str:
    if not secret:
        return "(empty)"
    if len(secret) <= 2:
        return "*" * len(secret)
    return secret[0] + "*" * (len(secret) - 2) + secret[-1]


def _find_first(driver, selectors):
    """Return the first visible element matching any of the given selectors."""
    explicit = [s for s in selectors if s]
    for sel in explicit:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            continue
        for el in els:
            try:
                if el.is_displayed():
                    return el, sel
            except Exception:
                continue
    return None, None


def _dump_form_diagnostics(driver) -> None:
    """Print every input + iframe on the page so we can identify the real form."""
    try:
        inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"  --- inputs on page: {len(inputs)} ---")
        for i, el in enumerate(inputs[:25]):
            try:
                info = {
                    "type": el.get_attribute("type"),
                    "name": el.get_attribute("name"),
                    "id": el.get_attribute("id"),
                    "placeholder": el.get_attribute("placeholder"),
                    "aria": el.get_attribute("aria-label"),
                    "autocomplete": el.get_attribute("autocomplete"),
                    "shown": el.is_displayed(),
                }
                print(f"    [{i}] {info}")
            except Exception as exc:
                print(f"    [{i}] <error reading: {exc}>")
    except Exception as exc:
        print(f"  input enumeration failed: {exc}")
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"  --- iframes on page: {len(frames)} ---")
        for i, fr in enumerate(frames[:10]):
            try:
                print(f"    iframe[{i}] src={fr.get_attribute('src')}")
            except Exception:
                pass
        if frames:
            print(
                "  NOTE: form may be inside an iframe; selectors won't reach it "
                "without switching frames."
            )
    except Exception as exc:
        print(f"  iframe enumeration failed: {exc}")
    try:
        body = driver.find_element(By.TAG_NAME, "body").text or ""
        print(f"  --- visible body (first 400 chars) ---\n  {body[:400]!r}")
    except Exception:
        pass


def _build_auth0_authorize_url(domain, client_id, redirect_uri, scope):
    """Generate a valid Auth0 /authorize URL with our own PKCE pair.

    Auth0's Universal Login form only renders when reached via /authorize with
    a fresh, valid state/nonce/code_challenge. Hitting /login directly yields an
    error page. We build our own request so the form renders and we can submit
    credentials. Auth0 validates the credentials and redirects to redirect_uri
    with a ?code=... on success — that redirect proves login worked.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "response_type": "code",
        "response_mode": "query",
        "state": secrets.token_urlsafe(16),
        "nonce": secrets.token_urlsafe(16),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"https://{domain}/authorize?" + urllib.parse.urlencode(params)
    return url, verifier


def main() -> int:
    login_url = _require("PAYWALL_TEST_LOGIN_URL")
    username = _require("PAYWALL_TEST_USERNAME")
    password = _require("PAYWALL_TEST_PASSWORD")
    article_url = os.getenv("PAYWALL_TEST_ARTICLE_URL")  # optional, informational

    email_sel = os.getenv("PAYWALL_TEST_EMAIL_SELECTOR")
    pass_sel = os.getenv("PAYWALL_TEST_PASSWORD_SELECTOR")
    submit_sel = os.getenv("PAYWALL_TEST_SUBMIT_SELECTOR")
    success_text = os.getenv("PAYWALL_TEST_SUCCESS_TEXT", "").strip()

    # Auth0 mode: build our own /authorize request so Universal Login renders.
    auth0_domain = os.getenv("PAYWALL_TEST_AUTH0_DOMAIN")
    auth0_redirect = os.getenv("PAYWALL_TEST_AUTH0_REDIRECT_URI", "")
    if auth0_domain:
        login_url, _verifier = _build_auth0_authorize_url(
            auth0_domain,
            os.getenv("PAYWALL_TEST_AUTH0_CLIENT_ID", ""),
            auth0_redirect,
            os.getenv("PAYWALL_TEST_AUTH0_SCOPE", "openid profile email"),
        )

    print("=" * 72)
    print("PAYWALL LOGIN SPIKE")
    print("=" * 72)
    print(f"auth0 mode  : {'YES (' + auth0_domain + ')' if auth0_domain else 'no'}")
    print(f"login_url   : {login_url}")
    print(f"article_url : {article_url or '(none - login check only)'}")
    print(f"username    : {_mask(username)}")
    print(f"password    : {_mask(password)}")
    proxy = os.getenv("SELENIUM_PROXY") or os.getenv("SQUID_PROXY_URL")
    print(f"proxy       : {'set' if proxy else 'NOT SET (will use crawler default)'}")
    print("-" * 72)

    extractor = ContentExtractor()
    driver = None
    try:
        print("[1/5] Creating stealth driver (residential proxy wired)...")
        driver = extractor._create_undetected_driver()

        print("[2/5] Loading login page...")
        driver.set_page_load_timeout(45)
        try:
            driver.get(login_url)
        except Exception as exc:
            print(f"  page load returned/timed out (continuing): {exc}")
        print(f"  landed on: {driver.current_url}")
        print(f"  page title: {driver.title}")

        # The login page may be a JS SPA (e.g. Auth0 Universal Login) that
        # renders the form after load. Poll for the email/username field first.
        cookies_before = {c.get("name") for c in driver.get_cookies()}
        email_el = used_email_sel = None
        deadline = time.time() + 20
        while time.time() < deadline:
            email_el, used_email_sel = _find_first(
                driver, [email_sel, *EMAIL_CANDIDATES]
            )
            if email_el:
                break
            time.sleep(1)

        if not email_el:
            print("  Could not locate username/email field after 20s.")
            _dump_form_diagnostics(driver)
            return 2
        print(f"  email selector   : {used_email_sel}")

        print("[3/5] Submitting credentials...")
        email_el.clear()
        email_el.send_keys(username)

        # Password may be on the same screen or on a second (identifier-first) step.
        pass_el, used_pass_sel = _find_first(driver, [pass_sel, *PASSWORD_CANDIDATES])
        if not pass_el:
            print("  password not on screen 1; clicking continue (identifier-first)")
            cont_el, _ = _find_first(driver, [submit_sel, *SUBMIT_CANDIDATES])
            if cont_el:
                cont_el.click()
            else:
                from selenium.webdriver.common.keys import Keys

                email_el.send_keys(Keys.RETURN)
            pdeadline = time.time() + 15
            while time.time() < pdeadline:
                pass_el, used_pass_sel = _find_first(
                    driver, [pass_sel, *PASSWORD_CANDIDATES]
                )
                if pass_el:
                    break
                time.sleep(1)

        if not pass_el:
            print("  Could not locate password field.")
            _dump_form_diagnostics(driver)
            return 2
        print(f"  password selector: {used_pass_sel}")
        pass_el.clear()
        pass_el.send_keys(password)

        submit_el, used_submit_sel = _find_first(
            driver, [submit_sel, *SUBMIT_CANDIDATES]
        )
        if submit_el:
            print(f"  submit selector  : {used_submit_sel}")
            submit_el.click()
        else:
            print("  No submit button found; sending RETURN on password field.")
            from selenium.webdriver.common.keys import Keys

            pass_el.send_keys(Keys.RETURN)

        # Give the auth round-trip time to complete and set cookies. For Auth0,
        # success means we get redirected off the login domain (back to the app).
        def _auth_progressed(d):
            cur = d.current_url
            if auth0_domain:
                return (auth0_domain not in cur) or ("code=" in cur)
            return cur != login_url or _has_session_cookie(d)

        try:
            WebDriverWait(driver, 25).until(_auth_progressed)
        except Exception:
            pass
        time.sleep(4)

        cookies = driver.get_cookies()
        cookies_after = {c.get("name") for c in cookies}
        new_cookies = cookies_after - cookies_before
        current_url = driver.current_url
        left_login_page = current_url != login_url
        login_form_gone = not _find_first(driver, [email_sel, *EMAIL_CANDIDATES])[0]
        auth0_redirected = bool(
            auth0_domain
            and ((auth0_domain not in current_url) or ("code=" in current_url))
        )

        print("[4/5] Evaluating login result...")
        print(f"  cookies after login : {len(cookies)} (new: {len(new_cookies)})")
        print(f"  navigated off login : {left_login_page} -> {current_url}")
        print(f"  login form gone     : {login_form_gone}")
        if auth0_domain:
            print(f"  auth0 redirected out: {auth0_redirected}")
        success_text_present = None
        if success_text:
            page = driver.page_source.lower()
            success_text_present = success_text.lower() in page
            print(f"  success_text '{success_text}': {success_text_present}")

        # Login is successful if Auth0 redirected us back to the app (definitive),
        # or we got new session cookies plus a corroborating signal.
        signals = [
            bool(new_cookies),
            left_login_page,
            login_form_gone,
            bool(success_text_present),
            auth0_redirected,
        ]
        login_ok = auth0_redirected or (
            bool(new_cookies)
            and (left_login_page or login_form_gone or bool(success_text_present))
        )

        print("[5/5] Optional: fetching one article post-login (informational)...")
        if article_url:
            try:
                driver.get(article_url)
                time.sleep(4)
                sel_text = _visible_text(driver)
                print(f"  selenium body chars : {len(sel_text)}")
                http_len, http_status = _http_fetch_with_cookies(
                    cookies, article_url, proxy
                )
                print(f"  http status         : {http_status}")
                print(f"  http body chars     : {http_len}")
            except Exception as exc:
                print(f"  article fetch error : {exc}")
        else:
            print("  (skipped - no PAYWALL_TEST_ARTICLE_URL provided)")

        print("=" * 72)
        print("RESULT")
        print("=" * 72)
        print("  login form found    : YES")
        print(f"  new session cookies : {len(new_cookies)}")
        print(f"  navigated off login : {left_login_page}")
        print(f"  login form gone     : {login_form_gone}")
        if auth0_domain:
            print(f"  auth0 redirected out: {auth0_redirected}")
        if success_text:
            print(f"  success marker seen : {success_text_present}")
        print(f"  positive signals    : {sum(1 for s in signals if s)}/5")
        if login_ok:
            print(
                "\n  VERDICT: LOGIN SUCCEEDED. We obtained an authenticated "
                "session. Authenticated extraction is feasible for this site."
            )
            return 0
        print(
            "\n  VERDICT: LOGIN NOT CONFIRMED. Form was found and submitted but "
            "no authenticated session was detected. Check credentials, the "
            "login URL, success_text, or whether the site uses SSO/2FA/a JS "
            "challenge on the login endpoint."
        )
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _has_session_cookie(driver) -> bool:
    try:
        return any("sess" in (c.get("name", "").lower()) for c in driver.get_cookies())
    except Exception:
        return False


def _visible_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return ""


def _http_fetch_with_cookies(cookies, article_url, proxy):
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    for c in cookies:
        try:
            session.cookies.set(c.get("name"), c.get("value"), domain=c.get("domain"))
        except Exception:
            continue
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = session.get(article_url, headers=headers, timeout=30)
    except Exception as exc:
        return 0, f"ERR:{exc}"
    return len(resp.text), resp.status_code


if __name__ == "__main__":
    raise SystemExit(main())
