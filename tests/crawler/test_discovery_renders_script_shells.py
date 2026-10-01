"""A homepage whose links exist only after JavaScript runs is rendered.

Before this, discovery read the empty shell such a site serves to a plain
request, found no links, and recorded a quiet day -- so nothing was queued and
extraction's browser never saw a page from the site.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.crawler import discovery as discovery_module
from src.crawler import discovery_render
from src.crawler.discovery_render import (
    FORGET_AFTER_MISSES,
    RENDER_MISSES_KEY,
    RENDER_REQUIRED_KEY,
    RENDER_SIGNAL_KEY,
    HomepageRenderer,
    RenderOutcome,
    miss_update,
    remember_update,
    render_is_remembered,
)
from src.utils.bot_sensitivity_manager import BotSensitivityManager

SOURCE_URL = "https://example.com"

SHELL = (
    '<html><head><script src="/app.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)

RENDERED = (
    "<html><body>"
    + "".join(
        f'<a href="/news/2026/09/30/council-votes-on-budget-{i}">Council {i}</a>'
        f"<p>Story text about the council meeting {i}.</p>"
        for i in range(4)
    )
    + "</body></html>"
)


# ---------------------------------------------------------------- doubles


class FakeSensitivity:
    def __init__(self, last_detection=None, config=None):
        self.last_detection = last_detection
        self.config = config or {
            "inter_request_min": 2.0,
            "inter_request_max": 4.0,
            "captcha_backoff_max": 3600,
        }
        self.detections: list[tuple] = []

    def get_sensitivity_config(self, host, source_id=None):
        return self.config

    def get_last_bot_detection_at(self, host, source_id=None):
        return self.last_detection

    def record_bot_detection(self, host, url, event_type, **kwargs):
        self.detections.append((host, url, event_type, kwargs))
        return 6


class FakeExtractor:
    def __init__(self, *, html=RENDERED, navigates=True, challenge=False):
        self.html = html
        self.navigates = navigates
        self.challenge = challenge
        self.backoff_domains: set[str] = set()
        self.captcha_backoffs: list[str] = []
        self.closed = 0
        self.navigated: list[str] = []
        self.driver_error: Exception | None = None

    def _check_rate_limit(self, domain):
        return domain in self.backoff_domains

    def get_persistent_driver(self):
        if self.driver_error:
            raise self.driver_error
        return SimpleNamespace(page_source=self.html)

    def _navigate_with_human_behavior(self, driver, url):
        self.navigated.append(url)
        return self.navigates

    def _detect_captcha_or_challenge(self, driver):
        return self.challenge

    def _handle_captcha_backoff(self, domain):
        self.captcha_backoffs.append(domain)

    def close_persistent_driver(self):
        self.closed += 1


def make_renderer(extractor=None, sensitivity=None, max_renders=5, sleeps=None):
    extractor = extractor or FakeExtractor()
    sensitivity = sensitivity or FakeSensitivity()
    sleeps = sleeps if sleeps is not None else []
    renderer = HomepageRenderer(
        max_renders=max_renders,
        extractor_factory=lambda: extractor,
        sensitivity_factory=lambda: sensitivity,
        sleep=sleeps.append,
    )
    return renderer, extractor, sensitivity, sleeps


# ------------------------------------------------------- the renderer's rules


class TestRendererRules:
    def test_renders_the_page_through_the_extraction_browser(self):
        renderer, extractor, _, _ = make_renderer()
        outcome = renderer.render(SOURCE_URL, "src-1")
        assert outcome.rendered
        assert outcome.html == RENDERED
        assert extractor.navigated == [SOURCE_URL]

    def test_waits_out_the_sensitivity_delay_after_a_plain_fetch(self):
        renderer, _, _, sleeps = make_renderer()
        renderer.render(SOURCE_URL, "src-1", just_fetched=True)
        assert len(sleeps) == 1
        assert 2.0 <= sleeps[0] <= 4.0

    def test_no_delay_when_nothing_just_hit_the_host(self):
        renderer, _, _, sleeps = make_renderer()
        renderer.render(SOURCE_URL, "src-1")
        assert sleeps == []

    def test_stops_at_the_per_run_budget(self):
        renderer, extractor, _, _ = make_renderer(max_renders=1)
        assert renderer.render(SOURCE_URL).rendered
        outcome = renderer.render("https://other.example.com")
        assert outcome.skipped == "budget"
        assert extractor.navigated == [SOURCE_URL]

    def test_skips_a_source_inside_its_persisted_bot_backoff(self):
        recent = datetime.utcnow() - timedelta(minutes=10)
        renderer, extractor, _, _ = make_renderer(
            sensitivity=FakeSensitivity(last_detection=recent)
        )
        outcome = renderer.render(SOURCE_URL, "src-1")
        assert outcome.skipped == "backoff"
        assert extractor.navigated == []

    def test_a_timezone_aware_detection_is_compared_in_utc(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=10)
        renderer, extractor, _, _ = make_renderer(
            sensitivity=FakeSensitivity(last_detection=recent)
        )
        assert renderer.render(SOURCE_URL).skipped == "backoff"

    def test_renders_once_the_backoff_has_passed(self):
        old = datetime.utcnow() - timedelta(hours=3)
        renderer, _, _, _ = make_renderer(
            sensitivity=FakeSensitivity(last_detection=old)
        )
        assert renderer.render(SOURCE_URL).rendered

    def test_a_failed_backoff_lookup_does_not_stop_the_render(self):
        sensitivity = FakeSensitivity()
        sensitivity.get_last_bot_detection_at = Mock(side_effect=RuntimeError)
        renderer, _, _, _ = make_renderer(sensitivity=sensitivity)
        assert renderer.render(SOURCE_URL).rendered

    def test_a_broken_sensitivity_manager_does_not_stop_the_render(self):
        sensitivity = FakeSensitivity()
        sensitivity.get_sensitivity_config = Mock(side_effect=RuntimeError)
        renderer, _, _, sleeps = make_renderer(sensitivity=sensitivity)
        assert renderer.render(SOURCE_URL, just_fetched=True).rendered
        assert sleeps == []

    def test_skips_a_domain_in_the_extractors_captcha_backoff(self):
        extractor = FakeExtractor()
        extractor.backoff_domains.add("example.com")
        renderer, _, _, _ = make_renderer(extractor=extractor)
        assert renderer.render(SOURCE_URL).skipped == "backoff"

    def test_a_challenge_is_recorded_as_a_bot_detection(self):
        extractor = FakeExtractor(challenge=True)
        renderer, _, sensitivity, _ = make_renderer(extractor=extractor)
        outcome = renderer.render(SOURCE_URL, "src-1")
        assert outcome.challenge and not outcome.rendered
        assert extractor.captcha_backoffs == ["example.com"]
        host, url, event, kwargs = sensitivity.detections[0]
        assert (host, url, event) == ("example.com", SOURCE_URL, "captcha_detected")
        assert kwargs["source_id"] == "src-1"

    def test_a_failed_detection_record_still_reports_the_challenge(self):
        sensitivity = FakeSensitivity()
        sensitivity.record_bot_detection = Mock(side_effect=RuntimeError)
        renderer, _, _, _ = make_renderer(
            extractor=FakeExtractor(challenge=True), sensitivity=sensitivity
        )
        assert renderer.render(SOURCE_URL).challenge

    def test_failed_navigation_renders_nothing(self):
        renderer, _, _, _ = make_renderer(extractor=FakeExtractor(navigates=False))
        assert renderer.render(SOURCE_URL).skipped == "error"

    def test_a_driver_error_closes_the_driver(self):
        extractor = FakeExtractor()
        extractor.driver_error = RuntimeError("chrome died")
        renderer, _, _, _ = make_renderer(extractor=extractor)
        outcome = renderer.render(SOURCE_URL)
        assert outcome.skipped == "error"
        assert "chrome died" in outcome.details["error"]
        assert extractor.closed == 1

    def test_no_browser_means_no_render(self):
        renderer = HomepageRenderer(
            max_renders=5,
            extractor_factory=Mock(side_effect=RuntimeError("no chrome")),
            sensitivity_factory=FakeSensitivity,
        )
        assert renderer.render(SOURCE_URL).skipped == "unavailable"

    def test_close_quits_a_started_browser_only(self):
        renderer, extractor, _, _ = make_renderer()
        renderer.close()
        assert extractor.closed == 0
        renderer.render(SOURCE_URL)
        renderer.close()
        assert extractor.closed == 1

    @pytest.mark.parametrize(
        "env, expected",
        [(None, discovery_render.DEFAULT_MAX_RENDERS_PER_RUN), ("3", 3), ("x", 25)],
    )
    def test_budget_comes_from_the_environment(self, monkeypatch, env, expected):
        if env is None:
            monkeypatch.delenv("DISCOVERY_RENDER_MAX_PER_RUN", raising=False)
        else:
            monkeypatch.setenv("DISCOVERY_RENDER_MAX_PER_RUN", env)
        assert HomepageRenderer().max_renders == expected

    def test_the_default_browser_is_headless(self, monkeypatch):
        monkeypatch.delenv("DISCOVERY_SELENIUM_MODE", raising=False)
        with patch("src.crawler.ContentExtractor") as extractor_cls:
            discovery_render._default_extractor_factory()
        extractor_cls.assert_called_once_with(selenium_mode="headless")

    def test_the_default_sensitivity_manager(self):
        with patch("src.utils.bot_sensitivity_manager.DatabaseManager"):
            manager = discovery_render._default_sensitivity_manager()
        assert isinstance(manager, BotSensitivityManager)


# --------------------------------------------------------------- the memory


class TestRenderMemory:
    def test_remembered_only_when_set(self):
        assert not render_is_remembered(None)
        assert not render_is_remembered({})
        assert not render_is_remembered({RENDER_REQUIRED_KEY: None})
        assert render_is_remembered({RENDER_REQUIRED_KEY: {"since": "x"}})

    def test_remember_resets_the_misses(self):
        update = remember_update(4)
        assert update[RENDER_REQUIRED_KEY]["links_found"] == 4
        assert update[RENDER_MISSES_KEY] == 0

    def test_misses_count_up_then_forget(self):
        meta: dict[str, Any] = {RENDER_REQUIRED_KEY: {"since": "x"}}
        for expected in range(1, FORGET_AFTER_MISSES):
            update = miss_update(meta)
            assert update == {RENDER_MISSES_KEY: expected}
            meta.update(update)
        assert miss_update(meta) == {RENDER_REQUIRED_KEY: None, RENDER_MISSES_KEY: 0}

    def test_a_garbled_miss_count_starts_over(self):
        assert miss_update({RENDER_MISSES_KEY: "lots"}) == {RENDER_MISSES_KEY: 1}
        assert miss_update(None) == {RENDER_MISSES_KEY: 1}


# ---------------------------------------------------- discovery's homepage step


class FakeRenderer:
    def __init__(self, outcome: RenderOutcome):
        self.outcome = outcome
        self.calls: list[tuple] = []
        self.closed = False

    def render(self, url, source_id=None, *, just_fetched=False):
        self.calls.append((url, source_id, just_fetched))
        return self.outcome

    def close(self):
        self.closed = True


def make_discovery(page=SHELL, status=200, renderer=None, enabled=True):
    d = discovery_module.NewsDiscovery.__new__(discovery_module.NewsDiscovery)
    d.timeout = 30
    d.user_agent = "test"
    d.max_articles_per_source = 25
    d.telemetry = None
    d.database_url = None
    d.proxy_pool = []
    d._render_homepages = enabled
    d._homepage_renderer = renderer
    d.fetches = []
    d.meta_writes = []

    def fetch(url, timeout=None):
        d.fetches.append(url)
        return SimpleNamespace(status_code=status, text=page)

    d._fetch_with_ssl_fallback = fetch
    d._update_source_meta = lambda sid, updates: d.meta_writes.append(updates)
    d._get_existing_urls = lambda host=None: set()
    d._discover_from_section_urls = lambda **kw: []
    return d


class TestHomepageStep:
    def test_a_script_shell_is_signalled_and_rendered(self):
        renderer = FakeRenderer(RenderOutcome(html=RENDERED))
        d = make_discovery(renderer=renderer)
        html, status, rendered = d._homepage_html(SOURCE_URL, "src-1", None)
        assert (html, status, rendered) == (RENDERED, 200, True)
        assert renderer.calls == [(SOURCE_URL, "src-1", True)]
        signal = d.meta_writes[0][RENDER_SIGNAL_KEY]
        assert signal["signals"]["spa_root"] is True

    def test_an_ordinary_homepage_is_not_rendered(self):
        renderer = FakeRenderer(RenderOutcome(html=RENDERED))
        d = make_discovery(page=RENDERED, renderer=renderer)
        assert d._homepage_html(SOURCE_URL, "src-1", None) == (RENDERED, 200, False)
        assert renderer.calls == [] and d.meta_writes == []

    def test_an_error_page_is_not_diagnosed(self):
        renderer = FakeRenderer(RenderOutcome(html=RENDERED))
        d = make_discovery(status=404, renderer=renderer)
        assert d._homepage_html(SOURCE_URL, "src-1", None)[2] is False
        assert renderer.calls == [] and d.meta_writes == []

    def test_a_remembered_source_goes_straight_to_the_browser(self):
        renderer = FakeRenderer(RenderOutcome(html=RENDERED))
        d = make_discovery(renderer=renderer)
        meta = {RENDER_REQUIRED_KEY: {"since": "x"}}
        assert d._homepage_html(SOURCE_URL, "src-1", meta) == (RENDERED, None, True)
        assert d.fetches == []
        assert renderer.calls == [(SOURCE_URL, "src-1", False)]

    def test_a_failed_remembered_render_falls_back_without_a_second_render(self):
        renderer = FakeRenderer(RenderOutcome(skipped="backoff"))
        d = make_discovery(renderer=renderer)
        meta = {RENDER_REQUIRED_KEY: {"since": "x"}}
        assert d._homepage_html(SOURCE_URL, "src-1", meta) == (SHELL, 200, False)
        assert d.fetches == [SOURCE_URL]
        assert len(renderer.calls) == 1

    def test_a_skipped_render_keeps_the_signal(self):
        d = make_discovery(renderer=FakeRenderer(RenderOutcome(skipped="budget")))
        assert d._homepage_html(SOURCE_URL, "src-1", None) == (SHELL, 200, False)
        assert RENDER_SIGNAL_KEY in d.meta_writes[0]

    def test_with_rendering_switched_off_the_signal_is_still_written(self):
        d = make_discovery(enabled=False)
        assert d._homepage_html(SOURCE_URL, "src-1", None) == (SHELL, 200, False)
        assert RENDER_SIGNAL_KEY in d.meta_writes[0]
        assert d._homepage_renderer is None

    def test_an_unreadable_response_is_passed_through(self):
        d = make_discovery(page=MagicMock(), renderer=FakeRenderer(RenderOutcome()))
        assert d._homepage_html(SOURCE_URL, None, None)[2] is False

    def test_a_failed_diagnosis_is_passed_through(self):
        d = make_discovery(renderer=FakeRenderer(RenderOutcome()))
        with patch(
            "src.utils.capture_diagnosis.diagnose_capture",
            side_effect=RuntimeError,
        ):
            assert d._homepage_html(SOURCE_URL, None, None) == (SHELL, 200, False)


class TestSettleMemory:
    remembered = {RENDER_REQUIRED_KEY: {"since": "x"}}

    def test_links_from_a_new_render_are_remembered(self):
        d = make_discovery()
        d._settle_render_memory("src-1", None, 4)
        assert d.meta_writes[0][RENDER_REQUIRED_KEY]["links_found"] == 4

    def test_links_from_a_remembered_render_write_nothing(self):
        d = make_discovery()
        d._settle_render_memory("src-1", dict(self.remembered), 4)
        assert d.meta_writes == []

    def test_links_after_misses_reset_them(self):
        d = make_discovery()
        meta = {**self.remembered, RENDER_MISSES_KEY: 2}
        d._settle_render_memory("src-1", meta, 4)
        assert d.meta_writes[0][RENDER_MISSES_KEY] == 0

    def test_no_links_from_a_remembered_render_is_a_miss(self):
        d = make_discovery()
        d._settle_render_memory("src-1", dict(self.remembered), 0)
        assert d.meta_writes == [{RENDER_MISSES_KEY: 1}]

    def test_no_links_from_a_new_render_writes_nothing(self):
        d = make_discovery()
        d._settle_render_memory("src-1", None, 0)
        assert d.meta_writes == []


class TestDiscoveryEndToEnd:
    def test_a_script_shell_site_yields_rendered_links_without_a_build(self):
        renderer = FakeRenderer(RenderOutcome(html=RENDERED))
        d = make_discovery(renderer=renderer)
        with patch.object(discovery_module, "_newspaper_build_worker") as build:
            found = d.discover_with_newspaper4k(SOURCE_URL, rss_already_attempted=True)
        build.assert_not_called()
        assert len(found) == 4
        assert {a["discovery_method"] for a in found} == {"homepage_rendered"}
        assert all(a["metadata"]["homepage_rendered"] for a in found)
        assert any(RENDER_REQUIRED_KEY in w for w in d.meta_writes)

    def test_rendered_section_links_skip_the_build(self):
        sections = (
            '<html><body><a href="/category/news">News</a>'
            '<a href="/category/sports">Sports</a></body></html>'
        )
        d = make_discovery(renderer=FakeRenderer(RenderOutcome(html=sections)))
        with patch("multiprocessing.Process") as process:
            found = d.discover_with_newspaper4k(SOURCE_URL, rss_already_attempted=True)
        process.assert_not_called()
        assert found == []

    def test_an_ordinary_site_keeps_its_homepage_links_label(self):
        d = make_discovery(page=RENDERED, renderer=FakeRenderer(RenderOutcome()))
        found = d.discover_with_newspaper4k(SOURCE_URL, rss_already_attempted=True)
        assert {a["discovery_method"] for a in found} == {"homepage_links"}
        assert d._homepage_renderer.calls == []


class TestRendererLifecycle:
    def test_the_flag_defaults_on(self, monkeypatch):
        monkeypatch.delenv("DISCOVERY_RENDER_HOMEPAGES", raising=False)
        d = discovery_module.NewsDiscovery.__new__(discovery_module.NewsDiscovery)
        d._render_homepages = True
        assert isinstance(d._get_homepage_renderer(), HomepageRenderer)
        assert d._get_homepage_renderer() is d._homepage_renderer

    def test_a_double_without_the_flag_has_no_renderer(self):
        d = discovery_module.NewsDiscovery.__new__(discovery_module.NewsDiscovery)
        assert d._get_homepage_renderer() is None

    def test_close_quits_and_forgets_the_renderer(self):
        renderer = FakeRenderer(RenderOutcome())
        d = make_discovery(renderer=renderer)
        d.close_homepage_renderer()
        assert renderer.closed and d._homepage_renderer is None
        d.close_homepage_renderer()  # nothing left to close

    @pytest.mark.parametrize("value, enabled", [("true", True), ("off", False)])
    def test_init_reads_the_flag(self, monkeypatch, value, enabled):
        monkeypatch.setenv("DISCOVERY_RENDER_HOMEPAGES", value)
        with (
            patch.object(discovery_module.NewsDiscovery, "_configure_proxy_routing"),
            patch.object(discovery_module.NewsDiscovery, "_set_global_proxy_env"),
            patch.object(discovery_module, "create_telemetry_system"),
            patch.object(
                discovery_module.NewsDiscovery,
                "_resolve_database_url",
                return_value="postgresql://u:p@localhost/db",
            ),
        ):
            d = discovery_module.NewsDiscovery()
        assert d._render_homepages is enabled
        assert d._homepage_renderer is None


class TestErrorPagesAreNotDiagnosed:
    def _settle(self, status):
        d = discovery_module.NewsDiscovery.__new__(discovery_module.NewsDiscovery)
        d.proxy_manager = None
        d._note_capture_diagnosis = Mock()
        response = SimpleNamespace(status_code=status, text=SHELL)
        d._settle_response(SOURCE_URL, "example.com", None, None, response, 5, None)
        return d._note_capture_diagnosis

    def test_a_404_is_not_diagnosed(self):
        self._settle(404).assert_not_called()

    def test_a_200_is_diagnosed(self):
        self._settle(200).assert_called_once()


# ----------------------------------------------- the persisted detection read


@pytest.fixture
def sensitivity_manager():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    with patch("src.utils.bot_sensitivity_manager.DatabaseManager") as db_cls:
        db_cls.return_value.get_session.return_value = session
        manager = BotSensitivityManager()
        manager.db = db_cls.return_value
    return manager, session


class TestLastBotDetection:
    def test_read_by_source_id(self, sensitivity_manager):
        manager, session = sensitivity_manager
        when = datetime(2026, 9, 30, 12, 0)
        session.execute.return_value.fetchone.return_value = (when,)
        assert manager.get_last_bot_detection_at("example.com", "src-1") == when

    def test_read_by_host(self, sensitivity_manager):
        manager, session = sensitivity_manager
        when = datetime(2026, 9, 30, 12, 0)
        session.execute.return_value.fetchone.return_value = (when,)
        assert manager.get_last_bot_detection_at("example.com") == when

    def test_never_detected(self, sensitivity_manager):
        manager, session = sensitivity_manager
        session.execute.return_value.fetchone.return_value = (None,)
        assert manager.get_last_bot_detection_at("example.com", "src-1") is None

    def test_an_unusable_host_reads_nothing(self, sensitivity_manager):
        manager, _ = sensitivity_manager
        with patch(
            "src.utils.bot_sensitivity_manager.find_source_sql",
            return_value=(None, {}),
        ):
            assert manager.get_last_bot_detection_at("") is None

    def test_a_database_error_reads_nothing(self, sensitivity_manager):
        manager, session = sensitivity_manager
        session.execute.side_effect = RuntimeError("down")
        assert manager.get_last_bot_detection_at("example.com", "src-1") is None
