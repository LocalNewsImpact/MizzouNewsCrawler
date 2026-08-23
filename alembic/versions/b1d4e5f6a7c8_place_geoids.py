"""Per-place GEOIDs on article_places.

A regional story's geography is its mentions, not one story-level code: a state
championship matters to the two teams' cities. Each extracted place row now
carries its own GEOID (city -> place, county -> county), resolved from the
bundled gazetteer.

Revision ID: b1d4e5f6a7c8
Revises: a9c3d4e5f6b7
Create Date: 2026-08-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1d4e5f6a7c8"
down_revision: Union[str, None] = "a9c3d4e5f6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("article_places", sa.Column("geoid", sa.Text(), nullable=True))
    op.add_column("article_places", sa.Column("geoid_level", sa.Text(), nullable=True))
    op.create_index("ix_article_places_geoid", "article_places", ["geoid"])


def downgrade() -> None:
    op.drop_index("ix_article_places_geoid", table_name="article_places")
    op.drop_column("article_places", "geoid_level")
    op.drop_column("article_places", "geoid")
