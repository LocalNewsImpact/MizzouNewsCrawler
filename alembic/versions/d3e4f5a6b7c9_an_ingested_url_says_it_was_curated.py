"""An ingested URL says it was curated.

A URL uploaded as part of a chosen set has already been judged. Selection IS
the filter, and it ran before the crawler ever saw the link, so URL
verification and the MediaCloud wire check add nothing -- the point of the
upload is to collect and export those specific URLs.

The flag belongs on the URL RECORD, not the dataset: a dataset holds both
kinds. WSU-Washington-State has 2,681 ingested links and 6 crawled ones;
Mizzou-Missouri-State has ~234,800 crawled and ~1,178 ingested. A
dataset-level bypass would be wrong in both directions.

`candidate_links.discovered_by` already carries the provenance -- a
`discovery.` prefix means the crawler found it, anything else means a person
handed it over -- so this backfills from that. It is a POSITIVE marker rather
than an inferred absence, which is the constraint
`docs/CURATED_DATASETS_NEED_A_BYPASS.md` sets: a row must say why a check did
not run, and `wire_check_status` being NULL-able would have made the WSU import
a silent success and a silent enrichment failure.
"""

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c9"
down_revision = "c2d3e4f5a6b8"
branch_labels = None
depends_on = None

#: What `discovered_by` looks like when the crawler found the link itself.
DISCOVERY_PREFIX = "discovery."


def upgrade() -> None:
    op.add_column(
        "candidate_links",
        sa.Column(
            "is_curated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Backfill from provenance. `discovered_by` is NULL on a few very old rows;
    # those stay false, because an unknown provenance is not a curation claim.
    op.execute(f"""
        UPDATE candidate_links
           SET is_curated = true
         WHERE discovered_by IS NOT NULL
           AND discovered_by NOT LIKE '{DISCOVERY_PREFIX}%'
        """)
    # The wire check and URL verification both filter on it, and the WSU
    # dataset alone puts 2,681 rows behind that filter.
    op.create_index(
        "ix_candidate_links_is_curated",
        "candidate_links",
        ["is_curated"],
        postgresql_where=sa.text("is_curated"),
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_links_is_curated", table_name="candidate_links")
    op.drop_column("candidate_links", "is_curated")
