"""The corpus stamp reads four indexes.

Datadesk keys every cached answer on one stamp, `corpus_version`, and
re-derives it every five minutes. Four of its parts are a newest-row
question:

    SELECT max(created_at), max(entities_extracted_at) FROM articles
    SELECT max(enriched_at) FROM article_enrichment
    SELECT max(added_at)    FROM article_places_manual

Postgres answers `max(col)` by reading one row off the end of a btree on
`col`, and none of the four columns has one:

- `articles.created_at` is only the second column of
  `ix_articles_publish_date_created`, which a max cannot read from the end.
- `articles.entities_extracted_at` has `idx_articles_pending_entities`,
  which indexes `candidate_link_id` over the rows where it IS NULL -- the
  opposite set to the one a max reads.
- `article_enrichment.enriched_at` and `article_places_manual.added_at`
  have nothing.

So each rebuild is a sequential scan of `articles` (the two maxima share
one) and one of `article_enrichment`. Datadesk #428 stopped every request
from running the rebuild at once when the stamp expired; it did not make
the rebuild cheap, and it is the only query in datadesk that runs on a
clock rather than on a change. Datadesk's review of 2026-09-30, item 6,
asked for the first two; the other two are the same question one table
over.

PRODUCTION FIRST, CONCURRENTLY. As with `u6v7w8x9y0z1`, the indexes are
built in production by hand with CREATE INDEX CONCURRENTLY before this
merges, and this migration is the same indexes for a database built from
scratch: plain, because Alembic runs inside a transaction and a fresh
database has no concurrent writer, and IF NOT EXISTS, so it is a no-op
where they already stand.

Revision ID: 687d44c97977
Revises: f4a5b6c7d8e9
Create Date: 2026-09-30 18:00:00.000000
"""

from alembic import op

revision = "687d44c97977"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None

#: (index, table, column). One plain ascending btree each: a max reads a
#: btree backward, so the direction is immaterial.
INDEXES = (
    ("ix_articles_created_at", "articles", "created_at"),
    ("ix_articles_entities_extracted_at", "articles", "entities_extracted_at"),
    ("ix_article_enrichment_enriched_at", "article_enrichment", "enriched_at"),
    ("ix_article_places_manual_added_at", "article_places_manual", "added_at"),
)


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})")


def downgrade() -> None:
    for name, _table, _column in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
