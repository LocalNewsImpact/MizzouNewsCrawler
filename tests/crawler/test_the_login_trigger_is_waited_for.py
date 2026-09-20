"""The control that opens the login modal is polled for, like the field inside it.

`_login_form` looked the trigger up ONCE, immediately after `driver.get()`.
Connext renders it with JavaScript, so on www.yakimaherald.com it was not in the
DOM yet. The modal was never opened, and `_fill_and_submit` then polled twenty
seconds for a field that could not exist. From production, 2026-09-20:

    16:41:59  Authenticating to yakimaherald.com before extraction
    16:43:01  form login: login trigger selector 'a[data-mg2-action='login']' not found
    16:43:41  Authenticated login: username/email field not found
    16:43:41  Login to yakimaherald.com did not confirm; continuing unauthenticated

Two warnings, both true, neither naming the cause -- and the run then fetched a
paywalled publisher anonymously, storing a wall as `paywall` and a furniture page
as `not_article`.

Measured in Playwright against the same page: at 3 seconds after load both login
controls report not-displayed; at 5-6 seconds they are displayed, the Connext
modal opens, and `POST https://prod-amg-proxy-connext.azurewebsites.net/api/user`
answers 200 with `Log In` going hidden and `My Account` becoming visible.

So the asymmetry was the whole defect: the field the modal contains had a
20-second poll, the trigger that opens the modal had none.
"""

from __future__ import annotations

import inspect

from src.crawler import authenticated_login as al


class _Element:
    def __init__(self, displayed=True):
        self._displayed = displayed
        self.clicked = False

    def is_displayed(self):
        return self._displayed

    def click(self):
        self.clicked = True

    def clear(self):
        pass

    def send_keys(self, _value):
        pass


class _DriverAppearingAfter:
    """A driver whose trigger appears only on the Nth lookup, like a JS render."""

    def __init__(self, appears_on_call: int):
        self.appears_on_call = appears_on_call
        self.calls = 0
        self.trigger = _Element()
        self.current_url = "https://www.yakimaherald.com/"
        self.page_source = "<html></html>"

    def set_page_load_timeout(self, _n):
        pass

    def get(self, _url):
        pass

    def find_elements(self, _by, selector):
        if "mg2-action" in selector:
            self.calls += 1
            return [self.trigger] if self.calls >= self.appears_on_call else []
        return []

    def execute_script(self, *_a):
        return None

    def get_cookies(self):
        return []


class TestTheTriggerIsPolled:
    def test_a_trigger_that_renders_late_is_still_found(self, monkeypatch):
        monkeypatch.setattr(al.time, "sleep", lambda _s: None)
        driver = _DriverAppearingAfter(appears_on_call=4)
        # `_fill_and_submit` is not the subject here; the trigger is.
        monkeypatch.setattr(al, "_fill_and_submit", lambda *a, **k: False)
        al._login_form(
            driver,
            {
                "login_url": "https://www.yakimaherald.com/",
                "login_trigger_selector": "a[data-mg2-action='login']",
                "field_timeout": 20,
            },
            "u",
            "p",
        )
        assert driver.calls >= 4, "the trigger was looked up once and given up on"
        assert driver.trigger.clicked, "the trigger was found but never clicked"

    def test_it_gives_up_eventually(self, monkeypatch):
        """A selector that is genuinely wrong must still fail, not hang."""
        monkeypatch.setattr(al.time, "sleep", lambda _s: None)
        driver = _DriverAppearingAfter(appears_on_call=10_000)
        monkeypatch.setattr(al, "_fill_and_submit", lambda *a, **k: False)
        assert (
            al._login_form(
                driver,
                {
                    "login_url": "https://x.example/",
                    "login_trigger_selector": "a.nope",
                    "field_timeout": 2,
                },
                "u",
                "p",
            )
            is False
        )

    def test_the_trigger_and_the_field_share_one_budget(self):
        """They are the same kind of wait on the same kind of render, and one
        having 20 seconds while the other had none is what broke this host."""
        source = inspect.getsource(al._login_form)
        assert 'cfg.get("field_timeout", 20)' in source

    def test_the_modal_is_given_time_to_render(self):
        """One second was optimistic -- Playwright needed about six -- and being
        wrong there is indistinguishable from a wrong selector, because what
        fails is the field lookup afterwards."""
        source = inspect.getsource(al._login_form)
        assert 'cfg.get("modal_delay", 5)' in source
        # NOT "no time.sleep(1) anywhere": the polling loop added above ticks
        # once a second, which is a legitimate one-second sleep. What must be
        # gone is the FLAT one-second wait that used to follow the click, so the
        # assertion is that the wait after the trigger is the configurable one.
        after_click = source[source.index("execute_script") :]
        assert 'time.sleep(float(cfg.get("modal_delay", 5)))' in after_click
        assert "\n            time.sleep(1)\n" not in after_click


class TestTheClickFallbackIsStillThere:
    def test_a_js_click_backs_up_a_refused_click(self):
        """The control is visible, enabled and stable but sits outside the
        viewport on this host, which is enough to refuse an ordinary click."""
        source = inspect.getsource(al._login_form)
        assert 'execute_script("arguments[0].click();", trigger)' in source
