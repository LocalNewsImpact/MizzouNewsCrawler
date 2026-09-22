"""An owner has an ultimate owner.

`sources.owner` is the publisher's owner as somebody typed it, and the byline
review asks a question of it that it cannot answer on its own: is this reporter
filing for two unrelated publishers, or for two mastheads of one company?

Two different problems sat in the 126 cross-owner rows on Mizzou:

  the same owner, spelled differently   "Gray Media" / "Gray Television"
                                        "Lancaster Management Inc" / "Inc."
                                        "News-Press & Gazette Company" /
                                        "Newspress and Gazette Company"
  a real parent                         Boone County Journals is owned by
                                        Missourian Publishing; Missourian
                                        Publishing and the University of
                                        Missouri are ultimately one ownership

The first is spelling and `byline_review.owner_key` settles it without anybody
deciding. The second is a fact about companies that no string comparison can
reach, so it is recorded here.

NOT per dataset, unlike a byline decision: who owns a publisher is true of the
publisher, not of a corpus.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8c2f6d0b5e31"
down_revision: Union[str, Sequence[str], None] = "7b1e5c9a4d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "owner_groups",
        sa.Column("id", sa.String(), primary_key=True),
        # The owner as `byline_review.owner_key` reduces it, so every spelling
        # of one owner reaches the same row.
        sa.Column("owner_key", sa.String(), nullable=False, unique=True),
        # One of the owner strings, kept so a person reading the table sees a
        # name rather than "newspressgazette".
        sa.Column("owner_example", sa.Text(), nullable=True),
        # The ultimate owner's key: what the cross-owner test compares.
        sa.Column("group_key", sa.String(), nullable=False, index=True),
        sa.Column("group_name", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("owner_groups")
