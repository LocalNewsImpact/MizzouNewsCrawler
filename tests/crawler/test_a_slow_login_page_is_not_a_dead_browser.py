"""A slow login page is a slow page, not a dead browser.

2026-10-14, `validate-login`: chinookobserver.com failed with
`DriverUnresponsive: form login: the browser stopped answering`, and
www.wenatcheeworld.com's return to its homepage failed three times and voided
the cookie diff. Both pages were ad-heavy homepages still loading.

The login asked chromedriver for a 45s page load, but the Selenium client gives
up on chromedriver at 30s (`_client_config.timeout`, set last when the driver
is built). The 45s was never reached: the client's ReadTimeout fired first,
and `driver_unresponsive` reads that, correctly, as a dead browser.

Pinned here:

- the page-load timeout a login sets stays under the client timeout, so a slow
  page raises chromedriver's own TimeoutException -- which `_open` already
  treats as a usable partial DOM;
- a page that times out is stopped, so its DOM settles;
- the witness's trips to the publisher's origin count a timed-out load that
  landed on the origin as an arrival.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.cli.commands import validate_login as vl
from src.crawler import authenticated_login as al
from src.crawler.driver_health import DriverUnresponsive

urllib3_exceptions = pytest.importorskip("urllib3.exceptions")
selenium_exceptions = pytest.importorskip("selenium.common.exceptions")


def _dead():
    return urllib3_exceptions.ReadTimeoutError(
        None, "http://localhost:43445", "Read timed out. (read timeout=30)"
    )


def _driver(client_timeout):
    driver = MagicMock()
    if client_timeout is None:
        driver.command_executor = SimpleNamespace()
    else:
        driver.command_executor._client_config.timeout = client_timeout
    return driver


class TestThePageLoadTimeout:
    @pytest.mark.parametrize(
        "client,expected",
        [
            (30, 25.0),  # what every driver is built with
            (90, 45.0),  # a client that can wait: the login's own figure
            (None, 45.0),  # unreadable client: the login's own figure
            (6, 5.0),  # never below five seconds
        ],
    )
    def test_it_is_kept_under_the_client_timeout(self, client, expected):
        driver = _driver(client)
        assert al.bounded_page_load_timeout(driver) == expected
        driver.set_page_load_timeout.assert_called_once_with(expected)

    @pytest.mark.parametrize(
        "fn",
        [
            "_login_auth0",
            "_login_form",
            "_login_newzware",
            "_login_simplecirc",
            "_login_etype",
        ],
    )
    def test_every_mechanism_sets_it_through_the_helper(self, fn):
        body = inspect.getsource(getattr(al, fn))
        assert "bounded_page_load_timeout(driver)" in body
        assert "set_page_load_timeout(" not in body


class TestTheLoginPageLoad:
    def test_a_slow_page_is_stopped_and_the_login_carries_on(self):
        driver = MagicMock()
        driver.get.side_effect = selenium_exceptions.TimeoutException("slow")
        al._open(driver, "https://www.chinookobserver.com/", "form login")
        driver.execute_script.assert_called_once_with("window.stop();")

    def test_a_dead_driver_still_raises_and_is_not_stopped(self):
        driver = MagicMock()
        driver.get.side_effect = _dead()
        with pytest.raises(DriverUnresponsive):
            al._open(driver, "https://www.chinookobserver.com/", "form login")
        driver.execute_script.assert_not_called()


class TestArrivingAtTheOrigin:
    def test_a_clean_load_arrives(self):
        driver = MagicMock()
        assert vl.arrive(driver, "https://www.wenatcheeworld.com/") is True

    def test_a_timed_out_load_on_the_origin_arrives(self):
        driver = MagicMock()
        driver.get.side_effect = selenium_exceptions.TimeoutException("slow")
        driver.current_url = "https://www.wenatcheeworld.com/"
        assert vl.arrive(driver, "https://www.wenatcheeworld.com/") is True
        driver.execute_script.assert_called_once_with("window.stop();")

    def test_a_timed_out_load_left_elsewhere_does_not(self):
        driver = MagicMock()
        driver.get.side_effect = selenium_exceptions.TimeoutException("slow")
        driver.current_url = "https://auth.mcclatchy.com/u/login"
        assert vl.arrive(driver, "https://www.tri-cityherald.com/") is False

    def test_a_dead_driver_does_not(self):
        driver = MagicMock()
        driver.get.side_effect = _dead()
        assert vl.arrive(driver, "https://www.wenatcheeworld.com/") is False
        driver.execute_script.assert_not_called()

    def test_the_witness_uses_it_both_ways(self):
        body = inspect.getsource(vl.witness)
        assert body.count("arrive(driver, origin)") == 2
        assert "driver.get(origin)" not in body
