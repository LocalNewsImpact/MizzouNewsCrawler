"""Record that a publication has a paywall, and what it costs.

Revision ID: p1q2r3s4t5u6
Revises: d86ffabfebe9
Create Date: 2026-08-28

Three columns, and deliberately not a fourth.

`requires_login` already exists and means something narrower than it
reads: the extractor performs a browser login for this publisher, which
is true of seven sources because seven are configured. Whether a
publication *has* a paywall is a fact about the publication and true of
many more, so it is its own column -- and the one somebody ticks on a
record long before anybody automates the login.

The subscription is an amount and the period it covers. One of each
rather than a monthly column and an annual one: two numbers about the
same subscription can disagree, and a yearly figure is arithmetic on a
monthly one.

No credentials here. The username and password for a paywalled publisher
live in Secret Manager under `auth_secret_name`, which is the convention
this table already follows and the reason `auth_config` carries the
comment that credentials are never stored in it. A password column would
be readable by every role holding SELECT on sources, which includes the
read-only analytics role and every CSV anybody exports.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p1q2r3s4t5u6"
down_revision: Union[str, None] = "d86ffabfebe9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add has_paywall, subscription cost and the login page."""
    # What somebody ticks on the record. Not null with a false default, so
    # "we have not looked" and "there is no paywall" are not the same
    # answer written the same way -- an unticked box is the second, and
    # the review queue is where the first gets settled.
    op.add_column(
        "sources",
        sa.Column(
            "has_paywall",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # What a subscription costs, and what that buys. Numeric rather than
    # float: money in a float is money that does not add up.
    op.add_column(
        "sources",
        sa.Column("subscription_cost", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("subscription_period", sa.String(16), nullable=True),
    )

    # Where a person signs in. `auth_config` holds one for the publishers
    # whose login is automated, but that column is the extractor's
    # parameters and is null on every publisher nobody has automated --
    # which is all of them but seven, and exactly the ones somebody
    # reading the record needs the link for.
    op.add_column("sources", sa.Column("login_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove them again."""
    op.drop_column("sources", "login_url")
    op.drop_column("sources", "subscription_period")
    op.drop_column("sources", "subscription_cost")
    op.drop_column("sources", "has_paywall")
