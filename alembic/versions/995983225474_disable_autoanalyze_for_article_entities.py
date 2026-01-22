"""disable_autoanalyze_for_article_entities

Revision ID: 995983225474
Revises: 7312b1db764e
Create Date: 2025-11-30 18:54:59.916242

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '995983225474'
down_revision: Union[str, Sequence[str], None] = '7312b1db764e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Disable autovacuum ANALYZE for article_entities.

    The article_entities table is write-once, read-many:
    - Written only during bulk entity extraction for new sources
    - Read constantly by NER queries and analytics

    Auto-analyze wastes resources checking this table daily when it rarely changes.
    Instead, we manually run ANALYZE after bulk entity insertion via:
      session.execute(text('ANALYZE article_entities'))

    This ensures new entities are indexed immediately when added, without
    unnecessary daily overhead for a mostly-static table.

    Note: We keep autovacuum enabled for cleanup, just disable auto-analyze.
    """
    # Disable auto-analyze but keep autovacuum for cleanup
    # Setting scale_factor=0 and huge threshold effectively disables it
    op.execute("""
        ALTER TABLE article_entities SET (
            autovacuum_analyze_scale_factor = 0,
            autovacuum_analyze_threshold = 1000000000
        )
    """)


def downgrade() -> None:
    """Re-enable autovacuum analyze with 2% threshold."""
    op.execute("""
        ALTER TABLE article_entities SET (
            autovacuum_analyze_scale_factor = 0.02,
            autovacuum_analyze_threshold = 50
        )
    """)
