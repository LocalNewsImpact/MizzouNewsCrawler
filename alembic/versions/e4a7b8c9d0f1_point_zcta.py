"""ZCTA on block-resolved points.

The ZCTA — the Census's ZIP-code geography — is the smallest official unit a
reader recognizes by name, and it is a real GEOID that joins to ACS tables
exactly like the rest of the ladder. The block lookup's geocoder response
already carries it, so block-level points store it at no extra cost. NULL for
points resolved above block level and for stories with no point.

Revision ID: e4a7b8c9d0f1
Revises: d3f6a7b8c9e0
Create Date: 2026-08-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7b8c9d0f1"
down_revision: Union[str, None] = "d3f6a7b8c9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "article_enrichment", sa.Column("point_zcta", sa.String(5), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("article_enrichment", "point_zcta")
