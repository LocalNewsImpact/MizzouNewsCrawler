"""The control that opens a login is found by what it means, not by one name.

union-bulletin logged in at 15:17 UTC on 2026-09-21 and then, on a new driver
twenty minutes later, failed both attempts:

    form login: login trigger selector 'a[data-mg2-action='login']' not found
    Login form found by shape (identifier-first: no password field on this screen)
    Authenticated login: password field not found

One selector was the whole search, so a control rendered late, rendered hidden
in a collapsed menu, and rendered under another name all read the same. And with
the modal shut, shape discovery took a lone email box beside a button -- the
newsletter sign-up -- for an identifier-first login.

Pinned here:

- the page is asked several questions, most trustworthy first: form already
  open, already signed in, configured selector, login-ish attributes, login text,
  then the configured selector or attribute even when hidden;
- a newsletter box, a "Sign up", a "Subscribe" and a "Log out" are never taken
  for a login;
- when nothing opens a login, the login STOPS rather than guessing, and says
  what the page did have.

The JS is run in a real Chrome where one exists (the Selenium job); a mocked DOM
cannot say whether a traversal picks the right element.
"""

from __future__ import annotations

import inspect
from urllib.parse import quote

import pytest

from src.crawler import authenticated_login as al
from src.crawler.authenticated_login import LOGIN_TRIGGER_DISCOVERY_JS

CONNEXT = "a[data-mg2-action='login']"


@pytest.fixture(scope="module")
def driver():
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


def _ask(driver, body: str, configured: str | None = CONNEXT) -> dict:
    driver.get(
        "data:text/html;charset=utf-8," + quote(f"<html><body>{body}</body></html>")
    )
    return driver.execute_script(LOGIN_TRIGGER_DISCOVERY_JS, configured)


NEWSLETTER = (
    '<form><input type="email" placeholder="Your email address">'
    "<button>Subscribe</button></form>"
)


@pytest.mark.enable_selenium
class TestWhatThePageIsAsked:
    def test_the_configured_control_when_visible(self, driver):
        found = _ask(driver, '<a href="#" data-mg2-action="login">Log In</a>')
        assert found["why"] == "configured selector"
        assert found["visible"] is True
        assert found["trigger"].text == "Log In"

    def test_a_renamed_control_is_still_found_by_its_attributes(self, driver):
        """The name the host was configured with has changed."""
        found = _ask(
            driver, '<a href="#" data-mg2-action="signin" class="hdr">Account</a>'
        )
        assert found["why"] == "attribute says login"
        assert found["census"]["selector_total"] == 0

    def test_a_control_with_no_telling_attribute_is_found_by_its_text(self, driver):
        found = _ask(driver, '<button class="btn-x1">Sign in</button>')
        assert found["why"] == "text says log in"

    def test_a_hidden_configured_control_is_offered_for_a_script_click(self, driver):
        """A collapsed header menu. Connext's handler is delegated, so a
        script click on the hidden element still opens the modal."""
        found = _ask(
            driver,
            '<nav style="display:none"><a href="#" data-mg2-action="login">Log In</a></nav>',
        )
        assert found["why"] == "configured selector, hidden"
        assert found["visible"] is False
        assert found["census"]["selector_total"] == 1
        assert found["census"]["selector_visible"] == 0

    def test_visible_beats_hidden(self, driver):
        found = _ask(
            driver,
            '<nav style="display:none"><a data-mg2-action="login">Log In</a></nav>'
            "<button>Log in</button>",
        )
        assert found["why"] == "text says log in"

    def test_an_open_form_needs_no_click(self, driver):
        found = _ask(driver, '<input type="text"><input type="password">')
        assert found["trigger"] is None
        assert found["census"]["fields_open"] is True

    def test_a_signed_in_browser_needs_nothing(self, driver):
        found = _ask(driver, '<a href="/logout">Log Out</a>')
        assert found["trigger"] is None
        assert found["census"]["logged_in"] is True

    def test_subscriber_log_in_is_a_login(self, driver):
        """`subscribe` is excluded as a word, so `Subscriber` is not."""
        found = _ask(driver, "<button>Subscriber Log In</button>", configured=None)
        assert found["why"] == "text says log in"

    def test_an_invalid_configured_selector_does_not_throw(self, driver):
        found = _ask(driver, "<button>Log in</button>", configured="a[[[")
        assert found["why"] == "text says log in"


@pytest.mark.enable_selenium
class TestWhatIsNeverALogin:
    def test_the_newsletter_box_that_failed_union_bulletin(self, driver):
        found = _ask(driver, NEWSLETTER)
        assert found["trigger"] is None
        assert found["why"] == "nothing on the page opens a login"

    @pytest.mark.parametrize(
        "control",
        [
            "<button>Sign up</button>",
            "<button>Subscribe</button>",
            '<a href="/logout">Log out</a>',
            '<a href="/users/forgot-login">Forgot your login?</a>',
            '<a href="/register" class="login-register">Create account</a>',
        ],
    )
    def test_these_are_not_taken(self, driver, control):
        found = _ask(driver, control, configured=None)
        assert found["trigger"] is None

    def test_long_text_that_mentions_signing_in_is_not_a_control(self, driver):
        found = _ask(
            driver,
            "<a href='/faq'>Why do I need to sign in to read this story?</a>",
            configured=None,
        )
        assert found["trigger"] is None


# ---------------------------------------------------------------------------
# The Python half, against a driver that answers the script with a census.
# ---------------------------------------------------------------------------
class _Trigger:
    def __init__(self, refuse_click=False):
        self.clicked = False
        self.refuse_click = refuse_click

    def click(self):
        if self.refuse_click:
            raise RuntimeError("element not interactable")
        self.clicked = True

    def is_displayed(self):
        return True


class _CensusDriver:
    """Answers LOGIN_TRIGGER_DISCOVERY_JS with each census in turn."""

    current_url = "https://www.union-bulletin.com/"

    def __init__(self, answers):
        self.answers = list(answers)
        self.script_clicks = []

    def execute_script(self, script, *args):
        if script == LOGIN_TRIGGER_DISCOVERY_JS:
            return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if script == "arguments[0].click();":
            self.script_clicks.append(args[0])
            return None
        return None

    def find_elements(self, *_a):
        return []


def _census(**kw):
    base = {"selector_total": 0, "fields_open": False, "logged_in": False}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(al.time, "sleep", lambda *_a: None)


class TestOpeningTheModal:
    CFG = {"field_timeout": 3, "modal_delay": 0}

    def test_a_visible_trigger_is_clicked(self):
        t = _Trigger()
        d = _CensusDriver(
            [
                {
                    "trigger": t,
                    "why": "configured selector",
                    "visible": True,
                    "census": _census(),
                }
            ]
        )
        assert al._open_login_modal(d, self.CFG, CONNEXT) == "opened"
        assert t.clicked

    def test_a_hidden_trigger_is_clicked_by_script(self):
        t = _Trigger()
        d = _CensusDriver(
            [
                {
                    "trigger": t,
                    "why": "configured selector, hidden",
                    "visible": False,
                    "census": _census(),
                }
            ]
        )
        assert al._open_login_modal(d, self.CFG, CONNEXT) == "opened"
        assert not t.clicked
        assert d.script_clicks == [t]

    def test_a_refused_click_falls_back_to_script(self):
        t = _Trigger(refuse_click=True)
        d = _CensusDriver(
            [
                {
                    "trigger": t,
                    "why": "configured selector",
                    "visible": True,
                    "census": _census(),
                }
            ]
        )
        assert al._open_login_modal(d, self.CFG, CONNEXT) == "opened"
        assert d.script_clicks == [t]

    def test_a_late_render_is_waited_for(self):
        t = _Trigger()
        nothing = {"trigger": None, "why": "nothing", "census": _census()}
        d = _CensusDriver(
            [
                nothing,
                nothing,
                {
                    "trigger": t,
                    "why": "configured selector",
                    "visible": True,
                    "census": _census(),
                },
            ]
        )
        assert (
            al._open_login_modal(d, {"field_timeout": 60, "modal_delay": 0}, CONNEXT)
            == "opened"
        )
        assert t.clicked

    def test_an_open_form_is_not_clicked_shut(self):
        d = _CensusDriver(
            [{"trigger": None, "why": "open", "census": _census(fields_open=True)}]
        )
        assert al._open_login_modal(d, self.CFG, CONNEXT) == "opened"

    def test_a_signed_in_browser_is_reported(self):
        d = _CensusDriver(
            [{"trigger": None, "why": "in", "census": _census(logged_in=True)}]
        )
        assert al._open_login_modal(d, self.CFG, CONNEXT) == "signed_in"

    def test_nothing_found_says_what_the_page_had(self, caplog):
        census = _census(selector_total=1, selector_visible=0, ready_state="loading")
        d = _CensusDriver([{"trigger": None, "why": "nothing", "census": census}])
        assert (
            al._open_login_modal(d, {"field_timeout": 0, "modal_delay": 0}, CONNEXT)
            is None
        )
        assert "'ready_state': 'loading'" in caplog.text
        assert "union-bulletin.com" in caplog.text


class TestNoGuessingWithTheModalShut:
    def test_the_login_stops_instead_of_discovering_fields(self, monkeypatch):
        """The newsletter box is what shape discovery found last time."""
        called = []
        monkeypatch.setattr(al, "_open_login_modal", lambda *a, **k: None)
        monkeypatch.setattr(al, "_fill_and_submit", lambda *a, **k: called.append(1))

        class _D:
            def set_page_load_timeout(self, _n):
                pass

            def get(self, _u):
                pass

        ok = al._login_form(
            _D(),
            {
                "login_url": "https://www.union-bulletin.com/",
                "login_trigger_selector": CONNEXT,
            },
            "u",
            "p",
        )
        assert ok is False
        assert called == []

    def test_a_signed_in_browser_skips_the_form(self, monkeypatch):
        called = []
        monkeypatch.setattr(al, "_open_login_modal", lambda *a, **k: "signed_in")
        monkeypatch.setattr(al, "_fill_and_submit", lambda *a, **k: called.append(1))
        monkeypatch.setattr(al, "_session_cookie_present", lambda *a, **k: True)

        class _D:
            current_url = "https://www.union-bulletin.com/"
            page_source = "Log Out"

            def set_page_load_timeout(self, _n):
                pass

            def get(self, _u):
                pass

            def find_elements(self, *_a):
                return []

        assert al._login_form(
            _D(),
            {
                "login_url": "https://www.union-bulletin.com/",
                "login_trigger_selector": CONNEXT,
            },
            "u",
            "p",
        )
        assert called == []

    def test_hosts_without_a_trigger_are_unchanged(self):
        """The trigger step only runs when a trigger is configured."""
        source = inspect.getsource(al._login_form)
        assert "if trigger_sel:" in source
        assert source.index("if trigger_sel:") < source.index("_open_login_modal(")
