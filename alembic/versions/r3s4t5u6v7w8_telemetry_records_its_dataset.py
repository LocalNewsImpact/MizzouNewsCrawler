"""Every telemetry row records the dataset whose work produced it.

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-09-07

Eight tables record what the pipeline did, and not one of them records
which dataset it did it for. `jobs` comes closest: its `params` JSON
carries a `dataset_label` ("Mizzou Missouri State"), but a JSON field is
not a queryable column and the label is not the key anything else joins
on.

The absence is only visible once something asks a per-dataset question.
Answering "what has extraction done for Mizzou in the last hour" today
means joining `extraction_telemetry_v2` back to `candidate_links` on
`url` to reach a `dataset_id` -- a join across 315k rows, on a text
column, to recover a fact the writing job already knew. Every consumer
that wants the answer pays that cost and has to be trusted to get the
join right. Recording the fact at write time costs one column.

The column holds the dataset UUID, matching `candidate_links.dataset_id`
and `articles.dataset_id`. It does not hold the slug or the label. The
three names for a dataset already coexist -- the CLI accepts any of them,
`jobs.params` stores the label, the review UI shows the label, and the
database keys on the UUID -- and mixing them is not hypothetical: the
work queue compared `candidate_links.dataset_id` against a caller-supplied
string and would have matched nothing had the caller not resolved it
first. `resolve_dataset_id` turns any of the three into the UUID; it runs
once when a job starts, and everything the job writes carries the result.

Nullable, with no backfill in this migration. Historical rows have no
answer that this schema change can supply: some can be recovered by
joining to the corpus, some cannot be recovered at all, and a backfill
that guesses is worse than a null that admits it. New rows carry the
dataset from the job that writes them; the backfill of what is
recoverable is a separate, resumable job.
"""

import sqlalchemy as sa
from alembic import op

revision = "r3s4t5u6v7w8"
down_revision = "q2r3s4t5u6v7"
branch_labels = None
depends_on = None


# The tables a pipeline run writes to, each with the timestamp the Live
# Logs page orders by. The index is composite because every question the
# page asks is "the most recent activity for this dataset", and a plain
# index on dataset_id would still sort 315k extraction rows to answer it.
# `jobs` and `verification_jobs` are the run itself; the rest are the
# per-record milestones it emits.
TELEMETRY_TABLES = (
    ("jobs", "started_at"),
    ("verification_jobs", "created_at"),
    ("extraction_telemetry_v2", "created_at"),
    ("content_type_detection_telemetry", "created_at"),
    ("url_verifications", "created_at"),
    ("verification_telemetry", "created_at"),
    ("byline_cleaning_telemetry", "created_at"),
    ("article_enrichment", "enriched_at"),
)


def upgrade() -> None:
    for table, ordered_by in TELEMETRY_TABLES:
        op.add_column(table, sa.Column("dataset_id", sa.String(), nullable=True))
        op.create_index(
            f"ix_{table}_dataset_id",
            table,
            ["dataset_id", sa.text(f"{ordered_by} DESC")],
        )


def downgrade() -> None:
    for table, _ordered_by in TELEMETRY_TABLES:
        op.drop_index(f"ix_{table}_dataset_id", table_name=table)
        op.drop_column(table, "dataset_id")
