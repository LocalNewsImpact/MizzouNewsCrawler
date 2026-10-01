"""Discovery's browser of last resort: a homepage whose links exist only after
JavaScript runs.

Some sites (Wix, React and similar builders) answer a plain request with an
empty shell and write their links in client-side. Discovery read that shell,
found nothing, and recorded the source as having no new articles -- so no link
was ever queued, and extraction's own browser never got a page to open. The
site was dead to the pipeline while looking exactly like a quiet one.

This module renders such a homepage in the same browser extraction uses, so
the rules that already govern browser traffic govern this too:

- Egress goes through the auth relay, which asks the proxy router which Squid
  serves each host (``proxy_relay._router_upstream``).
- A source still inside its bot-detection backoff is not rendered.
- The render waits out the source's bot-sensitivity delay after the plain
  fetch that just hit the same host.
- A challenge on the rendered page is recorded as a bot detection, which
  raises the source's sensitivity exactly as an extraction challenge does.
- A run renders at most ``DISCOVERY_RENDER_MAX_PER_RUN`` homepages.

The need is remembered in ``sources.metadata`` so the next run goes straight
to the browser instead of fetching a shell it already knows is empty.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

#: Set once a render found links the plain fetch could not. Its presence sends
#: the next run straight to the browser.
RENDER_REQUIRED_KEY = "discovery_render_required"

#: The latest plain-fetch verdict that the homepage is a script shell, kept
#: whether or not a render followed -- the signal on its own.
RENDER_SIGNAL_KEY = "discovery_render_signal"

#: Consecutive remembered renders that found no links. At FORGET_AFTER_MISSES
#: the memory is dropped and the next run tries a plain fetch again, in case
#: the site stopped needing a browser.
RENDER_MISSES_KEY = "discovery_render_misses"
FORGET_AFTER_MISSES = 3

DEFAULT_MAX_RENDERS_PER_RUN = 25


def render_is_remembered(source_meta: dict | None) -> bool:
    """Whether an earlier run found this homepage needs a browser."""
    return isinstance(source_meta, dict) and bool(source_meta.get(RENDER_REQUIRED_KEY))


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def signal_update(signals: dict[str, Any]) -> dict[str, Any]:
    """The metadata write recording that a plain fetch saw a script shell."""
    return {RENDER_SIGNAL_KEY: {"at": _now_iso(), "signals": signals}}


def remember_update(links_found: int) -> dict[str, Any]:
    """The metadata write recording that the browser found links."""
    return {
        RENDER_REQUIRED_KEY: {"since": _now_iso(), "links_found": links_found},
        RENDER_MISSES_KEY: 0,
    }


def miss_update(source_meta: dict | None) -> dict[str, Any]:
    """The metadata write for a remembered render that found nothing.

    After FORGET_AFTER_MISSES in a row the memory is cleared, so a site that
    no longer needs a browser is not rendered forever.
    """
    misses = 0
    if isinstance(source_meta, dict):
        try:
            misses = int(source_meta.get(RENDER_MISSES_KEY) or 0)
        except (TypeError, ValueError):
            misses = 0
    misses += 1
    if misses >= FORGET_AFTER_MISSES:
        return {RENDER_REQUIRED_KEY: None, RENDER_MISSES_KEY: 0}
    return {RENDER_MISSES_KEY: misses}


@dataclass
class RenderOutcome:
    """What a render attempt produced, and why if it produced nothing."""

    html: str | None = None
    skipped: str | None = None  # budget | backoff | unavailable | error
    challenge: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def rendered(self) -> bool:
        return bool(self.html) and not self.challenge


def _default_extractor_factory():
    from src.crawler import ContentExtractor

    # Headless unless told otherwise: the discovery pod runs no X server, and
    # the extractor's "headful" default would start Chrome against a display
    # that is not there.
    mode = os.getenv("DISCOVERY_SELENIUM_MODE", "headless")
    return ContentExtractor(selenium_mode=mode)


def _default_sensitivity_manager():
    from src.utils.bot_sensitivity_manager import BotSensitivityManager

    return BotSensitivityManager()


class HomepageRenderer:
    """Render homepages in the extraction browser, under its rate rules.

    The browser and the bot-sensitivity manager are created on first use: a
    discovery run that meets no script shell starts no Chrome.
    """

    def __init__(
        self,
        *,
        max_renders: int | None = None,
        extractor_factory: Callable[[], Any] | None = None,
        sensitivity_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if max_renders is None:
            try:
                max_renders = int(
                    os.getenv(
                        "DISCOVERY_RENDER_MAX_PER_RUN",
                        str(DEFAULT_MAX_RENDERS_PER_RUN),
                    )
                )
            except ValueError:
                max_renders = DEFAULT_MAX_RENDERS_PER_RUN
        self.max_renders = max_renders
        self.renders = 0
        self._extractor_factory = extractor_factory or _default_extractor_factory
        self._sensitivity_factory = sensitivity_factory or _default_sensitivity_manager
        self._extractor = None
        self._sensitivity = None
        self._sleep = sleep

    def _get_sensitivity(self):
        if self._sensitivity is None:
            self._sensitivity = self._sensitivity_factory()
        return self._sensitivity

    def _get_extractor(self):
        if self._extractor is None:
            self._extractor = self._extractor_factory()
        return self._extractor

    def _in_bot_backoff(self, host: str, source_id: str | None) -> bool:
        """Whether the source's last bot detection is inside its backoff.

        The extractor's own backoff lives in process memory, so it says
        nothing about a challenge another pod met an hour ago. The persisted
        record is ``sources.last_bot_detection_at``; the window is the
        source's sensitivity-scaled ``captcha_backoff_max``.
        """
        manager = self._get_sensitivity()
        config = manager.get_sensitivity_config(host, source_id)
        window = float(config.get("captcha_backoff_max", 3600))
        last = None
        try:
            last = manager.get_last_bot_detection_at(host, source_id)
        except Exception:
            logger.debug("last bot detection lookup failed for %s", host)
        if last is None:
            return False
        if last.tzinfo is not None:
            last = last.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime.utcnow() - last < timedelta(seconds=window)

    def _space_after_plain_fetch(self, host: str, source_id: str | None) -> None:
        config = self._get_sensitivity().get_sensitivity_config(host, source_id)
        low = float(config.get("inter_request_min", 1.0))
        high = float(config.get("inter_request_max", max(low, 2.5)))
        self._sleep(random.uniform(low, max(low, high)))

    def render(
        self,
        url: str,
        source_id: str | None = None,
        *,
        just_fetched: bool = False,
    ) -> RenderOutcome:
        """Render ``url`` and return its HTML, or why there is none.

        ``just_fetched`` says a plain request reached this host moments ago,
        so the render waits out the inter-request delay first.
        """
        host = urlparse(url).netloc
        if self.renders >= self.max_renders:
            logger.info(
                "Not rendering %s: %d homepages already rendered this run",
                url,
                self.renders,
            )
            return RenderOutcome(skipped="budget")

        try:
            if self._in_bot_backoff(host, source_id):
                logger.info("Not rendering %s: source is in bot backoff", url)
                return RenderOutcome(skipped="backoff")
        except Exception:
            logger.debug("bot backoff check failed for %s", url, exc_info=True)

        try:
            extractor = self._get_extractor()
        except Exception as exc:
            logger.warning("No browser for discovery render of %s: %s", url, exc)
            return RenderOutcome(skipped="unavailable", details={"error": str(exc)})

        if extractor._check_rate_limit(host):
            logger.info("Not rendering %s: domain is in CAPTCHA backoff", url)
            return RenderOutcome(skipped="backoff")

        if just_fetched:
            try:
                self._space_after_plain_fetch(host, source_id)
            except Exception:
                logger.debug("render spacing lookup failed for %s", url)

        self.renders += 1
        try:
            driver = extractor.get_persistent_driver()
            if not extractor._navigate_with_human_behavior(driver, url):
                return RenderOutcome(skipped="error", details={"navigation": False})

            if extractor._detect_captcha_or_challenge(driver):
                logger.warning("Rendered homepage %s is a bot challenge", url)
                extractor._handle_captcha_backoff(host)
                try:
                    self._get_sensitivity().record_bot_detection(
                        host,
                        url,
                        "captcha_detected",
                        response_indicators={"stage": "discovery_render"},
                        source_id=source_id,
                    )
                except Exception:
                    logger.debug("bot detection record failed for %s", url)
                return RenderOutcome(challenge=True)

            html = driver.page_source
            logger.info("Rendered homepage %s (%d chars)", url, len(html or ""))
            return RenderOutcome(html=html)
        except Exception as exc:
            logger.warning("Discovery render of %s failed: %s", url, exc)
            try:
                extractor.close_persistent_driver()
            except Exception:
                pass
            return RenderOutcome(skipped="error", details={"error": str(exc)[:200]})

    def close(self) -> None:
        """Quit the browser if one was started."""
        if self._extractor is not None:
            try:
                self._extractor.close_persistent_driver()
            except Exception:
                logger.debug("closing discovery browser failed", exc_info=True)
