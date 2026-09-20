"""A login form is found by its shape, not by guessing attribute names.

`EMAIL_CANDIDATES` keys on `type`, `name`, `id` and `autocomplete`. Component
frameworks often set none of them, and a longer list cannot reach markup that
carries no attribute to match. Connext is the case on record: its inputs are
`input.connext-login-a-cep-login__input` with no id, no name and no
autocomplete -- class only -- so yakimaherald needed every selector configured by
hand, and www.columbian.com still fails with `username/email field not found`
because Newzware's form is the same kind of markup.

The question a browser asks instead: `input[type="password"]` is near-universal,
because a password manager has to find it too. So anchor there and work outwards
by structure -- the username is the nearest visible text-like input before it in
the same scope, and the submit control comes from that scope by role.

These tests drive the real script against real DOM, in a real browser, because
the thing under test is a DOM traversal and asserting on its source would prove
nothing about whether it selects the right element.
"""

from __future__ import annotations

import pytest

from src.crawler.authenticated_login import LOGIN_FIELD_DISCOVERY_JS

CONNEXT_CLASS_ONLY = """
<body>
  <form class="search"><input class="q" placeholder="Search"></form>
  <div class="connext-modal">
    <input class="connext-login-a-cep-login__input">
    <input class="connext-login-a-cep-login__input" type="password">
    <button class="connext-login-a-cep-login__button">Sign In</button>
  </div>
</body>
"""

REGISTRATION_AND_LOGIN = """
<body>
  <form id="register">
    <input name="email"><input type="password"><input type="password">
    <button type="submit">Create account</button>
  </form>
  <form id="login">
    <input name="email"><input type="password">
    <button type="submit">Log in</button>
  </form>
</body>
"""

IDENTIFIER_FIRST = """
<body>
  <form id="step1">
    <input type="email" name="username">
    <button type="submit">Continue</button>
  </form>
</body>
"""

SEARCH_BOX_BEFORE_LOGIN = """
<body>
  <header><form><input type="text" name="search_query" placeholder="Search"></form></header>
  <form id="login">
    <input type="text" id="acct">
    <input type="password">
    <button type="submit">Log in</button>
  </form>
</body>
"""

HIDDEN_FORM = """
<body>
  <form id="login" style="display:none">
    <input name="email"><input type="password"><button type="submit">Log in</button>
  </form>
</body>
"""


@pytest.fixture(scope="module")
def driver():
    """A real browser, or skip.

    Skipped rather than mocked: a mocked DOM cannot tell us whether a traversal
    picks the right element, which is the only thing these tests are for. The
    Selenium Headful Regression job runs them in the crawler image, which has
    Chrome; a laptop or a lean CI image without one skips instead of erroring.
    """
    webdriver = pytest.importorskip("selenium.webdriver")
    opts = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage"):
        opts.add_argument(arg)
    try:
        d = webdriver.Chrome(options=opts)
    except Exception as exc:  # pragma: no cover - environment without Chrome
        pytest.skip(f"no usable Chrome here: {exc}")
    yield d
    d.quit()


def _discover(driver, html: str):
    driver.get("data:text/html;charset=utf-8," + html)
    return driver.execute_script(LOGIN_FIELD_DISCOVERY_JS)


def _attr(el, name):
    return el.get_attribute(name) if el else None


class TestItReachesMarkupNoAttributeGuessCanMatch:
    pytestmark = pytest.mark.enable_selenium

    def test_a_class_only_connext_form(self, driver):
        """The case that forced every yakimaherald selector to be configured."""
        found = _discover(driver, CONNEXT_CLASS_ONLY)
        assert found, "nothing found in a class-only form"
        assert _attr(found["email"], "class") == "connext-login-a-cep-login__input"
        assert _attr(found["password"], "type") == "password"
        assert found["submit"].text.strip() == "Sign In"

    def test_the_search_box_is_not_taken_as_the_username(self, driver):
        """A header search input sits before the login and is text-like.

        It is excluded twice over: different scope, and its name looks like a
        search. Getting this wrong would type the subscriber's email into a site
        search on every login.
        """
        found = _discover(driver, SEARCH_BOX_BEFORE_LOGIN)
        assert _attr(found["email"], "id") == "acct"


class TestItPicksTheLoginNotTheRegistration:
    pytestmark = pytest.mark.enable_selenium

    def test_two_password_fields_lose_to_one(self, driver):
        """Two means registration or change-password. One means login."""
        found = _discover(driver, REGISTRATION_AND_LOGIN)
        form_id = driver.execute_script(
            "return arguments[0].closest('form').id;", found["password"]
        )
        assert form_id == "login"

    def test_the_submit_comes_from_the_same_scope(self, driver):
        found = _discover(driver, REGISTRATION_AND_LOGIN)
        assert found["submit"].text.strip() == "Log in"


class TestIdentifierFirstFlows:
    pytestmark = pytest.mark.enable_selenium

    def test_a_screen_with_no_password_still_yields_the_identifier(self, driver):
        """Auth0 and Microsoft ask for the identifier first.

        There is no password to anchor on yet, so the fallback accepts a lone
        text-like input in a scope that can submit -- and says so, because a caller
        has to know to expect a second screen.
        """
        found = _discover(driver, IDENTIFIER_FIRST)
        assert found["password"] is None
        assert _attr(found["email"], "name") == "username"
        assert "identifier-first" in found["why"]

    def test_the_password_anchored_path_says_which_it_used(self, driver):
        found = _discover(driver, CONNEXT_CLASS_ONLY)
        assert "password" in found["why"]


class TestItRefusesRatherThanGuesses:
    pytestmark = pytest.mark.enable_selenium

    def test_a_hidden_form_is_not_offered(self, driver):
        """Connext ships its modal `display:none` until JS reveals it.

        Filling a hidden form types into nothing and submits nothing, so an
        invisible match is worse than no match: the caller would stop looking.
        """
        assert _discover(driver, HIDDEN_FORM) is None

    def test_a_page_with_no_form_returns_nothing(self, driver):
        assert _discover(driver, "<body><p>No login here</p></body>") is None
