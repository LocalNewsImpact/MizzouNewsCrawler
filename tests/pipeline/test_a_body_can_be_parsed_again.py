"""A body the parser got wrong is parsed again from the page it came from.

1,143 WSU bodies were stored before #716 with text that was not the story
above or below it, or with every paragraph run into one. The pages were
right; the parser was not. 889 of those pages are in the raw HTML archive.
Fetching them again would cost a request and a signed-in session each, spend
the hosts' patience, and may no longer return the page that was served --
so the rewind can name the archived page, and extraction parses it instead
of fetching.
"""

from __future__ import annotations

import inspect
import json

import pytest

import src.crawler as crawler_module
from src.cli.commands import extraction
from src.crawler import ContentExtractor
from src.pipeline import refetch

CAPTURE = "gs://mizzou-news-crawler-raw-html/2026/09/19/ptleader.com/a1.html.gz"
RETAINED = (
    "gs://mizzou-news-crawler-raw-html/retained/wsu-reextract-2026-10-14/"
    "2026/09/19/ptleader.com/a1.html.gz"
)


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.params: list[dict] = []

    def execute(self, statement, params=None):
        self.params.append(params)
        return _Result(self.answers.pop(0)) if self.answers else _Result()

    def commit(self):
        pass


def _article(raw_gcs_path=CAPTURE, authenticated_session="true"):
    return {
        "id": "a1",
        "candidate_link_id": "link-a1",
        "link_status": "extracted",
        "url": "https://www.ptleader.com/stories/a1",
        "raw_gcs_path": raw_gcs_path,
        "authenticated_session": authenticated_session,
    }


def _note(session) -> dict:
    return json.loads(next(p["note"] for p in session.params if p and "note" in p))


class TestWhereTheCaptureIsRead:
    def test_the_original_path_by_default(self):
        assert refetch.replay_uri(CAPTURE) == CAPTURE

    def test_a_retained_copy_below_the_root(self):
        root = "retained/wsu-reextract-2026-10-14/"
        assert refetch.replay_uri(CAPTURE, root) == RETAINED

    @pytest.mark.parametrize("path", [None, "", "/tmp/a1.html.gz"])
    def test_no_capture_names_none(self, path):
        assert refetch.replay_uri(path, "retained/x") is None


class TestWhatAReplayRewindRecords:
    def test_it_names_the_capture_and_the_session_it_ran_under(self):
        session = _Session(answers=[[_article()]])
        counts = refetch.mark(
            session,
            ["a1"],
            by="damon",
            reason="flattened; parser fixed in #716",
            replay=True,
            archive_root="retained/wsu-reextract-2026-10-14",
        )
        assert counts["replay"] == 1
        note = _note(session)
        assert note["replay"] == RETAINED
        assert note["replay_session"] == "true"

    def test_an_article_with_no_capture_is_rewound_for_a_fetch(self):
        session = _Session(answers=[[_article(raw_gcs_path=None)]])
        counts = refetch.mark(session, ["a1"], by="damon", reason="x", replay=True)
        assert counts["marked"] == 1
        assert counts["replay"] == 0
        assert "replay" not in _note(session)

    def test_an_ordinary_rewind_names_no_capture(self):
        session = _Session(answers=[[_article()]])
        refetch.mark(session, ["a1"], by="damon", reason="x")
        assert "replay" not in _note(session)


class TestWhatExtractionReadsBack:
    def test_a_recorded_capture_and_its_session(self):
        session = _Session(answers=[[{"replay": RETAINED, "replay_session": "true"}]])
        assert refetch.replay_for_link(session, "link-a1") == (RETAINED, True)

    def test_an_anonymous_capture_says_so(self):
        session = _Session(answers=[[{"replay": RETAINED, "replay_session": None}]])
        assert refetch.replay_for_link(session, "link-a1") == (RETAINED, None)

    def test_no_capture_recorded_means_fetch(self):
        session = _Session(answers=[[{"replay": None, "replay_session": None}]])
        assert refetch.replay_for_link(session, "link-a1") is None

    def test_the_page_is_loaded_from_the_archive(self, monkeypatch):
        monkeypatch.setattr(
            "src.utils.raw_html_archive.fetch_html", lambda uri: "<html>page</html>"
        )
        session = _Session(answers=[[{"replay": RETAINED, "replay_session": "true"}]])
        replay = extraction._replay_capture(session, "link-a1", "https://x/a1")
        assert replay == extraction._Replay(
            html="<html>page</html>", uri=RETAINED, session=True
        )

    def test_a_capture_the_archive_no_longer_holds_is_fetched(self, monkeypatch):
        """The rewind asked for the body to be redone; a fetch still does that."""
        monkeypatch.setattr("src.utils.raw_html_archive.fetch_html", lambda uri: None)
        session = _Session(answers=[[{"replay": RETAINED, "replay_session": "true"}]])
        assert extraction._replay_capture(session, "link-a1", "https://x/a1") is None


STORY_HTML = """
<html><head><title>Port Townsend council approves the ferry dock lease</title>
<meta property="og:title" content="Port Townsend council approves the ferry dock lease">
</head><body><article>
<h1>Port Townsend council approves the ferry dock lease</h1>
<p>PORT TOWNSEND - The city council voted 6-1 on Monday to approve a
twenty-year lease for the ferry dock, ending two years of negotiation with
the state ferry system over maintenance costs and liability.</p>
<p>Council members said the agreement keeps the dock open to foot traffic and
commits the state to repairs the city could not afford on its own budget.</p>
<p>The lease takes effect in January, after a final review by the port
commission and a public hearing scheduled for December.</p>
</article></body></html>
"""


def _fetch_is_a_failure(*_args, **_kwargs):
    raise AssertionError("a replay fetched")


@pytest.fixture
def credentialed_selenium_host(monkeypatch):
    """The hardest host to replay: credentialed, Selenium-only, fetch-first.

    Every rung that could fetch raises, so a replay that reaches one fails.
    `SELENIUM_AVAILABLE` is pinned on: it differs between dev and CI, and
    with it off the Selenium rungs would be skipped for the wrong reason.
    """
    monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)
    extractor = ContentExtractor()
    monkeypatch.setattr(extractor, "_requires_login", lambda host: True)
    monkeypatch.setattr(
        extractor,
        "_get_domain_extraction_method",
        lambda domain: ("selenium", "paywall"),
    )
    for rung in (
        "_fetch_page_html",
        "_fetch_amp_html",
        "_extract_with_unblock_proxy",
        "get_persistent_driver",
    ):
        monkeypatch.setattr(extractor, rung, _fetch_is_a_failure)
    calls: list[str] = []

    def selenium(url, result, metrics, reason, **_kwargs):
        calls.append(reason)
        return True, False

    monkeypatch.setattr(extractor, "_run_selenium_extraction", selenium)
    return extractor, calls


class TestAReplayFetchesNothing:
    @pytest.mark.parametrize("mcmetadata_on", [True, False])
    def test_the_capture_is_parsed_and_no_rung_runs(
        self, credentialed_selenium_host, monkeypatch, mcmetadata_on
    ):
        extractor, selenium_calls = credentialed_selenium_host
        monkeypatch.setattr(extractor, "_mcmetadata_enabled", lambda: mcmetadata_on)
        result = extractor.extract_content(
            "https://www.ptleader.com/stories/a1", html=STORY_HTML, replay=True
        )
        assert selenium_calls == []
        assert "twenty-year lease" in (result["content"] or "")
        assert result["metadata"]["replayed"] is True

    def test_without_replay_the_same_host_goes_to_the_browser(
        self, credentialed_selenium_host
    ):
        """The fixture is not toothless: the ordinary path does try Selenium."""
        extractor, selenium_calls = credentialed_selenium_host
        extractor.extract_content(
            "https://www.ptleader.com/stories/a1", html=STORY_HTML
        )
        assert selenium_calls

    def test_this_drivers_session_is_not_recorded_as_the_captures(
        self, credentialed_selenium_host
    ):
        """No login ran in a replay; `False` would say the page was anonymous."""
        extractor, _ = credentialed_selenium_host
        result = extractor.extract_content(
            "https://www.ptleader.com/stories/a1", html=STORY_HTML, replay=True
        )
        assert result["metadata"]["authenticated_session"] is None

    @pytest.mark.parametrize("left_over", [404, 403])
    def test_a_replay_carries_no_status_from_the_fetch_before_it(
        self, credentialed_selenium_host, left_over
    ):
        """It fetched nothing, so it got no status.

        On 2026-10-15, 51 WSU stories re-parsed from good archived pages read
        the previous article's 404 or 403, were judged no article, and were
        stored as text_unavailable with their bodies dropped.
        """
        extractor, _ = credentialed_selenium_host
        extractor._last_fetch_http_status = left_over
        result = extractor.extract_content(
            "https://www.ptleader.com/stories/a1", html=STORY_HTML, replay=True
        )
        assert result["metadata"]["http_status"] is None
        assert extractor._last_fetch_http_status is None

    def test_a_replay_without_the_page_is_refused(self, credentialed_selenium_host):
        extractor, _ = credentialed_selenium_host
        with pytest.raises(ValueError):
            extractor.extract_content("https://www.ptleader.com/a1", replay=True)


class TestTheReplacedRowDescribesTheNewBody:
    def test_the_new_extractions_metadata_is_merged_over_the_old(self):
        """Only `refetch.completed_at` was written, so a replaced body kept the
        byline result, wire evidence and trim record of the parse it replaced."""
        sql = " ".join(str(extraction.ARTICLE_REFETCH_SQL).split())
        assert "|| CAST(:metadata AS jsonb)" in sql

    def test_the_replace_binds_it(self):
        source = inspect.getsource(extraction)
        call = source.index("ARTICLE_REFETCH_SQL,\n")
        params = source[call : source.index("},", call)]
        assert '"metadata": json.dumps(content.get("metadata", {}))' in params

    def test_the_extraction_loop_replays_a_rewound_link(self):
        source = inspect.getsource(extraction)
        assert "_replay_capture(session, str(url_id), url)" in source
        assert 'meta["authenticated_session"] = replay.session' in source
        assert "html=replay.html, metrics=metrics, replay=True" in source
