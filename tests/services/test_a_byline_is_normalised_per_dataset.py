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
        assert json.loads(rows["Nate Sandford"]["variants"]) == ["Nate Sanford"]
        assert json.loads(rows["Nate Sandford"]["differs_by"]) == [br.DIFF_SPELLING]

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
