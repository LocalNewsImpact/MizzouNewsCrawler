"""Three fixes from the 2026-10-15 WSU credentialed run.

1. A PDF is not a page. ptleader.com/dynamicpage/pdf/222596 opened in Chrome's
   PDF viewer three times; each was a "browser failure" for the host.
2. A page that loaded is not a refusal. Those three reached the per-host limit
   and the run skipped ptleader.com -- 35 articles -- while every login held.
3. A re-parse needs no login. 61 pendoreillerivervalley re-parses waited two
   hours behind a login refused by reCAPTCHA.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

import src.crawler as crawler_module
from src.cli.commands import extraction
from src.crawler import ContentExtractor
from src.crawler.browser_errors import is_pdf_viewer
from src.services import work_queue as wq

URL = "https://ptleader.com/dynamicpage/pdf/222596"
VIEWER = "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html"


class TestAPdfIsRecognised:
    def test_the_viewer_is_a_pdf(self):
        assert is_pdf_viewer(VIEWER)

    @pytest.mark.parametrize(
        "url", [URL, "chrome-error://chromewebdata/", None, 42, "about:blank"]
    )
    def test_anything_else_is_not(self, url):
        assert not is_pdf_viewer(url)

    def test_the_browser_path_stops_there(self):
        source = inspect.getsource(ContentExtractor._extract_with_selenium)
        assert "if is_pdf_viewer(nav_final_url):" in source
        assert "self.loaded_a_pdf = True" in source

    def test_the_flag_is_reset_for_every_article(self):
        assert "self.loaded_a_pdf = False" in inspect.getsource(
            ContentExtractor.extract_content
        )

    def test_the_loop_settles_the_link(self):
        flat = " ".join(inspect.getsource(extraction).split())
        assert 'if getattr(extractor, "loaded_a_pdf", False):' in flat
        assert 'give_up(session, [str(url_id)], outcome="pdf_document")' in flat
        assert '{"status": "not_article", "id": str(url_id)}' in flat


@pytest.fixture
def extractor(monkeypatch):
    monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)
    ex = ContentExtractor()
    monkeypatch.setattr(ContentExtractor, "_auth_failed_domains", set())
    ex._selenium_failure_counts = {}
    return ex


def _run(ex, status, pdf=False):
    def fetch(url):
        ex._last_navigation_status = status
        ex.loaded_a_pdf = pdf
        return {}

    ex._extract_with_selenium = fetch
    result = {
        "url": URL,
        "title": None,
        "author": None,
        "publish_date": None,
        "content": None,
        "metadata": {},
        "extraction_methods": {},
    }
    ex._run_selenium_extraction(URL, result, None, "test")
    return ex._selenium_failure_counts.get("ptleader.com", 0)


class TestOnlyARefusalCounts:
    @pytest.mark.parametrize("status", [200, 301, 304])
    def test_a_page_that_answered_does_not_count(self, extractor, status):
        assert _run(extractor, status) == 0

    def test_a_pdf_does_not_count(self, extractor):
        assert _run(extractor, None, pdf=True) == 0

    @pytest.mark.parametrize("status", [None, 403, 503])
    def test_a_refusal_or_no_answer_counts(self, extractor, status):
        assert _run(extractor, status) == 1

    def test_three_pages_do_not_shut_the_host(self, extractor):
        for _ in range(4):
            _run(extractor, 200)
        assert extractor._selenium_failure_counts.get("ptleader.com", 0) == 0

    def test_the_status_is_this_navigations(self):
        """Reset at the start of every browser fetch, so a navigation that never
        happens is not read as the previous article's 200."""
        source = inspect.getsource(ContentExtractor._extract_with_selenium)
        reset = source.index("self._last_navigation_status = None")
        assert reset < source.index("driver = self.get_persistent_driver()")


@pytest.fixture
def links():
    """A host cooling down after a refused login, run on SQLite."""
    engine = create_engine("sqlite://")
    failed = datetime.utcnow() - timedelta(minutes=5)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE sources (id TEXT, auth_last_failed_at TIMESTAMP)")
        )
        conn.execute(
            text("CREATE TABLE candidate_links (id TEXT, source_id TEXT, status TEXT)")
        )
        conn.execute(
            text("CREATE TABLE articles (candidate_link_id TEXT, metadata JSON)")
        )
        conn.execute(
            text("INSERT INTO sources VALUES ('po', :t), ('ok', NULL)"), {"t": failed}
        )
        conn.execute(
            text("INSERT INTO candidate_links VALUES (:i, :s, :st)"),
            [
                {"i": "replay", "s": "po", "st": "refetch"},
                {"i": "live-refetch", "s": "po", "st": "refetch"},
                {"i": "new", "s": "po", "st": "article"},
                {"i": "healthy", "s": "ok", "st": "article"},
            ],
        )
        conn.execute(
            text("INSERT INTO articles VALUES (:i, :m)"),
            [
                {"i": "replay", "m": '{"refetch": {"replay": "gs://b/x.html.gz"}}'},
                {"i": "live-refetch", "m": '{"refetch": {"reason": "x"}}'},
            ],
        )
    return engine


def _served(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cl.id FROM candidate_links cl JOIN sources s ON s.id = cl.source_id "
                f"WHERE (NOT {wq.LOGIN_COOLING_DOWN} OR {wq.IS_REPLAY})"
            ),
            {"login_cooldown_cutoff": wq.login_cooldown_cutoff()},
        )
        return {r[0] for r in rows}


class TestAReparseIsNotHeldByALogin:
    def test_a_replay_on_a_cooling_host_is_served(self, links):
        assert "replay" in _served(links)

    def test_work_that_needs_the_login_still_waits(self, links):
        served = _served(links)
        assert "live-refetch" not in served
        assert "new" not in served

    def test_a_healthy_host_is_unaffected(self, links):
        assert "healthy" in _served(links)

    def test_both_queries_apply_it(self):
        source = inspect.getsource(wq.WorkQueueCoordinator)
        assert source.count("(NOT {LOGIN_COOLING_DOWN} OR {IS_REPLAY})") == 2
