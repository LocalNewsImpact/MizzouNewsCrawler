"""tune autovacuum for high-write tables

Revision ID: 7312b1db764e
Revises: 146ea14c7cf2
Create Date: 2025-11-27 21:58:57.077953

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7312b1db764e'
down_revision: Union[str, Sequence[str], None] = '146ea14c7cf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tune autovacuum settings for high-write tables.
    
    Default autovacuum_analyze_scale_factor = 0.1 (10% of rows must change).
    For article_entities (830k rows), this requires 83k changes before ANALYZE runs.
    We observed 8-day stale statistics with only 66k modifications.
    
    These table-specific settings trigger ANALYZE more frequently:
    - article_entities: 2% = 16.6k changes (was 83k)
    - candidate_links: 5% = 2.5k changes (was 5k)
    - articles: 5% = 2.2k changes (was 4.3k)
    """
    op.execute("""
        ALTER TABLE article_entities SET (
            autovacuum_vacuum_scale_factor = 0.05,
            autovacuum_analyze_scale_factor = 0.02
        )
    """)
    
    op.execute("""
        ALTER TABLE candidate_links SET (
            autovacuum_vacuum_scale_factor = 0.1,
            autovacuum_analyze_scale_factor = 0.05
        )
    """)
    
    op.execute("""
        ALTER TABLE articles SET (
            autovacuum_analyze_scale_factor = 0.05
        )
    """)


def downgrade() -> None:
    """Reset autovacuum settings to defaults."""
    op.execute("ALTER TABLE article_entities RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)")
    op.execute("ALTER TABLE candidate_links RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)")
    op.execute("ALTER TABLE articles RESET (autovacuum_analyze_scale_factor)")
