"""A gazetteer the whole state shares.

The gazetteer is built per publisher inside a 20-mile radius and matched
that way in code (`get_gazetteer_rows` filters on `Gazetteer.source_id`),
which has three consequences measured on 2026-09-15:

  CIRCULAR EVIDENCE. Every candidate is within 22.2 miles of one
  publisher, so any match resolves near that publisher. A story naming a
  chain matches the branch in the publisher's own town -- not because the
  story is about that town, but because it is the only branch in the
  table for that source. Used as evidence for the grounding gate, that
  launders the publisher-city bias the gate exists to stop.

  LOST RECALL. A story about a town 30 miles from its publisher gets no
  institution evidence at all, however distinctively it names a school
  there. "Mizzou Arena" is in the gazetteer, resolved to Columbia, and
  invisible to every publisher further out.

  DUPLICATION. 558,540 rows hold 83,325 distinct OSM features, 6.7 copies
  each, because a feature is stored once per nearby source.

This is the shape that fixes all three: one row per feature per state.

WHY A SECOND TABLE RATHER THAN A COLUMN. `gazetteer` is per-source by
definition -- its rows carry `dataset_id`, `source_id`, `host_id` and
`distance_miles`, and `byline_cleaner` reads it for organisation names.
Adding a nullable state to it would leave two incompatible grains in one
table and no way to tell which query wanted which. The per-source table
keeps working, unchanged, while this one is built alongside it.

`gazetteer_name_places` is the ambiguity index, and it is the rule from
docs/STATEWIDE_GAZETTEER.md §3.1 made into a lookup. Statewide a chain
name resolves to dozens of places and therefore locates nothing:
walmart supercenter occurs in 149, pizza hut in 140, aldi in 72. A name
is usable only where `place_count = 1`, and then `place_geoid` carries
the answer -- so the gate asks one indexed question instead of counting
distinct places across tens of thousands of rows per article.

Deduplicated statewide, of 62,478 distinct names 24,249 resolve to
exactly one place and 1,255 are ambiguous. No brand list, no heuristic:
the data says which is which.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "z1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gazetteer_features",
        sa.Column("id", sa.String(), primary_key=True),
        # Two letters, and never guessed: `resolve_source_state` returns
        # "" rather than a default, because 896 of 901 Vermont sources
        # arrive without a state and defaulting one geocoded publishers
        # into the wrong state without failing loudly.
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("osm_type", sa.String(), nullable=False),
        sa.Column("osm_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_norm", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        # Filled by `geocode-gazetteer`. `geocoded_at` is separate
        # because a point outside any incorporated place resolves to NO
        # place, which is an answer and must not be asked again.
        sa.Column("place_geoid", sa.String(7), nullable=True),
        sa.Column("place_name", sa.String(120), nullable=True),
        sa.Column("county_geoid", sa.String(5), nullable=True),
        sa.Column("geocoded_at", sa.DateTime(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        # One row per feature per state. Loads are idempotent on this.
        sa.UniqueConstraint(
            "state", "osm_type", "osm_id", name="uq_gazetteer_features_osm"
        ),
    )
    # The matcher's question: this state's features for this name.
    op.create_index(
        "ix_gazetteer_features_state_name",
        "gazetteer_features",
        ["state", "name_norm"],
    )
    # The backfill's question: what still owes a lookup.
    op.create_index(
        "ix_gazetteer_features_geocoded_at", "gazetteer_features", ["geocoded_at"]
    )

    op.create_table(
        "gazetteer_name_places",
        sa.Column("state", sa.String(2), primary_key=True),
        sa.Column("name_norm", sa.String(), primary_key=True),
        # How many distinct Census places this name occurs in, statewide.
        # 1 is usable evidence; anything more locates nothing.
        sa.Column("place_count", sa.Integer(), nullable=False),
        # Set only when place_count = 1, so a caller cannot read an
        # answer off an ambiguous name by accident.
        sa.Column("place_geoid", sa.String(7), nullable=True),
        sa.Column("place_name", sa.String(120), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_gazetteer_name_places_unique",
        "gazetteer_name_places",
        ["state", "place_count"],
    )


def downgrade() -> None:
    op.drop_index("ix_gazetteer_name_places_unique", table_name="gazetteer_name_places")
    op.drop_table("gazetteer_name_places")
    op.drop_index(
        "ix_gazetteer_features_geocoded_at", table_name="gazetteer_features"
    )
    op.drop_index(
        "ix_gazetteer_features_state_name", table_name="gazetteer_features"
    )
    op.drop_table("gazetteer_features")
