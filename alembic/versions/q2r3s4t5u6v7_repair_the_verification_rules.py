"""Repair four verification rules that never compiled, and bound a fifth.

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-09-06

Four of the 46 active rules in `verification_patterns` carry regexes that
do not compile: `/(entertainment`, `obituar(y`, `/(us-world-news` and
`/(weather` are each missing a closing parenthesis.
`URLVerificationService._load_dynamic_patterns` logs the compile failure
and skips the rule, so they have never matched a URL. Nothing is broken
by them; they are dormant, and the corpus they would have filtered is
what made the measurements below possible.

Repairing a regex turns a rule on, and three of the four should stay off.
They filter on **subject matter**, and a topic rule skips the fetch --
the article row is never created, so nothing downstream can notice the
mistake. Measured against production:

- **weather** `/(weather|forecast|radar|stormtrack|doppler)`. No token is
  safe. Of 747 fetched `/weather/` articles, 392 are ordinary stories:
  storm damage, closures, flooding. Even `/forecast` keeps 173 of 257,
  and the byline cannot separate them because meteorologists sign their
  forecasts (251 of 257 are bylined). Telling a forecast from a story
  about the weather needs a model; until then the pipeline over-allows.

- **obituary** `obituar(y|ies)`. Of 754 obituary-claimed articles a
  reviewer has ruled on, 147 were restored as ordinary stories -- a
  person's death reported as news, which is local journalism. A URL rule
  would skip the fetch, so those would never reach the queue that
  rescued them.

- **entertainment** `/(entertainment|movies|tv|streaming|celebrities)`.
  No status exists for entertainment, so the rule falls through to
  `not_article`, which is false about the URL: an entertainment story is
  a story. `tv` is unbounded and matches any path segment beginning
  "tv". Deleted rather than repaired.

The fourth is activated, narrowed to the one token that earns it.
`us_world_news` was `/(us-world-news|national-news|world|politics|washington)`,
and per token, among fetched articles:

    /world/        2,740 fetched, 2,739 wire   100.0%
    /world (loose)   109 fetched,    75 wire    68.8%
    /politics        833 fetched,   549 wire    65.9%
    /national-news   197 fetched,    87 wire    44.2%
    /washington       66 fetched,    22 wire    33.3%

Read rather than counted, because `wire` says whether the wire detector
fired, not whether a story is local:

- **/politics** is Missouri congressional maps, Columbia school board
  candidates, Kansas City-area election results, a Kansas county paying
  $3M over a small-town newspaper raid. State and local political
  coverage, which is the corpus this project exists to measure. 281 rows.
- **/washington** is Washington, Missouri: the city council's sales tax
  renewals, cross country qualifying for state, a motorcyclist who struck
  a deer -- plus Washington University in St. Louis. 41 rows, and two of
  eight sampled were about the other Washington.
- **/national-news** is the opposite: KOAM republishing national feed
  copy -- Florida flooding, California storms -- which is national
  content the wire detector missed rather than local journalism. Left out
  anyway: 197 rows is little to gain, and its precision is unproven
  because the status it would be measured against is the one that failed.
- **/world loose** matches Worlds of Fun, "World class care at Northeast
  Missouri", a world record broken by a Nixa 10-year-old, and a great
  deal of Kansas City World Cup coverage -- KC is a 2026 host city, so
  this is a growing category, not a fixed one.

So the rule as written would have discarded roughly 322 local articles,
a third of everything under `/politics/`, and it would discard more each
month as World Cup coverage builds. Bounded to `/world/` it is right
2,739 times out of 2,740 -- the exception, a story about a campaign
against a World Cup jail, was already `out_of_scope` -- and it records
`wire`, which is what those pages are, rather than claiming they are not
articles.

One thing to watch: `/world/` is safe because no local section is called
that. If a publisher opens a `/world/` section for World Cup coverage
this changes, and the discovery review queue is where it would show up.

And one rule that is not broken and is over-matching: **feed** is
`/feed`, unbounded, so it rejects `/feeding-the-hungry`,
`/feed-seed-grain` and `/feeders-pet-and-supply`. Twenty links, each a
local story treated as an RSS feed. Bounded here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q2r3s4t5u6v7"
down_revision: Union[str, None] = "p1q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The rules themselves are in src/services/verification_rules.py, so a
# test can read them: `tests/alembic/__init__.py` shadows the alembic
# package when the whole suite runs, and a migration module imported from
# a test then fails on `from alembic import op`.
from src.services.verification_rules import (  # noqa: E402
    DELETED,
    ORIGINALS,
    REPAIRS,
)


def upgrade() -> None:
    conn = op.get_bind()
    for pattern_type, regex, active in REPAIRS:
        if active is None:
            conn.execute(
                sa.text(
                    "UPDATE verification_patterns SET pattern_regex = :rx, "
                    "updated_at = now() WHERE pattern_type = :t"
                ),
                {"rx": regex, "t": pattern_type},
            )
        else:
            conn.execute(
                sa.text(
                    "UPDATE verification_patterns SET pattern_regex = :rx, "
                    "is_active = :a, updated_at = now() WHERE pattern_type = :t"
                ),
                {"rx": regex, "a": active, "t": pattern_type},
            )
    # No status exists for entertainment, so the rule can only say
    # `not_article`, which is not true of an entertainment story.
    for pattern_type in DELETED:
        conn.execute(
            sa.text("DELETE FROM verification_patterns WHERE pattern_type = :t"),
            {"t": pattern_type},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for pattern_type, regex, active in ORIGINALS:
        if active is None:
            conn.execute(
                sa.text(
                    "UPDATE verification_patterns SET pattern_regex = :rx, "
                    "updated_at = now() WHERE pattern_type = :t"
                ),
                {"rx": regex, "t": pattern_type},
            )
        else:
            conn.execute(
                sa.text(
                    "UPDATE verification_patterns SET pattern_regex = :rx, "
                    "is_active = :a, updated_at = now() WHERE pattern_type = :t"
                ),
                {"rx": regex, "a": active, "t": pattern_type},
            )
    # The deleted rule is not recreated: its id is gone, and a rule that
    # can only write a false status is not something to restore.
