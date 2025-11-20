"""fix_hash_columns_to_bigint

Revision ID: 8656775d7ad0
Revises: 61de0fe110e1
Create Date: 2025-11-20 16:44:36.313853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8656775d7ad0'
down_revision: Union[str, Sequence[str], None] = '61de0fe110e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Fix hash columns that can exceed 32-bit integer range
    # Python's hash() returns values that can be larger than INTEGER (max 2,147,483,647)
    
    # content_cleaning_segments.segment_text_hash: Integer -> BigInteger
    op.alter_column('content_cleaning_segments', 'segment_text_hash',
                    type_=sa.BigInteger(),
                    existing_type=sa.Integer(),
                    existing_nullable=True)
    
    # content_cleaning_wire_events.pattern_text_hash: Integer -> BigInteger
    op.alter_column('content_cleaning_wire_events', 'pattern_text_hash',
                    type_=sa.BigInteger(),
                    existing_type=sa.Integer(),
                    existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Revert BigInteger back to Integer
    op.alter_column('content_cleaning_wire_events', 'pattern_text_hash',
                    type_=sa.Integer(),
                    existing_type=sa.BigInteger(),
                    existing_nullable=True)
    
    op.alter_column('content_cleaning_segments', 'segment_text_hash',
                    type_=sa.Integer(),
                    existing_type=sa.BigInteger(),
                    existing_nullable=True)
