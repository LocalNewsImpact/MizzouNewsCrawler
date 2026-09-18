"""A manually enqueued link carries the source that owns it.

The script set `source` and `source_name` to the bare host and left `source_id`
NULL. Extraction is unaffected -- it LEFT JOINs sources -- and so is
classification, so the article looks finished. Enrichment's candidate query does
not:

    JOIN dataset_sources ds ON ds.source_id = cl.source_id

An inner join on NULL matches nothing, so the article is never a candidate,
never gets a place, and nothing anywhere reports it as skipped. The publisher's
city and state that the geography prompt is grounded on hang off the same id.

3,002 WSU tracker URLs were about to be enqueued this way.

NOT IN tests/scripts/ ON PURPOSE. `tests/conftest.py` marks everything under
that directory `local_scripts`, and `pytest.ini` deselects that marker -- the
marker's own description is "skipped in CI". A test for this placed there would
pass locally and gate nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "manual_enqueue_urls", ROOT / "scripts/manual_enqueue_urls.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _module()

SOURCES = {
    "ptleader.com": {
        "id": "src-pt",
        "host": "ptleader.com",
        "canonical_name": "Port Townsend Leader",
        "city": "Port Townsend",
        "county": "Jefferson",
        "type": "print native",
    },
    "spokesman.com": {
        "id": "src-spk",
        "host": "www.spokesman.com",
        "canonical_name": "Spokesman-Review",
        "city": "Spokane",
        "county": "Spokane",
        "type": "print native",
    },
}


def _build(urls, sources=SOURCES):
    return MOD._build_dataframe(
        urls,
        status="article",
        discovered_by="manual-import",
        priority=5,
        metadata_flag=False,
        dataset_id="ds-1",
        sources=sources,
    )


class TestTheHostKey:
    @pytest.mark.parametrize(
        "given,want",
        [
            ("www.ptleader.com", "ptleader.com"),
            ("ptleader.com:443", "ptleader.com"),
            ("PTLeader.com", "ptleader.com"),
            ("user@www.ptleader.com", "ptleader.com"),
            ("", ""),
        ],
    )
    def test_it_strips_what_sources_does_not_store(self, given, want):
        assert MOD._lookup_host(given) == want

    def test_a_url_with_www_finds_a_source_stored_without_it(self):
        """And the reverse: the two spellings are mixed across the table, so
        matching on the raw netloc would miss half of them."""
        df, unknown = _build(["https://www.ptleader.com/stories/x"])
        assert unknown == {}
        assert df.iloc[0]["source_id"] == "src-pt"

    def test_a_url_without_www_finds_a_source_stored_with_it(self):
        df, unknown = _build(["https://spokesman.com/story/y"])
        assert unknown == {}
        assert df.iloc[0]["source_id"] == "src-spk"


class TestWhatTheRowCarries:
    def test_source_id_is_set(self):
        df, _ = _build(["https://ptleader.com/stories/x"])
        assert df.iloc[0]["source_id"] == "src-pt"

    def test_the_denormalised_columns_come_from_the_source_not_the_url(self):
        """Every row discovery writes carries these; geography reads the city."""
        df, _ = _build(["https://ptleader.com/stories/x"])
        row = df.iloc[0]
        assert row["source_city"] == "Port Townsend"
        assert row["source_county"] == "Jefferson"
        assert row["source_type"] == "print native"

    def test_source_carries_the_publisher_name_not_the_host(self):
        """259,025 existing rows have `source` different from the host: it is
        the name. Writing the host there made manual rows the odd ones out."""
        df, _ = _build(["https://ptleader.com/stories/x"])
        assert df.iloc[0]["source"] == "Port Townsend Leader"
        assert df.iloc[0]["source_name"] == "Port Townsend Leader"


class TestAnUnclaimedHost:
    def test_it_is_counted_and_named(self):
        df, unknown = _build(
            [
                "https://ptleader.com/stories/x",
                "https://nobody.example.com/a",
                "https://nobody.example.com/b",
            ]
        )
        assert unknown == {"nobody.example.com": 2}

    def test_the_row_still_falls_back_to_the_host_for_a_name(self):
        """So a run with --allow-unknown-hosts writes something legible rather
        than a null publisher."""
        df, _ = _build(["https://nobody.example.com/a"])
        row = df.iloc[0]
        assert row["source"] == "nobody.example.com"
        assert "source_id" not in row or row.get("source_id") is None

    def test_no_sources_at_all_means_every_host_is_unknown(self):
        """A lookup that silently returned nothing must not read as success."""
        df, unknown = _build(["https://ptleader.com/stories/x"], sources={})
        assert unknown == {"ptleader.com": 1}


class TestTheReport:
    def test_it_says_what_the_missing_id_costs(self, capsys):
        MOD._report_unknown({"nobody.example.com": 2}, allowed=False)
        out = capsys.readouterr().out
        assert "refused" in out
        assert "source_id" in out
        assert "nobody.example.com" in out

    def test_it_says_so_when_they_are_written_anyway(self, capsys):
        MOD._report_unknown({"nobody.example.com": 2}, allowed=True)
        assert "enqueued anyway" in capsys.readouterr().out

    def test_nothing_unknown_prints_nothing(self, capsys):
        MOD._report_unknown({}, allowed=False)
        assert capsys.readouterr().out == ""
