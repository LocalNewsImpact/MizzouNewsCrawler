"""Integration tests for the backfield enrichment schema (Phase 1).

PostgreSQL only, matching the repo's migration policy (the SQLite path is
deprecated; CI runs a postgres service container). The test upgrades through
the full chain to the enrichment revision, verifies the schema — including the
two shapes SQLite cannot represent, text[] and the GIN index — then downgrades
one revision and verifies clean removal.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).parent.parent.parent
REVISION = "f8b2d3c4e5a6"
TABLES = (
    "article_enrichment",
    "article_places",
    "article_people",
    "article_organizations",
)


def _pg_url() -> str | None:
    url = os.environ.get("ENRICHMENT_PG_URL") or os.environ.get("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else None


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "USE_CLOUD_SQL_CONNECTOR": "false"}
    return subprocess.run(
        ["alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.mark.skipif(
    _pg_url() is None, reason="needs a PostgreSQL DATABASE_URL or ENRICHMENT_PG_URL"
)
def test_migration_roundtrip():
    url = _pg_url()
    up = _alembic(url, "upgrade", REVISION)
    assert up.returncode == 0, up.stderr[-3000:]

    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        tables = set(insp.get_table_names())
        for t in TABLES:
            assert t in tables, f"{t} missing after upgrade"

        articles = {c["name"] for c in insp.get_columns("articles")}
        assert {"enriched_at", "enrichment_attempts"} <= articles

        enrichment = {c["name"] for c in insp.get_columns("article_enrichment")}
        for col in (
            "profile_version",
            "steps_applied",
            "skip_reason",
            "backfield_commit",
            "model",
            "prompt_versions",
            "cost_usd",
            "is_news_content",
            "scope",
            "scope_confidence",
            "subject",
            "topic",
            "format",
            "timeframe",
            "user_need",
            "rationales",
            "point_place",
            "point_method",
            "point_lat",
            "point_lon",
            "point_gnis",
        ):
            assert col in enrichment, f"article_enrichment.{col} missing"

        with engine.connect() as conn:
            col_type = conn.execute(
                sa.text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='article_enrichment' AND column_name='steps_applied'"
                )
            ).scalar()
            assert col_type == "ARRAY", f"steps_applied is {col_type}, expected ARRAY"

            gin = conn.execute(
                sa.text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname='ix_article_enrichment_steps_applied'"
                )
            ).scalar()
            assert gin and "gin" in gin.lower(), "GIN index on steps_applied missing"

            # cascade: a child row must not survive its article
            conn.execute(
                sa.text(
                    "INSERT INTO candidate_links "
                    "(id, url, source, discovered_at, status, created_at) "
                    "VALUES ('enr-test-cl-1', 'https://example.test/enr-test-1', "
                    "'enr-test', now(), 'new', now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO articles "
                    "(id, status, candidate_link_id, created_at, extracted_at) "
                    "VALUES ('enr-test-1', 'labeled', 'enr-test-cl-1', now(), now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO article_people (article_id, name) "
                    "VALUES ('enr-test-1', 'Test Person')"
                )
            )
            conn.execute(sa.text("DELETE FROM articles WHERE id='enr-test-1'"))
            orphans = conn.execute(
                sa.text(
                    "SELECT count(*) FROM article_people WHERE article_id='enr-test-1'"
                )
            ).scalar()
            assert orphans == 0, "ON DELETE CASCADE did not remove the child row"
            conn.rollback()
    finally:
        engine.dispose()

    down = _alembic(url, "downgrade", "-1")
    assert down.returncode == 0, down.stderr[-3000:]

    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        tables = set(insp.get_table_names())
        for t in TABLES:
            assert t not in tables, f"{t} survived downgrade"
        articles = {c["name"] for c in insp.get_columns("articles")}
        assert "enriched_at" not in articles
        assert "enrichment_attempts" not in articles
    finally:
        engine.dispose()
