"""A link nothing has judged has no decision to backfill.

`backfill_decisions` rescores decisions that were made and not recorded.
Its select therefore takes links whose status IS a verdict -- `article`,
`not_article`, `wire`, `obituary`, `opinion`, `weather` -- or that have
an article row. A link at `discovered` has none of those: it was found,
and nothing has judged it since.

SO IT SELECTED NOTHING. On 2026-09-14 a March window returned
`considered: 0` while 500 such links sat in the corpus, and the discovery
review queue -- which reads `url_verifications` -- had nothing to show
for any of them. 563 March links had been reset to `discovered` for
re-extraction the day before; setting that status queues a link for
EXTRACTION, and review is a different destination that nothing put them
in.

`include_unjudged` admits them, and what it writes is labelled as what it
is. A first score is not a backfill: there was no decision, so the row
carries `decided_by: "prescore"` and `verdict_kind: "never_judged"`, and
is counted apart from agreement because there is nothing for it to agree
with. Folding 410 unjudged rows into an agreement rate would move a
percentage that is about something else.
"""

from tests.test_the_backlog_of_decisions_can_be_reviewed import (
    _Row,
    _rows,
    _service,
    _Sniffer,
)


def _harness(monkeypatch, rows, sniffer=None):
    svc = _service(sniffer or _Sniffer())
    _rows(svc, rows, monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )
    return svc, written


class TestTheFlagIsWhatAdmitsThem:
    def test_the_select_leaves_them_out_by_default(self):
        """THE BUG, in the statement rather than in a count: without the
        flag the status list has no `discovered` in it, so a March window
        of 500 such links considered none of them."""
        import inspect

        from src.services.url_verification import URLVerificationService

        source = inspect.getsource(URLVerificationService.backfill_decisions)
        select = source[source.index("SELECT cl.id") : source.index("params: dict")]
        assert "'discovered'" in select
        assert ":unjudged" in select, "the flag has to gate it, not a code path"

    def test_the_default_is_off(self):
        """It changes what the command means, so it is asked for."""
        import inspect

        from src.services.url_verification import URLVerificationService

        signature = inspect.signature(URLVerificationService.backfill_decisions)
        assert signature.parameters["include_unjudged"].default is False

    def test_the_cli_offers_it(self):
        from pathlib import Path

        source = Path("src/cli/commands/verification_backfill.py").read_text()
        assert '"--unjudged"' in source
        assert "include_unjudged=args.unjudged" in source


class TestWhatAFirstScoreSays:
    def test_it_is_not_called_a_backfill(self, monkeypatch):
        """`backfill` records that a decision's mechanism was not
        captured. `prescore` records that there was no decision. A
        reviewer asked "was the pipeline right" about a link the pipeline
        never ruled on is being asked a question with no answer."""
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/one", "discovered")]
        )
        svc.backfill_decisions(include_unjudged=True)
        assert written[0].meta["decided_by"] == "prescore"
        assert written[0].meta["verdict_kind"] == "never_judged"

    def test_it_does_not_invent_a_verdict(self, monkeypatch):
        """`accepted` is false for one of these -- not fetched, status not
        `article` -- so the ordinary path would label it
        `rejected_as_not_a_story`, which is a verdict nobody reached."""
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/one", "discovered")]
        )
        svc.backfill_decisions(include_unjudged=True)
        assert written[0].meta["verdict_kind"] != "rejected_as_not_a_story"
        assert written[0].new_status == "discovered"

    def test_it_has_nothing_to_agree_with(self, monkeypatch):
        """Absent, not false. Anything reading the key without checking
        `verdict_kind` first would count a false as a disagreement."""
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/one", "discovered")]
        )
        svc.backfill_decisions(include_unjudged=True)
        assert "agrees_with_recorded" not in written[0].meta

    def test_it_still_records_which_mechanism_scored_it(self, monkeypatch):
        """A rule hit here is a rule's opinion, not the model's, and the
        queue tells them apart on this key -- the same way it does for a
        rescore."""
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/one", "discovered")]
        )
        svc.backfill_decisions(include_unjudged=True)
        assert written[0].meta["rescored_by"] == "sniffer"

    def test_it_carries_the_score_and_the_link(self, monkeypatch):
        svc, written = _harness(
            monkeypatch,
            [_Row("c1", "https://a.example/one", "discovered", dataset_id="d1")],
        )
        svc.backfill_decisions(include_unjudged=True)
        assert written[0].candidate_link_id == "c1"
        assert written[0].dataset_id == "d1"
        assert written[0].storysniffer_result is True


class TestItIsCountedApart:
    def test_it_is_not_an_agreement(self, monkeypatch):
        svc, _ = _harness(
            monkeypatch, [_Row("c1", "https://a.example/one", "discovered")]
        )
        counts = svc.backfill_decisions(include_unjudged=True)
        assert counts["never_judged"] == 1
        assert counts["agree"] == 0
        assert counts["disagree"] == 0

    def test_it_does_not_move_the_error_rate(self, monkeypatch):
        """410 of the 500 March rows were unjudged. Counted as agreements
        they would have reported a 0% error rate over a population that
        had not been judged at all."""
        svc, _ = _harness(
            monkeypatch,
            [
                _Row("c1", "https://a.example/one", "discovered"),
                _Row("c2", "https://a.example/two", "discovered"),
                # One real disagreement: rejected as not a story, and the
                # model says story.
                _Row("c3", "https://a.example/three", "not_article"),
            ],
        )
        counts = svc.backfill_decisions(include_unjudged=True)
        assert counts["never_judged"] == 2
        assert counts["agree"] + counts["disagree"] == 1
        assert counts["disagree"] == 1

    def test_it_is_still_written(self, monkeypatch):
        """Counted apart, not skipped -- the row is the whole point."""
        svc, written = _harness(
            monkeypatch,
            [
                _Row("c1", "https://a.example/one", "discovered"),
                _Row("c2", "https://a.example/two", "discovered"),
            ],
        )
        counts = svc.backfill_decisions(include_unjudged=True)
        assert counts["written"] == 2
        assert len(written) == 2

    def test_a_dry_run_writes_none_of_them(self, monkeypatch):
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/one", "discovered")]
        )
        counts = svc.backfill_decisions(include_unjudged=True, dry_run=True)
        assert counts["never_judged"] == 1
        assert counts["written"] == 0
        assert written == []


class TestAJudgedLinkIsStillJudged:
    def test_a_discovered_link_that_was_fetched_is_not_unjudged(self, monkeypatch):
        """An article row means verification accepted it, whatever the
        status has since been overwritten to. `discovered` plus a body is
        a decision that was made, so it rescores rather than prescores."""
        svc, written = _harness(
            monkeypatch,
            [
                _Row(
                    "c1",
                    "https://a.example/one",
                    "discovered",
                    was_fetched=True,
                    article_status="enriched",
                )
            ],
        )
        counts = svc.backfill_decisions(include_unjudged=True)
        assert counts["never_judged"] == 0
        assert written[0].meta["decided_by"] == "backfill"
        assert written[0].meta["verdict_kind"] == "accepted"

    def test_the_ordinary_path_is_untouched(self, monkeypatch):
        """The flag admits more rows; it must not change how the rows
        that were always admitted are read."""
        svc, written = _harness(
            monkeypatch, [_Row("c1", "https://a.example/one", "wire")]
        )
        counts = svc.backfill_decisions(include_unjudged=True)
        assert written[0].meta["verdict_kind"] == "rejected_by_topic_rule"
        assert counts["topic_held"] == 1
