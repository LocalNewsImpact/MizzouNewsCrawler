"""Every call to somebody else's service leaves a row.

We could not answer "how many MediaCloud calls do we make a day". The
only evidence was `articles.wire_check_attempted_at` -- one column per
ARTICLE, overwritten on every retry -- so retries were invisible, a call
that failed and succeeded looked like one call, and the number was a
lower bound nobody could put a margin on.

WHAT THIS IS FOR, and it is not cost. MediaCloud is free and the
question is whether we are being a good neighbour and whether they are
up:

  politeness   the rate we actually achieved, against the rate we
               configured. `waited_ms` records what the limiter held
               back, so a run that never waits is a limiter that is not
               binding and a rate nobody is enforcing.
  outages      errors arriving together. All 15 recorded MediaCloud
               failures in the corpus fall in two windows -- one evening
               in December, one day in March -- which is the shape of
               their outage, not of our articles.
  blocking     429 and 403, which need a different response from a
               timeout and until now were indistinguishable from one.

That last point is why `status_code` and `error_class` are separate
columns rather than one string. The corpus holds 14 failures recorded as
`error:JSONDecodeError` -- the client asked for JSON and got something
else, which is what a gateway error page, a rate-limit page and an empty
body all look like from inside `.json()`. One string could not tell
them apart and neither could we.

A ROW PER CALL, not per subject. That is the whole point: the subject is
recorded alongside (`subject_type`, `subject_id`) so a failure can be
traced back to the article it was for, but the grain is the call, and
retries are separate rows.

Deliberately not on the article: `articles` is the corpus, and a corpus
table that grows a column every time we want to watch something
operational ends up unreadable. This is telemetry and it lives with the
telemetry.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y0z1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "x9y0z1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_api_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Whose service. One row per call to anything we do not run.
        sa.Column("service", sa.Text(), nullable=False),
        # Which call on it, so a slow endpoint is separable from a slow
        # service.
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # How long the call took, and how long we held ourselves back
        # before making it. The second is the politeness evidence.
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("waited_ms", sa.Integer(), nullable=True),
        # 'ok', 'api_error' (they answered with a status), or 'error'
        # (the call did not complete). Three classes, because the
        # response to each is different.
        sa.Column("outcome", sa.Text(), nullable=False),
        # Separate columns on purpose: `error:JSONDecodeError` as one
        # string cannot distinguish a rate limit from an outage.
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error_class", sa.Text(), nullable=True),
        # Which attempt this was, so a retried call is two rows that can
        # still be read as one attempt sequence.
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        # What the call was for. Nullable: not every call has a subject.
        sa.Column("subject_type", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("dataset_id", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    # The rate question: calls per service per day.
    op.create_index(
        "ix_external_api_calls_rate",
        "external_api_calls",
        ["service", "called_at"],
    )
    # The outage and blocking questions, which are only ever asked about
    # the failures -- a partial index so the common case costs nothing.
    op.create_index(
        "ix_external_api_calls_failures",
        "external_api_calls",
        ["service", "called_at"],
        postgresql_where=sa.text("outcome <> 'ok'"),
    )
    # Tracing a failure back to what it was for.
    op.create_index(
        "ix_external_api_calls_subject",
        "external_api_calls",
        ["subject_type", "subject_id"],
        postgresql_where=sa.text("subject_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_external_api_calls_subject", table_name="external_api_calls")
    op.drop_index("ix_external_api_calls_failures", table_name="external_api_calls")
    op.drop_index("ix_external_api_calls_rate", table_name="external_api_calls")
    op.drop_table("external_api_calls")
