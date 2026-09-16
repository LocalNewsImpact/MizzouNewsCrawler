"""An entity records which STATEWIDE feature it matched.

`article_entities.matched_gazetteer_id` carries a foreign key to
`gazetteer`, the per-source table. Pointing it at `gazetteer_features`
fails:

    insert or update on table "article_entities" violates foreign key
    constraint "article_entities_matched_gazetteer_id_fkey"

which is the constraint doing its job -- it stopped a rematch of 2.9M
rows writing ids that resolve to nothing. (The constraint was there all
along; an `information_schema` query run against this table on
2026-09-16 returned no rows and was believed. `pg_constraint` is the
one to ask.)

A NEW COLUMN RATHER THAN A DROPPED CONSTRAINT. The per-source table and
its matches still exist and are still read -- `gazetteer_places` narrows
its geocoding to features some article matched -- so the old column keeps
its meaning and its integrity. The new one says which statewide feature
an entity matched, under the rules in docs/STATEWIDE_GAZETTEER.md §8:
exact, normalised, and scoped to the source's own states.

Neither column is what the grounding gate reads. That asks
`gazetteer_name_places` by `entity_norm` and state, because a name in
more than one Census place locates nothing however well it matched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "z3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "article_entities",
        sa.Column("matched_feature_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "article_entities_matched_feature_id_fkey",
        "article_entities",
        "gazetteer_features",
        ["matched_feature_id"],
        ["id"],
    )
    op.create_index(
        "ix_article_entities_matched_feature_id",
        "article_entities",
        ["matched_feature_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_article_entities_matched_feature_id", table_name="article_entities"
    )
    op.drop_constraint(
        "article_entities_matched_feature_id_fkey",
        "article_entities",
        type_="foreignkey",
    )
    op.drop_column("article_entities", "matched_feature_id")
