"""add e-edition url path filters

Revision ID: 43a60f360933
Revises: ebac28990451
Create Date: 2025-12-20 14:06:06.444030

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '43a60f360933'
down_revision: Union[str, Sequence[str], None] = 'ebac28990451'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add e-edition URL path patterns to url_path_filters table
    op.execute("""
        INSERT INTO url_path_filters (path_pattern, filter_type, reason, active, notes)
        VALUES
            ('/e-edition/', 'contains', 'E-edition pages', true, 'Digital newspaper replica pages'),
            ('/eedition/', 'contains', 'E-edition pages', true, 'Digital newspaper replica pages (no hyphen)')
        ON CONFLICT (path_pattern) DO NOTHING
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove e-edition patterns
    op.execute("""
        DELETE FROM url_path_filters
        WHERE path_pattern IN ('/e-edition/', '/eedition/')
    """)
