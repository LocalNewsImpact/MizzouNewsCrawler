"""A browser that stops answering is replaced, not retried.

Measured on rotation `authenticated-extraction-d2vw4`, 2026-09-21: the Chrome
driver stopped answering on yakimaherald.com at 15:23 UTC. The exception was

    HTTPConnectionPool(host='localhost', port=41555): Read timed out.
    (read timeout=30)

-- urllib3 on the way to chromedriver, not Selenium's page-load timeout -- and
the failure path then asked the same dead driver for a screenshot, logs,
cookies and localStorage, each waiting 30s three times over. About twelve
minutes an article; the worker made no queue request for sixteen minutes, and
pendoreillerivervalley, which was owed its retry, never came up.

What is pinned here:

- the classifier tells the two failures apart, by exception type;
- a dead driver ends the navigation after ONE command, with no diagnostics;
- it is killed from outside, because `quit()` is a command too;
- a page that is merely slow still gets its three attempts;
- a replacement driver never re-fetches a login-gated host, because it has no
  session and the fetch would store a wall.
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from src.crawler import ContentExtractor, driver_health
from src.crawler.driver_health import driver_pids, driver_unresponsive, kill_driver

urllib3_exceptions = pytest.importorskip("urllib3.exceptions")
selenium_exceptions = pytest.importorskip("selenium.common.exceptions")

LOCAL = "http://localhost:41555"


def _read_timeout():
    return urllib3_exceptions.ReadTimeoutError(
        None, LOCAL, "Read timed out. (read timeout=30)"
    )


class TestTheClassifier:
    def test_the_measured_exception_is_a_dead_driver(self):
        assert driver_unresponsive(_read_timeout())

    def test_retries_exhausted_is_a_dead_driver(self):
        exc = urllib3_exceptions.MaxRetryError(None, LOCAL, reason=_read_timeout())
        assert driver_unresponsive(exc)

    def test_it_is_found_through_the_exception_chain(self):
        try:
            try:
                raise _read_timeout()
            except Exception as inner:
                raise RuntimeError("wrapped") from inner
        except RuntimeError as outer:
            assert driver_unresponsive(outer)

    @pytest.mark.parametrize("exc", [TimeoutError(), ConnectionRefusedError()])
    def test_socket_level_failures_are_a_dead_driver(self, exc):
        assert driver_unresponsive(exc)

    def test_a_page_load_timeout_is_not(self):
        """Chrome answered: the page was slow. That is worth retrying."""
        assert not driver_unresponsive(selenium_exceptions.TimeoutException("load"))

    def test_any_webdriver_exception_is_not(self):
        """chromedriver replying with an error is chromedriver alive."""
        exc = selenium_exceptions.WebDriverException("no such element")
        exc.__cause__ = _read_timeout()
        assert not driver_unresponsive(exc)

    def test_an_ordinary_error_is_not(self):
        assert not driver_unresponsive(ValueError("bad selector"))

    def test_a_self_referential_chain_terminates(self):
        exc = RuntimeError("loop")
        exc.__context__ = exc
        assert not driver_unresponsive(exc)


class TestKillingIt:
    def _driver(self, service_pid=111, browser_pid=222):
        driver = MagicMock()
        driver.service.process.pid = service_pid
        driver.browser_pid = browser_pid
        return driver

    def test_both_processes_are_found(self):
        assert driver_pids(self._driver()) == [111, 222]

    def test_a_driver_without_them_yields_nothing(self):
        driver = MagicMock(spec=[])
        assert driver_pids(driver) == []

    def test_they_are_signalled_and_the_driver_is_never_asked(self):
        driver = self._driver()
        with patch.object(driver_health.os, "kill") as kill:
            assert kill_driver(driver) == [111, 222]
        assert kill.call_count == 2
        driver.quit.assert_not_called()

    def test_an_already_dead_process_is_not_an_error(self):
        with patch.object(driver_health.os, "kill", side_effect=ProcessLookupError):
            assert kill_driver(self._driver()) == []


@pytest.fixture
def shared_driver():
    saved = (
        ContentExtractor._shared_persistent_driver,
        ContentExtractor._shared_driver_reuse_count,
        ContentExtractor._authenticated_domains,
        ContentExtractor._auth_failed_domains,
        ContentExtractor._auth_attempts,
    )
    driver = MagicMock()
    driver.service.process.pid = 111
    driver.browser_pid = 222
    ContentExtractor._shared_persistent_driver = driver
    ContentExtractor._authenticated_domains = {"yakimaherald.com"}
    ContentExtractor._auth_failed_domains = {"x.example"}
    ContentExtractor._auth_attempts = {"yakimaherald.com": 1}
    yield driver
    (
        ContentExtractor._shared_persistent_driver,
        ContentExtractor._shared_driver_reuse_count,
        ContentExtractor._authenticated_domains,
        ContentExtractor._auth_failed_domains,
        ContentExtractor._auth_attempts,
    ) = saved


class TestClosingAnUnresponsiveDriver:
    def test_it_is_killed_not_quit(self, shared_driver):
        with patch("src.crawler.kill_driver", return_value=[111, 222]) as kill:
            ContentExtractor().close_persistent_driver(unresponsive=True)
        kill.assert_called_once_with(shared_driver)
        shared_driver.quit.assert_not_called()

    def test_the_login_state_resets_as_for_any_new_driver(self, shared_driver):
        with patch("src.crawler.kill_driver", return_value=[]):
            ContentExtractor().close_persistent_driver(unresponsive=True)
        assert ContentExtractor._shared_persistent_driver is None
        assert ContentExtractor._authenticated_domains == set()
        assert ContentExtractor._auth_failed_domains == set()
        assert ContentExtractor._auth_attempts == {}

    def test_an_ordinary_close_still_quits(self, shared_driver):
        with patch("src.crawler.kill_driver") as kill:
            ContentExtractor().close_persistent_driver()
        shared_driver.quit.assert_called_once()
        kill.assert_not_called()


class TestNavigation:
    URL = "https://www.yakimaherald.com/news/local/article_de7b4664.html"

    def _extractor(self):
        e = ContentExtractor()
        e._maybe_import_selenium_cookies = MagicMock(return_value=False)
        e.close_persistent_driver = MagicMock()
        return e

    def _driver(self, get_error):
        driver = MagicMock()
        driver.get.side_effect = get_error
        for name in ("get_screenshot_as_base64", "get_log", "execute_script"):
            getattr(driver, name).side_effect = RuntimeError("diagnostics")
        return driver

    def test_a_dead_driver_costs_one_command(self):
        e, driver = self._extractor(), self._driver(_read_timeout())

        assert e._navigate_with_human_behavior(driver, self.URL) is False

        assert driver.get.call_count == 1
        driver.get_screenshot_as_base64.assert_not_called()
        driver.get_log.assert_not_called()
        e.close_persistent_driver.assert_called_once_with(unresponsive=True)

    def test_a_slow_page_still_gets_its_attempts(self):
        e = self._extractor()
        driver = self._driver(selenium_exceptions.TimeoutException("slow"))

        assert e._navigate_with_human_behavior(driver, self.URL) is False

        assert driver.get.call_count == 3
        e.close_persistent_driver.assert_not_called()


class TestTheReplacementDriverHasNoSession:
    def test_a_login_host_is_not_refetched_after_a_reset(self):
        """Source-level, because reaching this branch needs a navigation that
        succeeds and then a detector that raises -- the order is the point."""
        import inspect

        body = inspect.getsource(ContentExtractor._navigate_with_human_behavior)
        reset = body.index("except Exception as driver_exc:")
        after = body[reset:]
        guard = after.index("if self._requires_login(domain):")
        refetch = after.index("driver = self.get_persistent_driver()")
        assert guard < refetch
        assert "unresponsive=driver_unresponsive(driver_exc)" in after[:guard]
