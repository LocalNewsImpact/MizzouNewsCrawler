"""`extraction_method` was stored with its quotes, so nothing matched it.

The column was created with `server_default="'http'"`. In SQLAlchemy that
string is passed through verbatim, so the default became the six
characters `'http'` -- quotes included -- rather than the four somebody
meant. Every row inserted since carried them.

Nothing noticed, because nothing compares the value except one place, and
that place is the one thing that needed to:

    UPDATE sources SET extraction_method = :method, selenium_only = ...
    WHERE host = :host
    AND (extraction_method = 'http' OR extraction_method IS NULL)

That is the escalation in `src/crawler/__init__.py`: when a fetch meets
bot protection or a JavaScript wall, it switches the publisher to
Selenium so the next attempt renders the page. Its WHERE clause matched
32 of 1,148 sources. The other 1,096 held `'http'` and were invisible to
it, so it had fired four times in the system's life.

What that cost, found by reading the captures rather than the code: 45
articles across five publishers whose body was the static HTML shell of a
JavaScript-rendered page -- 5,308 bytes whose only text is a registration
form's country dropdown, byte-identical across emissourian.com,
newspressnow.com, columbiamissourian.com and stltoday.com. Every one had
been fetched with `http_fetch` and never with Selenium, because the
switch that would have changed that could not see them. They ended as
`paused` articles with no recorded reason, and one as `not_article` --
a verdict reached on a body that was never the article.

Two changes, and the second is the one that lasts:

  - the rows are unquoted, so the escalation can see them
  - the default is corrected, so new publishers do not arrive invisible

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "w8x9y0z1a2b3"
down_revision: Union[str, Sequence[str], None] = "v7w8x9y0z1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The default first: a row inserted between these two statements
    # would otherwise arrive quoted and be missed by the second.
    op.alter_column(
        "sources",
        "extraction_method",
        existing_type=sa.String(32),
        existing_nullable=False,
        server_default="http",
    )
    # `btrim(value, '''')` strips leading and trailing single quotes and
    # leaves everything else alone, so a value that was never quoted is
    # untouched and re-running this is free.
    op.execute(
        """
        UPDATE sources
        SET extraction_method = btrim(extraction_method, '''')
        WHERE extraction_method LIKE '''%'''
        """
    )


def downgrade() -> None:
    # Deliberately not restoring the quotes. They were a typo that made a
    # safety mechanism inert for the life of the column, and putting them
    # back would do it again.
    op.alter_column(
        "sources",
        "extraction_method",
        existing_type=sa.String(32),
        existing_nullable=False,
        server_default="http",
    )
