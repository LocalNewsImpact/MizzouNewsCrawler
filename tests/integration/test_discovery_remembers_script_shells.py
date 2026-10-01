"""The learned "needs a browser" flag survives the database between runs.

The unit tests hand discovery a metadata dict. This one does what production
does: run one writes the flag through ``_update_source_meta``, and the next run
reads it back the way it reads every source -- ``get_sources_to_process`` then
``SourceProcessor._parse_source_meta`` -- so a key that is written but never
reaches the next run, or is reshaped on the way, fails here.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.crawler.discovery import NewsDiscovery
from src.crawler.discovery_render import (
    FORGET_AFTER_MISSES,
    RENDER_MISSES_KEY,
    RENDER_REQUIRED_KEY,
    RENDER_SIGNAL_KEY,
    RenderOutcome,
)
from src.crawler.source_processing import SourceProcessor
from src.models.database import DatabaseManager

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")

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


class ScriptedRenderer:
    """Returns the queued outcomes in order and records each call."""

    def __init__(self, *outcomes: RenderOutcome):
        self.outcomes = list(outcomes)
        self.calls: list[bool] = []

    def render(self, url, source_id=None, *, just_fetched=False):
        self.calls.append(just_fetched)
        return self.outcomes.pop(0)

    def close(self):
        pass


@pytest.fixture
def shell_source():
    if not (POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL):
        pytest.skip("PostgreSQL test database not configured (set TEST_DATABASE_URL)")
    db = DatabaseManager(POSTGRES_TEST_URL)
    source_id = f"test-render-{uuid.uuid4().hex[:8]}"
    host = f"{source_id}.example.org"
    with db.engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO sources (
                    id, canonical_name, host, host_norm, type,
                    rss_consecutive_failures, rss_transient_failures,
                    no_effective_methods_consecutive
                )
                VALUES (:id, :name, :host, :host, 'news', 0, '[]', 0)
            """),
            {"id": source_id, "name": "Script Shell Gazette", "host": host},
        )
    yield source_id, host
    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM candidate_links WHERE source_id = :id"),
            {"id": source_id},
        )
        conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})


def _discovery(page: str, renderer: ScriptedRenderer) -> NewsDiscovery:
    d = NewsDiscovery(database_url=POSTGRES_TEST_URL)
    d._render_homepages = True
    d._homepage_renderer = renderer
    d.fetches = []

    def fetch(url, timeout=None):
        d.fetches.append(url)
        return SimpleNamespace(status_code=200, text=page)

    d._fetch_with_ssl_fallback = fetch
    d._discover_from_section_urls = lambda **kw: []
    return d


def _next_run_meta(d: NewsDiscovery, host: str) -> tuple[str, str, dict | None]:
    """What the next run sees for this source, read the way a run reads it."""
    sources_df, _ = d.get_sources_to_process(host_filter=host)
    assert len(sources_df) == 1
    row = sources_df.iloc[0]
    processor = SourceProcessor(discovery=d, source_row=row)
    processor.source_id = str(row["id"])
    return str(row["url"]), str(row["id"]), processor._parse_source_meta()


def _run(d: NewsDiscovery, url: str, source_id: str, meta: dict | None) -> list:
    return d.discover_with_newspaper4k(
        url, source_id, source_meta=meta, rss_already_attempted=True
    )


def test_the_learned_flag_sends_the_next_run_straight_to_the_browser(shell_source):
    source_id, host = shell_source

    # Run 1: a plain fetch meets the shell; the browser finds the links.
    first = ScriptedRenderer(RenderOutcome(html=RENDERED))
    d1 = _discovery(SHELL, first)
    url, sid, meta = _next_run_meta(d1, host)
    assert not (meta or {}).get(RENDER_REQUIRED_KEY)
    found = _run(d1, url, sid, meta)
    assert len(found) == 4
    assert d1.fetches == [url]
    assert first.calls == [True]

    # Run 2, a new process: the flag comes back out of `sources`.
    second = ScriptedRenderer(RenderOutcome(html=RENDERED))
    d2 = _discovery(SHELL, second)
    url, sid, meta = _next_run_meta(d2, host)
    assert meta[RENDER_REQUIRED_KEY]["links_found"] == 4
    assert meta[RENDER_SIGNAL_KEY]["signals"]["spa_root"] is True

    found = _run(d2, url, sid, meta)
    assert len(found) == 4
    assert {a["discovery_method"] for a in found} == {"homepage_rendered"}
    assert d2.fetches == [], "a remembered shell must not be fetched plain first"
    assert second.calls == [False]


def test_empty_renders_wear_the_flag_off_and_plain_fetching_resumes(shell_source):
    source_id, host = shell_source

    d = _discovery(SHELL, ScriptedRenderer(RenderOutcome(html=RENDERED)))
    url, sid, meta = _next_run_meta(d, host)
    _run(d, url, sid, meta)

    # The site starts serving links to plain requests; the browser now sees
    # an empty page each run (a redesign, say). Each run is a fresh process.
    for miss in range(1, FORGET_AFTER_MISSES + 1):
        d = _discovery(RENDERED, ScriptedRenderer(RenderOutcome(html="<html/>")))
        url, sid, meta = _next_run_meta(d, host)
        assert meta.get(RENDER_REQUIRED_KEY), f"forgotten too early (miss {miss})"
        _run(d, url, sid, meta)
        assert d.fetches == []

    renderer = ScriptedRenderer()
    d = _discovery(RENDERED, renderer)
    url, sid, meta = _next_run_meta(d, host)
    assert not meta.get(RENDER_REQUIRED_KEY)
    assert meta.get(RENDER_MISSES_KEY) == 0

    found = _run(d, url, sid, meta)
    assert d.fetches == [url]
    assert renderer.calls == []
    assert {a["discovery_method"] for a in found} == {"homepage_links"}


def test_a_render_that_finds_nothing_teaches_nothing(shell_source):
    source_id, host = shell_source
    d = _discovery(SHELL, ScriptedRenderer(RenderOutcome(skipped="budget")))
    url, sid, meta = _next_run_meta(d, host)
    _run(d, url, sid, meta)

    _, _, meta = _next_run_meta(d, host)
    assert RENDER_SIGNAL_KEY in meta, "the shell is still signalled"
    assert not meta.get(RENDER_REQUIRED_KEY)
