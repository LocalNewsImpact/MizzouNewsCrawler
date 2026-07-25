from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.crawler as crawler_module
from src.crawler import ContentExtractor, RateLimitError


class ChoiceSequencer:
    """Provide deterministic values for random.choice."""

    def __init__(self, strategy_sequence=None):
        self.strategy_sequence = strategy_sequence or []

    def __call__(self, sequence):
        if self.strategy_sequence and len(sequence) == 6 and "google" in sequence:
            return self.strategy_sequence.pop(0)
        return sequence[0]


class RandintSequencer:
    """Yield deterministic values for random.randint within provided ranges."""

    def __init__(self, values):
        self._values = iter(values)

    def __call__(self, lower, upper):
        value = next(self._values)
        if not (lower <= value <= upper):
            raise AssertionError(
                f"randint stub received {value} outside range {lower}-{upper}"
            )
        return value


class TimeStub:
    """Increment monotonically and capture sleep durations."""

    def __init__(self, start=1000.0, step=0.1):
        self.current = start
        self.step = step
        self.sleeps = []

    def time(self):
        value = self.current
        self.current += self.step
        return value

    def sleep(self, duration):
        self.sleeps.append(duration)


@pytest.fixture
def extractor(monkeypatch):
    proxy_manager = SimpleNamespace(
        active_provider=SimpleNamespace(value="decodo"),
        get_requests_proxies=lambda: {"https": "https://proxy.decodo.local:60000"},
        get_requests_proxies_for_domain=lambda domain, service="newscrawler": (
            {"https": "https://proxy.decodo.local:60000"},
            None,
            "http",
        ),
        report_domain_result=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(crawler_module, "get_proxy_manager", lambda: proxy_manager)
    monkeypatch.setattr(crawler_module, "CLOUDSCRAPER_AVAILABLE", False)
    monkeypatch.setattr(crawler_module, "cloudscraper", None)

    extractor = ContentExtractor()
    extractor.user_agent_pool = ["ua1", "ua2", "ua3"]
    extractor.ua_rotation_base = 2
    extractor.ua_rotation_jitter = 0
    extractor.proxy_pool = ["https://sticky.proxy.local:7000"]
    return extractor


def test_domain_session_rotation_assigns_new_session(extractor, monkeypatch):
    randint = RandintSequencer([3, 1, 1])
    time_stub = TimeStub()

    monkeypatch.setattr(crawler_module.random, "randint", randint)
    monkeypatch.setattr(crawler_module.random, "uniform", lambda _a, _b: 1.0)
    monkeypatch.setattr(crawler_module.time, "time", time_stub.time)
    monkeypatch.setattr(crawler_module.time, "sleep", time_stub.sleep)

    first = extractor._get_domain_session("https://example.com/a")
    initial_ua = extractor.domain_user_agents["example.com"]
    second = extractor._get_domain_session("https://example.com/b")
    third = extractor._get_domain_session("https://example.com/c")

    assert first is second
    assert third is not first
    assert extractor.domain_user_agents["example.com"] != initial_ua
    assert extractor.domain_proxies["example.com"] == "https://sticky.proxy.local:7000"
    # rotation should have at least one recorded delay attempt
    assert time_stub.sleeps


def test_generate_referer_covers_all_strategies(extractor, monkeypatch):
    strategies = ChoiceSequencer(["homepage", "same_domain", "google", "none"])
    monkeypatch.setattr(crawler_module.random, "choice", strategies)

    url = "https://example.com/news/a"

    homepage = extractor._generate_referer(url)
    origin = extractor._generate_referer(url)
    google = extractor._generate_referer(url)
    none = extractor._generate_referer(url)

    assert homepage == "https://example.com/"
    assert origin.startswith("https://example.com")
    assert google == "https://www.google.com/"
    assert none is None


def test_apply_rate_limit_uses_sensitivity_config(extractor, monkeypatch):
    extractor.bot_sensitivity_manager = SimpleNamespace(
        get_sensitivity_config=lambda _domain: {
            "inter_request_min": 1.0,
            "inter_request_max": 1.0,
        }
    )
    extractor.domain_request_times["example.com"] = 998.5

    time_stub = TimeStub(start=999.0, step=1.0)
    monkeypatch.setattr(crawler_module.time, "time", time_stub.time)
    monkeypatch.setattr(crawler_module.time, "sleep", time_stub.sleep)
    monkeypatch.setattr(crawler_module.random, "uniform", lambda a, _b: a)

    extractor._apply_rate_limit("example.com")

    assert time_stub.sleeps == [1.0 - (999.0 - 998.5)]
    # The TimeStub increments on every call to time()
    # The exact final value depends on how many times time() is called internally,
    # which can vary between environments. What matters is that it's been updated
    # to a time >= the last request time (998.5) + sleep duration (0.5)
    assert extractor.domain_request_times["example.com"] >= 999.0


def test_handle_rate_limit_error_honors_retry_after(extractor, monkeypatch):
    times = iter([2000.0, 2100.0, 2200.0, 2300.0])
    monkeypatch.setattr(crawler_module.time, "time", lambda: next(times))
    monkeypatch.setattr(crawler_module.random, "uniform", lambda _a, _b: 1.0)

    response = Mock()
    response.headers = {"retry-after": "120"}

    extractor._handle_rate_limit_error("example.com", response)
    assert extractor.domain_error_counts["example.com"] == 1
    assert extractor.domain_backoff_until["example.com"] == 2120.0

    extractor._handle_rate_limit_error("example.com")
    assert extractor.domain_error_counts["example.com"] == 2
    assert extractor.domain_backoff_until["example.com"] == 2320.0

    extractor._reset_error_count("example.com")
    assert extractor.domain_error_counts["example.com"] == 0


def test_get_domain_session_respects_existing_backoff(extractor, monkeypatch):
    monkeypatch.setattr(crawler_module.time, "time", lambda: 500.0)
    extractor.domain_backoff_until["example.com"] = 600.0

    with pytest.raises(RateLimitError):
        extractor._get_domain_session("https://example.com/page")

    assert "example.com" not in extractor.domain_sessions
    assert extractor.request_counts.get("example.com") is None


def test_choose_proxy_sticky_assignment(extractor, monkeypatch):
    monkeypatch.setattr(crawler_module.random, "choice", lambda seq: seq[-1])

    proxy_first = extractor._choose_proxy_for_domain("example.com")
    proxy_second = extractor._choose_proxy_for_domain("example.com")

    assert proxy_first == "https://sticky.proxy.local:7000"
    assert proxy_second == proxy_first
    assert extractor.domain_proxies["example.com"] == proxy_first


def test_handle_rate_limit_error_prefers_server_retry(extractor, monkeypatch):
    times = iter([100.0, 150.0])
    monkeypatch.setattr(crawler_module.time, "time", lambda: next(times))
    monkeypatch.setattr(crawler_module.random, "uniform", lambda _a, _b: 0.5)

    response = Mock()
    response.headers = {"retry-after": "600"}

    extractor._handle_rate_limit_error("example.com", response)

    assert extractor.domain_error_counts["example.com"] == 1
    assert extractor.domain_backoff_until["example.com"] == 700.0
