"""A rework row stops asking.

Four links have sat open in `pipeline_rework` since 2026-09-14 -- three on
newspressnow.com, one on fultonsun.com. Selenium fails on those hosts every
time; the extraction log reached failure #136. The work queue serves them,
every one fails, the domain enters cooldown, the queue then has nothing
servable, and the extract step waits 30 seconds and asks again. It did that for
two hours until the pod deadline killed it, and the housekeeping workflow
failed. Both of the last two runs died that way, and neither reached the
classify or enrich stages behind it.

Nothing was wrong with the scoping. `--rework` is passed to the queue and
`REWORK_ONLY` restricts what it serves. The set was correct, bounded, and
unfetchable -- and nothing said how many times to find that out.

`attempts` is that number. A row is counted when a run takes it and closed at
`rework.MAX_ATTEMPTS` with outcome `failed_max_attempts`, which is the word
enrichment's orchestrator already uses for the same judgement. The bound has to
live on the row rather than in the run, because the run that gives up is not
the run that tried before it: each one starts over, and three runs of infinite
patience are indistinguishable from one.

Counted at the START of a step, matching how `settle` already works here, so a
row closed by a run's own attempt reads as closed on the next one.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "z5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipeline_rework",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("pipeline_rework", "attempts")
