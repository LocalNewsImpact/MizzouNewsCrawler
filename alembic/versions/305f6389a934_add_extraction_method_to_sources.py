"""add_extraction_method_to_sources

Revision ID: 305f6389a934
Revises: i2j3k4l5m6n7
Create Date: 2025-12-12 14:45:57.279387

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '305f6389a934'
down_revision: Union[str, Sequence[str], None] = 'i2j3k4l5m6n7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add extraction_method column to sources table.

    Replaces selenium_only boolean with extraction_method string:
    - 'http': default, use HTTP requests
    - 'selenium': use Selenium browser
    - 'unblock': use Decodo unblock proxy for strong bot protection

    Migrates existing selenium_only=true rows to extraction_method='selenium'.
    """
    # Add extraction_method column with default 'http'
    op.add_column(
        'sources',
        sa.Column(
            'extraction_method',
            sa.String(32),
            nullable=False,
            server_default="'http'"
        )
    )

    # Migrate existing selenium_only=true to extraction_method='selenium'
    op.execute(
        """
        UPDATE sources
        SET extraction_method = 'selenium'
        WHERE selenium_only = true
        """
    )

    # For PerimeterX protected domains, use 'unblock' method
    op.execute(
        """
        UPDATE sources
        SET extraction_method = 'unblock'
        WHERE bot_protection_type = 'perimeterx'
        AND selenium_only = true
        """
    )

    # Add index for extraction_method queries
    op.create_index(
        'ix_sources_extraction_method',
        'sources',
        ['extraction_method']
    )


def downgrade() -> None:
    """Remove extraction_method column, restore selenium_only behavior."""
    # Drop index
    op.drop_index('ix_sources_extraction_method', 'sources')

    # Update selenium_only based on extraction_method before dropping
    op.execute(
        """
        UPDATE sources
        SET selenium_only = true
        WHERE extraction_method IN ('selenium', 'unblock')
        """
    )

    # Drop extraction_method column
    op.drop_column('sources', 'extraction_method')
