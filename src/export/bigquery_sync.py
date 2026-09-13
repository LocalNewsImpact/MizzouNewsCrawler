"""What BigQuery is allowed to hold, defined once and checkable.

THE DRIFT THIS EXISTS TO STOP
-----------------------------
`EXPORTABLE_STATUSES` sat in `enrichment/repository.py` referenced by
nothing. The filter that actually decides what reaches BigQuery lives in
eleven scheduled queries in the BigQuery Data Transfer service, each one
carrying its own copy of the status list as a string. A constant in the
repository and the real rule in a console are two copies of one fact, and
nothing failed when they disagreed.

They had already disagreed. Measured 2026-09-13:

    articles, article_enrichment, article_labels, article_entities,
    article_geoids          filter on status
    article_places, article_people, article_organizations
                            NO filter -- every row, whatever the article

So places, people and organizations were exported for articles that were
not. 348 rows on the day it was found: 138 places, 115 organizations, 95
people, attributed to articles absent from the corpus. `article_geoids`,
the one derived table that filters, carried zero -- which is the proof
that the filter is what matters and its absence is what leaks.

WHY A CHECKER AND NOT A GENERATOR
---------------------------------
The eleven queries are not one shape. `articles` wraps its select in a
ROW_NUMBER dedup; the derived tables use a subquery on article_id; three
sync whole tables with no filter because they are not article-scoped at
all. Generating that text from here would mean encoding every shape, and
the generator would then be a third copy to drift.

So this defines the RULE -- which tables are article-scoped, and the
fragment their query must contain -- and audits the deployed queries
against it. The shapes stay where they are; the rule lives in one place
and a test can fail when reality stops matching it.
"""

from __future__ import annotations

from src.enrichment.repository import EXPORTABLE_STATUSES

#: Tables whose rows belong to an article, and which must therefore carry
#: the article's own export decision. A row here for an article that is not
#: exported is a row nothing can join to and nothing should count.
ARTICLE_SCOPED_TABLES: tuple[str, ...] = (
    "articles",
    "article_enrichment",
    "article_labels",
    "article_entities",
    "article_geoids",
    "article_places",
    "article_people",
    "article_organizations",
)

#: Tables that are not article-scoped and are synced whole. Listed so that
#: "no filter" is a recorded decision rather than an omission: a new table
#: is in one list or the other, and `audit` refuses one that is in neither.
UNSCOPED_TABLES: tuple[str, ...] = (
    "candidate_links",
    "sources",
    "syndicators",
    "dataset_funnel",
    "cin_labels",
    "entities",
    "march_sheet_ids",
    "openrouter_traces",
    "sheet_export_log",
)


def status_list_sql() -> str:
    """The status list as it appears inside a scheduled query."""
    return ",".join(f"'{status}'" for status in EXPORTABLE_STATUSES)


def required_fragment(table: str) -> str | None:
    """The SQL an article-scoped table's sync must contain, or None.

    Matched on the status list rather than the whole clause, because the
    surrounding shape legitimately differs per table -- a dedup wrapper, an
    alias, a subquery on article_id -- and pinning the shape here would
    make this a copy of the queries instead of a rule about them.
    """
    if table not in ARTICLE_SCOPED_TABLES:
        return None
    return f"status IN ({status_list_sql()})"


def audit(deployed: dict[str, str], *, require_complete: bool = False) -> list[str]:
    """What is wrong with the deployed sync queries. Empty means agreement.

    `deployed` maps destination table to the scheduled query's SQL.

    Two questions, deliberately separable. Whether the queries GIVEN are
    correct is always asked. Whether every article-scoped table HAS a sync
    is asked only under `require_complete`, because the caller that knows
    it holds the whole warehouse is the live check, and a partial check
    would otherwise report every table it did not ask about.
    """
    problems: list[str] = []
    known = set(ARTICLE_SCOPED_TABLES) | set(UNSCOPED_TABLES)
    for table, query in sorted(deployed.items()):
        if table not in known:
            problems.append(
                f"{table}: not declared article-scoped or unscoped. Add it to "
                "one of the two lists so its export decision is recorded."
            )
            continue
        fragment = required_fragment(table)
        if fragment is None:
            continue
        normalised = " ".join(query.split())
        if fragment not in normalised:
            problems.append(
                f"{table}: article-scoped but its sync does not filter on "
                f"{fragment!r}. Rows will be exported for articles that are "
                "not."
            )
    if require_complete:
        for table in sorted(set(ARTICLE_SCOPED_TABLES) - set(deployed)):
            problems.append(f"{table}: article-scoped and has no sync at all.")
    return problems
