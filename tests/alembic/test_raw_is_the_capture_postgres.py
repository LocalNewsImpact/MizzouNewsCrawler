"""The rename lands on a table with rows in it, and what depends on the
column follows without being told.

Three things are asserted against a real PostgreSQL, because none can be
seen in a migration file:

- `text_length` measures the cleaned body once the column prefers `text`,
  and an empty string is a measured zero rather than a fall-through to the
  capture. coalesce() skips NULL, not ''.
- The partial index `ix_articles_rot47_ciphertext` and a column-level grant
  both follow the rename on their own: PostgreSQL holds them by attribute
  number, not by name. Production carries eight such grants.
- Downgrade restores the old name and the old expression, so the migration
  can be backed out without a hand-written repair.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

PREVIOUS = "z6f7a8b9c0d1"


def _alembic(args, env, cwd):
    done = subprocess.run(
        ["alembic", *args], capture_output=True, text=True, env=env, cwd=cwd
    )
    assert done.returncode == 0, done.stderr
    return done


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL")
    or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
    reason="PostgreSQL test database not configured",
)
def test_raw_is_the_capture_and_text_length_measures_the_clean():
    database_url = os.environ["TEST_DATABASE_URL"]
    project_root = Path(__file__).parent.parent.parent
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["USE_CLOUD_SQL_CONNECTOR"] = "false"
    engine = create_engine(database_url)

    suffix = uuid.uuid4().hex[:8]
    source_id, link_id = str(uuid.uuid4()), f"rn-link-{suffix}"
    ids = {k: f"rn-{k}-{suffix}" for k in ("clean", "rawonly", "emptied")}
    role = f"rename_probe_{suffix}"

    # One migration short of the one under test: rows and a grant exist
    # under the OLD name, which is the state production is in.
    _alembic(["downgrade", PREVIOUS], env, project_root)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO sources (id, host, host_norm) VALUES (:id, :h, :h)"),
                {"id": source_id, "h": f"{suffix}.example"},
            )
            conn.execute(
                text(
                    "INSERT INTO candidate_links (id, url, source, source_id, status, "
                    "discovered_at) VALUES (:id, :url, :src, :sid, 'article', now())"
                ),
                {
                    "id": link_id,
                    "url": f"https://{suffix}.example/",
                    "src": "t",
                    "sid": source_id,
                },
            )
            for key, content, body, excerpt in (
                ("clean", "RAW CAPTURE with chrome around it", "clean", None),
                ("rawonly", "raw only", None, None),
                ("emptied", "raw", "", "ex"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO articles (id, candidate_link_id, url, status, "
                        "wire_check_status, title, content, text, text_excerpt, "
                        "created_at, extracted_at, enrichment_attempts) VALUES "
                        "(:id, :lid, :url, 'cleaned', 'local', 't', :content, :body, "
                        ":excerpt, now(), now(), 0)"
                    ),
                    {
                        "id": ids[key],
                        "lid": link_id,
                        "url": f"https://{suffix}.example/{key}",
                        "content": content,
                        "body": body,
                        "excerpt": excerpt,
                    },
                )
            conn.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            conn.execute(text(f"GRANT SELECT (content) ON articles TO {role}"))
            before = {
                r.id: r.text_length
                for r in conn.execute(
                    text("SELECT id, text_length FROM articles WHERE id = ANY(:ids)"),
                    {"ids": list(ids.values())},
                )
            }
        # The old expression preferred the capture.
        assert before[ids["clean"]] == len("RAW CAPTURE with chrome around it")
        assert before[ids["emptied"]] == len("raw")

        if True:
            _alembic(["upgrade", "head"], env, project_root)

            with engine.begin() as conn:
                cols = {
                    r.column_name: r.generation_expression
                    for r in conn.execute(
                        text(
                            "SELECT column_name, generation_expression "
                            "FROM information_schema.columns "
                            "WHERE table_name = 'articles' "
                            "AND column_name IN ('raw', 'content', 'text_length')"
                        )
                    )
                }
                assert "raw" in cols and "content" not in cols
                expression = (cols["text_length"] or "").lower().replace(" ", "")
                assert "coalesce(text,raw" in expression, expression

                after = {
                    r.id: r.text_length
                    for r in conn.execute(
                        text(
                            "SELECT id, text_length FROM articles WHERE id = ANY(:ids)"
                        ),
                        {"ids": list(ids.values())},
                    )
                }
                assert after[ids["clean"]] == len("clean"), "measures the cleaned body"
                assert after[ids["rawonly"]] == len(
                    "raw only"
                ), "falls back to the capture"
                assert after[ids["emptied"]] == 0, "'' is a measured zero, not absence"

                indexes = {
                    r.indexname: r.indexdef
                    for r in conn.execute(
                        text(
                            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'articles'"
                        )
                    )
                }
                assert "ix_articles_text_length" in indexes
                rot47 = indexes.get("ix_articles_rot47_ciphertext", "")
                assert "raw" in rot47 and "content" not in rot47, rot47

                granted = [
                    r.column_name
                    for r in conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.column_privileges "
                            "WHERE table_name = 'articles' AND grantee = :role"
                        ),
                        {"role": role},
                    )
                ]
                assert granted == ["raw"], granted

                # The new name takes writes.
                conn.execute(
                    text(
                        "UPDATE articles SET raw = 'rewritten capture' WHERE id = :id"
                    ),
                    {"id": ids["rawonly"]},
                )
                assert conn.execute(
                    text("SELECT text_length FROM articles WHERE id = :id"),
                    {"id": ids["rawonly"]},
                ).scalar() == len("rewritten capture")

            # And it backs out.
            _alembic(["downgrade", PREVIOUS], env, project_root)
            with engine.begin() as conn:
                cols = {
                    r.column_name: r.generation_expression
                    for r in conn.execute(
                        text(
                            "SELECT column_name, generation_expression "
                            "FROM information_schema.columns "
                            "WHERE table_name = 'articles' "
                            "AND column_name IN ('raw', 'content', 'text_length')"
                        )
                    )
                }
                assert "content" in cols and "raw" not in cols
                assert "coalesce(content,text" in (
                    cols["text_length"] or ""
                ).lower().replace(" ", "")
                restored = conn.execute(
                    text("SELECT text_length FROM articles WHERE id = :id"),
                    {"id": ids["clean"]},
                ).scalar()
                assert restored == len("RAW CAPTURE with chrome around it")
    finally:
        _alembic(["upgrade", "head"], env, project_root)
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM articles WHERE id = ANY(:ids)"),
                {"ids": list(ids.values())},
            )
            conn.execute(
                text("DELETE FROM candidate_links WHERE id = :id"), {"id": link_id}
            )
            conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})
            conn.execute(text(f"REVOKE ALL ON articles FROM {role}"))
            conn.execute(text(f"DROP ROLE {role}"))
