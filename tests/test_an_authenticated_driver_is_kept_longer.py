"""The authenticated worker's driver is recycled less often.

`SELENIUM_DRIVER_REUSE_LIMIT` does two jobs. Rotating the driver makes a
crawler look less like one machine working steadily through a site -- the
bot-detection job -- and recycling also reaps Chrome renderer processes. A login
removes the first reason on that host: the session identifies us on every
request whatever the driver does. It does not remove the second, so the
authenticated path takes a higher bound rather than no bound.

It matters because of how work is served. The queue hands a worker ONE domain
and at most three articles per request, then rotates. So a credentialed host is
visited in short bursts -- and `_authenticated_domains` is cleared every time
the driver is recreated. At the default of 10 uses (roughly three visits) the
worker drops every session it holds and signs in again on each host's next
turn. Across the 1,038 WSU links behind seven paywalled publishers that is a
great many logins, each one submitted to a publisher who is watching;
`cascadiadaily.com` counts them and locks the account out.

The limit is chosen by an explicit WORKER MODE, not by "is any domain logged
in". That was the first attempt and it was wrong: `_authenticated_domains`
accumulates for the life of the process, so the first successful login raised
the limit for every anonymous domain in the same batch too -- taking rotation
away from hosts that never asked, which is precisely what the limit exists to
give them. An authenticated worker draws only credentialed domains from the
queue (`WorkRequest.requires_login`), so raising its limit affects nothing else.
"""

from __future__ import annotations

import inspect

import pytest

from src.crawler import ContentExtractor


@pytest.fixture(autouse=True)
def _clean_class_state():
    """These are class attributes, so a test must not leak into the next."""
    before = (
        set(ContentExtractor._authenticated_domains),
        ContentExtractor._shared_driver_reuse_limit,
        ContentExtractor._shared_driver_reuse_limit_authenticated,
        ContentExtractor._authenticated_worker,
    )
    yield
    (
        ContentExtractor._authenticated_domains,
        ContentExtractor._shared_driver_reuse_limit,
        ContentExtractor._shared_driver_reuse_limit_authenticated,
        ContentExtractor._authenticated_worker,
    ) = (set(before[0]), before[1], before[2], before[3])


def _limits(*, authenticated_worker, ordinary=10, authed=50):
    ContentExtractor._authenticated_worker = authenticated_worker
    ContentExtractor._shared_driver_reuse_limit = ordinary
    ContentExtractor._shared_driver_reuse_limit_authenticated = authed


class TestWhichLimitApplies:
    def test_an_ordinary_worker_takes_the_ordinary_limit(self):
        _limits(authenticated_worker=False)
        assert ContentExtractor._driver_reuse_limit() == 10

    def test_the_authenticated_worker_takes_the_higher_one(self):
        _limits(authenticated_worker=True)
        assert ContentExtractor._driver_reuse_limit() == 50

    def test_a_login_alone_does_not_raise_it(self):
        """The bug this design replaced.

        `_authenticated_domains` accumulates for the life of the process and is
        cleared only on recycle, so keying off it meant one successful login
        stopped rotating every anonymous domain the same worker went on to
        fetch.
        """
        _limits(authenticated_worker=False)
        ContentExtractor._authenticated_domains = {"ptleader.com"}
        assert ContentExtractor._driver_reuse_limit() == 10

    def test_the_authenticated_worker_keeps_the_higher_limit_before_any_login(self):
        """It is a property of the worker, not of what it has managed so far.

        Otherwise the first host of a run pays the churn the mode exists to
        avoid.
        """
        _limits(authenticated_worker=True)
        ContentExtractor._authenticated_domains = set()
        assert ContentExtractor._driver_reuse_limit() == 50

    def test_it_falls_back_when_neither_was_initialised(self):
        _limits(authenticated_worker=False, ordinary=None, authed=None)
        assert ContentExtractor._driver_reuse_limit() == 10
        ContentExtractor._authenticated_worker = True
        assert ContentExtractor._driver_reuse_limit() == 50

    def test_the_authenticated_bound_is_higher_by_default(self):
        """A lower authenticated bound would invert the whole point."""
        import os

        ordinary = int(os.environ.get("SELENIUM_DRIVER_REUSE_LIMIT", "10"))
        authed = int(os.environ.get("SELENIUM_DRIVER_REUSE_LIMIT_AUTHENTICATED", "50"))
        assert authed > ordinary


class TestTheModeIsReadFromTheEnvironment:
    def test_it_is_off_unless_a_run_sets_it(self, monkeypatch):
        """Provisioning is not built yet, so the default must be the old
        behaviour -- see docs/AN_AUTHENTICATED_WORKER_IS_PROVISIONED.md."""
        monkeypatch.delenv("EXTRACTION_AUTHENTICATED_WORKER", raising=False)
        _limits(authenticated_worker=None)
        assert ContentExtractor._driver_reuse_limit() == 10
        assert ContentExtractor._authenticated_worker is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
    def test_the_truthy_spellings_turn_it_on(self, monkeypatch, value):
        monkeypatch.setenv("EXTRACTION_AUTHENTICATED_WORKER", value)
        _limits(authenticated_worker=None)
        assert ContentExtractor._driver_reuse_limit() == 50

    @pytest.mark.parametrize("value", ["", "0", "false", "no"])
    def test_anything_else_leaves_it_off(self, monkeypatch, value):
        monkeypatch.setenv("EXTRACTION_AUTHENTICATED_WORKER", value)
        _limits(authenticated_worker=None)
        assert ContentExtractor._driver_reuse_limit() == 10

    def test_it_is_read_once_and_cached(self, monkeypatch):
        """Read per fetch, an env change mid-run would move the limit under a
        driver that already holds sessions."""
        monkeypatch.setenv("EXTRACTION_AUTHENTICATED_WORKER", "true")
        _limits(authenticated_worker=None)
        assert ContentExtractor._driver_reuse_limit() == 50
        monkeypatch.setenv("EXTRACTION_AUTHENTICATED_WORKER", "false")
        assert ContentExtractor._driver_reuse_limit() == 50


class TestItIsStillBounded:
    def test_there_is_no_unlimited_branch(self):
        """Recycling also reaps renderer processes, which a login does not fix."""
        code = inspect.getsource(ContentExtractor._driver_reuse_limit)
        body = "\n".join(
            line for line in code.splitlines() if not line.strip().startswith("#")
        )
        for forever in ("float('inf')", 'float("inf")', "return 0", "return None"):
            assert forever not in body

    def test_the_recycle_decision_reads_the_helper(self):
        code = inspect.getsource(ContentExtractor.get_persistent_driver)
        assert "_driver_reuse_limit()" in code

    def test_the_log_says_what_is_being_dropped(self):
        """A silent recycle is what made the login churn invisible."""
        code = inspect.getsource(ContentExtractor.get_persistent_driver)
        assert "authenticated=" in code
        assert "_authenticated_domains" in code
