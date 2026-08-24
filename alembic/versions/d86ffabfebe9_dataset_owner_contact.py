"""Record who owns a dataset, so a published visual can say so.

A visual built on this corpus is embedded in somebody else's article, and
the page carries no attribution beyond free text somebody typed into the
chart's own config -- "LNIC research corpus", written by hand, meaning
nothing to a reader who wants to check it or ask about it.

Attribution has to come from the dataset rather than the chart, because
the dataset is what the claim is about. `datasets` has no field for it:
`name` and `description` describe the data, and nothing names a person.

Two columns, both nullable. Nullable because they are unknown for every
row that exists today and inventing a steward for a dataset is worse than
admitting there is not one recorded -- a published contact that reaches
nobody is a worse answer than no contact.

Deliberately not derived from the console's grants. A grant says who may
read a dataset, which is access control; publishing it as attribution
would put staff account addresses into a JSON feed anybody can fetch.
These are the address a dataset chooses to publish, which is a different
thing that happens to look similar.

Revision ID: d86ffabfebe9
Revises: 28a393d67304

The identifier is a digest of what the migration does rather than a hand
picked string, after an invented one collided with a merge revision and
alembic answered with two heads where there is one chain.
"""

import sqlalchemy as sa
from alembic import op

revision = "d86ffabfebe9"
down_revision = "28a393d67304"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("owner_name", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("owner_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("datasets", "owner_email")
    op.drop_column("datasets", "owner_name")
