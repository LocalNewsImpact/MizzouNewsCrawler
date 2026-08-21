"""Record WHY a story has no point GEOID.

An absent code must be distinguishable by cause: designed absence (regional
stories carry a place set instead; national/international/other assert no
codeable geography) versus failure (city not in the Census gazetteer,
publication state unknown). NULL means a point GEOID is present.

Revision ID: d3f6a7b8c9e0
Revises: c2e5f6a7b8d9
Create Date: 2026-08-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f6a7b8c9e0"
down_revision: Union[str, None] = "c2e5f6a7b8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "article_enrichment", sa.Column("geo_skip_reason", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("article_enrichment", "geo_skip_reason")
