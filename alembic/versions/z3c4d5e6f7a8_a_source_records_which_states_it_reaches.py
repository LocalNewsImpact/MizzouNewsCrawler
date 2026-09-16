"""A source records which states it reaches.

Entity matching must be contained to a source's own geography: a
Washington publisher reading the Missouri gazetteer, and eighteen others,
is 99% wasted work and a standing invitation to match the wrong
Springfield. `docs/STATEWIDE_GAZETTEER.md` §9.

The scope cannot be the dataset's state. A dataset is a coverage list,
not a location list -- the Mizzou dataset legitimately holds KMBZ
(Mission, KS) and Dos Mundos (Overland Park, KS), because the Kansas City
metro spans the line -- and 896 of 901 Vermont sources arrive with no
state at all, so guessing one is forbidden (`resolve_source_state`, and
tests/test_gazetteer_state_resolution.py).

So it is the source's own state, plus any state whose border falls within
its coverage radius. Measured rather than modelled: each source's
existing 20-mile OSM build is joined to the state-keyed features, and a
state that contributed a real share of those POIs is in reach. Of 246
sources, 198 reach exactly one state and 48 reach two.

THE THRESHOLD IS 10%, and the distribution chose it. Secondary states
divide cleanly: 23 contribute 20% or more of a source's POIs -- Dos
Mundos is 45% Kansas, Fox4KC 40% -- and 7 more are 10-20%. Below that
there is one state in the 5-10% band and 17 under 5%, several at a
single POI. Opening Kansas's whole 17,997-feature gazetteer to a
Missouri paper on the strength of one spillover POI is the error this
table exists to prevent.

Stored rather than recomputed so the scope is auditable: a question about
why an article matched a place in another state has an answer with a
date on it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "z2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_gazetteer_scope",
        sa.Column("source_id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(2), primary_key=True),
        # The source's own state, as opposed to one it merely reaches.
        sa.Column("is_home", sa.Boolean(), nullable=False, server_default=sa.false()),
        # What the decision was made on, kept so it can be re-read.
        sa.Column("pois", sa.Integer(), nullable=True),
        sa.Column("share", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_source_gazetteer_scope_source", "source_gazetteer_scope", ["source_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_gazetteer_scope_source", table_name="source_gazetteer_scope"
    )
    op.drop_table("source_gazetteer_scope")
