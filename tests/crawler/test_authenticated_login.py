"""Unit tests for src.crawler.authenticated_login.

Covers the pure helpers (Auth0 authorize-URL/PKCE construction, credential
resolution) and the form-login flow using a lightweight fake Selenium driver.
No database or network access.
"""

from __future__ import annotations

import urllib.parse

import pytest
from selenium.webdriver.common.keys import Keys

from src.crawler import authenticated_login as al


# ---------------------------------------------------------------------------
# build_auth0_authorize_url
# ---------------------------------------------------------------------------
def test_build_auth0_authorize_url_contains_required_params():
    url = al.build_auth0_authorize_url(
        "login.example.com",
        "client123",
        "https://www.example.com/callback",
        "openid profile email",
    )
    assert url.startswith("https://login.example.com/authorize?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["client_id"] == ["client123"]
    assert query["redirect_uri"] == ["https://www.example.com/callback"]
    assert query["scope"] == ["openid profile email"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    # PKCE challenge and CSRF params must be present and non-empty.
    assert query["code_challenge"][0]
    assert query["state"][0]
    assert query["nonce"][0]


def test_build_auth0_authorize_url_is_single_use_per_call():
    a = al.build_auth0_authorize_url("d", "c", "r", "s")
    b = al.build_auth0_authorize_url("d", "c", "r", "s")
    # Fresh state/nonce/challenge each call (single-use, cannot be hardcoded).
    assert a != b


# ---------------------------------------------------------------------------
# resolve_credentials
# ---------------------------------------------------------------------------
def test_resolve_credentials_none_secret():
    assert al.resolve_credentials(None) == (None, None)
    assert al.resolve_credentials("") == (None, None)


def test_resolve_credentials_env_override(monkeypatch):
    # Secret name normalizes to an uppercase env prefix.
    monkeypatch.setenv("PUBLISHER_AUTH_SPOKESMAN_COM_USERNAME", "user@x.com")
    monkeypatch.setenv("PUBLISHER_AUTH_SPOKESMAN_COM_PASSWORD", "s3cret")
    user, pw = al.resolve_credentials("publisher-auth-spokesman-com")
    assert user == "user@x.com"
    assert pw == "s3cret"


def test_resolve_credentials_env_missing_falls_through(monkeypatch):
    # Only username present -> not a valid env override; no secret manager here.
    monkeypatch.setenv("PUBLISHER_AUTH_NOPE_USERNAME", "only-user")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    # With no GCP project and no secret manager payload, resolution fails.
    user, pw = al.resolve_credentials("publisher-auth-nope")
    assert (user, pw) == (None, None)


# ---------------------------------------------------------------------------
# Fake Selenium driver for exercising the login flow
# ---------------------------------------------------------------------------
class FakeElement:
    def __init__(self, tag="input", attrs=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.value = ""
        self.clicked = False

    def is_displayed(self):
        return True

    def clear(self):
        self.value = ""

    def send_keys(self, keys):
        self.value += str(keys)

    def click(self):
        self.clicked = True


class FakeDriver:
    """Minimal driver that matches CSS selectors against configured elements."""

    def __init__(
        self, elements_by_selector, *, login_url, success_url, landing_url=None
    ):
        # elements_by_selector: dict[str, list[FakeElement]]
        self._elements = elements_by_selector
        self._login_url = login_url
        self._success_url = success_url
        # Where a get() actually lands, when the site redirects elsewhere (e.g.
        # Newzware bouncing the login page to its own SSO host).
        self._landing_url = landing_url
        self.current_url = "about:blank"
        self.page_source = ""

    def set_page_load_timeout(self, _seconds):
        pass

    def get(self, url):
        self.current_url = self._landing_url or url

    def find_elements(self, _by, selector):
        return self._elements.get(selector, [])

    # Called by _fill_and_submit's submit click via FakeElement; simulate the
    # post-submit navigation to the logged-in page.
    def _navigate_to_success(self):
        self.current_url = self._success_url


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(al.time, "sleep", lambda *_a, **_k: None)


def test_perform_login_missing_credentials_returns_false():
    driver = FakeDriver({}, login_url="u", success_url="v")
    assert (
        al.perform_login(
            driver,
            auth_type="form",
            auth_config={"login_url": "u"},
            username="",
            password="",
        )
        is False
    )


def test_form_login_success(monkeypatch):
    email = FakeElement(attrs={"type": "email"})
    password = FakeElement(attrs={"type": "password"})
    submit = FakeElement(tag="button")

    login_url = "https://news.example.com/login"
    success_url = "https://news.example.com/account"

    elements = {
        'input[type="email"]': [email],
        'input[type="password"]': [password],
        'button[type="submit"]': [submit],
    }
    driver = FakeDriver(elements, login_url=login_url, success_url=success_url)

    # When the submit button is clicked, simulate navigation off the login page.
    def _click():
        submit.clicked = True
        driver.current_url = success_url

    submit.click = _click  # type: ignore[method-assign]

    ok = al.perform_login(
        driver,
        auth_type="form",
        auth_config={"login_url": login_url},
        username="user@example.com",
        password="pw",
    )
    assert ok is True
    assert email.value == "user@example.com"
    assert password.value == "pw"


def test_form_login_no_fields_returns_false(_no_sleep):
    login_url = "https://news.example.com/login"
    driver = FakeDriver({}, login_url=login_url, success_url="x")
    ok = al.perform_login(
        driver,
        auth_type="form",
        auth_config={
            "login_url": login_url,
            # The fields never appear (that's the point) — don't poll the
            # default 20s field_timeout waiting for them.
            "field_timeout": 0,
        },
        username="user@example.com",
        password="pw",
    )
    assert ok is False


def test_form_login_with_trigger_selector_clicks_trigger_before_submit():
    trigger = FakeElement(tag="a")
    email = FakeElement(attrs={"type": "text"})
    password = FakeElement(attrs={"type": "password"})
    submit = FakeElement(tag="button")

    login_url = "https://news.example.com/"
    success_url = "https://news.example.com/account"

    elements = {
        "a[data-mg2-action='login']": [trigger],
        ".modal-login-email": [email],
        ".modal-login-password": [password],
        ".modal-login-submit": [submit],
    }
    driver = FakeDriver(elements, login_url=login_url, success_url=success_url)

    def _submit_click():
        submit.clicked = True
        driver.current_url = success_url

    submit.click = _submit_click  # type: ignore[method-assign]

    ok = al.perform_login(
        driver,
        auth_type="form",
        auth_config={
            "login_url": login_url,
            "login_trigger_selector": "a[data-mg2-action='login']",
            "email_selector": ".modal-login-email",
            "password_selector": ".modal-login-password",
            "submit_selector": ".modal-login-submit",
        },
        username="user@example.com",
        password="pw",
    )
    assert ok is True
    assert trigger.clicked is True
    assert email.value == "user@example.com"
    assert password.value == "pw"


def test_form_login_with_trigger_disappearance_counts_as_success():
    trigger = FakeElement(tag="a")
    email = FakeElement(attrs={"type": "text"})
    password = FakeElement(attrs={"type": "password"})
    submit = FakeElement(tag="button")

    login_url = "https://news.example.com/"
    elements = {
        "a[data-mg2-action='login']": [trigger],
        ".modal-login-email": [email],
        ".modal-login-password": [password],
        ".modal-login-submit": [submit],
    }
    driver = FakeDriver(elements, login_url=login_url, success_url=login_url)

    def _submit_click():
        submit.clicked = True
        # Modal-style flow: same URL, but login trigger is no longer visible.
        driver._elements["a[data-mg2-action='login']"] = []

    submit.click = _submit_click  # type: ignore[method-assign]

    ok = al.perform_login(
        driver,
        auth_type="form",
        auth_config={
            "login_url": login_url,
            "login_trigger_selector": "a[data-mg2-action='login']",
            "email_selector": ".modal-login-email",
            "password_selector": ".modal-login-password",
            "submit_selector": ".modal-login-submit",
        },
        username="user@example.com",
        password="pw",
    )
    assert ok is True


def test_form_login_requires_login_url():
    driver = FakeDriver({}, login_url="x", success_url="y")
    ok = al.perform_login(
        driver,
        auth_type="form",
        auth_config={},
        username="user",
        password="pw",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# newzware (SSO handoff, e.g. The Columbian)
# ---------------------------------------------------------------------------
NEWZWARE_LOGIN_URL = "https://www.columbian.com/login/"
NEWZWARE_SSO_URL = (
    "https://columbian.newzware.com/ss70v2/columbian/common/template.jsp?nwmodule=sso"
)
NEWZWARE_REJECTION = "User name and password could not be validated."


def _newzware_driver(*, on_submit, page_source=""):
    """Driver that lands on the Newzware SSO host, as the real login page does."""
    email = FakeElement(attrs={"type": "email"})
    password = FakeElement(attrs={"type": "password"})
    submit = FakeElement(tag="button")
    driver = FakeDriver(
        {
            'input[type="email"]': [email],
            'input[type="password"]': [password],
            'button[type="submit"]': [submit],
        },
        login_url=NEWZWARE_LOGIN_URL,
        success_url=None,
        landing_url=NEWZWARE_SSO_URL,
    )
    driver.page_source = page_source
    submit.click = lambda: on_submit(driver)  # type: ignore[method-assign]
    return driver, email, password


def test_newzware_login_success_after_handoff_back_to_publisher():
    def _handoff(driver):
        # Newzware validates, then posts login_id+hash back to the publisher.
        driver.current_url = "https://www.columbian.com/process-login"
        driver.page_source = "<a>Log Out</a>"

    driver, email, password = _newzware_driver(on_submit=_handoff)

    ok = al.perform_login(
        driver,
        auth_type="newzware",
        auth_config={
            "login_url": NEWZWARE_LOGIN_URL,
            "success_text": "Log Out",
        },
        username="user@example.com",
        password="pw",
    )
    assert ok is True
    assert email.value == "user@example.com"
    assert password.value == "pw"


def test_newzware_login_rejected_credentials_stay_on_sso_host():
    # Bad credentials: Newzware shows its validation error and never hands off.
    driver, _email, _password = _newzware_driver(
        on_submit=lambda d: None, page_source=NEWZWARE_REJECTION
    )

    ok = al.perform_login(
        driver,
        auth_type="newzware",
        auth_config={"login_url": NEWZWARE_LOGIN_URL, "return_timeout": 0},
        username="user@example.com",
        password="wrong",
    )
    # The plain `form` mechanism would call this a success (the path changed
    # when we were redirected off /login/ to the SSO host), which is the whole
    # reason newzware needs its own success check.
    assert ok is False


def test_newzware_login_bounced_back_to_login_page_is_failure():
    def _bounce(driver):
        driver.current_url = NEWZWARE_LOGIN_URL

    driver, _email, _password = _newzware_driver(on_submit=_bounce)

    ok = al.perform_login(
        driver,
        auth_type="newzware",
        auth_config={"login_url": NEWZWARE_LOGIN_URL, "return_timeout": 0},
        username="user@example.com",
        password="pw",
    )
    assert ok is False


def test_newzware_login_missing_success_marker_is_failure():
    def _handoff(driver):
        driver.current_url = "https://www.columbian.com/process-login"
        driver.page_source = "<a>Subscribe</a>"

    driver, _email, _password = _newzware_driver(on_submit=_handoff)

    ok = al.perform_login(
        driver,
        auth_type="newzware",
        auth_config={
            "login_url": NEWZWARE_LOGIN_URL,
            "success_text": "Log Out",
            "return_timeout": 0,
        },
        username="user@example.com",
        password="pw",
    )
    assert ok is False


def test_newzware_login_requires_login_url():
    driver = FakeDriver({}, login_url="x", success_url="y")
    ok = al.perform_login(
        driver,
        auth_type="newzware",
        auth_config={},
        username="user",
        password="pw",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# simplecirc (email + billing ZIP, no password; e.g. Port Townsend Leader)
# ---------------------------------------------------------------------------
SIMPLECIRC_LOGIN_URL = "https://ptleader.com/login/"


def _simplecirc_driver(*, on_submit):
    email = FakeElement(attrs={"type": "email"})
    zip_field = FakeElement(attrs={"type": "text"})
    submit = FakeElement(tag="button")
    # The real page also carries an unrelated "Admin Login Only" form; include
    # its fields so a mechanism that reached for the generic candidate selectors
    # would visibly grab the wrong ones.
    admin_user = FakeElement(attrs={"type": "text"})
    admin_pass = FakeElement(attrs={"type": "password"})

    driver = FakeDriver(
        {
            al.SIMPLECIRC_EMAIL_SELECTOR: [email],
            al.SIMPLECIRC_ZIP_SELECTOR: [zip_field],
            al.SIMPLECIRC_SUBMIT_SELECTOR: [submit],
            'input[type="password"]': [admin_pass],
            'input[name="username"]': [admin_user],
        },
        login_url=SIMPLECIRC_LOGIN_URL,
        success_url=None,
    )
    submit.click = lambda: on_submit(driver)  # type: ignore[method-assign]
    return driver, email, zip_field, admin_pass


def test_simplecirc_login_success_when_form_disappears():
    def _logged_in(driver):
        # WordPress creates the session and re-renders the page without the form.
        driver._elements[al.SIMPLECIRC_EMAIL_SELECTOR] = []

    driver, email, zip_field, admin_pass = _simplecirc_driver(on_submit=_logged_in)

    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={"login_url": SIMPLECIRC_LOGIN_URL},
        credentials={"username": "sub@example.com", "zip": "98368"},
    )
    assert ok is True
    assert email.value == "sub@example.com"
    assert zip_field.value == "98368"
    # The admin-only password field must never be touched.
    assert admin_pass.value == ""


def test_simplecirc_login_failure_when_form_still_present():
    driver, _email, _zip, _admin = _simplecirc_driver(on_submit=lambda d: None)

    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={"login_url": SIMPLECIRC_LOGIN_URL},
        credentials={"username": "sub@example.com", "zip": "00000"},
    )
    assert ok is False


def test_simplecirc_login_honors_failure_text():
    def _rejected(driver):
        driver._elements[al.SIMPLECIRC_EMAIL_SELECTOR] = []
        driver.page_source = "No subscription found for that email and ZIP."

    driver, _email, _zip, _admin = _simplecirc_driver(on_submit=_rejected)

    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={
            "login_url": SIMPLECIRC_LOGIN_URL,
            "failure_text": "No subscription found",
        },
        credentials={"username": "sub@example.com", "zip": "00000"},
    )
    assert ok is False


def test_simplecirc_login_accepts_account_id_instead_of_email():
    def _logged_in(driver):
        driver._elements[al.SIMPLECIRC_EMAIL_SELECTOR] = []

    driver, email, zip_field, _admin = _simplecirc_driver(on_submit=_logged_in)

    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={"login_url": SIMPLECIRC_LOGIN_URL},
        credentials={"account_id": "123456", "zip": "98368"},
    )
    assert ok is True
    assert email.value == "123456"


def test_simplecirc_login_requires_zip():
    driver, _email, _zip, _admin = _simplecirc_driver(on_submit=lambda d: None)

    # A password is not a substitute for the billing ZIP.
    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={"login_url": SIMPLECIRC_LOGIN_URL},
        username="sub@example.com",
        password="hunter2",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# resolve_auth_credentials
# ---------------------------------------------------------------------------
def test_resolve_auth_credentials_env_override_with_zip(monkeypatch):
    monkeypatch.setenv("PUBLISHER_AUTH_PTLEADER_COM_USERNAME", "sub@example.com")
    monkeypatch.setenv("PUBLISHER_AUTH_PTLEADER_COM_ZIP", "98368")
    creds = al.resolve_auth_credentials("publisher-auth-ptleader-com")
    assert creds == {"username": "sub@example.com", "zip": "98368"}


def test_resolve_auth_credentials_username_alone_is_not_an_override(monkeypatch):
    # A username with no secret field must not short-circuit Secret Manager.
    monkeypatch.setenv("PUBLISHER_AUTH_LONELY_USERNAME", "only-user")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    assert al.resolve_auth_credentials("publisher-auth-lonely") == {}


def test_resolve_credentials_still_returns_username_password_pair(monkeypatch):
    monkeypatch.setenv("PUBLISHER_AUTH_X_COM_USERNAME", "u@x.com")
    monkeypatch.setenv("PUBLISHER_AUTH_X_COM_PASSWORD", "pw")
    assert al.resolve_credentials("publisher-auth-x-com") == ("u@x.com", "pw")


def test_resolve_auth_credentials_secret_manager_payload(monkeypatch):
    # No env override set: resolution falls through to Secret Manager. Unknown
    # fields in the payload are dropped; empty values are dropped.
    monkeypatch.setattr(
        al,
        "_load_secret_payload",
        lambda name, project: (
            '{"username": "sub@example.com", "zip": "98368",'
            ' "note": "not-a-credential", "password": ""}'
        ),
    )
    creds = al.resolve_auth_credentials("publisher-auth-ptleader-com")
    assert creds == {"username": "sub@example.com", "zip": "98368"}


def test_resolve_auth_credentials_invalid_json_payload(monkeypatch):
    monkeypatch.setattr(al, "_load_secret_payload", lambda name, project: "not json")
    assert al.resolve_auth_credentials("publisher-auth-bad") == {}


def test_resolve_auth_credentials_non_dict_json_payload(monkeypatch):
    monkeypatch.setattr(al, "_load_secret_payload", lambda name, project: '["u", "pw"]')
    assert al.resolve_auth_credentials("publisher-auth-list") == {}


# ---------------------------------------------------------------------------
# _wait_for / _page_source helpers
# ---------------------------------------------------------------------------
def test_wait_for_true_immediately():
    assert al._wait_for(object(), lambda d: True, timeout=5) is True


def test_wait_for_times_out_when_predicate_stays_false():
    assert al._wait_for(object(), lambda d: False, timeout=0) is False


def test_wait_for_swallows_predicate_exceptions():
    def _boom(_driver):
        raise RuntimeError("flaky DOM read")

    assert al._wait_for(object(), _boom, timeout=0) is False


def test_wait_for_polls_until_predicate_turns_true():
    calls = {"n": 0}

    def _third_time_lucky(_driver):
        calls["n"] += 1
        return calls["n"] >= 3

    assert al._wait_for(object(), _third_time_lucky, timeout=5) is True
    assert calls["n"] == 3


def test_page_source_returns_empty_string_when_driver_raises():
    class _DeadDriver:
        @property
        def page_source(self):
            raise RuntimeError("browser went away")

    assert al._page_source(_DeadDriver()) == ""


# ---------------------------------------------------------------------------
# perform_login credential plumbing
# ---------------------------------------------------------------------------
def test_perform_login_accepts_credentials_dict(monkeypatch):
    seen = {}

    def _fake_form(driver, cfg, username, password):
        seen["username"], seen["password"] = username, password
        return True

    monkeypatch.setattr(al, "_login_form", _fake_form)
    ok = al.perform_login(
        object(),
        auth_type="form",
        auth_config={"login_url": "https://x.example.com/login"},
        credentials={"username": "dict-user", "password": "dict-pw"},
    )
    assert ok is True
    assert seen == {"username": "dict-user", "password": "dict-pw"}


def test_perform_login_credentials_dict_wins_over_kwargs(monkeypatch):
    # Legacy username/password kwargs must not clobber the dict payload.
    seen = {}

    def _fake_form(driver, cfg, username, password):
        seen["username"], seen["password"] = username, password
        return True

    monkeypatch.setattr(al, "_login_form", _fake_form)
    al.perform_login(
        object(),
        auth_type="form",
        auth_config={},
        username="kwarg-user",
        password="kwarg-pw",
        credentials={"username": "dict-user", "password": "dict-pw"},
    )
    assert seen == {"username": "dict-user", "password": "dict-pw"}


def test_perform_login_mechanism_exception_returns_false(monkeypatch):
    def _explode(driver, cfg, username, password):
        raise RuntimeError("selenium session died")

    monkeypatch.setattr(al, "_login_form", _explode)
    ok = al.perform_login(
        object(),
        auth_type="form",
        auth_config={},
        username="u",
        password="pw",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# _fill_and_submit click fallbacks
# ---------------------------------------------------------------------------
def _blocked_submit_form(login_url):
    email = FakeElement(attrs={"type": "email"})
    password = FakeElement(attrs={"type": "password"})
    submit = FakeElement(tag="button")

    def _blocked_click():
        raise RuntimeError("element click intercepted: overlay in the way")

    submit.click = _blocked_click  # type: ignore[method-assign]
    driver = FakeDriver(
        {
            'input[type="email"]': [email],
            'input[type="password"]': [password],
            'button[type="submit"]': [submit],
        },
        login_url=login_url,
        success_url=None,
    )
    return driver, email, password, submit


def test_fill_and_submit_falls_back_to_js_click():
    driver, _email, _password, submit = _blocked_submit_form(
        "https://news.example.com/login"
    )
    js_clicks = []
    driver.execute_script = (  # type: ignore[attr-defined]
        lambda script, el: js_clicks.append(el)
    )

    assert al._fill_and_submit(driver, {}, "u", "pw") is True
    assert js_clicks == [submit]


def test_fill_and_submit_falls_back_to_enter_when_js_click_fails():
    driver, _email, password, _submit = _blocked_submit_form(
        "https://news.example.com/login"
    )
    # FakeDriver has no execute_script, so the JS fallback raises too and the
    # final fallback presses Enter in the password field.
    assert al._fill_and_submit(driver, {}, "u", "pw") is True
    assert password.value.endswith(Keys.RETURN)


# ---------------------------------------------------------------------------
# _login_form: trigger selector configured but missing
# ---------------------------------------------------------------------------
def test_form_login_proceeds_when_trigger_selector_not_found():
    email = FakeElement(attrs={"type": "email"})
    password = FakeElement(attrs={"type": "password"})
    submit = FakeElement(tag="button")

    login_url = "https://news.example.com/login"
    success_url = "https://news.example.com/account"
    driver = FakeDriver(
        {
            'input[type="email"]': [email],
            'input[type="password"]': [password],
            'button[type="submit"]': [submit],
        },
        login_url=login_url,
        success_url=success_url,
    )

    def _click():
        driver.current_url = success_url

    submit.click = _click  # type: ignore[method-assign]

    ok = al.perform_login(
        driver,
        auth_type="form",
        auth_config={
            "login_url": login_url,
            "login_trigger_selector": "a.does-not-exist",
        },
        username="u",
        password="pw",
    )
    # A missing trigger is logged but must not abort the login attempt.
    assert ok is True


# ---------------------------------------------------------------------------
# simplecirc / newzware: remaining branches
# ---------------------------------------------------------------------------
def test_simplecirc_login_fails_when_zip_field_missing():
    email = FakeElement(attrs={"type": "email"})
    driver = FakeDriver(
        {al.SIMPLECIRC_EMAIL_SELECTOR: [email]},
        login_url=SIMPLECIRC_LOGIN_URL,
        success_url=None,
    )
    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={"login_url": SIMPLECIRC_LOGIN_URL},
        credentials={"username": "sub@example.com", "zip": "98368"},
    )
    assert ok is False


def test_simplecirc_login_success_text_beats_form_presence():
    # With an explicit success marker configured, its presence decides the
    # outcome even if the login form is still rendered on the page.
    def _logged_in(driver):
        driver.page_source = "<p>Welcome back, subscriber</p>"

    driver, email, zip_field, _admin = _simplecirc_driver(on_submit=_logged_in)
    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={
            "login_url": SIMPLECIRC_LOGIN_URL,
            "success_text": "Welcome back",
        },
        credentials={"username": "sub@example.com", "zip": "98368"},
    )
    assert ok is True
    assert email.value == "sub@example.com"
    assert zip_field.value == "98368"


def test_simplecirc_login_honors_custom_selectors():
    email = FakeElement(attrs={"type": "email"})
    zip_field = FakeElement(attrs={"type": "text"})
    submit = FakeElement(tag="button")
    driver = FakeDriver(
        {
            "#custom-email": [email],
            "#custom-zip": [zip_field],
            "#custom-submit": [submit],
        },
        login_url=SIMPLECIRC_LOGIN_URL,
        success_url=None,
    )
    submit.click = lambda: setattr(  # type: ignore[method-assign]
        driver, "page_source", "<p>My Subscription</p>"
    )
    ok = al.perform_login(
        driver,
        auth_type="simplecirc",
        auth_config={
            "login_url": SIMPLECIRC_LOGIN_URL,
            "email_selector": "#custom-email",
            "zip_selector": "#custom-zip",
            "submit_selector": "#custom-submit",
            "success_text": "My Subscription",
        },
        credentials={"username": "sub@example.com", "zip": "98368"},
    )
    assert ok is True


def test_newzware_login_success_without_success_marker():
    # No success_text configured: returning to the publisher host on a
    # non-login path is sufficient proof of the handoff.
    def _handoff(driver):
        driver.current_url = "https://www.columbian.com/process-login"
        driver.page_source = "<html>anything</html>"

    driver, _email, _password = _newzware_driver(on_submit=_handoff)
    ok = al.perform_login(
        driver,
        auth_type="newzware",
        auth_config={"login_url": NEWZWARE_LOGIN_URL},
        username="user@example.com",
        password="pw",
    )
    assert ok is True
