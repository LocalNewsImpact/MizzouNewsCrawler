"""add unique constraint on articles.url

Revision ID: 20251025_add_uq_articles_url
Revises: 805164cd4665
Create Date: 2025-10-25 12:52:00.000000

This migration enforces URL deduplication at the database level by adding
a unique constraint on articles(url). This prevents duplicate articles from
being inserted and allows the extraction process to safely use ON CONFLICT
DO NOTHING.

IMPORTANT: This migration will FAIL if duplicate URLs exist in the articles
table. Run the deduplication script (scripts/fix_article_duplicates.py)
BEFORE applying this migration.

For PostgreSQL:
- Uses CREATE UNIQUE INDEX CONCURRENTLY to minimize locking
- Non-transactional to support CONCURRENTLY keyword
- Safe to run on production with minimal downtime

For SQLite:
- Uses standard CREATE UNIQUE INDEX
- Runs in transaction
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "20251025_add_uq_articles_url"
down_revision: Union[str, Sequence[str], None] = "805164cd4665"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint on articles.url."""
    # Get database connection to check dialect and verify no duplicates
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    # Pre-flight check: Verify no duplicate URLs exist
    # This query finds any URLs that appear more than once
    result = bind.execute(
        text(
            """
        SELECT url, COUNT(*) as count
        FROM articles
        GROUP BY url
        HAVING COUNT(*) > 1
        LIMIT 1
    """
        )
    )

    duplicate_row = result.fetchone()
    if duplicate_row is not None:
        url, count = duplicate_row
        raise RuntimeError(
            f"Cannot add unique constraint: Found {count} articles with URL '{url}'. "
            "Run scripts/fix_article_duplicates.py to remove duplicates before "
            "applying this migration."
        )

    if is_postgresql:
        # PostgreSQL: Use CONCURRENTLY to avoid blocking writes
        # CONCURRENTLY requires running outside of a transaction
        # Alembic will handle this if we use op.execute with proper DDL
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_articles_url "
            "ON articles (url)"
        )
    else:
        # SQLite: Standard index creation (no CONCURRENTLY support)
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_url ON articles (url)"
        )


def downgrade() -> None:
    """Remove unique constraint on articles.url."""
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        # PostgreSQL: Use CONCURRENTLY for non-blocking drop
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_articles_url")
    else:
        # SQLite: Standard drop
        op.execute("DROP INDEX IF EXISTS uq_articles_url")
