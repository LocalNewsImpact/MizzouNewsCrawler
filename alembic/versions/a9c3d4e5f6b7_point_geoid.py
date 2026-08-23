"""Add the FIPS/GEOID point columns to article_enrichment.

Decision 2026-08-21: the location target is the deepest available Census GEOID
(state 2 / county 5 / place 7 / tract 11 / block 15), not precise coordinates.
point_geoid holds the code; point_geoid_level says how deep the ladder got.
GEOIDs nest by prefix, so county rollups are LEFT(point_geoid, 5).

Revision ID: a9c3d4e5f6b7
Revises: f8b2d3c4e5a6
Create Date: 2026-08-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9c3d4e5f6b7"
down_revision: Union[str, None] = "f8b2d3c4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "article_enrichment", sa.Column("point_geoid", sa.Text(), nullable=True)
    )
    op.add_column(
        "article_enrichment", sa.Column("point_geoid_level", sa.Text(), nullable=True)
    )
    op.create_index(
        "ix_article_enrichment_point_geoid", "article_enrichment", ["point_geoid"]
    )


def downgrade() -> None:
    op.drop_index("ix_article_enrichment_point_geoid", table_name="article_enrichment")
    op.drop_column("article_enrichment", "point_geoid_level")
    op.drop_column("article_enrichment", "point_geoid")
