"""Authenticated login for subscriber / paywalled publishers.

Drives a browser login on an existing Selenium driver so that the resulting
session cookies carry through to subsequent (paywalled) article fetches. Whether
any individual story is paywalled is decided dynamically by the publisher; this
module simply establishes an authenticated session for the domain.

Five login mechanisms are supported:

* ``auth0`` – Auth0 Universal Login (OAuth2 / OIDC with PKCE). The form only
  renders when reached via ``/authorize`` with a fresh, valid
  state/nonce/code_challenge, so we build our own authorize request. Success is
  proven when Auth0 redirects back to the application callback with a ``code=``
  (i.e. the credentials were accepted).
* ``form`` – a plain username/password login form POST.
* ``newzware`` – the Newzware subscription platform's SSO handoff, where the
  publisher's login page redirects to a separate Newzware host that validates
  the credentials and posts a signed handoff back to the publisher.
* ``simplecirc`` – the SimpleCirc subscriber form, which has no password: the
  subscriber authenticates with their email (or account number) plus the
  billing ZIP code on the account.
* ``etype`` – the eType Services metered paywall, whose login form is guarded
  by an invisible reCAPTCHA v3 that locks the submit button until Google's
  script resolves. The form is submitted directly to sidestep that lock.

The password-based mechanisms handle "identifier-first" flows where the password
field only appears after the email is submitted.

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


#: Find a login form by its SHAPE rather than by guessing attribute names.
#:
#: The candidate lists above key on `type`, `name`, `id` and `autocomplete`, and
#: component-framework markup often sets none of them. Connext is the case on
#: record: its inputs are `input.connext-login-a-cep-login__input` with no id, no
#: name and no autocomplete -- class only -- so not one of EMAIL_CANDIDATES can
#: match, and yakimaherald needed every selector configured by hand. A longer list
#: does not reach a class-only input; a different question does.
#:
#: The question browsers ask: `input[type="password"]` is near-universal, because
#: a password manager has to find it too and the browser's own autofill depends on
#: it. So anchor there and work outwards structurally:
#:
#:   1. every VISIBLE password input is a candidate anchor
#:   2. its scope is the enclosing form (or the nearest container holding inputs,
#:      for modals built out of divs)
#:   3. the username is the nearest visible text-like input BEFORE it in that
#:      scope -- which is why a header search box cannot be picked: different form,
#:      and never between a label and its password
#:   4. the submit control comes from the scope by role, not by name
#:
#: Scopes holding exactly one password input are preferred, because two means a
#: registration or change-password form rather than a login.
#:
#: This does not replace configured selectors. Those still win, so a host that has
#: been witnessed keeps behaving exactly as it did.
LOGIN_FIELD_DISCOVERY_JS = r"""
const TEXTISH = new Set(["text", "email", "tel", "", null, undefined]);
const SEARCHY = /search|query|^q$|keyword/i;
const SUBMITTY = /log ?in|sign ?in|continue|next|submit|enter/i;

function visible(el) {
  if (!el || el.disabled || el.readOnly) return false;
  if (el.type === "hidden") return false;
  if (!el.getClientRects().length && el.offsetParent === null) return false;
  const s = window.getComputedStyle(el);
  return s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0";
}

function scopeOf(el) {
  const form = el.closest("form");
  if (form) return form;
  // Modals are often divs. Walk up until a container holds another input.
  let node = el.parentElement;
  while (node && node !== document.body) {
    if (node.querySelectorAll("input").length > 1) return node;
    node = node.parentElement;
  }
  return document.body;
}

function textish(el) {
  if (el.tagName !== "INPUT") return false;
  const t = (el.getAttribute("type") || "").toLowerCase();
  if (!TEXTISH.has(t)) return false;
  const hay = [el.name, el.id, el.placeholder, el.getAttribute("aria-label")]
    .filter(Boolean).join(" ");
  return !SEARCHY.test(hay);
}

function submitIn(scope) {
  const explicit = [...scope.querySelectorAll(
    'button[type="submit"], input[type="submit"]')].filter(visible);
  if (explicit.length) return explicit[explicit.length - 1];
  const buttons = [...scope.querySelectorAll(
    'button, [role="button"], input[type="button"]')].filter(visible);
  const named = buttons.filter(b => SUBMITTY.test(
    (b.innerText || b.value || b.getAttribute("aria-label") || "")));
  if (named.length) return named[named.length - 1];
  return buttons.length ? buttons[buttons.length - 1] : null;
}

const anchors = [...document.querySelectorAll('input[type="password"]')]
  .filter(visible);

let best = null;
for (const pw of anchors) {
  const scope = scopeOf(pw);
  const passwords = [...scope.querySelectorAll('input[type="password"]')]
    .filter(visible);
  const all = [...scope.querySelectorAll("input")].filter(visible);
  const before = all.slice(0, all.indexOf(pw)).filter(textish);
  const candidate = {
    password: pw,
    email: before.length ? before[before.length - 1] : null,
    submit: submitIn(scope),
    // One password field means a login. Two means registration or a change.
    score: (passwords.length === 1 ? 4 : 0)
         + (before.length ? 2 : 0)
         + (submitIn(scope) ? 1 : 0),
  };
  if (!best || candidate.score > best.score) best = candidate;
}

if (best) {
  return {email: best.email, password: best.password, submit: best.submit,
          why: "anchored on a visible password input"};
}

// Identifier-first: the password is on a later screen, so there is nothing to
// anchor on yet. Accept a lone text-like input in a scope that can submit.
const lone = [...document.querySelectorAll("input")].filter(visible).filter(textish);
for (const el of lone) {
  const scope = scopeOf(el);
  if ([...scope.querySelectorAll('input[type="password"]')].length) continue;
  const submit = submitIn(scope);
  if (!submit) continue;
  return {email: el, password: null, submit: submit,
          why: "identifier-first: no password field on this screen"};
}
return null;
"""


def discover_login_fields(driver) -> dict:
    """Locate the login fields by shape. Returns {} when nothing looks like one.

    Never raises: discovery is an improvement on a guess, so a page that defeats
    it must fall back rather than fail the login.
    """
    try:
        found = driver.execute_script(LOGIN_FIELD_DISCOVERY_JS)
    except Exception as exc:  # pragma: no cover - driver/JS variety
        logger.debug("login field discovery failed: %s", exc)
        return {}
    if not isinstance(found, dict) or not found.get("email"):
        return {}
    logger.info("Login form found by shape (%s)", found.get("why"))
    return found


# Credential fields a publisher secret may carry. Most publishers authenticate
# with username + password; SimpleCirc publishers authenticate with the
# subscriber's email + billing ZIP (or account number + ZIP) and have no
# password at all.
CREDENTIAL_FIELDS = ("username", "password", "zip", "account_id")


def resolve_auth_credentials(
    secret_name: Optional[str], project: Optional[str] = None
) -> dict:
    """Resolve the full credential payload for a publisher secret.

    Resolution order:
      1. Environment override keyed by the normalized secret name, e.g. secret
         ``publisher-auth-spokesman-com`` -> ``PUBLISHER_AUTH_SPOKESMAN_COM_USERNAME``
         / ``..._PASSWORD`` (also ``..._ZIP`` / ``..._ACCOUNT_ID``). Useful for
         local runs and single-publisher pods.
      2. GCP Secret Manager: the secret payload is a JSON object, e.g.
         ``{"username": ..., "password": ...}`` or, for SimpleCirc publishers,
         ``{"username": ..., "zip": ...}``.

    Returns ``{}`` if the credentials cannot be resolved. The environment
    override only applies when it yields a username plus at least one secret
    field, so a partially-set environment falls through to Secret Manager.
    """
    if not secret_name:
        return {}

    key = re.sub(r"[^A-Z0-9]+", "_", secret_name.upper()).strip("_")
    env_creds = {
        field: os.getenv(f"{key}_{field.upper()}")
        for field in CREDENTIAL_FIELDS
        if os.getenv(f"{key}_{field.upper()}")
    }
    if env_creds.get("username") and len(env_creds) > 1:
        return env_creds

    payload = _load_secret_payload(secret_name, project)
    if payload:
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            logger.warning("Auth secret '%s' payload is not valid JSON", secret_name)
            return {}
        if not isinstance(data, dict):
            logger.warning("Auth secret '%s' payload is not a JSON object", secret_name)
            return {}
        return {k: v for k, v in data.items() if k in CREDENTIAL_FIELDS and v}

    return {}


def resolve_credentials(
    secret_name: Optional[str], project: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Resolve ``(username, password)`` for a publisher secret.

    Convenience wrapper over :func:`resolve_auth_credentials` for the
    password-based mechanisms. Returns ``(None, None)`` when unresolvable.
    """
    creds = resolve_auth_credentials(secret_name, project)
    return creds.get("username"), creds.get("password")


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


def _wait_for(driver, predicate, timeout: float) -> bool:
    """Poll ``predicate(driver)`` until it is true or ``timeout`` seconds pass."""
    deadline = time.time() + timeout
    while True:
        try:
            if predicate(driver):
                return True
        except Exception:
            pass
        if time.time() >= deadline:
            return False
        time.sleep(1)


def _page_source(driver) -> str:
    try:
        return driver.page_source or ""
    except Exception:
        return ""


def _fill_and_submit(driver, cfg: dict, username: str, password: str) -> bool:
    """Fill the login form and submit, handling identifier-first flows.

    Returns True if the credentials were entered and submitted, False if the
    form fields could not be located.
    """
    email_sel = cfg.get("email_selector")
    pass_sel = cfg.get("password_selector")
    submit_sel = cfg.get("submit_selector")

    # The form may be rendered by JS after load; poll for the email field.
    # The timeout is config-overridable (tests use a tiny value so a login
    # page with no fields fails fast instead of polling for 20s).
    email_el = None
    discovered: dict = {}
    field_timeout = float(cfg.get("field_timeout", 20))
    deadline = time.time() + field_timeout
    while True:
        # Configured selectors first, always. A host that has been witnessed with
        # explicit selectors must keep behaving exactly as it did -- discovery is
        # for the hosts nobody has configured, not a second opinion on the ones
        # that work.
        email_el, _ = _find_first(driver, [email_sel, *EMAIL_CANDIDATES])
        if email_el:
            break
        # Then by shape. This is what reaches a class-only input, which no
        # attribute guess can.
        discovered = discover_login_fields(driver)
        if discovered.get("email"):
            email_el = discovered["email"]
            break
        if time.time() >= deadline:
            break
        time.sleep(1)
    if not email_el:
        logger.warning(
            "Authenticated login: username/email field not found "
            "(no configured selector matched, and no password-anchored form "
            "was visible to work outwards from)"
        )
        return False

    email_el.clear()
    email_el.send_keys(username)

    # Password may be on the same screen or a second (identifier-first) step.
    pass_el, _ = _find_first(driver, [pass_sel, *PASSWORD_CANDIDATES])
    if not pass_el:
        pass_el = discovered.get("password")
    if not pass_el:
        cont_el, _ = _find_first(driver, [submit_sel, *SUBMIT_CANDIDATES])
        if not cont_el:
            cont_el = discovered.get("submit")
        if cont_el:
            cont_el.click()
        else:
            email_el.send_keys(Keys.RETURN)
        pdeadline = time.time() + 15
        while time.time() < pdeadline:
            pass_el, _ = _find_first(driver, [pass_sel, *PASSWORD_CANDIDATES])
            if pass_el:
                break
            # The second screen is a new DOM, so discovery runs again rather than
            # reusing the handles found before the identifier was submitted.
            again = discover_login_fields(driver)
            if again.get("password"):
                pass_el = again["password"]
                discovered = again
                break
            time.sleep(1)
    if not pass_el:
        logger.warning("Authenticated login: password field not found")
        return False

    pass_el.clear()
    pass_el.send_keys(password)

    submit_el, _ = _find_first(driver, [submit_sel, *SUBMIT_CANDIDATES])
    if not submit_el:
        # By shape: the scope's submit control, found by role and by what its
        # label says, not by a name we guessed.
        submit_el = discovered.get("submit")
    if submit_el:
        try:
            submit_el.click()
        except Exception:
            # Some publisher pages overlay ad/cookie elements above the submit
            # button; retry via JS click or Enter as a resilient fallback.
            try:
                driver.execute_script("arguments[0].click();", submit_el)
            except Exception:
                pass_el.send_keys(Keys.RETURN)
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

    # Success = Auth0 redirects back to the app callback (off the login host,
    # or carrying an authorization ?code=). Compare the URL's host rather than
    # substring-testing the domain, so a callback URL that merely echoes the
    # Auth0 domain in a query param (e.g. ?returnTo=https://tenant.auth0.com/…)
    # isn't misread as success.
    def _off_auth0_host(url: str) -> bool:
        return urllib.parse.urlparse(url).netloc != domain

    def _redirected(d):
        cur = d.current_url
        return _off_auth0_host(cur) or ("code=" in cur)

    try:
        WebDriverWait(driver, 25).until(_redirected)
    except Exception:
        pass
    time.sleep(3)
    current = driver.current_url
    return _off_auth0_host(current) or ("code=" in current)


def _login_form(driver, cfg: dict, username: str, password: str) -> bool:
    login_url = cfg.get("login_url")
    if not login_url:
        logger.warning("form login requires login_url in auth_config")
        return False
    trigger_sel = cfg.get("login_trigger_selector")

    try:
        driver.set_page_load_timeout(45)
    except Exception:
        pass
    try:
        driver.get(login_url)
    except Exception as exc:
        logger.warning("form login: navigation to login URL failed: %s", exc)

    # Some publishers (e.g., Connext) render login fields in a modal that opens
    # only after clicking a login trigger on the homepage.
    if trigger_sel:
        # POLL FOR IT. Looked up once, immediately after `driver.get()`, this
        # found nothing on www.yakimaherald.com: Connext renders the control
        # with JS and it is not in the DOM yet. The modal was therefore never
        # opened, and `_fill_and_submit` then polled twenty seconds for a field
        # that could not exist -- two warnings, both true, neither naming the
        # cause:
        #
        #   16:43:01  form login: login trigger selector '...' not found
        #   16:43:41  Authenticated login: username/email field not found
        #
        # Measured in Playwright against the same page: at 3 seconds both
        # controls read as not displayed; at 5-6 seconds they are displayed and
        # the login completes, with Connext's /api/user answering 200.
        #
        # The asymmetry was the defect -- the field that the modal contains got
        # a 20-second poll, the trigger that OPENS the modal got none. Same
        # budget for both.
        trigger = None
        trigger_deadline = time.time() + float(cfg.get("field_timeout", 20))
        while True:
            trigger, _ = _find_first(driver, [trigger_sel])
            if trigger or time.time() >= trigger_deadline:
                break
            time.sleep(1)
        if trigger:
            try:
                trigger.click()
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", trigger)
                except Exception as exc:
                    logger.warning(
                        "form login: failed to click login trigger '%s': %s",
                        trigger_sel,
                        exc,
                    )
            # The modal it opens is rendered by JS too. One second was optimistic
            # -- Playwright needed about six against this host -- and being wrong
            # here is indistinguishable from a wrong selector, because what fails
            # is the field lookup afterwards.
            time.sleep(float(cfg.get("modal_delay", 5)))
        else:
            logger.warning(
                "form login: login trigger selector '%s' not found",
                trigger_sel,
            )

    if not _fill_and_submit(driver, cfg, username, password):
        return False

    time.sleep(3)
    current_url = driver.current_url
    login_path = urllib.parse.urlparse(login_url).path.rstrip("/")
    current_path = urllib.parse.urlparse(current_url).path.rstrip("/")
    left_login_page = current_path != login_path
    trigger_disappeared = False
    if trigger_sel:
        try:
            still_visible, _ = _find_first(driver, [trigger_sel])
            trigger_disappeared = still_visible is None
        except Exception:
            trigger_disappeared = False
    success_text = (cfg.get("success_text") or "").strip()
    success_text_seen = False
    if success_text:
        try:
            success_text_seen = success_text.lower() in driver.page_source.lower()
        except Exception:
            success_text_seen = False
    # An affirmative answer wins outright, in both directions: a configured
    # cookie that is present means logged in, and one that is absent means not
    # -- the weaker proxies must not overrule it, because they are what reported
    # success on a session that was serving walls.
    confirmed = _session_cookie_present(driver, cfg)
    if confirmed is not None:
        return confirmed

    # No cookie configured. A session-establishing form login typically
    # navigates away from the login page and/or exposes an account marker. For
    # homepage modal logins the URL may stay unchanged, so treat disappearance
    # of the visible login trigger as a success marker as well. All three are
    # guesses; `success_cookie` is how a host stops guessing.
    return left_login_page or success_text_seen or trigger_disappeared


def _login_newzware(driver, cfg: dict, username: str, password: str) -> bool:
    """Log in through the Newzware SSO handoff (e.g. The Columbian).

    The publisher's login page redirects to the Newzware subscription system on
    a separate host, which renders its login form client-side. Newzware
    validates the credentials there and then auto-POSTs a signed handoff
    (``login_id`` + ``hash``) back to the publisher, which is what actually
    establishes the publisher-side session cookie.

    Success therefore means all three of: we came back to the publisher host, we
    are not sitting on the login page again, and Newzware did not show its
    credential-rejection message. The plain ``form`` mechanism cannot be used
    here — it compares URL *paths* to decide success, and the cross-domain
    redirect to Newzware changes the path immediately, so a failed login would
    look like a successful one.
    """
    login_url = cfg.get("login_url")
    if not login_url:
        logger.warning("newzware login requires login_url in auth_config")
        return False

    login_parts = urllib.parse.urlparse(login_url)
    return_host = cfg.get("return_host") or login_parts.netloc
    login_path = login_parts.path.rstrip("/")
    failure_text = cfg.get("failure_text", "could not be validated")
    return_timeout = float(cfg.get("return_timeout", 30))

    try:
        driver.set_page_load_timeout(45)
    except Exception:
        pass
    try:
        driver.get(login_url)
    except Exception as exc:
        logger.warning("newzware login: navigation to login URL failed: %s", exc)

    # The Newzware form is rendered by JS after load; _fill_and_submit polls.
    if not _fill_and_submit(driver, cfg, username, password):
        return False

    def _back_on_publisher(d):
        return urllib.parse.urlparse(d.current_url).netloc == return_host

    _wait_for(driver, _back_on_publisher, return_timeout)
    # The handoff POST lands on the publisher and then redirects onward; give
    # the session cookie a moment to be set before we judge the outcome.
    time.sleep(3)

    current = urllib.parse.urlparse(driver.current_url)
    if current.netloc != return_host:
        if failure_text and failure_text.lower() in _page_source(driver).lower():
            logger.warning("newzware login: credentials were rejected")
        else:
            logger.warning(
                "newzware login: never returned to %s (still at %s)",
                return_host,
                current.netloc,
            )
        return False

    if current.path.rstrip("/") == login_path:
        logger.warning("newzware login: bounced back to the login page")
        return False

    success_text = (cfg.get("success_text") or "").strip()
    if success_text and success_text.lower() not in _page_source(driver).lower():
        logger.warning(
            "newzware login: success marker '%s' not found after handoff",
            success_text,
        )
        return False
    return True


# SimpleCirc's WordPress login widget. Defaults are deliberately narrow: the
# publisher's login page also carries an unrelated "Admin Login Only" form, and
# the broad EMAIL_/PASSWORD_CANDIDATES lists would straddle the two forms.
SIMPLECIRC_EMAIL_SELECTOR = 'form[action*="admin-post.php"] input[name="email"]'
SIMPLECIRC_ZIP_SELECTOR = 'form[action*="admin-post.php"] input[name="zip"]'
SIMPLECIRC_SUBMIT_SELECTOR = 'form[action*="admin-post.php"] button[type="submit"]'


def session_signature(auth_config: dict | None) -> frozenset[str]:
    """The cookie NAMES a witnessed login for this host left behind.

    Read from `auth_config.witnessed.first_party_cookies_added`, which is already
    session-only: the infrastructure and ad-tech families were partitioned out
    before it was stored, so a load balancer's affinity cookie cannot end up
    standing in for a login.

    Names, never values. Values change every session and were deliberately never
    recorded; names do not. `wordpress_logged_in_9e191e36...` looks like a value
    but is a stable per-site name -- WordPress hashes the site URL into it -- so an
    exact match per host is right and a match across hosts would be wrong.

    An empty set means this host proved itself some other way. `etype` and `auth0`
    both do: their evidence is a redirect during the login and there is no cookie
    to look for afterwards. Empty is therefore a real answer and the caller must
    distinguish it from "the cookies are gone".
    """
    witnessed = ((auth_config or {}).get("witnessed") or {}) if auth_config else {}
    added = witnessed.get("first_party_cookies_added") or []
    names = set()
    for key in added:
        if not isinstance(key, str):
            continue
        # Stored as `name@domain`; the name is what survives a new session.
        names.add(key.split("@", 1)[0].strip())
    return frozenset(n for n in names if n)


def session_still_held(driver, signature: frozenset[str]) -> bool | None:
    """Whether the driver still carries the cookies that witnessed login left.

    `None` when there is nothing to check -- an empty signature, or a driver that
    cannot be read. None is NOT False: a host whose proof was a redirect has no
    cookie to lose, and reporting it as lapsed would refuse every fetch on it.

    Free to call at fetch time. `get_cookies()` is scoped to the current
    document's origin and at that point the driver is already standing on the
    publisher's page, which is exactly the origin the witness measured.
    """
    if not signature:
        return None
    try:
        held = {c.get("name") for c in (driver.get_cookies() or [])}
    except Exception as exc:  # pragma: no cover - driver fault is not a verdict
        logger.debug("could not read cookies to confirm the session: %s", exc)
        return None
    return bool(signature & held)


def _session_cookie_present(driver, cfg: dict) -> bool | None:
    """Whether the cookie a logged-in session carries is in the jar.

    THE ONLY AFFIRMATIVE CONFIRMATION AVAILABLE. Every other check is a proxy
    for the answer: whether the URL changed, whether a word appears in the page
    source, whether a login button went away. On a homepage modal login none of
    them is reliable, and on 2026-09-20 `www.yakimaherald.com` reported "did not
    confirm" on a login whose session was working -- then, later in the same run,
    reported the same thing on a login that was NOT working and served a wall,
    which the furniture rule filed as `not_article`. Two opposite states,
    indistinguishable in the log.

    A cookie is the session. Configure the name per host in
    `sources.auth_config.success_cookie` -- it is a DB column, so a wrong guess
    is a row edit rather than a deploy.

    Returns None when no cookie is configured, so the caller can fall back to
    the weaker checks rather than treating "not configured" as "not logged in".
    """
    name = (cfg.get("success_cookie") or "").strip()
    if not name:
        return None
    try:
        cookies = {c.get("name", "") for c in (driver.get_cookies() or [])}
    except Exception as exc:
        logger.warning("could not read cookies to confirm the session: %s", exc)
        return False
    if name in cookies:
        logger.info("session confirmed: cookie %r is set", name)
        return True
    logger.warning(
        "session NOT confirmed: cookie %r is absent (jar holds %d cookies)",
        name,
        len(cookies),
    )
    return False


def _login_simplecirc(driver, cfg: dict, creds: dict) -> bool:
    """Log in through a SimpleCirc subscriber form (e.g. Port Townsend Leader).

    SimpleCirc publishers do not authenticate with a password: the subscriber
    identifies with their email address (or account number) plus the billing ZIP
    code on the account. The form posts to the WordPress ``admin-post.php``
    handler, which establishes the session and redirects back to the login page,
    so success cannot be judged by the URL changing — we judge it by the login
    form no longer being on the page (plus an optional success marker).
    """
    login_url = cfg.get("login_url")
    if not login_url:
        logger.warning("simplecirc login requires login_url in auth_config")
        return False

    identifier = creds.get("username") or creds.get("account_id")
    zip_code = creds.get("zip")
    if not (identifier and zip_code):
        logger.warning(
            "simplecirc login requires a username/account_id and a zip in the "
            "credential secret"
        )
        return False

    email_sel = cfg.get("email_selector") or SIMPLECIRC_EMAIL_SELECTOR
    zip_sel = cfg.get("zip_selector") or SIMPLECIRC_ZIP_SELECTOR
    submit_sel = cfg.get("submit_selector") or SIMPLECIRC_SUBMIT_SELECTOR
    form_timeout = float(cfg.get("form_timeout", 20))

    try:
        driver.set_page_load_timeout(45)
    except Exception:
        pass
    try:
        driver.get(login_url)
    except Exception as exc:
        logger.warning("simplecirc login: navigation to login URL failed: %s", exc)

    email_el = None

    def _form_present(d):
        nonlocal email_el
        email_el, _ = _find_first(d, [email_sel])
        return email_el is not None

    if not _wait_for(driver, _form_present, form_timeout):
        logger.warning("simplecirc login: subscriber email field not found")
        return False

    zip_el, _ = _find_first(driver, [zip_sel])
    if not zip_el:
        logger.warning("simplecirc login: zip field not found")
        return False

    email_el.clear()
    email_el.send_keys(identifier)
    zip_el.clear()
    zip_el.send_keys(zip_code)

    submit_el, _ = _find_first(driver, [submit_sel])
    if submit_el:
        try:
            submit_el.click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", submit_el)
            except Exception:
                zip_el.send_keys(Keys.RETURN)
    else:
        zip_el.send_keys(Keys.RETURN)

    time.sleep(3)

    failure_text = (cfg.get("failure_text") or "").strip()
    if failure_text and failure_text.lower() in _page_source(driver).lower():
        logger.warning("simplecirc login: credentials were rejected")
        return False

    success_text = (cfg.get("success_text") or "").strip()
    if success_text:
        return success_text.lower() in _page_source(driver).lower()

    # No explicit marker configured: a failed login re-renders the login form,
    # so the form's disappearance is the signal that the session was created.
    still_showing_form, _ = _find_first(driver, [email_sel])
    if still_showing_form is not None:
        logger.warning("simplecirc login: login form still present after submit")
        return False
    return True


# The eType login form. Selectors are keyed off the Symfony form name rather
# than the generic candidate lists, because the login field is a bare
# ``type="text"`` input named ``etype_login[login]`` — it carries neither
# "email" nor "user" in its name or id, so EMAIL_CANDIDATES cannot find it.
ETYPE_FORM_NAME = "etype_login"
ETYPE_LOGIN_SELECTOR = 'form[name="etype_login"] input[name="etype_login[login]"]'
ETYPE_PASSWORD_SELECTOR = 'form[name="etype_login"] input[name="etype_login[password]"]'
# eType returns one generic message for a bad password, an unknown account and
# a lapsed subscription alike.
ETYPE_FAILURE_TEXT = "Incorrect login details or subscription has expired"


def _login_etype(driver, cfg: dict, username: str, password: str) -> bool:
    """Log in through an eType Services paywall (e.g. the Newport Miner).

    eType meters access with an ``_etype_fv`` cookie carrying ``{count, total}``
    — a small daily allowance of full articles, after which the publisher serves
    a truncated stub. An authenticated session is not metered at all, so the
    cookie is never set once this succeeds.

    The form cannot be driven by clicking its submit button. The page loads
    reCAPTCHA v3 (``<body data-rc="...">``) and holds a ``buttonLock`` on the
    submit handler until Google's script resolves a token into the hidden
    ``etype_login[recaptcha_response]`` field. In a headless pod that script is
    slow, proxied, or scored as automation, so the click can hang indefinitely.
    The server does not actually verify the token, so we fill the fields and
    call ``HTMLFormElement.submit()``, which bypasses the onsubmit handler (and
    therefore the lock) entirely.
    """
    login_url = cfg.get("login_url")
    if not login_url:
        logger.warning("etype login requires login_url in auth_config")
        return False

    login_sel = cfg.get("email_selector") or ETYPE_LOGIN_SELECTOR
    pass_sel = cfg.get("password_selector") or ETYPE_PASSWORD_SELECTOR
    form_timeout = float(cfg.get("form_timeout", 20))
    failure_text = cfg.get("failure_text", ETYPE_FAILURE_TEXT)

    try:
        driver.set_page_load_timeout(45)
    except Exception:
        pass
    try:
        driver.get(login_url)
    except Exception as exc:
        logger.warning("etype login: navigation to login URL failed: %s", exc)

    login_el = None

    def _form_present(d):
        nonlocal login_el
        login_el, _ = _find_first(d, [login_sel])
        return login_el is not None

    if not _wait_for(driver, _form_present, form_timeout):
        logger.warning("etype login: login field not found")
        return False

    pass_el, _ = _find_first(driver, [pass_sel])
    if not pass_el:
        logger.warning("etype login: password field not found")
        return False

    login_el.clear()
    login_el.send_keys(username)
    pass_el.clear()
    pass_el.send_keys(password)

    # Submit the form element itself, not the button — see the docstring.
    form_name = cfg.get("form_name") or ETYPE_FORM_NAME
    try:
        submitted = driver.execute_script(
            "var f = document.forms[arguments[0]];"
            "if (!f) { return false; } f.submit(); return true;",
            form_name,
        )
    except Exception as exc:
        logger.warning("etype login: direct form submit failed: %s", exc)
        return False
    if submitted is False:
        logger.warning("etype login: form '%s' not present on the page", form_name)
        return False

    time.sleep(3)

    if failure_text and failure_text.lower() in _page_source(driver).lower():
        logger.warning("etype login: credentials were rejected")
        return False

    # A rejected login re-renders the login form at the same path; a successful
    # one redirects to the site root (or to ``app_redirect`` when the login URL
    # carries one).
    login_path = urllib.parse.urlparse(login_url).path.rstrip("/")
    current_path = urllib.parse.urlparse(driver.current_url).path.rstrip("/")
    if current_path == login_path:
        logger.warning("etype login: still on the login page after submit")
        return False

    success_text = (cfg.get("success_text") or "").strip()
    if success_text and success_text.lower() not in _page_source(driver).lower():
        logger.warning(
            "etype login: success marker '%s' not found after submit", success_text
        )
        return False
    return True


def perform_login(
    driver,
    *,
    auth_type: Optional[str],
    auth_config: Optional[dict],
    username: Optional[str] = None,
    password: Optional[str] = None,
    credentials: Optional[dict] = None,
) -> bool:
    """Log into a publisher on ``driver``. Returns True on success.

    ``auth_type`` selects the mechanism ('auth0', 'form', 'newzware',
    'simplecirc' or 'etype'). ``auth_config`` carries the non-secret parameters
    (domain/client_id/redirect_uri/scope for auth0; login_url/selectors/
    success_text for form; login_url/return_host/success_text for newzware;
    login_url/selectors for simplecirc; login_url/selectors/failure_text for
    etype).

    Credentials may be passed either as ``username``/``password`` or as a
    ``credentials`` dict (see :func:`resolve_auth_credentials`). The dict form is
    required by mechanisms whose credentials are not a username/password pair —
    simplecirc authenticates with an email plus a billing ZIP code.
    """
    cfg = auth_config or {}
    creds = dict(credentials or {})
    if username:
        creds.setdefault("username", username)
    if password:
        creds.setdefault("password", password)

    mechanism = (auth_type or "form").lower()
    try:
        if mechanism == "simplecirc":
            return _login_simplecirc(driver, cfg, creds)

        # The remaining mechanisms are all username + password.
        user = creds.get("username")
        pw = creds.get("password")
        if not (user and pw):
            logger.warning("Authenticated login: missing username or password")
            return False
        if mechanism == "auth0":
            return _login_auth0(driver, cfg, user, pw)
        if mechanism == "newzware":
            return _login_newzware(driver, cfg, user, pw)
        if mechanism == "etype":
            return _login_etype(driver, cfg, user, pw)
        return _login_form(driver, cfg, user, pw)
    except Exception as exc:
        logger.error("Authenticated login raised: %s", exc, exc_info=True)
        return False
