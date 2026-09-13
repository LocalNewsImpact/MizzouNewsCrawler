"""Matching a duplicate to the story that survived, against real Postgres.

The comparison is SQL and normalisation is regex, so a mock proves nothing:
the reason the old dedup script left 343 links unmatchable is that it
normalised too little, and that is only visible against real URLs.
"""

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVISION = "x9y0z1a2b3c4"


def _pg_url():
    url = os.environ.get("ENRICHMENT_PG_URL") or os.environ.get("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else None


pytestmark = pytest.mark.skipif(_pg_url() is None, reason="needs PostgreSQL")


@pytest.fixture()
def db():
    url = _pg_url()
    env = {**os.environ, "DATABASE_URL": url, "USE_CLOUD_SQL_CONNECTOR": "false"}
    assert (
        subprocess.run(
            ["alembic", "upgrade", REVISION],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        ).returncode
        == 0
    )
    engine = sa.create_engine(url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        s.execute(
            sa.text(
                "INSERT INTO sources (id, host, host_norm, city, status) VALUES "
                "('dup-src', 'dup.example', 'dup.example', 'Linn', 'active') "
                "ON CONFLICT DO NOTHING"
            )
        )
        s.commit()
    yield factory
    with factory() as s:
        s.execute(sa.text("DELETE FROM articles WHERE id LIKE 'dup-%'"))
        s.execute(sa.text("DELETE FROM candidate_links WHERE id LIKE 'dup-%'"))
        s.execute(sa.text("DELETE FROM sources WHERE id = 'dup-src'"))
        s.commit()
    engine.dispose()


def _link(session, link_id, url, status="extracted"):
    session.execute(
        sa.text(
            "INSERT INTO candidate_links (id, url, source, source_id, "
            "discovered_at, status, created_at) VALUES (:id, :url, 'dup', "
            "'dup-src', now(), :status, now())"
        ),
        {"id": link_id, "url": url, "status": status},
    )


def _article(session, article_id, link_id, url):
    session.execute(
        sa.text(
            "INSERT INTO articles (id, candidate_link_id, url, status, "
            "wire_check_status, title, text, created_at, extracted_at) VALUES "
            "(:id, :link, :url, 'enriched', 'local', 'A story', 'Body.', "
            "now(), now())"
        ),
        {"id": article_id, "link": link_id, "url": url},
    )


VARIANTS = [
    ("scheme", "http://dup.example/a-story"),
    ("www", "https://www.dup.example/a-story"),
    ("trailing slash", "https://dup.example/a-story/"),
    ("tracking query", "https://dup.example/a-story?utm_source=x"),
    ("fragment", "https://dup.example/a-story#top"),
    ("case", "https://dup.example/A-Story"),
]


@pytest.mark.parametrize("what,url", VARIANTS, ids=[v[0] for v in VARIANTS])
def test_each_variant_is_matched_to_the_survivor(db, what, url):
    """Every one of these is the same story. The old script matched only the
    first two."""
    from src.cli.commands.duplicates import orphaned_links

    with db() as s:
        _link(s, "dup-keep", "https://dup.example/a-story")
        _article(s, "dup-art", "dup-keep", "https://dup.example/a-story")
        _link(s, "dup-other", url)
        s.commit()

        resolved = orphaned_links(s, "dup-src")

    assert [(r[0], r[2]) for r in resolved] == [("dup-other", "dup-art")], what


def test_a_link_with_its_own_article_is_not_a_duplicate(db):
    from src.cli.commands.duplicates import orphaned_links

    with db() as s:
        _link(s, "dup-keep", "https://dup.example/a-story")
        _article(s, "dup-art", "dup-keep", "https://dup.example/a-story")
        s.commit()
        assert orphaned_links(s, "dup-src") == []


def test_a_different_story_is_not_a_duplicate(db):
    """The whole point is not to collapse two real articles into one."""
    from src.cli.commands.duplicates import orphaned_links

    with db() as s:
        _link(s, "dup-keep", "https://dup.example/a-story")
        _article(s, "dup-art", "dup-keep", "https://dup.example/a-story")
        _link(s, "dup-other", "https://dup.example/another-story")
        s.commit()
        assert orphaned_links(s, "dup-src") == []


def test_marking_records_the_survivor_and_leaves_everything_else(db):
    from src.cli.commands.duplicates import DUPLICATE, mark, orphaned_links

    with db() as s:
        _link(s, "dup-keep", "https://dup.example/a-story")
        _article(s, "dup-art", "dup-keep", "https://dup.example/a-story")
        _link(s, "dup-other", "http://www.dup.example/a-story/")
        s.commit()

        assert mark(s, orphaned_links(s, "dup-src")) == 1
        rows = s.execute(
            sa.text(
                "SELECT id, status, error_message FROM candidate_links "
                "WHERE id LIKE 'dup-%' ORDER BY id"
            )
        ).fetchall()
        articles = s.execute(
            sa.text("SELECT count(*) FROM articles WHERE id LIKE 'dup-%'")
        ).scalar()

    by_id = {r[0]: (r[1], r[2]) for r in rows}
    assert by_id["dup-keep"][0] == "extracted", "the survivor's link is untouched"
    assert by_id["dup-other"][0] == DUPLICATE
    assert "dup-art" in by_id["dup-other"][1], "it names the article that survived"
    assert articles == 1, "nothing was deleted"


def test_running_it_twice_changes_nothing_the_second_time(db):
    """It runs nightly against a corpus people are still adding to."""
    from src.cli.commands.duplicates import mark, orphaned_links

    with db() as s:
        _link(s, "dup-keep", "https://dup.example/a-story")
        _article(s, "dup-art", "dup-keep", "https://dup.example/a-story")
        _link(s, "dup-other", "http://dup.example/a-story")
        s.commit()

        assert mark(s, orphaned_links(s, "dup-src")) == 1
        assert orphaned_links(s, "dup-src") == [], "already marked, no longer extracted"
        assert mark(s, orphaned_links(s, "dup-src")) == 0
