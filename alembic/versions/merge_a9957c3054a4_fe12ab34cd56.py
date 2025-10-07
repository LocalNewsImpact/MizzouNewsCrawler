"""merge heads a9957c3054a4 and fe12ab34cd56

Revision ID: m20251006_merge_heads
Revises: a9957c3054a4, fe12ab34cd56
Create Date: 2025-10-06 00:00:00.000000
"""
# revision identifiers, used by Alembic.
revision = '9f8e7d6c5b4a'
down_revision = ('a9957c3054a4', 'fe12ab34cd56')
branch_labels = None
depends_on = None


def upgrade():
    # Empty merge revision: records that two parallel heads were merged into this
    # revision. No schema changes performed here.
    return


def downgrade():
    # Downgrade is intentionally not implemented for this merge-only revision.
    raise NotImplementedError("Downgrade not supported for merge revision")
