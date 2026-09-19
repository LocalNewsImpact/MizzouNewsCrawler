"""The refusal, against real Postgres.

It is a `NOT EXISTS` against a JSON path in `candidate_links.meta`, so a
mock proves nothing: what matters is whether Postgres actually excludes the
row, and whether an article with NO verdict is still selected.
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
                "INSERT INTO datasets (id, slug, label, ingested_at) VALUES "
                "('wk-ds', 'withheld', 'Withheld', now()) ON CONFLICT DO NOTHING"
            )
        )
        s.execute(
            sa.text(
                "INSERT INTO sources (id, host, host_norm, city, status) VALUES "
                "('wk-src', 'wk.example', 'wk.example', 'Linn', 'active') "
                "ON CONFLICT DO NOTHING"
            )
        )
        s.execute(
            sa.text(
                "INSERT INTO dataset_sources (id, dataset_id, source_id) VALUES "
                "('wk-dss', 'wk-ds', 'wk-src') ON CONFLICT DO NOTHING"
            )
        )
        s.commit()
    yield factory
    with factory() as s:
        s.execute(sa.text("DELETE FROM articles WHERE id LIKE 'wk-%'"))
        s.execute(sa.text("DELETE FROM candidate_links WHERE id LIKE 'wk-%'"))
        s.execute(sa.text("DELETE FROM dataset_sources WHERE id = 'wk-dss'"))
        s.execute(sa.text("DELETE FROM sources WHERE id = 'wk-src'"))
        s.execute(sa.text("DELETE FROM datasets WHERE id = 'wk-ds'"))
        s.commit()
    engine.dispose()


def _candidate(session, suffix, kind=None):
    """One article at `labeled`, with a reviewer's verdict if given."""
    meta = (
        '{"review_verdict": {"verdict": "story", "kind": "%s"}}' % kind
        if kind
        else "{}"
    )
    session.execute(
        sa.text(
            "INSERT INTO candidate_links (id, url, source, source_id, dataset_id, "
            "discovered_at, status, created_at, meta) VALUES "
            "(:lid, :url, 'wk', 'wk-src', 'wk-ds', now(), 'extracted', now(), "
            "CAST(:meta AS json))"
        ),
        {
            "lid": f"wk-link-{suffix}",
            "url": f"https://wk.example/{suffix}",
            "meta": meta,
        },
    )
    session.execute(
        sa.text(
            "INSERT INTO articles (id, candidate_link_id, url, status, "
            "wire_check_status, title, raw, text, created_at, extracted_at, "
            "enrichment_attempts) VALUES (:aid, :lid, :url, 'labeled', 'local', "
            "'A story', 'Body with words.', 'Body with words.', now(), now(), 0)"
        ),
        {
            "aid": f"wk-art-{suffix}",
            "lid": f"wk-link-{suffix}",
            "url": f"https://wk.example/{suffix}",
        },
    )


WITHHELD = ["obituary", "opinion", "weather", "column", "wire", "other"]


@pytest.mark.parametrize("kind", WITHHELD)
def test_a_withheld_kind_is_never_a_candidate(db, kind):
    from src.enrichment.repository import select_candidates

    with db() as s:
        _candidate(s, "plain")
        _candidate(s, kind, kind=kind)
        s.commit()
        picked = {a.id for a in select_candidates(s, "withheld", 50, 3)}

    assert "wk-art-plain" in picked, "an ordinary story is still enriched"
    assert f"wk-art-{kind}" not in picked, kind


def test_an_article_with_no_verdict_is_still_enriched(db):
    """The gate must not turn into "only enrich what a reviewer approved":
    most of the corpus has never been in a queue."""
    from src.enrichment.repository import select_candidates

    with db() as s:
        _candidate(s, "plain")
        s.commit()
        assert {a.id for a in select_candidates(s, "withheld", 50, 3)} == {
            "wk-art-plain"
        }


def test_a_story_verdict_a_reviewer_did_not_withhold_is_enriched(db):
    """`news`, and a story with no kind named, are the pipeline's to
    decide."""
    from src.enrichment.repository import select_candidates

    with db() as s:
        _candidate(s, "news", kind="news")
        s.commit()
        assert "wk-art-news" in {a.id for a in select_candidates(s, "withheld", 50, 3)}


@pytest.mark.parametrize("kind", ["obituary", "column"])
def test_a_reprocess_refuses_it_too(db, kind):
    from src.enrichment.repository import select_reprocess_candidates

    with db() as s:
        _candidate(s, "plain")
        _candidate(s, kind, kind=kind)
        s.commit()
        picked = {a.id for a in select_reprocess_candidates(s, "withheld", 50, 3)}

    assert picked == {"wk-art-plain"}, kind


@pytest.mark.parametrize("kind", ["obituary", "column"])
def test_a_backfill_refuses_it_by_name(db, kind):
    """The one path a person drives directly, so the refusal has to say
    why rather than silently dropping the id."""
    from src.enrichment.repository import select_by_ids

    with db() as s:
        _candidate(s, kind, kind=kind)
        s.commit()
        report = select_by_ids(s, [f"wk-art-{kind}"], 3)

    assert report.candidates == []
    assert kind in report.rejected[f"wk-art-{kind}"]
    assert "never enriched" in report.rejected[f"wk-art-{kind}"]
