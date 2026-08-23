"""add_articles_publish_date_sort_index

Revision ID: a7c3f9e2d481
Revises: e7a1c2b3d4f5
Create Date: 2026-08-23 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7c3f9e2d481'
down_revision: Union[str, Sequence[str], None] = 'e7a1c2b3d4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the index the article browser's default sort needs.

    Datadesk's article grid orders by
    `publish_date DESC NULLS LAST, created_at DESC` and pages fifty rows
    at a time. With no matching index that is a sequential scan of every
    article followed by a sort:

        Limit  (actual time=4491.563..4497.427 rows=50)
          Buffers: shared hit=4294 read=57496
          ->  Gather Merge  (Workers Launched: 2)
                ->  Sort  Sort Key: publish_date DESC NULLS LAST,
                                    created_at DESC
                      Sort Method: top-N heapsort

    4.5 seconds and 57,496 blocks read from disk to return fifty rows,
    paid on every visit and every page.

    The ordering has to be spelled out. A plain ascending index on
    publish_date does not serve this sort — `candidate_links` already
    carries `ix_candidate_links_publish_date`, and the same query shape
    against that table still plans a full top-N heapsort, because a
    backward scan of an ascending index yields NULLS FIRST and the query
    asks for NULLS LAST. So this is raw DDL rather than
    `op.create_index`, which cannot express DESC or NULLS ordering.

    2,352 of 164,570 articles have no publish_date, so the NULLS LAST is
    not cosmetic.
    """
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_articles_publish_date_created
        ON articles (publish_date DESC NULLS LAST, created_at DESC)
        """
    )


def downgrade() -> None:
    """Downgrade schema - drop the sort index."""
    op.execute("DROP INDEX IF EXISTS ix_articles_publish_date_created")
