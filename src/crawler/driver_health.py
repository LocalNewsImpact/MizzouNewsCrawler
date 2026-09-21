"""A browser that stops answering is replaced, not retried.

Two things can go wrong with a Selenium navigation, and they need opposite
responses:

- THE PAGE did not load in time. Chrome answered and said so -- Selenium raises
  its own `TimeoutException` (a `WebDriverException`). A retry with a longer
  page-load timeout is a reasonable thing to try.
- THE DRIVER did not answer at all. The HTTP call from Python to chromedriver on
  `localhost` timed out at the command executor's client timeout, and the
  exception is urllib3's, not Selenium's. Every later command on that driver
  waits out the same timeout.

On 2026-09-21 a Chrome driver stopped answering on yakimaherald.com at 15:23 UTC.
Each `driver.get` took exactly 30.0s (the client timeout, not the page-load
timeout), and each failed attempt then ran about eight diagnostic commands --
screenshot, logs, cookies, localStorage -- against the same dead driver, each
with urllib3's three retries. About twelve minutes per article, three articles
per turn, and the worker made no queue request for sixteen minutes while it
kept pointing a browser at a publisher that had served reCAPTCHA two days
before. `quit()` would have hung the same way.

So a transport failure ends the navigation at once, and the driver is killed
from outside -- its processes signalled, never asked -- so the next article
starts on a new one.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
from typing import Any, Iterator

logger = logging.getLogger(__name__)

#: urllib3 names, matched by class name so this module imports neither urllib3
#: nor Selenium -- the extractor runs where either may be absent.
_TRANSPORT_FAILURES = frozenset(
    {
        "ReadTimeoutError",
        "ConnectTimeoutError",
        "MaxRetryError",
        "NewConnectionError",
        "ProtocolError",
        "RemoteDisconnected",
    }
)


class DriverUnresponsive(RuntimeError):
    """Raised where a login page load finds the driver not answering.

    A login swallowed every navigation error and carried on, which on a dead
    driver meant polling a page that never came for its fields. Spokesman,
    2026-09-21 17:08 UTC: the Auth0 authorize load timed out on localhost, the
    field search then waited three minutes on the stalled driver, found half a
    page, and spent one of the two login attempts on it. Raised instead, so the
    caller can replace the driver without charging the host for it.
    """


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _is_webdriver_exception(exc: BaseException) -> bool:
    return any(k.__name__ == "WebDriverException" for k in type(exc).__mro__)


def driver_unresponsive(exc: BaseException) -> bool:
    """True when the driver itself did not answer, rather than the page.

    A Selenium `WebDriverException` at the top means chromedriver replied --
    including its page-load `TimeoutException` -- so it is not this, whatever
    it wraps.
    """
    if _is_webdriver_exception(exc):
        return False
    for link in _chain(exc):
        if type(link).__name__ in _TRANSPORT_FAILURES:
            return True
        if isinstance(link, (socket.timeout, ConnectionRefusedError)):
            return True
    return False


def driver_pids(driver: Any) -> list[int]:
    """The chromedriver and browser process ids a driver object knows about.

    Selenium keeps the chromedriver process on `driver.service.process`;
    undetected-chromedriver also records the browser as `browser_pid`.
    """
    pids: list[int] = []
    service = getattr(driver, "service", None)
    process = getattr(service, "process", None)
    pid = getattr(process, "pid", None)
    if isinstance(pid, int):
        pids.append(pid)
    browser_pid = getattr(driver, "browser_pid", None)
    if isinstance(browser_pid, int) and browser_pid not in pids:
        pids.append(browser_pid)
    return pids


def kill_driver(driver: Any) -> list[int]:
    """Signal the driver's processes without sending it a command.

    `quit()` is a command, and a driver that does not answer commands does not
    answer that one either. Returns the pids signalled.
    """
    killed: list[int] = []
    for pid in driver_pids(driver):
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except ProcessLookupError:
            pass
        except Exception as e:  # pragma: no cover - platform-specific
            logger.warning("Could not kill driver process %s: %s", pid, e)
    return killed
