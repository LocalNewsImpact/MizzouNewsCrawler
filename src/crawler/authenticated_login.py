"""Authenticated login for subscriber / paywalled publishers.

Drives a browser login on an existing Selenium driver so that the resulting
session cookies carry through to subsequent (paywalled) article fetches. Whether
any individual story is paywalled is decided dynamically by the publisher; this
module simply establishes an authenticated session for the domain.

Two login mechanisms are supported:

* ``auth0`` – Auth0 Universal Login (OAuth2 / OIDC with PKCE). The form only
  renders when reached via ``/authorize`` with a fresh, valid
  state/nonce/code_challenge, so we build our own authorize request. Success is
  proven when Auth0 redirects back to the application callback with a ``code=``
  (i.e. the credentials were accepted).
* ``form`` – a plain username/password login form POST.

Both mechanisms handle "identifier-first" flows where the password field only
appears after the email is submitted.

Credentials are resolved at runtime from an environment override or GCP Secret
Manager and are NEVER persisted on the Source record or written to logs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
import urllib.parse
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

# Candidate selectors tried in order when no explicit selector is configured.
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


def resolve_credentials(
    secret_name: Optional[str], project: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Resolve (username, password) for a publisher secret.

    Resolution order:
      1. Environment override keyed by the normalized secret name, e.g. secret
         ``publisher-auth-spokesman-com`` -> ``PUBLISHER_AUTH_SPOKESMAN_COM_USERNAME``
         / ``..._PASSWORD``. Useful for local runs and single-publisher pods.
      2. GCP Secret Manager: the secret payload is a JSON object with
         ``{"username": ..., "password": ...}``.

    Returns ``(None, None)`` if the credentials cannot be resolved.
    """
    if not secret_name:
        return None, None

    key = re.sub(r"[^A-Z0-9]+", "_", secret_name.upper()).strip("_")
    env_user = os.getenv(f"{key}_USERNAME")
    env_pass = os.getenv(f"{key}_PASSWORD")
    if env_user and env_pass:
        return env_user, env_pass

    payload = _load_secret_payload(secret_name, project)
    if payload:
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            logger.warning("Auth secret '%s' payload is not valid JSON", secret_name)
            return None, None
        return data.get("username"), data.get("password")

    return None, None


def _load_secret_payload(secret_name: str, project: Optional[str]) -> Optional[str]:
    """Fetch the raw payload of a GCP Secret Manager secret, or None."""
    try:
        from google.cloud import secretmanager  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning(
            "Cannot resolve auth secret '%s': google-cloud-secret-manager "
            "unavailable: %s",
            secret_name,
            exc,
        )
        return None

    resource = secret_name
    if "/" not in resource:
        project = (
            project or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        )
        if not project:
            logger.warning(
                "Auth secret '%s' configured but no GCP project env set",
                secret_name,
            )
            return None
        resource = f"projects/{project}/secrets/{secret_name}/versions/latest"

    try:
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": resource})
        return response.payload.data.decode("utf-8").strip()
    except Exception as exc:  # pragma: no cover - network/API failure
        logger.error("Failed to load auth secret '%s': %s", resource, exc)
        return None


def build_auth0_authorize_url(
    domain: str, client_id: str, redirect_uri: str, scope: str
) -> str:
    """Build a valid Auth0 ``/authorize`` URL with a self-generated PKCE pair.

    The Universal Login form only renders when reached via ``/authorize`` with a
    fresh, valid state/nonce/code_challenge, so we generate our own request.
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
    return f"https://{domain}/authorize?" + urllib.parse.urlencode(params)


def _find_first(driver, selectors):
    """Return the first visible element matching any of the given selectors."""
    for sel in [s for s in selectors if s]:
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


def _fill_and_submit(driver, cfg: dict, username: str, password: str) -> bool:
    """Fill the login form and submit, handling identifier-first flows.

    Returns True if the credentials were entered and submitted, False if the
    form fields could not be located.
    """
    email_sel = cfg.get("email_selector")
    pass_sel = cfg.get("password_selector")
    submit_sel = cfg.get("submit_selector")

    # The form may be rendered by JS after load; poll for the email field.
    email_el = None
    deadline = time.time() + 20
    while time.time() < deadline:
        email_el, _ = _find_first(driver, [email_sel, *EMAIL_CANDIDATES])
        if email_el:
            break
        time.sleep(1)
    if not email_el:
        logger.warning("Authenticated login: username/email field not found")
        return False

    email_el.clear()
    email_el.send_keys(username)

    # Password may be on the same screen or a second (identifier-first) step.
    pass_el, _ = _find_first(driver, [pass_sel, *PASSWORD_CANDIDATES])
    if not pass_el:
        cont_el, _ = _find_first(driver, [submit_sel, *SUBMIT_CANDIDATES])
        if cont_el:
            cont_el.click()
        else:
            email_el.send_keys(Keys.RETURN)
        pdeadline = time.time() + 15
        while time.time() < pdeadline:
            pass_el, _ = _find_first(driver, [pass_sel, *PASSWORD_CANDIDATES])
            if pass_el:
                break
            time.sleep(1)
    if not pass_el:
        logger.warning("Authenticated login: password field not found")
        return False

    pass_el.clear()
    pass_el.send_keys(password)

    submit_el, _ = _find_first(driver, [submit_sel, *SUBMIT_CANDIDATES])
    if submit_el:
        submit_el.click()
    else:
        pass_el.send_keys(Keys.RETURN)
    return True


def _login_auth0(driver, cfg: dict, username: str, password: str) -> bool:
    domain = cfg.get("auth0_domain")
    client_id = cfg.get("client_id")
    redirect_uri = cfg.get("redirect_uri")
    if not (domain and client_id and redirect_uri):
        logger.warning(
            "auth0 login requires auth0_domain, client_id and redirect_uri "
            "in auth_config"
        )
        return False

    authorize_url = build_auth0_authorize_url(
        domain, client_id, redirect_uri, cfg.get("scope", "openid profile email")
    )
    try:
        driver.set_page_load_timeout(45)
    except Exception:
        pass
    try:
        driver.get(authorize_url)
    except Exception as exc:
        logger.warning("auth0 login: navigation to authorize URL failed: %s", exc)

    if not _fill_and_submit(driver, cfg, username, password):
        return False

    # Success = Auth0 redirects back to the app callback (off the login domain,
    # or carrying an authorization ?code=).
    def _redirected(d):
        cur = d.current_url
        return (domain not in cur) or ("code=" in cur)

    try:
        WebDriverWait(driver, 25).until(_redirected)
    except Exception:
        pass
    time.sleep(3)
    current = driver.current_url
    return (domain not in current) or ("code=" in current)


def _login_form(driver, cfg: dict, username: str, password: str) -> bool:
    login_url = cfg.get("login_url")
    if not login_url:
        logger.warning("form login requires login_url in auth_config")
        return False

    try:
        driver.set_page_load_timeout(45)
    except Exception:
        pass
    try:
        driver.get(login_url)
    except Exception as exc:
        logger.warning("form login: navigation to login URL failed: %s", exc)

    if not _fill_and_submit(driver, cfg, username, password):
        return False

    time.sleep(3)
    left_login_page = driver.current_url != login_url
    success_text = (cfg.get("success_text") or "").strip()
    success_text_seen = False
    if success_text:
        try:
            success_text_seen = success_text.lower() in driver.page_source.lower()
        except Exception:
            success_text_seen = False
    # A session-establishing form login typically navigates away from the login
    # page and/or exposes an account marker.
    return left_login_page or success_text_seen


def perform_login(
    driver,
    *,
    auth_type: Optional[str],
    auth_config: Optional[dict],
    username: str,
    password: str,
) -> bool:
    """Log into a publisher on ``driver``. Returns True on success.

    ``auth_type`` selects the mechanism ('auth0' or 'form'). ``auth_config``
    carries the non-secret parameters (domain/client_id/redirect_uri/scope for
    auth0; login_url/selectors/success_text for form).
    """
    cfg = auth_config or {}
    if not (username and password):
        logger.warning("Authenticated login: missing username or password")
        return False

    mechanism = (auth_type or "form").lower()
    try:
        if mechanism == "auth0":
            return _login_auth0(driver, cfg, username, password)
        return _login_form(driver, cfg, username, password)
    except Exception as exc:
        logger.error("Authenticated login raised: %s", exc, exc_info=True)
        return False
