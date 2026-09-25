"""A licensee is not always the operator.

`sources.owner` holds who owns a publication, and for a newspaper that is also
who runs it. For television it often is not.

KOLR in Springfield and KODE in Joplin are licensed to Mission Broadcasting
Inc and operated by Nexstar under shared-services agreements. The structure
exists because the combination would otherwise exceed the FCC's ownership
caps: if Nexstar owned them it would be over the limit. So Mission is the
correct answer to "who owns this licence" and Nexstar is the correct answer to
"who runs this newsroom", and the column could only hold one of them.

WHAT THAT COST. `cross_owner` fires when a byline appears under owners that
are not one company. It was firing on six Mizzou bylines that cross
Mission and Nexstar stations -- correctly, on a real ownership boundary, and
uselessly, because the reviewer's question is whether one person wrote them
and the answer is yes: it is one newsroom under two licences.

The fix that suggested itself was an `owner_groups` row collapsing Mission
into Nexstar. That would have written something FALSE into a column named
`owner`, and asserting common ownership of stations held apart for regulatory
reasons is not a small error.

So the licensee stays in `owner` and the operator gets its own column. The
signal groups on `coalesce(operator, owner)`: two stations under one operator
are one newsroom whoever holds the licences.

NULL FOR ALMOST EVERYTHING. A newspaper's owner runs it. Five Missouri
television stations look like candidates and only two are confirmed here --
Mission/Nexstar. A wrong operator silently suppresses a real cross-owner
question, which is worse than the noise it would remove, so unverified ones
are left null.

NO DATES. An operating agreement changes like an ownership does, and this
column can only say "now" -- the same limit `owner` has. A change history for
`sources`, with dates and reasons, is the answer to that and is a larger thing
than one column.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("operator", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "operator")
