"""Unit tests for src.crawler.authenticated_login.

Covers the pure helpers (Auth0 authorize-URL/PKCE construction, credential
resolution) and the form-login flow using a lightweight fake Selenium driver.
No database or network access.
"""

from __future__ import annotations

import urllib.parse

import pytest

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

    def __init__(self, elements_by_selector, *, login_url, success_url):
        # elements_by_selector: dict[str, list[FakeElement]]
        self._elements = elements_by_selector
        self._login_url = login_url
        self._success_url = success_url
        self.current_url = "about:blank"
        self.page_source = ""

    def set_page_load_timeout(self, _seconds):
        pass

    def get(self, url):
        self.current_url = url

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


def test_form_login_no_fields_returns_false():
    login_url = "https://news.example.com/login"
    driver = FakeDriver({}, login_url=login_url, success_url="x")
    ok = al.perform_login(
        driver,
        auth_type="form",
        auth_config={"login_url": login_url},
        username="user@example.com",
        password="pw",
    )
    assert ok is False


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
