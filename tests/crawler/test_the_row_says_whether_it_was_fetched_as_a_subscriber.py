"""A written article records whether a subscriber session was in force, and the
link records the HTTP status the fetch got.

Both were unanswerable from the data on 2026-09-20.

"Are we logged in to Yakima Herald or not?" -- the only auth column in
`extraction_telemetry_v2` is `proxy_authenticated`, which is the squid proxy;
body length proves nothing on a metered site (74 of 75 Yakima articles were over
800 characters whether or not a login had run). The extractor knew, per fetch,
in `_authenticated_domains`; nothing wrote it down.

"What status did the wall return?" -- `candidate_links.http_status` existed,
`browser_status.py` recovered a code for every navigation, and no UPDATE
anywhere set the column. All 20 credentialed fetches in that run carried NULL.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from src.cli.commands import extraction
from src.crawler import ContentExtractor


@pytest.fixture(autouse=True)
def _clean_class_state():
    before = set(ContentExtractor._authenticated_domains)
    yield
    ContentExtractor._authenticated_domains = set(before)


class TestSessionState:
    def _extractor(self, requires_login: bool):
        e = ContentExtractor()
        e._requires_login = lambda host: requires_login
        return e

    def test_a_confirmed_session_on_a_credentialed_host_is_true(self):
        e = self._extractor(True)
        ContentExtractor._authenticated_domains.add("yakimaherald.com")
        assert e._session_state("https://www.yakimaherald.com/news/x") is True

    def test_no_session_on_a_credentialed_host_is_false(self):
        """Post-#635 the fetch is refused, so this should never reach a written
        row. If it does, that is the finding, and False is what says so."""
        e = self._extractor(True)
        assert e._session_state("https://www.yakimaherald.com/news/x") is False

    def test_a_host_needing_no_login_is_none_not_false(self):
        """The question does not apply. False would read as "we should have
        been logged in and were not" on every open-web host."""
        e = self._extractor(False)
        assert e._session_state("https://example.com/story") is None

    def test_www_and_bare_are_the_same_host(self):
        e = self._extractor(True)
        ContentExtractor._authenticated_domains.add("ptleader.com")
        assert e._session_state("https://www.ptleader.com/stories/x") is True
        assert e._session_state("ptleader.com") is True


class TestTheBrowserResultCarriesBoth:
    def test_the_selenium_metadata_includes_the_session_state(self):
        source = inspect.getsource(ContentExtractor._extract_with_selenium)
        assert '"authenticated_session": self._session_state(url)' in source

    def test_the_selenium_metadata_includes_the_http_status(self):
        """The newspaper4k path always put it in the result; the browser path
        kept it on the extractor only, which is why the column stayed NULL."""
        source = inspect.getsource(ContentExtractor._extract_with_selenium)
        assert '"http_status": self._last_fetch_http_status' in source


class TestTheLinkRecordsTheStatus:
    def test_the_post_insert_write_binds_http_status(self):
        sql = str(extraction.CANDIDATE_EXTRACTED_SQL)
        assert "http_status = :http_status" in sql
        assert "status = :status" in sql

    def test_the_shared_update_is_unchanged(self):
        """Five failure-path callers use it with no status to give, and a
        missing bind is a database error rather than a NULL."""
        assert "http_status" not in str(extraction.CANDIDATE_STATUS_UPDATE_SQL)

    def test_the_post_insert_site_uses_the_new_statement(self):
        source = inspect.getsource(extraction._process_batch)
        body = "\n".join(
            ln for ln in source.splitlines() if not ln.strip().startswith("#")
        )
        assert "CANDIDATE_EXTRACTED_SQL," in body
        assert '"http_status": fetched_status' in body

    def test_the_status_comes_from_the_result_then_the_extractor(self):
        source = inspect.getsource(extraction._process_batch)
        assert '(metadata_value or {}).get("http_status")' in source
        assert (
            'getattr(\n                                extractor, "_last_fetch_http_status", None'
            in source
            or "_last_fetch_http_status" in source
        )
