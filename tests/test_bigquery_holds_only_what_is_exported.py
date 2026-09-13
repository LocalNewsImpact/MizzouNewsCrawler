"""The export filter is one rule, and drift from it fails here.

`EXPORTABLE_STATUSES` sat in the repository referenced by nothing while the
real filter lived in eleven BigQuery scheduled queries, each carrying its
own copy of the status list. Nothing failed when they disagreed -- and they
had: `article_places`, `article_people` and `article_organizations` synced
every row regardless of the article's status, so 348 rows were exported for
articles that were not (138 places, 115 organizations, 95 people).
`article_geoids`, the one derived table that filters, carried zero.
"""

from __future__ import annotations

import pytest

from src.enrichment.repository import EXPORTABLE_STATUSES
from src.export.bigquery_sync import (
    ARTICLE_SCOPED_TABLES,
    UNSCOPED_TABLES,
    audit,
    required_fragment,
    status_list_sql,
)

#: The shape the one correct derived sync actually deploys, verbatim from
#: `Sync Article Geoids from Cloud SQL` on 2026-09-13. The checker has to
#: accept this or it is not describing reality.
GEOIDS_DEPLOYED = (
    'SELECT * FROM EXTERNAL_QUERY("mizzou-news-crawler.us.cloudsql_connection", '
    '"SELECT g.* FROM article_geoids g WHERE g.article_id IN (SELECT id FROM '
    "articles WHERE status IN ('enriched','enrichment_skipped'));\");"
)

#: And the shape that leaked, verbatim from `Sync Article Places`.
PLACES_DEPLOYED = (
    'SELECT * FROM EXTERNAL_QUERY("mizzou-news-crawler.us.cloudsql_connection", '
    '"SELECT * FROM article_places;");'
)

#: `articles` wraps its select in a dedup. Kept here because it is why this
#: module checks for a fragment rather than generating the query: the shapes
#: differ per table and a generator would be a third copy to drift.
ARTICLES_DEPLOYED = (
    "WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY id ORDER BY "
    'extracted_at DESC) as rn FROM EXTERNAL_QUERY("mizzou-news-crawler.us.'
    'cloudsql_connection", "SELECT * FROM articles WHERE status IN '
    "('enriched','enrichment_skipped');\")) SELECT * EXCEPT(rn) FROM ranked "
    "WHERE rn = 1;"
)


class TestTheRuleIsOneDefinition:
    def test_the_status_list_comes_from_the_constant(self):
        """Not retyped. The whole failure was a second copy of this list."""
        assert status_list_sql() == ",".join(f"'{s}'" for s in EXPORTABLE_STATUSES)
        for status in EXPORTABLE_STATUSES:
            assert f"'{status}'" in status_list_sql()

    def test_adding_a_status_changes_what_is_required(self):
        """So the constant is load-bearing rather than decorative."""
        assert "enriched" in required_fragment("articles")

    def test_every_table_is_declared_in_exactly_one_list(self):
        assert not set(ARTICLE_SCOPED_TABLES) & set(UNSCOPED_TABLES)

    def test_an_unscoped_table_requires_nothing(self):
        assert required_fragment("candidate_links") is None
        assert required_fragment("dataset_funnel") is None


class TestTheAuditMatchesReality:
    def test_the_one_correct_derived_sync_passes(self):
        """If the checker rejected the query that demonstrably exports the
        right rows, the checker would be the thing that is wrong."""
        assert audit({"article_geoids": GEOIDS_DEPLOYED}) == []

    def test_the_dedup_wrapper_on_articles_passes(self):
        assert audit({"articles": ARTICLES_DEPLOYED}) == []

    def test_the_leak_is_caught(self):
        """THE REGRESSION. This query is what exported 138 place rows for
        articles that were not exported."""
        problems = audit({"article_places": PLACES_DEPLOYED})
        assert len(problems) == 1
        assert "article_places" in problems[0]
        assert "does not filter" in problems[0]

    def test_all_three_leaking_tables_are_caught(self):
        deployed = {
            "article_places": 'EXTERNAL_QUERY("c", "SELECT * FROM article_places;")',
            "article_people": 'EXTERNAL_QUERY("c", "SELECT * FROM article_people;")',
            "article_organizations": (
                'EXTERNAL_QUERY("c", "SELECT * FROM article_organizations;")'
            ),
        }
        assert len(audit(deployed)) == 3

    def test_whitespace_and_newlines_do_not_hide_a_filter(self):
        """A deployed query is free to be formatted. The rule is about the
        filter, not the indentation."""
        spaced = (
            "SELECT g.*\n  FROM article_geoids g\n  WHERE g.article_id IN (\n"
            "    SELECT id FROM articles\n    WHERE status IN "
            "('enriched','enrichment_skipped')\n  )"
        )
        assert audit({"article_geoids": spaced}) == []

    def test_a_filter_on_the_wrong_statuses_is_caught(self):
        """Filtering is not enough; it has to be THIS filter. A sync left on
        an older status list is the same leak wearing a filter."""
        stale = "SELECT * FROM article_places WHERE status IN ('enriched')"
        assert audit({"article_places": stale}) != []

    def test_a_table_in_neither_list_is_refused(self):
        """So a new table cannot be added to the warehouse without somebody
        saying whether it is article-scoped."""
        problems = audit({"article_sentiments": "SELECT * FROM article_sentiments"})
        assert len(problems) == 1
        assert "not declared" in problems[0]

    def test_a_missing_sync_is_reported_only_when_completeness_is_asked_for(self):
        """A partial check must not report every table it was not asked
        about, or the report is noise and gets ignored -- which is how this
        drifted. Completeness is the live check's question."""
        assert audit({"articles": ARTICLES_DEPLOYED}) == []
        problems = audit({"articles": ARTICLES_DEPLOYED}, require_complete=True)
        assert any("has no sync at all" in p for p in problems)
        assert any("article_places" in p for p in problems)

    def test_agreement_is_an_empty_list_not_a_truthy_report(self):
        deployed = {
            t: f"WHERE status IN ({status_list_sql()})" for t in ARTICLE_SCOPED_TABLES
        }
        deployed.update(dict.fromkeys(UNSCOPED_TABLES, "SELECT *"))
        assert audit(deployed) == []


class TestAgainstTheLiveWarehouse:
    """The unit tests above prove the checker works. This one proves the
    warehouse agrees, and is the only thing that can catch a change made in
    the BigQuery console. Skipped without credentials rather than passing,
    because a green test that never ran is how this drifted in the first
    place.
    """

    @pytest.mark.integration
    def test_the_deployed_syncs_match_the_rule(self):
        deployed = pytest.importorskip(
            "tests.helpers.bigquery_transfers", reason="live BigQuery check"
        ).deployed_sync_queries()
        found = audit(deployed, require_complete=True)
        assert found == [], "\n".join(found)
