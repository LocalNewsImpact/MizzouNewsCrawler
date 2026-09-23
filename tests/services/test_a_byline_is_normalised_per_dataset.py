"""A byline string is not a person until somebody says which person it is.

`articles.author` holds what a parser made of a page. Over Mizzou's 98,210 local
articles that is 7,921 distinct strings across 200 hosts, and counting them
counts spellings:

      645  one person, several spellings "Nate Sanford" / "Nate Sandford"
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

import json
from pathlib import Path

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

    def test_it_is_not_a_review_row(self):
        """A storage form, not a judgement: September 2025 wrote `str(list)`
        where the current path writes `", ".join(names)`. `repair_list_literals`
        rewrites it and nobody is asked."""
        assert br.LIST_LITERAL not in br.SIGNAL_ORDER
        row = br.BylineRow(
            raw='["Stanley Schwartz"]',
            articles=30,
            hosts=("a.example",),
            owners=("Owner",),
        )
        assert br.LIST_LITERAL not in br.signals_for(row)


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

    def test_a_title_word_does_not_eat_a_surname(self):
        """Marcus Officer files for fox4kc. The first rule cut the word out of
        every part that held it and left "Marcus", and then paired that with
        another byline as a misspelling of "Alyssa Mueller"."""
        assert br.split_names("Alyssa Mueller, Marcus Officer") == [
            "Alyssa Mueller",
            "Marcus Officer",
        ]
        assert br.split_names("Marcus Officer, Alyssa Mueller, Jonathan Ketz") == [
            "Marcus Officer",
            "Alyssa Mueller",
            "Jonathan Ketz",
        ]
        assert br.split_names("Dana President") == ["Dana President"]
        assert br.split_names("Jane Chief, Editor") == ["Jane Chief"]

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
            ("Amanda Barnes, Komu 8 Wellness Coach", br.STRAY_TITLE),
            ("Abby Volz - Southeast Arrow", br.PUBLICATION_SUFFIX),
            ("NPR Staff, www.kbia.org, npr-staff", br.CONTACT_FRAGMENT),
            ("Admin", br.NOT_A_PERSON),
            ("ABC 17 News Team", br.NOT_A_PERSON),
        ],
    )
    def test_each_defect_is_named(self, raw, signal):
        assert signal in self._row(raw).signals

    def test_a_plain_name_shows_nothing(self):
        assert self._row("Ivan Foley").signals == ()
        assert self._row("Ivan Foley").needs_review is False

    def test_one_string_can_show_several(self):
        row = self._row("ABC 17 News Team, www.kbia.org")
        assert br.CONTACT_FRAGMENT in row.signals
        assert br.NOT_A_PERSON in row.signals

    def test_co_authors_are_not_a_defect(self):
        """Stories have co-authors and the byline is their list. The work is to
        parse it into one record per person, which the reports do; it is never
        a queue row."""
        assert self._row("Conor Wilson; Moe Clark").signals == ()
        assert self._row("Loryn Kykendall, Julia Eastham, Kate Smith").signals == ()

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


class TestWhatDiffersIsSaid:
    """A reviewer reading "Nick McNeal" beside "Nick Mcneal" cannot see the
    difference. 66 of Mizzou's 645 variant rows differ by case alone, and 357
    list-literal rows differ from a plain string only by the brackets."""

    @pytest.mark.parametrize(
        "left, right, expected",
        [
            ("Nick McNeal", "Nick Mcneal", br.DIFF_CASE),
            ("Mark McLaughlin", "Mark Mclaughlin", br.DIFF_CASE),
            ('["Stanley Schwartz"]', "Stanley Schwartz", br.DIFF_BRACKETS),
            ("Reneé Dìaz", "Renee Diaz", br.DIFF_ACCENTS),
            ("Renee-Diaz", "Renee Diaz", br.DIFF_PUNCTUATION),
            ("Nate Sanford", "Nate Sandford", br.DIFF_SPELLING),
            ("Ivan Foley", "Ivan Foley", br.DIFF_NONE),
        ],
    )
    def test_the_difference_is_named(self, left, right, expected):
        assert br.difference_kind(left, right) == expected

    def test_it_reads_the_same_in_either_order(self):
        assert br.difference_kind("Stanley Schwartz", '["Stanley Schwartz"]') == (
            br.DIFF_BRACKETS
        )

    def test_the_candidates_csv_carries_it(self):
        from pathlib import Path

        source = Path("src/cli/commands/byline_report.py").read_text()
        assert '"differs_by"' in source
        assert "br.difference_kind(row.raw, variant)" in source


class TestTheQueueOrder:
    def test_worst_first_then_biggest(self):
        rows = [
            ("Ivan Foley", "a.example", "Owner", 700),
            ("Admin", "a.example", "Owner", 717),
            ('["Stanley Schwartz"]', "a.example", "Owner", 30),
            ("A B, C D", "a.example", "Owner", 900),
        ]
        ordered = [row.raw for row in br.candidates(rows)]
        assert ordered[-1] == "Admin"
        assert '["Stanley Schwartz"]' not in ordered, "a literal is repaired"
        assert "Ivan Foley" not in ordered, "a clean string is not queued"
        assert "A B, C D" not in ordered, "co-authors are not a queue row"

    def test_every_signal_has_a_label(self):
        assert set(br.SIGNAL_ORDER) == set(br.SIGNAL_LABELS)


class TestAuthorRecords:
    """One record per person per article, aligned to the article and the host
    it ran on. Every other report is an aggregate of these."""

    ROWS = [
        (
            "a-1",
            "Loryn Kykendall, Julia Eastham, Kate Smith",
            "ub.example",
            "Owner",
            None,
            "Council votes",
        ),
        ("a-2", '["Stanley Schwartz"]', "pike.example", "CherryRoad", None, "Fair"),
    ]

    def test_a_co_authored_article_becomes_one_record_each(self):
        records = br.author_records(self.ROWS)
        assert [r["byline"] for r in records if r["article_id"] == "a-1"] == [
            "Loryn Kykendall",
            "Julia Eastham",
            "Kate Smith",
        ]

    def test_each_record_keeps_its_article_and_host(self):
        records = br.author_records(self.ROWS)
        assert {r["host"] for r in records if r["article_id"] == "a-1"} == {
            "ub.example"
        }
        assert all(r["article_id"] for r in records)

    def test_the_position_says_who_led(self):
        records = [r for r in br.author_records(self.ROWS) if r["article_id"] == "a-1"]
        assert [(r["position"], r["of_authors"]) for r in records] == [
            (1, 3),
            (2, 3),
            (3, 3),
        ]

    def test_the_raw_string_is_kept_on_every_record(self):
        """A record can always be traced back to what the page carried."""
        records = br.author_records(self.ROWS)
        assert all(r["raw_byline"] for r in records)
        assert records[-1]["byline"] == "Stanley Schwartz"
        assert records[-1]["raw_byline"] == '["Stanley Schwartz"]'


class TestOwnershipIsAboutCompaniesNotStrings:
    """126 cross-owner rows on Mizzou held three different things: the same
    owner spelled two ways, one owner whose name contains a comma split by the
    report itself, and real parent ownership."""

    @pytest.mark.parametrize(
        "left, right",
        [
            ("Gray Media", "Gray Television"),
            ("Lancaster Management Inc", "Lancaster Management Inc."),
            ("News-Press & Gazette Company", "Newspress and Gazette Company"),
            (
                "South East Missouri State University",
                "Southeast Missouri State University",
            ),
            ("Faughn Media, LLC", "Faughn Media LLC"),
        ],
    )
    def test_one_owner_spelled_two_ways_is_one_owner(self, left, right):
        assert br.owner_key(left) == br.owner_key(right)

    def test_two_owners_are_still_two(self):
        assert br.owner_key("Carter Broadcast Group") != br.owner_key("Carey Media")

    def test_a_parent_is_a_fact_somebody_records(self):
        """No string comparison reaches it: Missourian Publishing and the
        University of Missouri are one ownership because somebody says so."""
        groups = {br.owner_key("Missourian Publishing Association"): "university"}
        assert br.owner_group("Missourian Publishing Association", groups) == (
            br.owner_group(
                "University of Missouri", {**groups, "universitymissouri": "university"}
            )
        )

    def test_a_grouped_pair_stops_being_a_cross_owner_row(self):
        rows = [
            ("Kellie Houx", "a.example", "Missourian Publishing Association", 40),
            ("Kellie Houx", "b.example", "University of Missouri", 3),
        ]
        ungrouped = br.candidates(rows)
        assert [r.top_signal for r in ungrouped] == [br.CROSS_OWNER]
        groups = {
            br.owner_key("Missourian Publishing Association"): "mizzou",
            br.owner_key("University of Missouri"): "mizzou",
        }
        assert br.candidates(rows, groups) == []

    def test_a_reporter_at_two_unrelated_owners_is_still_asked_about(self):
        rows = [
            ("Aaron Beard", "a.example", "Gannett", 30),
            ("Aaron Beard", "b.example", "Lee Enterprises", 4),
        ]
        assert [r.top_signal for r in br.candidates(rows)] == [br.CROSS_OWNER]


class TestADecisionIsNotAskedAgain:
    ROWS = [
        ("Nate Sandford", "knkx.example", "Cascade", 1),
        ("Nate Sanford", "knkx.example", "Cascade", 30),
    ]

    def test_a_decided_string_leaves_the_queue(self):
        assert [r.raw for r in br.candidates(self.ROWS)] != []
        decided = {"Nate Sandford": ["Nate Sanford"]}
        remaining = [r.raw for r in br.candidates(self.ROWS, decisions=decided)]
        assert "Nate Sandford" not in remaining

    def test_the_reports_count_the_decided_name(self):
        decided = {"Nate Sandford": ["Nate Sanford"]}
        report = {r["byline"]: r for r in br.bylines_with_hosts(self.ROWS, decided)}
        assert "Nate Sandford" not in report
        assert report["Nate Sanford"]["articles"] == 31

    def test_a_decision_naming_nobody_removes_the_byline(self):
        rows = [("Admin", "a.example", "Owner", 700)]
        report = br.bylines_with_hosts(rows, {"Admin": []})
        assert report == []

    def test_the_records_carry_the_decided_name(self):
        article_rows = [("a-1", "Nate Sandford", "knkx.example", "Cascade", None, "T")]
        records = br.author_records(article_rows, {"Nate Sandford": ["Nate Sanford"]})
        assert records[0]["byline"] == "Nate Sanford"
        assert records[0]["raw_byline"] == "Nate Sandford"


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

    def test_the_local_statuses_are_what_reached_the_export(self):
        """`labeled` is not here. Those are classified and not enriched, so
        they are in no export and nobody has read them: 81,786 of Mizzou's
        98,210 local articles, carrying 7,156 byline strings of their own."""
        assert set(br.LOCAL_STATUSES) == {"enriched", "enrichment_skipped"}


class TestRepairingListLiterals:
    """A schema artefact, fixed rather than reviewed."""

    def _session(self, rows):
        from unittest.mock import MagicMock

        session = MagicMock()
        session.execute.return_value.fetchall.return_value = rows
        session.execute.return_value.rowcount = 0
        return session

    def test_it_counts_what_it_would_write(self):
        session = self._session([('["Stanley Schwartz"]', 30), ("[]", 188)])
        result = br.repair_list_literals(session, "ds-1", dry_run=True)
        assert result["strings"] == 2
        assert result["articles"] == 218

    def test_a_dry_run_writes_nothing(self):
        session = self._session([('["Stanley Schwartz"]', 30)])
        br.repair_list_literals(session, "ds-1", dry_run=True)
        statements = [str(call.args[0]) for call in session.execute.call_args_list]
        assert not any("UPDATE articles" in s for s in statements)

    def test_it_writes_the_current_form(self):
        session = self._session([('["A B", "C D"]', 4)])
        result = br.repair_list_literals(session, "ds-1")
        assert result["examples"][0][1] == "A B, C D"

    def test_an_empty_list_clears_the_byline(self):
        session = self._session([("[]", 188)])
        result = br.repair_list_literals(session, "ds-1")
        assert result["examples"][0][1] == ""

    def test_it_repairs_every_status_not_only_the_exported_ones(self):
        """All 1,716 Mizzou literals sit at `labeled`, outside the export and
        still wrong. A report reads what was exported; a repair does not."""
        session = self._session([('["A B"]', 4)])
        br.repair_list_literals(session, "ds-1")
        statements = [str(call.args[0]) for call in session.execute.call_args_list]
        assert not any("a.status = ANY" in s for s in statements)

    def test_a_name_in_brackets_is_left_alone(self):
        """ "[Not a list" is a name, oddly punctuated."""
        session = self._session([("[Not a list", 2)])
        result = br.repair_list_literals(session, "ds-1")
        assert result["strings"] == 0


class TestApplyingADecision:
    def test_it_writes_the_names_onto_the_articles(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        session.execute.return_value.rowcount = 17
        written = br.apply_decision(session, "ds-1", '["Stan S"]', ["Stan S"])
        assert written == 17
        # The FIRST statement: the exact match. A second one follows it for the
        # bylines that carry this name beside a co-author, which is why the last
        # call is no longer this one.
        params = session.execute.call_args_list[0].args[1]
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


class TestTheQueueIsComputedForTheReviewer:
    """The signals live here and the person who acts on them works in datadesk,
    a different repository reading the same database. Computing the queue into
    a table keeps the rules in one place and keeps 7,921 strings from being
    scored inside a web request."""

    def _session(self, rows):
        """A session that answers each query with its own shape.

        One canned answer for every `execute` made the owner-group loader read
        `(byline, host, owner, articles)` as `(owner_key, group_key)`.
        """
        from unittest.mock import MagicMock

        def execute(statement, params=None):
            sql = str(statement)
            result = MagicMock()
            if "FROM owner_groups" in sql or "FROM byline_normalizations" in sql:
                answer: list = []
            elif "FROM articles" in sql:
                answer = list(rows)
            else:
                answer = []
            result.fetchall.return_value = answer
            result.__iter__ = lambda self: iter(answer)
            return result

        session = MagicMock()
        session.execute.side_effect = execute
        return session

    def test_a_dry_run_writes_nothing(self):
        session = self._session([("Admin", "a.example", "Owner", 700)])
        result = br.refresh_candidates(session, "ds-1", dry_run=True)
        assert result["written"] == 0
        statements = [str(call.args[0]) for call in session.execute.call_args_list]
        assert not any("INSERT INTO byline_review_candidates" in s for s in statements)

    def test_it_replaces_the_dataset_wholesale(self):
        """A decided string stops being written rather than lingering as a row
        nobody can act on."""
        session = self._session([("Admin", "a.example", "Owner", 700)])
        br.refresh_candidates(session, "ds-1")
        statements = [str(call.args[0]) for call in session.execute.call_args_list]
        deletes = [s for s in statements if "DELETE FROM byline_review_candidates" in s]
        assert deletes and "dataset_id = :dataset_id" in deletes[0]

    def test_a_row_carries_what_the_page_has_to_show(self):
        session = self._session([("Admin", "a.example", "Owner", 700)])
        br.refresh_candidates(session, "ds-1")
        inserts = [
            call.args[1]
            for call in session.execute.call_args_list
            if "INSERT INTO byline_review_candidates" in str(call.args[0])
        ]
        assert len(inserts) == 1
        row = inserts[0]
        assert row["raw"] == "Admin"
        assert row["signal"] == br.NOT_A_PERSON
        assert row["label"] == br.SIGNAL_LABELS[br.NOT_A_PERSON]
        assert row["articles"] == 700
        assert json.loads(row["hosts"]) == ["a.example"]
        assert json.loads(row["differs_by"]) == []

    def test_the_difference_is_written_beside_each_variant(self):
        session = self._session(
            [
                ("Nate Sanford", "a.example", "Owner", 30),
                ("Nate Sandford", "a.example", "Owner", 1),
            ]
        )
        br.refresh_candidates(session, "ds-1")
        rows = {
            call.args[1]["raw"]: call.args[1]
            for call in session.execute.call_args_list
            if "INSERT INTO byline_review_candidates" in str(call.args[0])
        }
        # ONE ROW FOR THE PAIR, keyed on the spelling with the most stories --
        # the one a reviewer is most likely to keep. Two rows asked about one
        # person twice and hoped the answers agreed.
        assert "Nate Sandford" not in rows
        row = rows["Nate Sanford"]
        assert json.loads(row["variants"]) == ["Nate Sandford"]
        assert json.loads(row["differs_by"]) == [br.DIFF_SPELLING]
        # Each spelling with its own count, because which one is right is judged
        # by comparing those: 30 stories against 1.
        assert [(g["name"], g["articles"]) for g in json.loads(row["group"])] == [
            ("Nate Sanford", 30),
            ("Nate Sandford", 1),
        ]

    def test_housekeeping_refreshes_it(self):
        from pathlib import Path

        yaml = pytest.importorskip("yaml")
        spec = yaml.safe_load(Path("k8s/argo/housekeeping-workflow.yaml").read_text())
        templates = {t["name"]: t for t in spec["spec"]["templates"]}
        steps = [
            step
            for group in templates["housekeeping"]["steps"]
            for step in group
            if step["name"] == "refresh-byline-queue"
        ]
        assert steps, "no refresh step"
        assert steps[0]["continueOn"] == {"failed": True}
        source = templates["refresh-byline-queue-step"]["script"]["source"]
        assert "refresh_candidates" in source
        assert "SELECT id FROM datasets" in source, "every dataset, not one"


class TestADecisionReachesTheArticle:
    """A decision is not finished when it is recorded.

    `articles.author` is the permanent record, and until the names reach it the
    correction exists only in a table nothing downstream reads -- the BigQuery
    export, the byline reports and anybody querying the corpus all still see the
    parser's string. Housekeeping applies them, so a decision made in the
    console reaches the corpus overnight without anybody running a command.
    """

    def _session(self, pending):
        """A session whose first SELECT returns the undecided-but-unapplied
        rows, and whose writes report one row each."""
        from unittest.mock import MagicMock

        session = MagicMock()
        calls = []

        def execute(statement, params=None):
            text = str(statement)
            calls.append((text, params))
            result = MagicMock()
            if "SELECT id, raw_byline" in text:
                result.fetchall.return_value = pending
            else:
                result.rowcount = 1
            return result

        session.execute.side_effect = execute
        session.calls = calls
        return session

    def test_it_writes_each_pending_decision(self):
        session = self._session(
            [("n-1", '["Stan S"]', ["Stan S"]), ("n-2", "Jon Smtih", ["Jon Smith"])]
        )
        result = br.apply_pending(session, "ds-1")
        assert result["decisions"] == 2
        assert result["articles"] == 2

    def test_it_takes_only_what_has_not_been_applied(self):
        """So a nightly run is idempotent: last night's decisions are not
        written again."""
        session = self._session([])
        br.apply_pending(session, "ds-1")
        select = session.calls[0][0]
        assert "applied_at IS NULL" in select
        assert "dataset_id = :dataset_id" in select

    def test_it_stamps_what_it_applied(self):
        session = self._session([("n-1", "Jon Smtih", ["Jon Smith"])])
        br.apply_pending(session, "ds-1")
        stamps = [c for c in session.calls if "SET applied_at" in c[0]]
        assert len(stamps) == 1
        assert stamps[0][1] == {"n": 1, "id": "n-1"}

    def test_a_decision_that_wrote_nothing_is_still_stamped(self):
        """Zero articles is the normal outcome for a string a previous run
        already fixed. Leaving the stamp null re-runs it every night forever."""
        from unittest.mock import MagicMock

        session = MagicMock()
        calls = []

        def execute(statement, params=None):
            text = str(statement)
            calls.append((text, params))
            result = MagicMock()
            if "SELECT id, raw_byline" in text:
                result.fetchall.return_value = [("n-1", "Jon Smtih", ["Jon Smith"])]
            else:
                result.rowcount = 0
            return result

        session.execute.side_effect = execute
        br.apply_pending(session, "ds-1")
        assert any("SET applied_at" in text for text, _ in calls)

    def test_names_stored_as_json_text_are_read(self):
        """sqlite hands a JSON column back as text; Postgres hands back a
        list. Both are the same decision."""
        session = self._session([("n-1", "Jon Smtih", '["Jon Smith"]')])
        assert br.apply_pending(session, "ds-1")["articles"] == 1
        writes = [c for c in session.calls if "UPDATE articles" in c[0]]
        assert writes and writes[0][1]["author"] == "Jon Smith"

    def test_a_dry_run_writes_nothing(self):
        session = self._session([("n-1", "Jon Smtih", ["Jon Smith"])])
        result = br.apply_pending(session, "ds-1", dry_run=True)
        assert result["articles"] == 0
        assert not [c for c in session.calls if "UPDATE" in c[0]]

    def test_it_commits_nothing_itself(self):
        """The caller owns the transaction: housekeeping commits per dataset, so
        one dataset failing does not discard the writes made before it."""
        session = self._session([("n-1", "Jon Smtih", ["Jon Smith"])])
        br.apply_pending(session, "ds-1")
        session.commit.assert_not_called()

    def test_housekeeping_applies_them(self):
        from pathlib import Path

        yaml = pytest.importorskip("yaml")
        spec = yaml.safe_load(Path("k8s/argo/housekeeping-workflow.yaml").read_text())
        templates = {t["name"]: t for t in spec["spec"]["templates"]}
        groups = templates["housekeeping"]["steps"]
        names = [step["name"] for group in groups for step in group]
        assert "apply-byline-decisions" in names
        # BEFORE the refresh: the queue is then recomputed from a corpus that
        # already carries the decision, so the count a reviewer opens in the
        # morning is of what is still wrong.
        assert names.index("apply-byline-decisions") < names.index(
            "refresh-byline-queue"
        )
        # And before the gate, like the rest of the maintenance.
        assert names.index("apply-byline-decisions") < names.index("anything-owed")
        step = next(
            s for g in groups for s in g if s["name"] == "apply-byline-decisions"
        )
        assert step["continueOn"] == {"failed": True}
        source = templates["apply-byline-decisions-step"]["script"]["source"]
        assert "apply_pending" in source
        assert "SELECT id FROM datasets" in source, "every dataset, not one"
        assert "session.commit()" in source, "a commit per dataset"

    def test_the_cli_and_the_schedule_make_the_same_write(self):
        """One implementation, so a decision applied by hand and one applied by
        the schedule cannot drift apart."""
        from pathlib import Path

        source = Path("src/cli/commands/byline_report.py").read_text()
        assert "br.apply_pending(" in source
        assert "UPDATE byline_normalizations" not in source


class TestOneRowIsOneName:
    """A byline string can name two people, and a row naming two is unanswerable.

    "Alyssa Mueller, Marcus Officer" was offered as one candidate, flagged as
    carrying a job title because "Officer" is a title word and the pattern read
    the whole string. Both names are correct; the reviewer could not accept, fix
    or drop two people at once, and the title it was flagged for was a surname.
    """

    ROWS = [
        ("Alyssa Mueller, Marcus Officer", "komu.com", "University of Missouri", 3),
        ("Alyssa Mueller", "komu.com", "University of Missouri", 5),
        ("Marcus Officer, Jonathan Ketz", "komu.com", "University of Missouri", 1),
    ]

    def _rows(self):
        return {row.raw: row for row in br.review_rows(self.ROWS)}

    def test_a_co_authored_string_is_not_a_row(self):
        assert "Alyssa Mueller, Marcus Officer" not in self._rows()

    def test_each_name_is_its_own_row(self):
        assert set(self._rows()) == {
            "Alyssa Mueller",
            "Marcus Officer",
            "Jonathan Ketz",
        }

    def test_a_surname_that_is_also_a_title_is_not_flagged(self):
        """The whole reason the row was unanswerable: read on its own, "Marcus
        Officer" is a person whose surname is Officer."""
        assert br.STRAY_TITLE not in self._rows()["Marcus Officer"].signals

    def test_a_row_says_which_strings_it_came_from(self):
        """A name sharing a byline is a different question from a name alone, so
        the reviewer is shown which it is."""
        assert self._rows()["Marcus Officer"].sources == (
            "Alyssa Mueller, Marcus Officer",
            "Marcus Officer, Jonathan Ketz",
        )

    def test_the_count_is_of_stories_carrying_the_name(self):
        """Alyssa Mueller has 5 of her own and 3 with a co-author."""
        assert self._rows()["Alyssa Mueller"].articles == 8

    def test_a_real_title_is_still_flagged(self):
        rows = {row.raw: row for row in br.review_rows([("Staff Writer", "h", "o", 2)])}
        assert br.STRAY_TITLE in rows["Staff Writer"].signals


class TestADecisionReachesACoAuthoredByline:
    """The review unit is a name; the column holds a string."""

    def test_a_fix_keeps_the_co_author(self):
        assert (
            br.replace_name(
                "Alyssa Mueller, Nate Sandford", "Nate Sandford", ["Nate Sanford"]
            )
            == "Alyssa Mueller, Nate Sanford"
        )

    def test_a_drop_removes_only_that_name(self):
        """A co-authored story keeps the co-author who is real."""
        assert (
            br.replace_name("Alyssa Mueller, Sports Desk", "Sports Desk", [])
            == "Alyssa Mueller"
        )

    def test_a_string_without_the_name_is_left_alone(self):
        assert br.replace_name("Alyssa Mueller", "Nate Sandford", ["x"]) is None

    def test_a_fix_onto_a_name_already_there_does_not_double_it(self):
        """ "Nate Sandford, Nate Sanford" is one person twice; writing the name
        twice would be a new defect."""
        assert (
            br.replace_name(
                "Nate Sandford, Nate Sanford", "Nate Sandford", ["Nate Sanford"]
            )
            == "Nate Sanford"
        )

    def test_the_exact_match_still_runs_first(self):
        """One statement covers the great majority; the per-row rewrite is only
        for the bylines that carry a co-author."""
        from unittest.mock import MagicMock

        session = MagicMock()
        session.execute.return_value.rowcount = 4
        session.execute.return_value.all.return_value = []
        assert br.apply_decision(session, "ds-1", "Jon Smtih", ["Jon Smith"]) == 4
        first = session.execute.call_args_list[0].args[1]
        assert first["raw_byline"] == "Jon Smtih"
        assert first["author"] == "Jon Smith"

    def test_the_shared_query_excludes_the_exact_match(self):
        """Or a row would be written twice, and counted twice."""
        assert "a.author <> :raw_byline" in br._SHARED_SQL
        assert "a.author LIKE :like" in br._SHARED_SQL


class TestASpellingClusterIsOneReview:
    """A variant is a relationship, and it was being asked as two questions.

    "Bruce E Stidham" and "Bruce E. Stidham" were separate rows, each naming the
    other as a variant. A reviewer had to answer the same person twice and hope
    the answers agreed.
    """

    #: Three spellings of one reporter, and one unrelated name. "Joe Mcgraw" and
    #: "Joseph Mcgraw" are NOT in here: they score 0.87 against each other, under
    #: the 0.88 the matcher requires, so as far as it is concerned they are two
    #: people -- which is the matcher's documented behaviour and not this test's
    #: subject.
    ROWS = [
        ("Nate Sanford", "a.example", "Owner", 12),
        ("Nate Sandford", "a.example", "Owner", 2),
        ("Nate Sandforde", "b.example", "Owner", 1),
        ("Sandra Quite-Different", "a.example", "Owner", 4),
    ]

    def _found(self):
        return {row.raw: row for row in br.candidates(self.ROWS)}

    def test_one_row_for_the_cluster(self):
        found = self._found()
        assert "Nate Sandford" not in found
        assert "Nate Sandforde" not in found
        assert "Nate Sanford" in found

    def test_the_spelling_with_the_most_stories_leads(self):
        """The one a reviewer is most likely to keep, so it is the proposal."""
        assert self._found()["Nate Sanford"].articles == 15

    def test_three_spellings_are_one_cluster_not_two_pairs(self):
        """A relationship, not a pair: three spellings are one person, and
        pairing them would ask two questions about three rows."""
        group = self._found()["Nate Sanford"].group
        assert [g["name"] for g in group] == [
            "Nate Sanford",
            "Nate Sandford",
            "Nate Sandforde",
        ]

    def test_each_spelling_carries_its_own_count(self):
        """Which spelling is right is judged by comparing these."""
        group = self._found()["Nate Sanford"].group
        assert [g["articles"] for g in group] == [12, 2, 1]

    def test_each_spelling_says_how_it_differs(self):
        group = self._found()["Nate Sanford"].group
        assert all("differs_by" in g for g in group)

    def test_the_cluster_carries_every_hosts(self):
        row = self._found()["Nate Sanford"]
        assert row.hosts == ("a.example", "b.example")

    def test_a_name_with_no_defect_is_not_in_the_queue_at_all(self):
        """Clustering changes which rows are ONE question, not which rows are
        questions. "Sandra Quite-Different" is spelled one way and shows nothing
        wrong, so it is not offered -- before this change or after."""
        assert "Sandra Quite-Different" not in self._found()

    def test_a_name_with_no_variant_carries_no_group(self):
        rows = [
            ("Sandra Quite-Different", "a.example", "One Owner", 4),
            ("Sandra Quite-Different", "b.example", "Other Owner", 1),
        ]
        found = {row.raw: row for row in br.candidates(rows)}
        row = found["Sandra Quite-Different"]
        assert row.group == ()
        assert row.articles == 5

    def test_a_folded_spellings_other_defect_is_not_lost(self):
        """A spelling folded into a cluster keeps its own questions.

        Here the minority spelling also appears under a second, unrelated owner
        -- which is a question of its own -- and folding the row in must not
        answer it by silence.
        """
        rows = [
            ("Nate Sanford", "a.example", "One Owner", 12),
            ("Nate Sandford", "a.example", "One Owner", 2),
            ("Nate Sandford", "b.example", "Other Owner", 1),
        ]
        found = {row.raw: row for row in br.candidates(rows)}
        row = found["Nate Sanford"]
        assert br.SPELLING_VARIANT in row.signals
        assert br.CROSS_OWNER in row.signals


class TestThePageSaysWhichStoryIsWrong:
    """A byline under unrelated owners is legitimate for a stringer and for papers
    sharing copy. Nothing on the row separated that from a misattribution --
    except the line the paper printed, where it printed one.

    It answers rarely, and the tests say so: of the 1,202 stories behind Mizzou's
    175 candidates, ONE disagrees. A page built around it would be empty 174 times
    out of 175; a page that shows it when it exists hands the reviewer the one
    case they can settle without judgement.
    """

    def _session(self, bodies):
        """A session whose body query returns `(author, id, url, title, host,
        head)` rows."""
        from unittest.mock import MagicMock

        session = MagicMock()

        def execute(statement, params=None):
            result = MagicMock()
            result.all.return_value = bodies if "left(a.text" in str(statement) else []
            return result

        session.execute.side_effect = execute
        return session

    def test_a_story_whose_page_names_somebody_else_is_named(self):
        session = self._session(
            [
                (
                    "Christopher Replogle",
                    "a-1",
                    "https://www.unterrifieddemocrat.com/stories/linn-r-2",
                    "Linn R-2 hires Haslag as MS/HS Principal",
                    "www.unterrifieddemocrat.com",
                    "By Neal A. Johnson, UD Editor\n\nLINN — Linn R-2 board members",
                )
            ]
        )
        found = br.find_mismatches(session, "ds-1", ["Christopher Replogle"])
        story = found["Christopher Replogle"][0]
        assert story["printed"] == "Neal A. Johnson"
        assert story["host"] == "www.unterrifieddemocrat.com"
        assert story["article_id"] == "a-1"

    def test_a_story_whose_page_agrees_is_not_named(self):
        session = self._session(
            [
                (
                    "Neal A. Johnson",
                    "a-2",
                    "https://x",
                    "T",
                    "h",
                    "By Neal A. Johnson, UD Editor\n\nText",
                )
            ]
        )
        assert br.find_mismatches(session, "ds-1", ["Neal A. Johnson"]) == {}

    def test_a_spelling_variant_is_not_a_mismatch(self):
        """ "Neal Johnson" against "Neal A. Johnson" is one person spelled two
        ways, which the queue settles as a cluster. Naming it here would send the
        reviewer to correct a story that is not wrong."""
        session = self._session(
            [("Neal Johnson", "a-3", "https://x", "T", "h", "By Neal A. Johnson\n\nT")]
        )
        assert br.find_mismatches(session, "ds-1", ["Neal Johnson"]) == {}

    def test_a_body_with_no_printed_byline_says_nothing(self):
        """The common case: only 6.8% of bodies print one."""
        session = self._session(
            [("Karl Zinke", "a-4", "https://x", "T", "h", "The council met Tuesday.")]
        )
        assert br.find_mismatches(session, "ds-1", ["Karl Zinke"]) == {}

    def test_no_names_asks_nothing(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        assert br.find_mismatches(session, "ds-1", []) == {}
        session.execute.assert_not_called()

    def test_at_most_ten_stories_a_byline(self):
        """A reviewer settles these one at a time, and a row carrying hundreds is
        a row nobody reads."""
        bodies = [
            ("A B", f"a-{n}", "https://x", "T", "h", "By Different Person\n\nT")
            for n in range(14)
        ]
        found = br.find_mismatches(self._session(bodies), "ds-1", ["A B"])
        assert len(found["A B"]) == 10

    def test_the_queue_carries_them(self):
        """Including for every spelling folded into a cluster: the misattributed
        story may carry the minority spelling."""
        source = Path("src/services/byline_review.py").read_text()
        assert "find_mismatches(" in source
        assert '"mismatches": json.dumps(' in source


class TestTheInsertBindsWhatItNames:
    """The refresh INSERT names its columns and binds its values in two separate
    strings, and they drifted: `mismatches` was added to the VALUES list and not
    to the columns, so every refresh raised

        A value is required for bind parameter 'mismatches'

    and the nightly queue refresh would have failed silently behind its
    `continueOn: failed`. It reached main because the edit that added the column
    was a string replacement that matched nothing -- the formatter had reflowed
    the line it was looking for -- and nothing checked the two lists against each
    other.
    """

    def _insert(self):
        source = Path("src/services/byline_review.py").read_text()
        start = source.index("INSERT INTO byline_review_candidates")
        end = source.index("CURRENT_TIMESTAMP)", start)
        # The SQL is built from adjacent string literals; strip the quoting so
        # the two lists can be counted.
        return "".join(
            part
            for line in source[start:end].splitlines()
            for part in [line.strip().strip('"').strip("'").strip()]
        )

    def test_it_binds_one_value_for_every_column(self):
        sql = self._insert()
        columns = sql[sql.index("(") + 1 : sql.index(")")].split(",")
        values = sql[sql.index("VALUES (") + 8 :].split(",")
        assert len(columns) == len(values), (
            f"{len(columns)} columns and {len(values)} values: "
            f"columns {[c.strip() for c in columns]} "
            f"values {[v.strip() for v in values]}"
        )

    def test_every_column_has_a_parameter_of_its_own_name(self):
        """Except the two the statement computes: the id and the timestamp."""
        sql = self._insert()
        columns = [
            c.strip().strip('"')
            for c in sql[sql.index("(") + 1 : sql.index(")")].split(",")
        ]
        values = sql[sql.index("VALUES (") + 8 :]
        for column in columns:
            if column in ("id", "computed_at"):
                continue
            name = "raw" if column == "raw_byline" else column
            name = "label" if column == "signal_label" else name
            assert f":{name}" in values, f"{column} is named and never bound"


class TestAStoryWhoseBylineWeNeverStored:
    """The queue is built from `articles.author`. A story published with an empty
    one is invisible to review, however plainly its page names the reporter.

    On 2026-09-23 that meant nine stories had to be decided in a chat message --
    five Examiner stories printing "Karl Zinke", two printing "Gregory Orear",
    one "KMAland Trevor" (a radio brand glued to a first name) and one "Liberty
    Hospital" (not a person). The user's answer: those belong in the queue.
    """

    def _session(self, bodies):
        from unittest.mock import MagicMock

        session = MagicMock()

        def execute(statement, params=None):
            result = MagicMock()
            result.all.return_value = (
                bodies if "coalesce(trim(a.author), '') = ''" in str(statement) else []
            )
            return result

        session.execute.side_effect = execute
        return session

    ROW = (
        "a-1",
        "https://www.examiner.net/story",
        "Council approves the levy",
        "www.examiner.net",
        "CherryRoad Media",
        "Headline here\n  Tue, 03/31/2026 - 2:11pm\n  admin\n  By:\n"
        "Karl Zinke, staff\nThe council met Tuesday.",
    )

    def test_a_story_with_no_byline_is_found_by_its_page(self):
        found = br.find_unstored(self._session([self.ROW]), "ds-1")
        assert list(found) == ["Karl Zinke"]
        assert found["Karl Zinke"][0]["article_id"] == "a-1"
        assert found["Karl Zinke"][0]["host"] == "www.examiner.net"

    def test_stories_printing_one_name_are_one_question(self):
        """Five Examiner stories printing "Karl Zinke" are one question about one
        person, not five."""
        rows = [
            (f"a-{n}", "https://x", "T", "www.examiner.net", "CherryRoad", self.ROW[5])
            for n in range(5)
        ]
        found = br.find_unstored(self._session(rows), "ds-1")
        assert len(found["Karl Zinke"]) == 5
        candidates = br.unstored_candidates(found)
        assert len(candidates) == 1
        assert candidates[0].articles == 5

    def test_the_candidate_proposes_the_printed_name(self):
        """The page already says it; the reviewer confirms it."""
        found = br.find_unstored(self._session([self.ROW]), "ds-1")
        row = br.unstored_candidates(found)[0]
        assert row.raw == "Karl Zinke"
        assert row.proposed == ("Karl Zinke",)
        assert row.signals == (br.PRINTED_NOT_STORED,)

    def test_a_page_printing_nothing_is_not_a_candidate(self):
        """Most unbylined stories really are unbylined: 738 of the 773 emptied on
        2026-09-22 print no byline anywhere."""
        row = list(self.ROW)
        row[5] = "Headline\n  admin\n\n\tCalling all volunteers!"
        assert br.find_unstored(self._session([tuple(row)]), "ds-1") == {}

    def test_a_decided_name_is_not_asked_again(self):
        found = br.find_unstored(self._session([self.ROW]), "ds-1")
        assert br.unstored_candidates(found, {"Karl Zinke": []}) == []

    def test_it_is_the_first_signal_in_the_order(self):
        """The only one whose answer is already known: the page says the name."""
        assert br.SIGNAL_ORDER[0] == br.PRINTED_NOT_STORED

    def test_only_local_stories_are_asked_about(self):
        """A wire story printing an AP reporter's name is not a missing local
        byline, and 2,900 of the corpus's unbylined stories are wire from two
        months of 2025."""
        session = self._session([])
        br.find_unstored(session, "ds-1")
        statement = str(session.execute.call_args_list[0].args[0])
        assert "a.status = ANY(:statuses)" in statement

    def test_the_queue_carries_them(self):
        source = Path("src/services/byline_review.py").read_text()
        assert "find_unstored(session, dataset_id, statuses)" in source
        assert "unstored_candidates(unstored, decided)" in source
