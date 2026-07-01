"""add authenticated extraction columns to sources

Adds per-publisher login configuration so the extractor can authenticate to
subscriber/paywalled sites before fetching articles:

- requires_login: whether this publisher needs a subscriber login
- auth_type: login mechanism ('auth0', 'form')
- auth_secret_name: name of the secret holding the credentials
- auth_config: non-secret login parameters (JSON)

Revision ID: f7a2b9c1d3e4
Revises: cea12b602254
Create Date: 2026-06-30 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f7a2b9c1d3e4"
down_revision: Union[str, Sequence[str], None] = "cea12b602254"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sources",
        sa.Column(
            "requires_login",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "sources",
        sa.Column("auth_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("auth_secret_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("auth_config", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_sources_requires_login",
        "sources",
        ["requires_login"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sources_requires_login", table_name="sources")
    op.drop_column("sources", "auth_config")
    op.drop_column("sources", "auth_secret_name")
    op.drop_column("sources", "auth_type")
    op.drop_column("sources", "requires_login")
