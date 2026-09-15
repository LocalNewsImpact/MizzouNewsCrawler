"""A point of interest records which Census place it sits in.

The enrichment model infers geography from institutions a story names --
"a senior at Mexico High School" locates a story in Mexico, "Southeast
Missouri State gymnastics" locates one in Cape Girardeau. That induction
is wanted: it is reasoning from evidence in the article, and it is not
the fabrication the grounding gate exists to stop.

The gate could not tell the two apart. It asked only whether the place
NAME appeared in the text, so it deleted the induction along with the
fabrication -- 70 of the 803 points the first backfill cleared had an
institution in the article sitting in the very city that was removed.

The verifier for that is the gazetteer, which already knows where each
institution is. What it does not know is which Census place that is:
`tags->>'addr:city'` is an OSM convenience field, present on 223,771 of
558,540 rows and absent on the rest, and it carries a postal city name
rather than a GEOID -- "Saint Louis" where the Census says "St. Louis",
and no way to join to a county, a tract or the ACS.

Every row has lat/lon. This records what those coordinates resolve to,
once, so the gate can ask the question without a network call and
without depending on whether an OSM contributor filled in an address.

`geocoded_at` rather than a nullable-means-pending convention: a POI in
open water or outside any incorporated place resolves to NO place, which
is a real answer and has to be distinguishable from one not yet asked.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "y0z1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gazetteer", sa.Column("place_geoid", sa.String(7), nullable=True))
    op.add_column("gazetteer", sa.Column("place_name", sa.String(120), nullable=True))
    op.add_column("gazetteer", sa.Column("county_geoid", sa.String(5), nullable=True))
    op.add_column(
        "gazetteer", sa.Column("geocoded_at", sa.DateTime(), nullable=True)
    )
    # The gate reads this by place, for the entities of one article.
    op.create_index("ix_gazetteer_place_geoid", "gazetteer", ["place_geoid"])
    # And the backfill selects what still owes a lookup.
    op.create_index("ix_gazetteer_geocoded_at", "gazetteer", ["geocoded_at"])


def downgrade() -> None:
    op.drop_index("ix_gazetteer_geocoded_at", table_name="gazetteer")
    op.drop_index("ix_gazetteer_place_geoid", table_name="gazetteer")
    op.drop_column("gazetteer", "geocoded_at")
    op.drop_column("gazetteer", "county_geoid")
    op.drop_column("gazetteer", "place_name")
    op.drop_column("gazetteer", "place_geoid")
