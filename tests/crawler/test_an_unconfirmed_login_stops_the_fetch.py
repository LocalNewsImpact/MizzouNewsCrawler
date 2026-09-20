"""No confirmed session, no fetch — and a login that fails is tried again.

`_ensure_authenticated` used to log "continuing unauthenticated (won't retry on
this driver)" and fall through to the fetch. On a publisher we hold a
subscription to, that means storing whatever the wall serves.

What it cost, on 2026-09-20, in one run:

    16:43:41  Login to yakimaherald.com did not confirm; continuing unauthenticated
    16:45:13  AUTHENTICATED SESSION GOT NO STORY on .../school-board-races-...
    16:45:16  Article body is furniture, not prose (cap/util shape)
              - marking as not_article (7458 chars)

A real school-board election story, captured as 7,458 characters of navigation
furniture and filed `not_article` with its text emptied. Every rule downstream
behaved correctly -- the body gates are supposed to refuse furniture. The fetch
is what should not have happened.

Three changes, and the third is what makes the first two trustworthy:

- the method returns whether the driver MAY fetch, and the caller honours it.
- a login that does not confirm is tried again, bounded at
  `_MAX_AUTH_ATTEMPTS` per driver per host. Bounded because the far end is an
  account: two attempts catch a modal that did not open, a third would be a
  credential being rejected, and repeating that is how an account is locked out.
- `auth_config.success_cookie` is an AFFIRMATIVE confirmation. Every other check
  is a proxy -- did the URL change, does a word appear in the source, did the
  login button vanish -- and on this host those proxies reported failure on a
  working session and success on a broken one. A cookie is the session.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from src.crawler import ContentExtractor
from src.crawler.authenticated_login import _session_cookie_present


@pytest.fixture(autouse=True)
def _clean_class_state():
    before = (
        set(ContentExtractor._authenticated_domains),
        set(ContentExtractor._auth_failed_domains),
        dict(ContentExtractor._auth_attempts),
    )
    yield
    ContentExtractor._authenticated_domains = set(before[0])
    ContentExtractor._auth_failed_domains = set(before[1])
    ContentExtractor._auth_attempts = dict(before[2])


class TestTheAnswerIsReturned:
    def test_a_host_needing_no_login_may_be_fetched(self):
        e = ContentExtractor()
        e._get_domain_auth_config = lambda host: None
        assert e._ensure_authenticated(MagicMock(), "example.com") is True

    def test_a_confirmed_session_may_be_fetched(self):
        e = ContentExtractor()
        ContentExtractor._authenticated_domains.add("ptleader.com")
        assert e._ensure_authenticated(MagicMock(), "ptleader.com") is True

    def test_a_spent_host_is_refused_rather_than_retried(self):
        e = ContentExtractor()
        ContentExtractor._auth_failed_domains.add("yakimaherald.com")
        assert e._ensure_authenticated(MagicMock(), "yakimaherald.com") is False

    def test_the_www_prefix_does_not_change_the_answer(self):
        e = ContentExtractor()
        ContentExtractor._authenticated_domains.add("yakimaherald.com")
        assert e._ensure_authenticated(MagicMock(), "www.yakimaherald.com") is True


class TestARefusalStopsTheFetch:
    def test_the_selenium_path_does_not_navigate_when_refused(self):
        """The whole point, asserted as "the page was never requested".

        An empty dict alone proves nothing -- this path returns `{}` for several
        reasons, so the first version of this test passed with the refusal
        disabled. What must be true is that navigation never happened.
        """
        e = ContentExtractor()
        navigated = []
        e.get_persistent_driver = lambda: MagicMock()
        e._ensure_authenticated = lambda *a, **k: False
        e._navigate_with_human_behavior = lambda *a, **k: navigated.append(a) or True
        result = e._extract_with_selenium("https://www.yakimaherald.com/news/x")
        assert navigated == [], "the page was fetched despite the refusal"
        assert result == {}

    def test_it_does_navigate_when_the_session_is_confirmed(self):
        """The other half: the refusal must not be refusing everything."""
        e = ContentExtractor()
        navigated = []
        e.get_persistent_driver = lambda: MagicMock()
        e._ensure_authenticated = lambda *a, **k: True
        e._navigate_with_human_behavior = lambda *a, **k: navigated.append(a) or False
        e._extract_with_selenium("https://www.yakimaherald.com/news/x")
        assert navigated, "a confirmed session should have been fetched"

    def test_an_error_deciding_is_not_permission(self):
        """An exception in the auth hook must not read as "go ahead" on a
        credentialed host."""
        source = inspect.getsource(ContentExtractor._extract_with_selenium)
        assert "may_fetch = not self._requires_login(" in source

    def test_the_refusal_is_logged_where_it_can_be_counted(self):
        source = inspect.getsource(ContentExtractor._ensure_authenticated)
        assert "REFUSING" in source


class TestTheRetryIsBounded:
    @pytest.fixture
    def login_returning(self, monkeypatch):
        """An extractor whose `perform_login` returns each result in turn.

        Patched through `monkeypatch`, not by assigning to the module: the first
        version of this fixture replaced `authenticated_login.perform_login`
        permanently and broke 24 tests in `test_authenticated_login.py` that ran
        after it.
        """

        def build(results):
            e = ContentExtractor()
            e._get_domain_auth_config = lambda host: {
                "auth_type": "form",
                "auth_secret_name": "publisher-auth-x",
                "auth_config": {"login_url": "https://x.example/login"},
            }
            calls = []

            def fake_perform_login(driver, **kwargs):
                calls.append(kwargs)
                return results[len(calls) - 1] if len(calls) <= len(results) else False

            import src.crawler.authenticated_login as al

            monkeypatch.setattr(al, "perform_login", fake_perform_login)
            monkeypatch.setattr(
                al,
                "resolve_auth_credentials",
                lambda name: {"username": "u", "password": "p"},
            )
            return e, calls

        return build

    def test_a_second_attempt_is_made(self, login_returning):
        e, calls = login_returning([False, True])
        assert e._ensure_authenticated(MagicMock(), "x.example") is True
        assert len(calls) == 2

    def test_it_stops_at_the_limit(self, login_returning):
        e, calls = login_returning([False, False, True])
        assert e._ensure_authenticated(MagicMock(), "x.example") is False
        assert len(calls) == ContentExtractor._MAX_AUTH_ATTEMPTS

    def test_the_limit_is_small_because_the_far_end_is_an_account(self):
        """A rejected credential retried indefinitely is how an account is
        locked out."""
        assert 1 < ContentExtractor._MAX_AUTH_ATTEMPTS <= 3

    def test_a_first_attempt_that_works_does_not_retry(self, login_returning):
        e, calls = login_returning([True])
        assert e._ensure_authenticated(MagicMock(), "x.example") is True
        assert len(calls) == 1

    def test_a_new_driver_gets_a_fresh_budget(self):
        """A modal that would not open on the last driver is not a reason to
        refuse the host for the life of the process."""
        source = inspect.getsource(ContentExtractor.close_persistent_driver)
        assert "_auth_attempts = {}" in source


class TestTheAffirmativeConfirmation:
    def _driver_with(self, *cookie_names):
        d = MagicMock()
        d.get_cookies.return_value = [{"name": n} for n in cookie_names]
        return d

    def test_a_present_cookie_confirms(self):
        assert (
            _session_cookie_present(
                self._driver_with("connext_sub", "other"),
                {"success_cookie": "connext_sub"},
            )
            is True
        )

    def test_an_absent_cookie_denies(self):
        assert (
            _session_cookie_present(
                self._driver_with("other"), {"success_cookie": "connext_sub"}
            )
            is False
        )

    def test_no_configured_cookie_means_no_answer_not_a_denial(self):
        """None, so the caller falls back to the weaker checks. Treating "not
        configured" as "not logged in" would refuse every host that has no
        cookie name yet."""
        assert _session_cookie_present(self._driver_with("x"), {}) is None

    def test_an_unreadable_jar_denies(self):
        d = MagicMock()
        d.get_cookies.side_effect = RuntimeError("no session")
        assert _session_cookie_present(d, {"success_cookie": "c"}) is False

    def test_the_cookie_overrules_the_weaker_checks_in_both_directions(self):
        """It reported success on a session serving walls, so the proxies must
        not be able to overrule an affirmative answer either way."""
        from src.crawler import authenticated_login as al

        source = inspect.getsource(al._login_form)
        assert "confirmed = _session_cookie_present(driver, cfg)" in source
        assert "if confirmed is not None:" in source
        idx = source.index("confirmed = _session_cookie_present")
        assert idx < source.index("return left_login_page or success_text_seen")
