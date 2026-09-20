"""A host with two source rows must not lose its subscription to the wrong one.

Measured on ptleader 2026-09-20. Two rows existed for one publisher:

    ptleader.com      requires_login=true   simplecirc  active
    www.ptleader.com  requires_login=false  no auth     orphan, 0 links

`_get_domain_auth_config` matched both and called `.fetchone()`, so which row answered
"does this host need a login" was whichever Postgres returned first. It returned
the orphan. So `fetch_plan` never set `credentialed`, the anonymous escapes
stayed enabled, and a publisher we hold a subscription to was fetched through
the proxies: nine articles of 282-530 characters, six filed as `paywall`, three
passed as `labeled` stubs. Nothing errored. The run reported success and stored
the wall.

Two properties, and the ordering is the one that matters:

- a row asserting `requires_login` wins, because no other row can satisfy that
  claim. Wrong in that direction costs an unnecessary login; wrong in the other
  costs the subscription and spends the publisher's patience anonymously.
- both `www.` spellings resolve, in BOTH directions -- this host serves both and
  the queue hands over whichever spelling the link carries. #626 made the
  bot-protection lookup www-agnostic on 2026-09-19; it did not touch this query,
  which is why the same class of defect was still here a day later.
"""

from __future__ import annotations

import inspect
import re

from src.crawler import ContentExtractor


def _lookup_sql() -> str:
    """The auth lookup with its SQL comments and Python comments stripped.

    The comments quote the defect, so an assertion that read them would pass
    with the fix reverted.
    """
    source = inspect.getsource(ContentExtractor._get_domain_auth_config)
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


class TestTheCredentialedRowWins:
    def test_the_query_orders_rather_than_taking_any_row(self):
        sql = _lookup_sql()
        assert "ORDER BY requires_login DESC" in sql

    def test_it_takes_exactly_one_row(self):
        """`LIMIT 1` beside the ORDER BY: ordering a query whose result is then
        read with `fetchone()` and no limit is the same gamble, written longer."""
        sql = _lookup_sql()
        assert "LIMIT 1" in sql

    def test_an_exact_host_match_breaks_the_tie(self):
        sql = _lookup_sql()
        order = sql.index("ORDER BY requires_login DESC")
        assert "(host = :host) DESC" in sql[order:]

    def test_credentials_break_the_next_tie(self):
        """Two rows both claiming a login: prefer the one that can perform it."""
        sql = _lookup_sql()
        order = sql.index("ORDER BY requires_login DESC")
        assert "auth_secret_name IS NOT NULL DESC" in sql[order:]


class TestBothSpellingsResolve:
    def test_the_bare_host_is_derived_not_assumed(self):
        """Asking about `www.ptleader.com` must find the row stored bare.

        The old query only added a `www.` prefix, so the bare-stored credentialed
        row was invisible to a `www.` link -- and this host's links carry both.
        """
        sql = _lookup_sql()
        assert re.search(r'host\[4:\].*startswith\("www\."\)', sql)

    def test_all_three_spellings_are_matched_on_both_columns(self):
        sql = _lookup_sql()
        assert "host IN (:host, :www_host, :bare_host)" in sql
        assert "host_norm IN (:host, :www_host, :bare_host)" in sql

    def test_the_www_form_is_built_from_the_bare_host(self):
        """`www.` + an already-`www.` host is `www.www.…`, which matches nothing
        and quietly reduced the query to two clauses."""
        sql = _lookup_sql()
        assert '"www_host": f"www.{bare_host}"' in sql
        assert '"www_host": f"www.{host}"' not in sql


class TestTheAnswerStillGatesTheFetch:
    def test_requires_login_is_what_the_fetch_plan_reads(self):
        """The cost of getting this wrong is not a missing login: it is an
        anonymous fetch of a host we hold a subscription to."""
        from src.crawler import fetch_plan

        code = inspect.getsource(fetch_plan.plan_fetch)
        assert "if credentialed:" in code
        assert "skip_http_methods=True" in code

    def test_the_extractor_passes_the_host_through_that_check(self):
        source = inspect.getsource(ContentExtractor)
        assert "credentialed=self._requires_login(domain)" in source
