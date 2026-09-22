"""A byline string is not a person until somebody says which person it is.

`articles.author` holds what a parser made of a page. Over Mizzou's 98,210 local
articles that is 7,921 distinct strings across 200 hosts, and counting them
counts spellings:

    2,689  several names in one string   "Aamer Madhani, Regina Garcia Cano"
      645  one person, several spellings "Nate Sanford" / "Nate Sandford"
      527  a list literal                `["Stanley Schwartz"]`, `[]`
      475  same name, unrelated owners
      135  not a person                  "Admin" -- 717 articles on 6 hosts
       40  a publication name            "Abby Volz - Southeast Arrow"
       36  a job title                   "Amanda Barnes, Komu 8 Wellness Coach"
        7  an address or domain          "NPR Staff, www.kbia.org, npr-staff"

3,367 need nothing. Resolved, the same corpus is 6,022 people on 187 hosts.

What is pinned here: the signals name a specific defect, the splitter proposes
and never invents, a near-match is offered rather than merged, and a decision
reaches only the dataset it was made in.
"""

from __future__ import annotations

import pytest

from src.services import byline_review as br


class TestTheListLiteral:
    """September 2025 stored the cleaner's output list, not its names: 1,716
    Mizzou articles read `["Stanley Schwartz"]` and 188 read `[]`."""

    def test_a_name_comes_out_of_it(self):
        assert br.split_names('["Stanley Schwartz"]') == ["Stanley Schwartz"]

    def test_several_names_come_out_of_it(self):
        assert br.split_names('["Aamer Madhani", "Konstantin Toropin"]') == [
            "Aamer Madhani",
            "Konstantin Toropin",
        ]

    def test_single_quotes_are_read_too(self):
        """Written by `str(list)`, so `json.loads` would refuse it."""
        assert br.split_names("['Kellie Houx']") == ["Kellie Houx"]

    def test_an_empty_list_names_nobody(self):
        assert br.split_names("[]") == []
        assert br.unwrap_list_literal("[]") == []

    def test_a_name_in_brackets_is_not_a_literal(self):
        assert br.unwrap_list_literal("[Not a list") is None
        assert br.unwrap_list_literal("Ivan Foley") is None

    def test_it_is_the_first_signal_worked(self):
        """A mechanical repair with one obvious answer, before any judgement."""
        assert br.SIGNAL_ORDER[0] == br.LIST_LITERAL


class TestTheSplitter:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Mallory Kruml", ["Mallory Kruml"]),
            (
                "Loryn Kykendall, Julia Eastham, Kate Smith",
                ["Loryn Kykendall", "Julia Eastham", "Kate Smith"],
            ),
            ("Conor Wilson; Moe Clark", ["Conor Wilson", "Moe Clark"]),
            ("Alex Frick & Mallory Kruml", ["Alex Frick", "Mallory Kruml"]),
            ("Freddy Monares and Nate Sanford", ["Freddy Monares", "Nate Sanford"]),
        ],
    )
    def test_it_separates_people(self, raw, expected):
        assert br.split_names(raw) == expected

    def test_a_publication_after_a_name_is_dropped(self):
        assert br.split_names("Abby Volz - Southeast Arrow") == ["Abby Volz"]
        assert br.split_names("Amanda Sullender/ Spokesman-Review, Monica Ruiz") == [
            "Amanda Sullender",
            "Monica Ruiz",
        ]

    def test_a_title_after_a_name_is_dropped(self):
        assert br.split_names("Patrick Fudally, Officer") == ["Patrick Fudally"]
        assert br.split_names("Amanda Barnes, Komu 8 Wellness Coach") == [
            "Amanda Barnes"
        ]

    def test_a_title_inside_the_name_is_removed_not_the_name(self):
        """ "Henry Brannan Murrow Fellow Sarah Wolf" is two people and a title.
        Dropping the part loses both; removing the title leaves something a
        reviewer can split."""
        assert br.split_names("Henry Brannan Murrow Fellow Sarah Wolf") == [
            "Henry Brannan Sarah Wolf"
        ]

    def test_an_address_is_not_a_name(self):
        assert "www.kbia.org" not in br.split_names("NPR Staff, www.kbia.org")

    def test_it_does_not_repair_a_name(self):
        """Proposing is the splitter's job; deciding is the reviewer's. A typo
        comes out exactly as written."""
        assert br.split_names("Nate Sandford") == ["Nate Sandford"]
        assert br.split_names("Mkruml") == ["Mkruml"]


class TestTheSignals:
    def _row(self, raw, hosts=("a.example",), owners=("Owner",), articles=1):
        row = br.BylineRow(raw=raw, articles=articles, hosts=hosts, owners=owners)
        row.signals = br.signals_for(row)
        return row

    @pytest.mark.parametrize(
        "raw, signal",
        [
            ('["Stanley Schwartz"]', br.LIST_LITERAL),
            ("Amanda Barnes, Komu 8 Wellness Coach", br.STRAY_TITLE),
            ("Abby Volz - Southeast Arrow", br.PUBLICATION_SUFFIX),
            ("NPR Staff, www.kbia.org, npr-staff", br.CONTACT_FRAGMENT),
            ("Admin", br.NOT_A_PERSON),
            ("ABC 17 News Team", br.NOT_A_PERSON),
            ("Conor Wilson; Moe Clark", br.MULTIPLE_NAMES),
        ],
    )
    def test_each_defect_is_named(self, raw, signal):
        assert signal in self._row(raw).signals

    def test_a_plain_name_shows_nothing(self):
        assert self._row("Ivan Foley").signals == ()
        assert self._row("Ivan Foley").needs_review is False

    def test_one_string_can_show_several(self):
        row = self._row("Amanda Sullender/ Spokesman-Review, Monica Ruiz")
        assert br.PUBLICATION_SUFFIX in row.signals
        assert br.MULTIPLE_NAMES in row.signals

    def test_unrelated_owners_is_a_signal_about_the_pair_not_the_string(self):
        """One reporter filing for two papers, a syndicated story the wire
        check missed, or a parse. A person decides, on the article."""
        same = self._row("Aaron Beard", hosts=("a.example",), owners=("Owner",))
        across = self._row(
            "Aaron Beard", hosts=("a.example", "b.example"), owners=("One", "Two")
        )
        assert br.CROSS_OWNER not in same.signals
        assert br.CROSS_OWNER in across.signals


class TestSpellingVariants:
    def _rows(self, *rows):
        return br.review_rows(rows)

    def test_accents_and_punctuation_are_one_person(self):
        found = {
            row.raw: row
            for row in self._rows(
                ("Reneé Dìaz", "nwpb.org", "Owner", 4),
                ("Renee-Diaz", "nwpb.org", "Owner", 1),
            )
        }
        assert br.SPELLING_VARIANT in found["Reneé Dìaz"].signals
        assert found["Reneé Dìaz"].variants == ("Renee-Diaz",)

    def test_a_typo_at_the_same_owner_is_offered(self):
        found = {
            row.raw: row
            for row in self._rows(
                ("Nate Sanford", "knkx.org", "Cascade", 30),
                ("Nate Sandford", "knkx.org", "Cascade", 1),
            )
        }
        assert found["Nate Sandford"].variants == ("Nate Sanford",)

    def test_similar_names_at_unrelated_owners_are_not_paired(self):
        """Blocked on the owner: two reporters at unrelated publishers with
        similar names are two reporters."""
        found = {
            row.raw: row
            for row in self._rows(
                ("Nate Sanford", "knkx.org", "Cascade", 30),
                ("Nate Sandford", "elsewhere.example", "Unrelated", 1),
            )
        }
        assert found["Nate Sandford"].variants == ()

    def test_word_order_is_not_ignored(self):
        """ "Smith John" is not "John Smith"; merging them merges two people."""
        assert br.normalised_name("John Smith") != br.normalised_name("Smith John")

    def test_a_pair_is_offered_never_merged(self):
        """0.90 pairs "Alex Frick" and "Alex Brick", who are two people. The
        proposal keeps each string as written; a reviewer decides."""
        found = {
            row.raw: row
            for row in self._rows(
                ("Alex Frick", "a.example", "Owner", 4),
                ("Alex Brick", "a.example", "Owner", 1),
            )
        }
        assert found["Alex Frick"].variants == ("Alex Brick",)
        assert found["Alex Frick"].proposed == ("Alex Frick",)


class TestTheQueueOrder:
    def test_worst_first_then_biggest(self):
        rows = [
            ("Ivan Foley", "a.example", "Owner", 700),
            ("Admin", "a.example", "Owner", 717),
            ('["Stanley Schwartz"]', "a.example", "Owner", 30),
            ("A B, C D", "a.example", "Owner", 900),
        ]
        ordered = [row.raw for row in br.candidates(rows)]
        assert ordered[0] == '["Stanley Schwartz"]'
        assert ordered[-1] == "A B, C D"
        assert "Ivan Foley" not in ordered, "a clean string is not queued"

    def test_every_signal_has_a_label(self):
        assert set(br.SIGNAL_ORDER) == set(br.SIGNAL_LABELS)


class TestTheReports:
    ROWS = [
        ("Conor Wilson; Moe Clark", "kitsapsun.com", "Gannett", 2),
        ("Conor Wilson", "kitsapsun.com", "Gannett", 8),
        ('["Stanley Schwartz"]', "example.com", "Other", 30),
        ("Admin", "example.com", "Other", 700),
    ]

    def test_a_byline_report_counts_people_not_strings(self):
        report = {row["byline"]: row for row in br.bylines_with_hosts(self.ROWS)}
        assert report["Conor Wilson"]["articles"] == 10, "both strings count"
        assert report["Conor Wilson"]["raw_forms"] == 2
        assert "Stanley Schwartz" in report, "the literal resolved to its person"
        assert '["Stanley Schwartz"]' not in report

    def test_a_byline_report_names_the_hosts(self):
        report = {row["byline"]: row for row in br.bylines_with_hosts(self.ROWS)}
        assert report["Conor Wilson"]["host_list"] == "kitsapsun.com"
        assert report["Conor Wilson"]["hosts"] == 1

    def test_a_host_report_counts_unique_bylines(self):
        report = {row["host"]: row for row in br.hosts_with_bylines(self.ROWS)}
        assert report["kitsapsun.com"]["unique_bylines"] == 2, "Wilson once, Clark once"
        assert report["example.com"]["unique_bylines"] == 2
        assert report["kitsapsun.com"]["articles"] == 10

    def test_a_host_report_counts_that_host_only(self):
        """Built from the byline's own totals it was wrong twice: a byline on
        four hosts gave each of them all four hosts' articles, and every owner
        those hosts belong to -- on Mizzou, all 50 owners against every host."""
        rows = [
            ("Aaron Beard", "one.example", "Owner One", 30),
            ("Aaron Beard", "two.example", "Owner Two", 4),
        ]
        report = {row["host"]: row for row in br.hosts_with_bylines(rows)}
        assert report["one.example"]["articles"] == 30
        assert report["two.example"]["articles"] == 4
        assert report["one.example"]["owner"] == "Owner One"
        assert report["two.example"]["owner"] == "Owner Two"

    def test_the_local_statuses_are_what_the_pipeline_kept(self):
        """Wire, opinion, obituaries and weather have their own statuses; a
        byline report over these is a report about local reporting."""
        assert set(br.LOCAL_STATUSES) == {
            "enriched",
            "labeled",
            "cleaned",
            "enrichment_skipped",
        }


class TestApplyingADecision:
    def test_it_writes_the_names_onto_the_articles(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        session.execute.return_value.rowcount = 17
        written = br.apply_decision(session, "ds-1", '["Stan S"]', ["Stan S"])
        assert written == 17
        params = session.execute.call_args.args[1]
        assert params["author"] == "Stan S"
        assert params["raw_byline"] == '["Stan S"]'
        assert params["dataset_id"] == "ds-1"

    def test_it_reaches_only_that_dataset_and_that_string(self):
        sql = br._APPLY_SQL
        assert "cl.dataset_id = :dataset_id" in sql
        assert "a.author = :raw_byline" in sql

    def test_no_names_clears_the_byline(self):
        """ "Admin" names nobody: the byline is emptied, not set to "[]"."""
        assert br.rendered([]) == ""
        assert br.rendered(["A", " ", "B"]) == "A, B"
