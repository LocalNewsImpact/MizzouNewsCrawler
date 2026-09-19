"""`last_modified` is stamped by the database, on every kind of write.

The point of a trigger over a generated `GREATEST(...)` of the six stage
timestamps is the writes that move none of them: a status change, a headline
repair, a metadata write. Those are most of what a curation pass does, and
they are what the 2026-09-19 retraction of 226 rows consisted of.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

PREVIOUS = "b1c2d3e4f5a7"


def _alembic(args, env, cwd):
    done = subprocess.run(
        ["alembic", *args], capture_output=True, text=True, env=env, cwd=cwd
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL")
    or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
    reason="PostgreSQL test database not configured",
)
def test_every_write_stamps_last_modified():
    database_url = os.environ["TEST_DATABASE_URL"]
    root = Path(__file__).parent.parent.parent
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["USE_CLOUD_SQL_CONNECTOR"] = "false"
    engine = create_engine(database_url)

    suffix = uuid.uuid4().hex[:8]
    src, link = str(uuid.uuid4()), f"lm-link-{suffix}"
    old, fresh = f"lm-old-{suffix}", f"lm-new-{suffix}"

    # Seeded BEFORE the migration, as production rows were: `created_at` back in
    # time and one stage timestamp later, so the backfill has something to pick.
    _alembic(["downgrade", PREVIOUS], env, root)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sources (id, host, host_norm) VALUES (:i, :h, :h)"),
            {"i": src, "h": f"{suffix}.example"},
        )
        conn.execute(
            text(
                "INSERT INTO candidate_links (id, url, source, source_id, status, discovered_at) "
                "VALUES (:i, :u, 't', :s, 'article', now())"
            ),
            {"i": link, "u": f"https://{suffix}.example/", "s": src},
        )
        conn.execute(
            text(
                "INSERT INTO articles (id, candidate_link_id, url, status, wire_check_status, title, "
                "created_at, extracted_at, enriched_at, enrichment_attempts) VALUES "
                "(:i, :l, :u, 'labeled', 'local', 'H', '2026-01-01', '2026-02-02', '2026-03-03', 0)"
            ),
            {"i": old, "l": link, "u": f"https://{suffix}.example/old"},
        )
    try:
        _alembic(["upgrade", "head"], env, root)

        with engine.begin() as conn:
            backfilled = conn.execute(
                text("SELECT last_modified FROM articles WHERE id = :i"), {"i": old}
            ).scalar()
            # The latest stage timestamp on the row, not the migration's clock.
            assert str(backfilled).startswith("2026-03-03"), backfilled

            nn = conn.execute(
                text(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name='articles' AND column_name='last_modified'"
                )
            ).one()
            assert nn[0] == "NO" and "now()" in (nn[1] or "")
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM pg_indexes WHERE indexname='ix_articles_last_modified'"
                    )
                ).scalar()
                == 1
            )

            # A fresh insert takes the default.
            conn.execute(
                text(
                    "INSERT INTO articles (id, candidate_link_id, url, status, wire_check_status, "
                    "created_at, extracted_at, enrichment_attempts) VALUES "
                    "(:i, :l, :u, 'cleaned', 'local', now(), now(), 0)"
                ),
                {"i": fresh, "l": link, "u": f"https://{suffix}.example/new"},
            )
            assert conn.execute(
                text("SELECT last_modified IS NOT NULL FROM articles WHERE id = :i"),
                {"i": fresh},
            ).scalar()

        # The writes a generated GREATEST() would miss.
        for column, value in (
            ("status", "curated_out"),
            ("title", "Repaired headline"),
        ):
            with engine.begin() as conn:
                before = conn.execute(
                    text("SELECT last_modified FROM articles WHERE id = :i"), {"i": old}
                ).scalar()
            time.sleep(0.01)
            with engine.begin() as conn:
                conn.execute(
                    text(f"UPDATE articles SET {column} = :v WHERE id = :i"),
                    {"v": value, "i": old},
                )
                after = conn.execute(
                    text("SELECT last_modified FROM articles WHERE id = :i"), {"i": old}
                ).scalar()
            assert after > before, f"a {column} write did not stamp last_modified"

        # And it cannot be written from outside: the trigger overrides.
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE articles SET last_modified = '2001-01-01' WHERE id = :i"),
                {"i": old},
            )
            got = conn.execute(
                text("SELECT last_modified FROM articles WHERE id = :i"), {"i": old}
            ).scalar()
        assert not str(got).startswith("2001"), "the trigger must own this column"

        # Sorting newest-first puts the row we just touched on top.
        with engine.begin() as conn:
            first = conn.execute(
                text(
                    "SELECT id FROM articles WHERE candidate_link_id = :l "
                    "ORDER BY last_modified DESC LIMIT 1"
                ),
                {"l": link},
            ).scalar()
        assert first == old

        _alembic(["downgrade", PREVIOUS], env, root)
        with engine.begin() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name='articles' AND column_name='last_modified'"
                    )
                ).scalar()
                == 0
            )
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                        "WHERE c.relname='articles' AND t.tgname='trg_articles_last_modified'"
                    )
                ).scalar()
                == 0
            )
    finally:
        _alembic(["upgrade", "head"], env, root)
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM articles WHERE candidate_link_id = :l"), {"l": link}
            )
            conn.execute(text("DELETE FROM candidate_links WHERE id = :l"), {"l": link})
            conn.execute(text("DELETE FROM sources WHERE id = :s"), {"s": src})
