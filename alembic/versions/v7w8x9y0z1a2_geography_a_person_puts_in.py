"""Geography a person puts in.

Some articles will never get their geography from the pipeline. A story
behind a paywall arrives as a headline and a subscription prompt, and no
amount of re-running the model reads what was not fetched.

A person contributes it, and it lives here rather than in
`article_geoids`, because `persist_outcome` deletes and rewrites an
article's geoid set on every enrichment run:

    DELETE FROM article_geoids WHERE article_id = :id

A human row written there is destroyed the next time anything
re-enriches that article -- including a run that produces worse geography
than the person did. So this table holds the contribution and
`build_story_geoids` REBUILDS the geoid set from it, emitting
`source = 'human'` rows alongside the extracted ones.

See docs/MANUAL_GEOGRAPHY.md.

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "v7w8x9y0z1a2"
down_revision: Union[str, Sequence[str], None] = "u6v7w8x9y0z1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "article_places_manual",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article_id", sa.Text, nullable=False, index=True),
        # What the reviewer wrote, as they wrote it. Kept beside the
        # resolved code so a wrong resolution can be told from a wrong
        # entry -- "Freeburg, IL" resolving to Illinois is a different
        # mistake from somebody meaning Illinois.
        sa.Column("full_name", sa.Text),
        sa.Column("city", sa.Text),
        sa.Column("county", sa.Text),
        sa.Column("state", sa.Text),
        # Resolved through lnic_contracts.geography, never typed. A
        # reviewer never enters a FIPS, and a human entry cannot land on
        # a rung the pipeline could not have reached.
        sa.Column("geoid", sa.Text),
        sa.Column("geoid_level", sa.Text),
        # The central location, or one of the places the story names.
        sa.Column("is_point", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("added_by", sa.Text, nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("note", sa.Text),
    )
    # One central location per article. A story has one centre by
    # definition, and two rows claiming it is a contradiction rather than
    # a disagreement worth keeping.
    op.create_index(
        "uq_manual_one_point_per_article",
        "article_places_manual",
        ["article_id"],
        unique=True,
        postgresql_where=sa.text("is_point"),
    )
    # The same place entered twice is a duplicate, not two mentions.
    op.create_index(
        "uq_manual_place_per_article",
        "article_places_manual",
        ["article_id", "geoid", "is_point"],
        unique=True,
        postgresql_where=sa.text("geoid IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_manual_place_per_article", table_name="article_places_manual")
    op.drop_index("uq_manual_one_point_per_article", table_name="article_places_manual")
    op.drop_table("article_places_manual")
