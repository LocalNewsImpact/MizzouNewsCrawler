"""index_what_the_blocked_page_asks

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-09-08 21:20:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "u6v7w8x9y0z1"
down_revision: Union[str, Sequence[str], None] = "t5u6v7w8x9y0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Give the operations page the three indexes it reads through.

    Datadesk's Blocked report answers "what is stopping articles from
    processing" and returned a 504 instead: 300 seconds, the Cloud Run
    ceiling, every time it was opened.

    Nothing was wrong with the page. It asks five questions of
    `extraction_telemetry_v2` -- how many URLs 404, 403, 429-or-5xx, hit
    a proxy challenge, were refused by the proxy -- and that table
    carries seventeen indexes, none of them on the two columns those
    questions filter by:

        count(DISTINCT url) ... WHERE http_status_code = 404   75s
        count(DISTINCT url) ... WHERE error_type = 'proxy_challenge'

    Each is a sequential scan of 838 MB to return a few hundred rows,
    and the page runs five of them: ~375 seconds before it reaches the
    ROT47 question, which scans all 1.5 GB of `articles.content` for a
    substring and takes over 120 seconds on its own.

    Combining the five into one pass with FILTER was the wrong repair
    and was measured before it was written: it does bring 375 seconds to
    87, but only by conceding the sequential scan for every branch. With
    the columns indexed the five questions read 5,628 matching rows
    instead of 253,530 and cost 5.8 seconds together, and the combined
    version would have been slower than what is here.

    The third index is partial. A btree cannot serve `LIKE '%k^Am%'`,
    but an index whose WHERE clause *is* that predicate can: Postgres
    proves the query's condition from the index's own and reads the
    matching rows directly. 64 articles still hold ROT47 ciphertext out
    of 164,066, so this indexes 64 rows.

        five fetch-failure counts    ~375s -> 5.8s
        ROT47 body count             >120s -> 0.19s
        publisher breakdowns                  14.8s

    All three were built in production with CONCURRENTLY, so no table
    was locked while the processor was polling. This migration is the
    same indexes for a database that is rebuilt from scratch, written
    the way `c4e8a1f52b7d` writes an out-of-band index: idempotent, and
    plain rather than CONCURRENTLY, because a fresh database has no
    concurrent writer to protect and Alembic runs inside a transaction.
    """
    bind = op.get_bind()

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_etv2_http_status_code "
        "ON extraction_telemetry_v2 (http_status_code)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_etv2_error_type "
        "ON extraction_telemetry_v2 (error_type)"
    )

    if bind.dialect.name == "postgresql":
        # The marker is ROT47-encoded "</p>". The percent signs are
        # single: doubling them to escape a driver placeholder was tried
        # and stored the pattern verbatim as '%%k^Am%%', which is a
        # working LIKE pattern the planner will not match against the
        # query's '%k^Am%' -- an index that is built, maintained, and
        # never used.
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_articles_rot47_ciphertext "
            "ON articles (id) WHERE content LIKE '%k^Am%'"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_articles_rot47_ciphertext")
    op.execute("DROP INDEX IF EXISTS ix_etv2_error_type")
    op.execute("DROP INDEX IF EXISTS ix_etv2_http_status_code")
