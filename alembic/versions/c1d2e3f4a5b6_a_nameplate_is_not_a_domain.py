"""A nameplate is not a domain.

`sources` carried one row for two things: a domain we crawl, and a newspaper
that exists. Where they coincide nothing complains; where they do not, every
count drawn off the table is wrong and the error is invisible.

`myleaderpaper.com` is one source row named "Leader". Behind it the Missouri
Press directory and the Blue Book name four Jefferson County papers. Across the
two directories 42 domains carry more than one nameplate, covering 97 papers,
and we hold 31 of those domains.

It runs the other way too. `lincolnnewsnow.com` now serves only a notice that
the Lincoln County Journal, Elsberry Democrat and Troy Free Press have moved to
their own sites. And `mainstreetnewsgroup.com` 404s, which a review read as four
dead newspapers -- two of which are publishing.

TWO TABLES, AND `sources` UNCHANGED. It keeps its meaning: a domain we crawl.

`nameplates` is one row per newspaper that exists, whether or not we can reach
it. That is the point of it: a replica-only paper, or one whose only web
presence is a Facebook page, is a newspaper we know about and cannot collect.
Today such a paper can only be absent, which reads the same as not knowing.

`nameplate_domains` says where a nameplate published and when. Several rows per
nameplate, several nameplates per domain. `path` carries the ones that are a
section of a larger site -- `higginsvilleadvance.com` redirects into
`lafayettemonews.com/category/higginsville-advance/`. `basis` records how the
claim was reached, the way `review/mopress.py` already argues a match, because a
link proven by a redirect is worth more than one inferred from two directories
agreeing, and a reviewer settling a conflict needs to see which they have.

SUCCESSION NEEDS NO THIRD TABLE. A nameplate leaving one domain for another is
its old row gaining a `to_date` and a new row opening; a split and a merge are
the same rows read in opposite directions.

Nothing is migrated. Both tables are created empty: what belongs in them is a
series of judgements about which spellings are one newspaper, and that is a
review, not a backfill.

Revision ID: c1d2e3f4a5b6
Revises: 4b7d8f2a6c53
"""

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "4b7d8f2a6c53"
branch_labels = None
depends_on = None

#: What a nameplate's web presence amounts to. `publishing` is the only one the
#: crawler can act on; the rest are why it cannot.
NAMEPLATE_STATUS = ("publishing", "print_only", "replica_only", "social_only", "closed", "unknown")

#: How a nameplate-to-domain claim was reached, strongest first. A redirect is
#: the site telling us; a masthead on the page is the site showing us; a
#: directory is somebody else's reading; `decided` is a person overruling all of
#: it, which is why it is last and why `decided_by` is required with it.
CLAIM_BASIS = ("redirect", "masthead_on_page", "directory", "decided")


def upgrade() -> None:
    op.create_table(
        "nameplates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        # Where the NEWSROOM is, which is not always the town it is filed
        # under: the Chariton Marquee is listed in Salem and sits in Salisbury.
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("county", sa.String(), nullable=True),
        sa.Column("fips", sa.String(length=5), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=False, server_default="MO"),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
        # Which reading of which directory carried it. A nameplate that stops
        # appearing has not necessarily closed, so the dates are evidence and
        # never a reason to delete the row.
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_seen", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('publishing','print_only','replica_only',"
            "'social_only','closed','unknown')",
            name="ck_nameplates_status",
        ),
    )
    op.create_index("ix_nameplates_fips", "nameplates", ["fips"])
    op.create_index("ix_nameplates_name", "nameplates", ["name"])

    op.create_table(
        "nameplate_domains",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("nameplate_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        # Null unless the nameplate is a SECTION of the domain rather than the
        # whole of it.
        sa.Column("path", sa.String(), nullable=True),
        sa.Column("from_date", sa.Date(), nullable=True),
        # Null means current. A closed row is how a split is recorded.
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["nameplate_id"], ["nameplates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "basis IN ('redirect','masthead_on_page','directory','decided')",
            name="ck_nameplate_domains_basis",
        ),
        # A person overruling the evidence has to sign it.
        sa.CheckConstraint(
            "basis <> 'decided' OR decided_by IS NOT NULL",
            name="ck_nameplate_domains_decided_by",
        ),
        sa.CheckConstraint(
            "to_date IS NULL OR from_date IS NULL OR to_date >= from_date",
            name="ck_nameplate_domains_dates",
        ),
    )
    op.create_index(
        "ix_nameplate_domains_nameplate", "nameplate_domains", ["nameplate_id"]
    )
    op.create_index("ix_nameplate_domains_source", "nameplate_domains", ["source_id"])
    # One nameplate may return to a domain it left, so the same pair is allowed
    # twice -- but not twice OPEN at once, which would be two current answers to
    # "where does this publish".
    op.create_index(
        "uq_nameplate_domain_current",
        "nameplate_domains",
        ["nameplate_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("to_date IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("nameplate_domains")
    op.drop_table("nameplates")
