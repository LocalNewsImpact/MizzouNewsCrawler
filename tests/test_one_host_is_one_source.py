"""One host is one source, however it is spelled.

Two paths insert a `sources` row on the fly -- `bot_sensitivity_manager`
recording a bot encounter and `discovery` pausing a host it cannot crawl -- and
both looked the row up with `host = :host OR host_norm = :host.lower()`. That
never strips `www.`, so a host seen as `www.ptleader.com` missed the loaded
`ptleader.com` row and a second row was inserted.

Neither path writes `dataset_sources`, so every twin is invisible to every
report that reads through a dataset. Five were in production on 2026-09-23,
including the twin of a Port Townsend Leader row carrying 425 stories.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from src.utils.source_lookup import find_source_sql, host_spellings


class TestTheSpellingsOfOneHost:
    def test_a_bare_host_reaches_its_www_form(self):
        assert "www.ptleader.com" in host_spellings("ptleader.com")

    def test_a_www_host_reaches_its_bare_form(self):
        assert "ptleader.com" in host_spellings("www.ptleader.com")

    def test_the_spelling_as_given_comes_first(self):
        """So a caller can prefer the row for exactly the host it was handed."""
        assert host_spellings("www.ptleader.com")[0] == "www.ptleader.com"
        assert host_spellings("ptleader.com")[0] == "ptleader.com"

    def test_case_is_folded(self):
        assert "ptleader.com" in host_spellings("WWW.PTLeader.COM")

    def test_a_subdomain_is_a_different_site(self):
        """`www` is the only prefix folded. Collapsing any subdomain would make
        `news.example.com` and `example.com` one source."""
        assert "example.com" not in host_spellings("news.example.com")

    def test_surrounding_space_is_not_a_different_host(self):
        assert host_spellings("  ptleader.com ")[0] == "ptleader.com"

    @pytest.mark.parametrize("empty", ["", "   ", None, "www.", "WWW."])
    def test_a_host_that_names_nothing_has_no_spellings(self, empty):
        """An empty list must reach the caller as "do not run a query": a query
        on an empty host would match every row that has one."""
        assert host_spellings(empty) == []
        assert find_source_sql(empty) == ("", {})


@pytest.fixture
def sources():
    """A sources table with the columns the lookup reads."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE sources (id VARCHAR PRIMARY KEY, host VARCHAR, "
                "host_norm VARCHAR, status VARCHAR)"
            )
        )
    return engine


def _add(engine, host, host_norm=None, status="active"):
    source_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sources (id, host, host_norm, status) "
                "VALUES (:i, :h, :n, :s)"
            ),
            {
                "i": source_id,
                "h": host,
                "n": host_norm if host_norm else host,
                "s": status,
            },
        )
    return source_id


def _find(engine, host):
    sql, params = find_source_sql(host)
    if not sql:
        return None
    with engine.begin() as conn:
        row = conn.execute(text(sql), params).fetchone()
    return str(row[0]) if row else None


class TestFindingTheSourceForAHost:
    def test_the_www_spelling_finds_the_bare_row(self, sources):
        """The Port Townsend Leader case: `ptleader.com` was loaded, discovery
        met `www.ptleader.com`, and a second row was inserted."""
        loaded = _add(sources, "ptleader.com")
        assert _find(sources, "www.ptleader.com") == loaded

    def test_the_bare_spelling_finds_the_www_row(self, sources):
        """The other direction, which is how `rangemedia.co` was created."""
        loaded = _add(sources, "www.rangemedia.co")
        assert _find(sources, "rangemedia.co") == loaded

    def test_a_host_recorded_only_in_host_norm_is_found(self, sources):
        """A site can be recorded under either column: the Washington Missourian
        is `www.missourian.com` with a `host_norm` of `www.emissourian.com`."""
        loaded = _add(sources, "www.missourian.com", host_norm="www.emissourian.com")
        assert _find(sources, "emissourian.com") == loaded

    def test_the_spelling_as_given_wins_when_both_rows_exist(self, sources):
        """Both spellings are already rows in production. Without an order the
        row returned would follow the table's physical order, and an encounter
        on one spelling would be recorded against the other."""
        bare = _add(sources, "chinookobserver.com")
        www = _add(sources, "www.chinookobserver.com")
        assert _find(sources, "chinookobserver.com") == bare
        assert _find(sources, "www.chinookobserver.com") == www

    def test_an_unrelated_host_is_not_found(self, sources):
        _add(sources, "ptleader.com")
        assert _find(sources, "example.com") is None

    def test_a_subdomain_does_not_match_the_bare_host(self, sources):
        _add(sources, "example.com")
        assert _find(sources, "news.example.com") is None

    def test_a_host_norm_with_the_dots_eaten_does_not_match_another_site(self, sources):
        """`host_norm` holds corrupted values in production -- `abcstlouis.com`
        is stored as `abcstlouiscom`. Those must not match anything but
        themselves."""
        _add(sources, "abcstlouis.com", host_norm="abcstlouiscom")
        assert _find(sources, "stlouis.com") is None


class TestNeitherPathBuildsItsOwnLookup:
    """One place decides what "the same host" means. The two paths had the same
    SQL inline and both were wrong the same way."""

    @pytest.mark.parametrize(
        "path",
        ["src/utils/bot_sensitivity_manager.py", "src/crawler/discovery.py"],
    )
    def test_the_old_lookup_is_gone(self, path):
        from pathlib import Path

        source = Path(path).read_text()
        assert "host = :host OR host_norm = :host_norm" not in source, (
            f"{path} still matches on host.lower() alone, which inserts a "
            "second row for the www spelling"
        )
        assert "find_source_sql" in source


class TestARetiredRowIsNotTheAnswer:
    """Retiring one of a pair is how a duplicate is settled. `newspressnow.com`
    was retired into `www.newspressnow.com` on 2026-09-24, its 1,093 links moved
    across; a lookup for the bare spelling still matches the retired row
    exactly, and must not be handed the row that was taken out of service."""

    @pytest.mark.parametrize("gone", ["retired", "inactive"])
    def test_the_live_row_wins_even_on_a_worse_spelling_match(self, sources, gone):
        live = _add(sources, "www.newspressnow.com")
        _add(sources, "newspressnow.com", status=gone)
        assert _find(sources, "newspressnow.com") == live

    def test_a_retired_row_is_still_found_when_it_is_all_there_is(self, sources):
        """The lookup answers "which row is this host", not "which row is
        live" -- a retired source still has a bot sensitivity and a history."""
        only = _add(sources, "kansascity.com", status="retired")
        assert _find(sources, "www.kansascity.com") == only

    def test_an_unrecorded_status_ranks_as_live(self, sources):
        """Five production rows have no status. That is not a statement that the
        source is finished."""
        unrecorded = _add(sources, "www.example.com", status=None)
        _add(sources, "example.com", status="retired")
        assert _find(sources, "example.com") == unrecorded
