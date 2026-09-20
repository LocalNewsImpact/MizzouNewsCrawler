"""A login is witnessed at entry.

Three columns on `sources` for credentialed publishers. None changes what the
crawler fetches today; they are where the entry-time validation writes and
where drift becomes visible.

`login_path` -- 'page', 'modal' or 'sso', declared by the person entering the
credentials with the site open. The engine can detect it (is there a password
field yet?), but a person who is looking knows, and a stored answer is what
the runtime reproduces rather than rediscovers.

`auth_last_failed_at`, `auth_failure_reason` -- set by the extractor when a
run refuses a host because its login did not confirm; cleared by a witnessed
success. www.yakimaherald.com was verified live in July 2026, its login
trigger stopped being found when the markup changed, and for two months every
run reported "did not confirm" and fetched anonymously. Nothing was recorded
that a person would see. With these set, /stats names the host as needing
re-validation instead of counting its links as claimable work.

See docs/A_LOGIN_IS_WITNESSED_AT_ENTRY.md.
"""

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d0"
down_revision = "d3e4f5a6b7c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("login_path", sa.String(16), nullable=True))
    op.add_column(
        "sources", sa.Column("auth_last_failed_at", sa.DateTime(), nullable=True)
    )
    op.add_column("sources", sa.Column("auth_failure_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "auth_failure_reason")
    op.drop_column("sources", "auth_last_failed_at")
    op.drop_column("sources", "login_path")
