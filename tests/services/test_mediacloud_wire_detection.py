"""MediaCloud headline matching, which decides what counts as wire.

Wire attribution keeps an article out of CIN, so what this module calls a
match is a publishing decision. More than half of it had no test: the
rate limiter, the date window a query is asked over, what happens to an
article when the API fails, and every branch of token resolution.

Nothing here reaches the network. The detector takes a search API by
constructor argument, which is what makes that possible.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.services.wire_detection import mediacloud as mc


def _article(**overrides):
    fields = {
        "article_id": "a1",
        "source": "Example Daily",
        "url": "https://www.example.com/news/story",
        "title": "Council approves the budget",
        "extracted_at": datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
    }
    fields.update(overrides)
    return mc.MediaCloudArticle(**fields)


class _FakeSearchApi:
    """Records the query it was asked and returns what it was given."""

    def __init__(self, stories=None, raises=None):
        self.stories = stories or []
        self.raises = raises
        self.calls = []

    def story_list(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.stories, None


# --- the pure helpers ---------------------------------------------------------


class TestNormalizeHost:
    def test_www_is_not_a_different_publisher(self):
        assert mc.normalize_host("https://www.example.com/a") == "example.com"

    def test_case_and_path_do_not_matter(self):
        assert mc.normalize_host("HTTPS://Example.COM/x?y=1") == "example.com"

    def test_a_url_with_no_host_is_empty(self):
        assert mc.normalize_host("not a url") == ""


class TestParseIso8601:
    def test_empty_is_none(self):
        assert mc.parse_iso8601("") is None

    def test_zulu_becomes_utc(self):
        assert mc.parse_iso8601("2026-03-04T12:00:00Z") == datetime(
            2026, 3, 4, 12, tzinfo=timezone.utc
        )

    def test_a_naive_stamp_is_assumed_utc(self):
        """The API returns stamps without an offset, and treating them as
        local time would move the query window by hours."""
        assert mc.parse_iso8601("2026-03-04T12:00:00") == datetime(
            2026, 3, 4, 12, tzinfo=timezone.utc
        )

    def test_an_offset_is_converted_not_dropped(self):
        assert mc.parse_iso8601("2026-03-04T07:00:00-05:00") == datetime(
            2026, 3, 4, 12, tzinfo=timezone.utc
        )

    def test_nonsense_is_none_rather_than_an_exception(self):
        assert mc.parse_iso8601("last tuesday") is None


class TestBuildQuery:
    def test_the_headline_is_quoted(self):
        assert mc.build_query("Council approves budget") == '"Council approves budget"'

    def test_a_quotation_mark_in_the_headline_is_escaped(self):
        """An unescaped quote ends the phrase early, and the query then
        matches on a few words rather than the headline."""
        assert mc.build_query('He said "no"') == '"He said \\"no\\""'


class TestSummarizeMatches:
    def test_the_articles_own_host_is_not_a_match(self):
        """A story is wire because someone ELSE ran it. Counting the
        publisher's own copy makes every article wire."""
        base = _article()
        stories = [
            {"id": 1, "url": "https://www.example.com/news/story"},
            {"id": 2, "url": "https://other.com/story"},
        ]
        count, hosts, ids = mc.summarize_matches(base, stories)
        assert (count, hosts, ids) == (1, ["other.com"], ["2"])

    def test_a_story_with_no_url_is_skipped(self):
        count, hosts, ids = mc.summarize_matches(_article(), [{"id": 3, "url": ""}])
        assert (count, hosts, ids) == (0, [], [])

    def test_hosts_are_deduped_but_stories_are_counted(self):
        """Two papers is a stronger signal than one paper twice, so the
        host list dedupes and the story count does not."""
        stories = [
            {"id": 1, "url": "https://other.com/a"},
            {"id": 2, "url": "https://www.other.com/b"},
            {"id": 3, "url": "https://third.com/c"},
        ]
        count, hosts, ids = mc.summarize_matches(_article(), stories)
        assert count == 3
        assert hosts == ["other.com", "third.com"]
        assert ids == ["1", "2", "3"]


class TestEnsureTimezone:
    def test_none_stays_none(self):
        assert mc.ensure_timezone(None) is None

    def test_a_naive_datetime_is_utc(self):
        assert mc.ensure_timezone(datetime(2026, 3, 4)).tzinfo == timezone.utc

    def test_an_aware_datetime_is_converted(self):
        eastern = timezone(timedelta(hours=-5))
        assert mc.ensure_timezone(datetime(2026, 3, 4, 7, tzinfo=eastern)) == datetime(
            2026, 3, 4, 12, tzinfo=timezone.utc
        )


# --- the rate limiter ---------------------------------------------------------


class TestRateLimiter:
    def test_a_rate_of_zero_is_refused(self):
        """It would divide by zero, and a limiter that permits everything
        is worse than none at all -- MediaCloud bans on rate."""
        with pytest.raises(ValueError):
            mc.RateLimiter(0)

    def test_the_first_call_does_not_wait(self):
        with patch.object(mc.time, "sleep") as sleep:
            mc.RateLimiter(2).wait()
        sleep.assert_not_called()

    def test_the_next_call_waits_out_the_interval(self):
        limiter = mc.RateLimiter(2)  # one call every 30 seconds
        with patch.object(mc.time, "monotonic", side_effect=[100.0, 110.0]):
            limiter.record()
            with patch.object(mc.time, "sleep") as sleep:
                limiter.wait()
        sleep.assert_called_once()
        assert sleep.call_args[0][0] == pytest.approx(20.0)

    def test_a_call_after_the_interval_does_not_wait(self):
        limiter = mc.RateLimiter(2)
        with patch.object(mc.time, "monotonic", side_effect=[100.0, 200.0]):
            limiter.record()
            with patch.object(mc.time, "sleep") as sleep:
                limiter.wait()
        sleep.assert_not_called()


# --- the result -------------------------------------------------------------


class TestDetectionResult:
    def _result(self, **overrides):
        fields = {
            "article": _article(),
            "query": '"Council approves the budget"',
            "story_count": 2,
            "matched_story_count": 1,
            "matched_hosts": ["other.com"],
            "matched_story_ids": ["2"],
            "status": "ok",
        }
        fields.update(overrides)
        return mc.DetectionResult(**fields)

    def test_has_matches_is_about_other_publishers(self):
        assert self._result().has_matches
        assert not self._result(matched_story_count=0).has_matches

    def test_the_metadata_carries_the_article_and_the_query(self):
        meta = self._result().to_metadata()
        assert meta["article_id"] == "a1"
        assert meta["source"] == "Example Daily"
        assert meta["query"] == '"Council approves the budget"'
        assert meta["status"] == "ok"
        assert meta["matched_hosts"] == ["other.com"]

    def test_the_metadata_copies_its_lists(self):
        """Stored metadata that shares a list with the live result changes
        under it."""
        result = self._result()
        meta = result.to_metadata()
        result.matched_hosts.append("third.com")
        assert meta["matched_hosts"] == ["other.com"]

    def test_the_wire_payload_names_the_provider_and_the_method(self):
        payload = self._result().to_wire_payload()
        assert payload["provider"] == "mediacloud"
        assert payload["detection_method"] == "headline_duplicate"
        assert payload["matched_story_count"] == 1

    def test_both_stamps_are_serialisable(self):
        result = self._result()
        assert result.to_metadata()["queried_at"] == result.queried_at.isoformat()
        assert result.to_wire_payload()["queried_at"] == result.queried_at.isoformat()


# --- the detector -----------------------------------------------------------


class TestDetect:
    def test_a_match_on_another_host_is_reported(self):
        api = _FakeSearchApi(
            stories=[
                {"id": 1, "url": "https://www.example.com/news/story"},
                {"id": 2, "url": "https://other.com/story"},
            ]
        )
        result = mc.MediaCloudDetector(api, rate_limiter=mc.RateLimiter(600)).detect(
            _article()
        )
        assert result.status == "ok"
        assert result.story_count == 2
        assert result.matched_story_count == 1
        assert result.matched_hosts == ["other.com"]

    def test_an_api_error_is_a_status_not_an_exception(self):
        """A failed lookup must leave the article unlabelled rather than
        stopping the run: 'we did not find out' is not 'not wire'.

        The error is built the way the installed library builds it --
        `APIResponseError(response, params, data)` -- because that is the
        shape the handler has to read, and it is not the shape the
        fallback class in this module has.
        """
        api = _FakeSearchApi(
            raises=mc.APIResponseError(
                SimpleNamespace(status_code=429), {}, {"note": "rate limited"}
            )
        )
        result = mc.MediaCloudDetector(api, rate_limiter=mc.RateLimiter(600)).detect(
            _article()
        )
        assert result.status == "api_error:429"
        assert result.story_count == 0
        assert not result.has_matches

    def test_the_fallback_errors_status_is_read_too(self):
        """Without the mediacloud package installed, APIResponseError is
        the class defined in this module, which carries the code
        directly."""
        assert mc._status_code_of(mc._FallbackAPIResponseError("x", 503)) == 503

    def test_an_error_carrying_neither_is_not_a_second_failure(self):
        """A handler that raises while handling loses the original error
        and the article with it."""
        assert mc._status_code_of(RuntimeError("no status anywhere")) == "unknown"

    def test_an_unexpected_failure_is_named_in_the_status(self):
        api = _FakeSearchApi(raises=TimeoutError("no answer"))
        result = mc.MediaCloudDetector(api, rate_limiter=mc.RateLimiter(600)).detect(
            _article()
        )
        assert result.status == "error:TimeoutError"
        assert result.story_count == 0

    def test_the_call_is_recorded_even_when_it_failed(self):
        """A failed call still cost a request. Not recording it lets the
        next one go out immediately, which is how a rate limit becomes a
        ban."""
        api = _FakeSearchApi(raises=TimeoutError())
        limiter = mc.RateLimiter(600)
        mc.MediaCloudDetector(api, rate_limiter=limiter).detect(_article())
        assert limiter._last_call is not None


class TestStoryListWindow:
    def test_the_window_is_the_day_either_side_of_extraction(self):
        """Wire copies do not appear at the same minute. A window of one
        day catches the same story on other sites."""
        api = _FakeSearchApi()
        mc.MediaCloudDetector(api, rate_limiter=mc.RateLimiter(600)).detect(_article())
        call = api.calls[0]
        assert call["start_date"] == datetime(2026, 3, 3).date()
        assert call["end_date"] == datetime(2026, 3, 5).date()
        assert call["query"] == '"Council approves the budget"'

    def test_a_local_stamp_is_converted_before_the_window_is_taken(self):
        """An offset stamp near midnight would otherwise shift the window
        by a day."""
        eastern = timezone(timedelta(hours=-5))
        api = _FakeSearchApi()
        mc.MediaCloudDetector(api, rate_limiter=mc.RateLimiter(600)).detect(
            _article(extracted_at=datetime(2026, 3, 4, 21, tzinfo=eastern))
        )
        call = api.calls[0]
        # 21:00-05:00 is 02:00 UTC on the 5th.
        assert call["start_date"] == datetime(2026, 3, 4).date()
        assert call["end_date"] == datetime(2026, 3, 6).date()

    def test_an_article_with_no_extraction_time_asks_about_today(self):
        api = _FakeSearchApi()
        mc.MediaCloudDetector(api, rate_limiter=mc.RateLimiter(600)).detect(
            _article(extracted_at=None)
        )
        call = api.calls[0]
        assert call["start_date"] == call["end_date"]


class TestFromToken:
    def test_an_empty_token_is_refused(self):
        with pytest.raises(ValueError):
            mc.MediaCloudDetector.from_token("")

    def test_a_missing_client_library_says_so(self):
        """The dependency is optional, and the failure has to name it
        rather than surface as a TypeError on None."""
        with patch.object(mc, "_SearchApiFactory", None):
            with pytest.raises(mc.MissingDependencyError) as excinfo:
                mc.MediaCloudDetector.from_token("t0ken")
        assert "mediacloud" in str(excinfo.value)

    def test_the_token_reaches_the_client(self):
        made = {}

        def factory(token):
            made["token"] = token
            return _FakeSearchApi()

        with patch.object(mc, "_SearchApiFactory", factory):
            detector = mc.MediaCloudDetector.from_token("t0ken", rate_per_minute=5)
        assert made["token"] == "t0ken"
        assert detector.rate_limiter._min_interval == pytest.approx(12.0)


# --- token resolution ---------------------------------------------------------


@pytest.fixture
def unresolved_token(monkeypatch):
    """The module caches its answer in a global, so each test starts over."""
    monkeypatch.setattr(mc, "_TOKEN_INITIALISED", False)
    monkeypatch.setattr(mc, "_RESOLVED_TOKEN", None)
    for key in (
        "MEDIACLOUD_API_TOKEN",
        "MEDIACLOUD_SECRET_NAME",
        "MEDIACLOUD_API_SECRET_NAME",
        "GCP_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)


class TestResolveApiToken:
    def test_the_environment_wins_and_is_stripped(self, unresolved_token, monkeypatch):
        monkeypatch.setenv("MEDIACLOUD_API_TOKEN", "  t0ken  ")
        assert mc.resolve_api_token() == "t0ken"

    def test_nothing_configured_is_none_not_an_error(self, unresolved_token):
        assert mc.resolve_api_token() is None

    def test_the_answer_is_cached(self, unresolved_token, monkeypatch):
        """Secret Manager is a network call; resolving per article would
        make one per article."""
        monkeypatch.setenv("MEDIACLOUD_API_TOKEN", "first")
        assert mc.resolve_api_token() == "first"
        monkeypatch.setenv("MEDIACLOUD_API_TOKEN", "second")
        assert mc.resolve_api_token() == "first"

    def test_a_blank_environment_value_is_not_a_token(
        self, unresolved_token, monkeypatch
    ):
        monkeypatch.setenv("MEDIACLOUD_API_TOKEN", "   ")
        assert mc.resolve_api_token() is None

    def test_a_bare_secret_name_needs_a_project(self, unresolved_token, monkeypatch):
        """Without one there is no resource path to ask for, and the
        warning has to name the variables that would supply it."""
        monkeypatch.setenv("MEDIACLOUD_SECRET_NAME", "mediacloud-token")
        assert mc.resolve_api_token() is None


class TestFirstNonemptyEnv:
    def test_the_first_set_key_wins(self, monkeypatch):
        monkeypatch.delenv("A_KEY", raising=False)
        monkeypatch.setenv("B_KEY", "second")
        monkeypatch.setenv("C_KEY", "third")
        assert mc._first_nonempty_env(["A_KEY", "B_KEY", "C_KEY"]) == "second"

    def test_whitespace_is_not_a_value(self, monkeypatch):
        monkeypatch.setenv("A_KEY", "   ")
        monkeypatch.setenv("B_KEY", "real")
        assert mc._first_nonempty_env(["A_KEY", "B_KEY"]) == "real"

    def test_nothing_set_is_none(self, monkeypatch):
        monkeypatch.delenv("A_KEY", raising=False)
        assert mc._first_nonempty_env(["A_KEY"]) is None
