"""CDP Network events must be requested before the browser is built.

A capability is read once, when the driver is constructed. The
`goog:loggingPrefs` request sat 86 lines BELOW `uc.Chrome(**uc_kwargs)` in
`_create_undetected_driver`, setting a field on an options object nobody would
read again. It raised nothing and logged nothing, so the performance log was
never enabled on the driver every production fetch uses -- and three readers of
`driver.get_log("performance")` quietly got nothing:

* `read_navigation_status` -- so `candidate_links.http_status` was NULL on every
  Selenium fetch. #638 fixed the plumbing that carried that value; the source
  was dry the whole time.
* `document_status` -- so a 404 or 403 behind a browser fetch could not be
  detected, which is the entire purpose of `browser_status.py`.
* `validate-login`'s `auth_responses` -- so every witnessed login recorded an
  empty response list. That is where a vendor's auth exchange is visible, and
  for Auth0 it is where the `realm` needed by the token grant would be found.

Found 2026-09-20 while asking why `auth_responses` was `[]` for all four hosts
witnessed that day, including the two recorded ones.

`_create_stealth_driver` sets the same capability before its construction and
was never affected; it is pinned here so a future edit cannot quietly reverse
which path is correct.
"""

from __future__ import annotations

import inspect
import re

import pytest

from src.crawler import _enable_performance_log


class _Options:
    """The parts of a Selenium options object these tests need."""

    def __init__(self, *, capability_raises=False):
        self.capabilities: dict = {}
        self.experimental: dict = {}
        self._capability_raises = capability_raises

    def set_capability(self, name, value):
        if self._capability_raises:
            raise RuntimeError("options API refused the capability")
        self.capabilities[name] = value

    def add_experimental_option(self, name, value):
        self.experimental[name] = value


class _OptionsWithoutExperimental(_Options):
    """Some Selenium/uc versions do not offer `add_experimental_option`.

    Defined as a subclass rather than by deleting the attribute, because `del`
    on an instance cannot remove a method that lives on the class -- the first
    version of this test did that and silently tested nothing.
    """

    add_experimental_option = None

    def __getattribute__(self, name):
        if name == "add_experimental_option":
            raise AttributeError(name)
        return super().__getattribute__(name)


class TestTheHelper:
    def test_it_requests_network_events(self):
        opts = _Options()
        assert _enable_performance_log(opts) is True
        assert opts.capabilities["goog:loggingPrefs"] == {"performance": "ALL"}

    def test_it_asks_for_the_network_domain_specifically(self):
        """Page and timeline events are volume we never read."""
        opts = _Options()
        _enable_performance_log(opts)
        prefs = opts.experimental["perfLoggingPrefs"]
        assert prefs["enableNetwork"] is True
        assert prefs["enablePage"] is False

    def test_no_preference_is_sent_as_an_empty_string(self):
        """An empty value takes the whole driver down, not just the logging.

        `traceCategories: ""` made Chrome reject the entire capability block:

            cannot parse capability: goog:chromeOptions
            from invalid argument: cannot parse perfLoggingPrefs
            from invalid argument: cannot parse traceCategories
            from invalid argument: cannot be empty

        Caught by the Selenium Headful Regression job on 2026-09-20 -- the only
        CI job that builds a real driver. `make check`, which the pre-push hook
        runs, deselects those tests, so nothing local could see it. A unit test
        cannot validate the options dict the way Chrome does, but it can refuse
        the shape that was already proven fatal.
        """
        opts = _Options()
        _enable_performance_log(opts)
        for key, value in opts.experimental["perfLoggingPrefs"].items():
            assert value != "", f"{key} would fail to parse"
        assert "traceCategories" not in opts.experimental["perfLoggingPrefs"]

    def test_it_reports_failure_rather_than_pretending(self):
        """The bug was a silent no-op, so the helper must not have one."""
        opts = _Options(capability_raises=True)
        assert _enable_performance_log(opts) is False

    def test_the_capability_is_what_matters_not_the_trimming(self):
        """Missing `add_experimental_option` must not lose the log."""
        opts = _OptionsWithoutExperimental()
        assert _enable_performance_log(opts) is True
        assert opts.capabilities["goog:loggingPrefs"] == {"performance": "ALL"}


class TestItIsRequestedBeforeConstruction:
    """The ordering, driven rather than read.

    A fake `uc` module records what the options object carried AT THE MOMENT
    `uc.Chrome` was called. With the capability set afterwards -- the bug -- the
    recorded snapshot is empty, so this fails.
    """

    def _fake_uc(self, snapshots: list):
        class FakeOptions(_Options):
            def __init__(self):
                super().__init__()
                self.arguments: list = []
                self.page_load_strategy = None

            def add_argument(self, arg):
                self.arguments.append(arg)

        class FakeChrome:
            def __init__(self, **kwargs):
                opts = kwargs.get("options")
                # A snapshot, not a reference: a later mutation must not be able
                # to make this look correct retroactively -- which is precisely
                # what the bug did to anyone reading the source top to bottom.
                snapshots.append(dict(getattr(opts, "capabilities", {})))
                raise RuntimeError("stop here -- construction is all we assert")

        class FakeUC:
            ChromeOptions = FakeOptions
            Chrome = FakeChrome

        return FakeUC()

    def _extractor(self):
        from src.crawler import ContentExtractor

        extractor = ContentExtractor.__new__(ContentExtractor)
        # The two attributes the method reads before it builds anything.
        extractor.selenium_mode = "headless"
        extractor._fingerprint_profile = None
        return extractor

    def test_the_options_already_carry_the_capability_when_chrome_is_built(
        self, monkeypatch
    ):
        snapshots: list = []
        monkeypatch.setattr("src.crawler.uc", self._fake_uc(snapshots), raising=False)

        # Every construction raises, so the method fails -- that is fine. What
        # is under test is what the options held when Chrome was REACHED.
        with pytest.raises(RuntimeError, match="construction is all we assert"):
            self._extractor()._create_undetected_driver(headless=True)

        assert snapshots, "uc.Chrome was never reached"
        assert snapshots[0].get("goog:loggingPrefs") == {"performance": "ALL"}

    def test_the_fallback_construction_carries_it_as_well(self, monkeypatch):
        """The primary raises here, so the second snapshot is the fallback's.

        Its options object is built from scratch, so it needs its own request.
        """
        snapshots: list = []
        monkeypatch.setattr("src.crawler.uc", self._fake_uc(snapshots), raising=False)

        with pytest.raises(RuntimeError, match="construction is all we assert"):
            self._extractor()._create_undetected_driver(headless=True)

        assert len(snapshots) >= 2, "the fallback construction was never reached"
        assert snapshots[-1].get("goog:loggingPrefs") == {"performance": "ALL"}


class TestNoPathSetsItTooLate:
    def _source(self, name: str) -> str:
        from src.crawler import ContentExtractor

        src = inspect.getsource(getattr(ContentExtractor, name))
        return "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )

    def test_the_undetected_path_does_not_set_it_after_constructing(self):
        """Regression guard for the exact shape of the bug.

        Comments stripped: the explanation beside the fix quotes the old call,
        and an unstripped check would match the prose.
        """
        body = self._source("_create_undetected_driver")
        first_construction = body.index("uc.Chrome(")
        after = body[first_construction:]
        assert "goog:loggingPrefs" not in after

    def test_the_undetected_path_requests_it_before_constructing(self):
        body = self._source("_create_undetected_driver")
        request = body.index("_enable_performance_log(options)")
        construction = body.index("uc.Chrome(")
        assert request < construction

    def test_the_fallback_options_get_it_too(self):
        """A primary-construction failure must not cost the log for the run."""
        body = self._source("_create_undetected_driver")
        assert "_enable_performance_log(options_fb)" in body
        fb_request = body.index("_enable_performance_log(options_fb)")
        fb_construction = body.index("uc_kwargs_fb")
        assert fb_request < fb_construction

    def test_the_stealth_path_was_always_correct_and_stays_so(self):
        body = self._source("_create_stealth_driver")
        request = body.index("goog:loggingPrefs")
        # This path builds the driver after its options are fully assembled.
        construction = len(body)
        for match in re.finditer(r"(uc\.Chrome\(|webdriver\.Chrome\()", body):
            construction = match.start()
            break
        assert request < construction


class TestTheReadersThatDependOnIt:
    def test_navigation_status_reads_the_performance_log(self):
        from src.crawler.browser_status import read_navigation_status

        assert 'get_log("performance")' in inspect.getsource(read_navigation_status)

    def test_a_missing_log_still_returns_a_pair_rather_than_raising(self):
        """It must fail soft: a driver without the capability raises on get_log,
        and a fetch must not die because telemetry is unavailable."""
        from src.crawler.browser_status import read_navigation_status

        class Driver:
            def get_log(self, _):
                raise RuntimeError("log types not enabled")

        assert read_navigation_status(Driver()) == (None, None)
