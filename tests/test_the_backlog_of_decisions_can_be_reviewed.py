"""The decisions taken before anything recorded them can be reviewed.

`url_verifications` holds a row per decision since #517, but 262,137
candidate links were decided before that and kept only their verdict, in
`candidate_links.status`. So the discovery review queue has nothing to
show for any of them -- and discovery has been idle since 2026-08-12, so
waiting for crawling to resume means waiting indefinitely.

storysniffer is a local model: with the HTTP pre-check off, `verify_url`
calls `sniffer.guess()` and nothing else. The whole backlog can be scored
in one offline pass, which is what makes this possible at all.

What it writes is a RESCORE, not the original decision. The pattern
filter ran first and both the rules and the model version have changed
since, so a disagreement between the rescore and the recorded verdict is
the finding rather than a defect: it is the first estimate of the error
rate before any person opens a row. Every row says `backfill` in
`decided_by` so nothing downstream can read it as what the pipeline
decided at the time.
"""

import pytest


class _Sniffer:
    """storysniffer, answering by URL so a fixture can disagree."""

    def __init__(self, answers=None, default=True):
        self.answers = answers or {}
        self.default = default
        self.asked = []

    def guess(self, url):
        self.asked.append(url)
        return self.answers.get(url, self.default)


class _Session:
    """The requests session, which the backfill must never touch."""

    def __init__(self):
        self.headers = {}

    def head(self, *args, **kwargs):
        raise RuntimeError("the backfill must not make a request")

    def get(self, *args, **kwargs):
        raise RuntimeError("the backfill must not make a request")


def _service(sniffer):
    from src.services.url_verification import URLVerificationService

    svc = URLVerificationService(http_session=_Session(), run_http_precheck=False)
    svc.sniffer = sniffer
    return svc


class _Row:
    """A candidate link as the select returns it.

    `was_fetched` is the whole verdict: nothing fetches a URL that
    verification rejected, so an article row means it was accepted --
    whatever the status has since been overwritten to."""

    def __init__(self, id, url, status, was_fetched=False, article_status=None):
        self.id = id
        self.url = url
        self.status = status
        self.was_fetched = was_fetched
        # What the content stage concluded once it had the body. The
        # only thing that can say storysniffer was wrong about an
        # acceptance.
        self.article_status = article_status or ("enriched" if was_fetched else None)


def _rows(svc, rows, monkeypatch):
    """Stand in for the select, so these test the decision and not SQL."""

    class _Result:
        def fetchall(self):
            return rows

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            return _Result()

    monkeypatch.setattr(svc.db, "get_session", lambda: _Session())


# --- it does not go near the network -----------------------------------------


def test_scoring_makes_no_request(monkeypatch):
    """The property the whole approach rests on. A backfill that fetched
    262,137 URLs would need the proxy, would be blocked, and would take
    days -- `_Session` raises on any request, so this fails loudly rather
    than quietly becoming a crawl."""
    sniffer = _Sniffer()
    svc = _service(sniffer)
    result = svc.verify_url("https://a.example/story")
    assert result["storysniffer_result"] is True
    assert sniffer.asked == ["https://a.example/story"]


# --- what a row says ----------------------------------------------------------


def test_a_backfilled_row_never_claims_to_be_the_original_decision(monkeypatch):
    """The mechanism that decided at the time was not recorded and cannot
    be recovered. Saying `sniffer` here would invent it."""
    svc = _service(_Sniffer())
    _rows(svc, [_Row("c1", "https://a.example/one", "article")], monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )

    svc.backfill_decisions()

    assert written[0].meta["decided_by"] == "backfill"
    assert written[0].meta["rescored_by"] == "sniffer"


def test_the_recorded_verdict_is_kept_as_the_status(monkeypatch):
    """`new_status` is what the pipeline concluded, not what the rescore
    thinks. The rescore is a second opinion beside it, never a rewrite."""
    svc = _service(_Sniffer(default=True))
    _rows(svc, [_Row("c1", "https://a.example/one", "not_article")], monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )

    svc.backfill_decisions()

    assert written[0].new_status == "not_article"
    assert written[0].storysniffer_result is True
    assert written[0].meta["agrees_with_recorded"] is False


def test_previous_status_is_left_unknown(monkeypatch):
    """It is not knowable. A row that guessed would be a row a reviewer
    could be misled by."""
    svc = _service(_Sniffer())
    _rows(svc, [_Row("c1", "https://a.example/one", "article")], monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )

    svc.backfill_decisions()

    assert written[0].previous_status is None


# --- the disagreement is the point --------------------------------------------


def test_agreement_and_disagreement_are_counted(monkeypatch):
    """The number this run exists to produce, over the two decisions
    that answer the same question the sniffer does."""
    sniffer = _Sniffer(
        answers={
            "https://a.example/kept": True,
            "https://a.example/rejected": True,
        }
    )
    svc = _service(sniffer)
    _rows(
        svc,
        [
            _Row("c1", "https://a.example/kept", "article", False),
            _Row("c2", "https://a.example/rejected", "not_article", False),
        ],
        monkeypatch,
    )
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    counts = svc.backfill_decisions()

    assert counts["considered"] == 2
    assert counts["agree"] == 1
    assert counts["disagree"] == 1


def test_a_dry_run_counts_without_writing(monkeypatch):
    svc = _service(_Sniffer())
    _rows(svc, [_Row("c1", "https://a.example/one", "not_article")], monkeypatch)
    called = []
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: called.append(rows))
    monkeypatch.setattr(
        svc, "_ensure_job", lambda name: pytest.fail("a dry run opens no job")
    )

    counts = svc.backfill_decisions(dry_run=True)

    assert counts["considered"] == 1
    assert counts["written"] == 0
    assert called == []


def test_the_limit_is_respected(monkeypatch):
    svc = _service(_Sniffer())
    _rows(
        svc,
        [_Row(f"c{n}", f"https://a.example/{n}", "article") for n in range(10)],
        monkeypatch,
    )
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    counts = svc.backfill_decisions(limit=3)

    assert counts["considered"] == 3


# --- failure is loud here, unlike the live path -------------------------------


def test_a_failed_write_raises(monkeypatch):
    """`record_verifications` swallows its failures on purpose: a
    verification run must not stop because it could not write its own
    audit row. That reasoning inverts here -- this run exists ONLY to
    write those rows, so a swallowed failure is a backfill that reports
    success and produces nothing."""
    svc = _service(_Sniffer())

    class _Broken:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add_all(self, rows):
            raise RuntimeError("no")

    monkeypatch.setattr(svc.db, "get_session", lambda: _Broken())
    with pytest.raises(RuntimeError):
        svc._write_backfilled([object()])


def test_no_job_means_nothing_is_written(monkeypatch):
    """Rather than rows with a null job id, which the column forbids."""
    svc = _service(_Sniffer())
    _rows(svc, [_Row("c1", "https://a.example/one", "article")], monkeypatch)
    monkeypatch.setattr(svc, "_ensure_job", lambda name: None)
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: pytest.fail("nothing to write")
    )

    counts = svc.backfill_decisions()

    assert counts["written"] == 0


# --- only where the verdict survived ------------------------------------------


def _select_sql():
    """The statement the backfill runs, without the prose about it.

    Comments are stripped: they explain which statuses were excluded and
    why, so a test reading them would pass on the explanation instead of
    the rule.
    """
    import inspect

    from src.services.url_verification import URLVerificationService

    source = inspect.getsource(URLVerificationService.backfill_decisions)
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def test_acceptance_is_read_from_the_fetch_not_the_status():
    """`candidate_links.status` is overwritten by later stages, so a link
    verification accepted can read `extracted`, `paused`, `obituary` or
    `wire` today. Measured against production 2026-09-07, 48% of `wire`
    and 49% of `opinion` rows have an article -- each of those statuses
    is written at both stages and neither can be read as a verdict.

    Nothing fetches a URL that verification rejected, so the article row
    is the verdict and it cannot be overwritten."""
    sql = _select_sql()
    assert "a.id IS NOT NULL" in sql
    assert "LEFT JOIN articles a" in sql


def test_both_error_types_are_selected():
    """A queue that only held rejections could not find a type I, and one
    that only held acceptances could not find the type II -- which is the
    error with no other surface, because a rejected URL leaves no row."""
    sql = _select_sql()
    assert "cl.status = 'article'" in sql
    assert "'not_article', 'wire'" in sql


def test_sampled_out_is_never_in_the_queue():
    """Discovery's own budget decision, not a classification about the
    URL (DISCOVERY_REVIEW_QUEUE.md §3)."""
    sql = _select_sql()
    assert "sampled_out" not in sql
    # Nor the statuses that are not verification outcomes at all.
    for other in ("'discovered'", "'404'", "'skipped'"):
        assert other not in sql


# --- the two errors are counted apart -----------------------------------------


def test_a_type_i_is_an_acceptance_the_model_rejects(monkeypatch):
    """A fetch spent on something that was not a story. The content stage
    catches these anyway, which is why they cost compute rather than the
    corpus."""
    svc = _service(_Sniffer(default=False))
    _rows(
        svc, [_Row("c1", "https://a.example/section/", "extracted", True)], monkeypatch
    )
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    counts = svc.backfill_decisions()

    assert counts["type_i"] == 1
    assert counts["type_ii"] == 0


def test_a_type_ii_is_a_rejection_the_model_calls_a_story(monkeypatch):
    """The error with no other surface: no article row, no status, no
    telemetry, and nothing downstream that can notice it went missing."""
    svc = _service(_Sniffer(default=True))
    _rows(
        svc, [_Row("c1", "https://a.example/story", "not_article", False)], monkeypatch
    )
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    counts = svc.backfill_decisions()

    assert counts["type_ii"] == 1
    assert counts["type_i"] == 0


def test_a_fetched_link_is_an_acceptance_whatever_its_status_says(monkeypatch):
    """The case that made the earlier version wrong: `wire` with an
    article row was ACCEPTED by verification and called wire afterwards
    by content analysis. Reading the status would score it a rejection
    and count a type II that never happened."""
    svc = _service(_Sniffer(default=True))
    _rows(svc, [_Row("c1", "https://a.example/ap-story", "wire", True)], monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )

    counts = svc.backfill_decisions()

    assert counts["agree"] == 1, "accepted and called a story: no disagreement"
    assert counts["type_ii"] == 0
    assert written[0].new_status == "wire"


# --- scoping to data somebody has cleaned -------------------------------------


def test_dates_bound_the_run():
    """An accepted link is dated by its article's publish date and a
    rejected one by when it was found -- it was never fetched, so that is
    the only date it has. One coalesce, not two code paths."""
    sql = _select_sql()
    assert "coalesce(a.publish_date, cl.discovered_at) >= CAST(:since AS date)" in sql
    assert "coalesce(a.publish_date, cl.discovered_at) < CAST(:until AS date)" in sql


# --- two questions, one record ------------------------------------------------


def test_a_wire_rejection_is_not_a_disagreement(monkeypatch):
    """A wire story IS a story. storysniffer admitting it is correct and
    the wire filter rejecting it is correct: the two answered different
    questions -- "is this a story?" and "do we want it?" -- and both were
    right. Counting that as a type II reports an error where nothing
    failed, on 40,651 links."""
    svc = _service(_Sniffer(default=True))
    _rows(svc, [_Row("c1", "https://a.example/ap", "wire", False)], monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )

    counts = svc.backfill_decisions()

    assert counts["type_ii"] == 0
    assert counts["disagree"] == 0
    assert counts["wire_held"] == 1
    # And the row says so, rather than claiming an agreement it cannot have.
    assert written[0].meta["verdict_kind"] == "rejected_as_wire"
    assert written[0].meta["agrees_with_recorded"] is None


def test_the_row_says_which_question_was_answered(monkeypatch):
    """The queue asks the reviewer about both judgements on one record,
    in one pass. It can only do that if the row says which question the
    pipeline's decision answered."""
    svc = _service(_Sniffer(default=True))
    _rows(
        svc,
        [
            _Row("c1", "https://a.example/one", "extracted", True),
            _Row("c2", "https://a.example/two", "not_article", False),
            _Row("c3", "https://a.example/three", "wire", False),
        ],
        monkeypatch,
    )
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )

    svc.backfill_decisions()

    assert [r.meta["verdict_kind"] for r in written] == [
        "accepted",
        "rejected_as_not_a_story",
        "rejected_as_wire",
    ]


# --- the score the model can actually give -----------------------------------


class _Model:
    """`path_only_model`, returning log-probabilities like the real one."""

    def __init__(self, pairs):
        self.pairs = pairs
        self.seen = []

    def predict_log_proba(self, frame):
        self.seen.append(frame)
        return [self.pairs]


def test_the_margin_comes_from_log_space_not_predict_proba():
    """`predict_proba` saturates -- 97.5% of 3,000 production URLs sit at
    exactly 0.0 or 1.0 -- which is where "there is no confidence signal"
    came from. It was the wrong output: the exponential destroys the
    information and it survives in logs, 2,990 distinct margins over the
    same 3,000 URLs."""
    svc = _service(_Sniffer())
    svc.sniffer.path_only_model = _Model([-12.0, 3.5])

    assert svc.score_margin("https://a.example/story") == pytest.approx(15.5)


def test_a_model_that_cannot_score_leaves_the_row_without_one():
    """A missing score is not a reason to fail a backfill of 44,000
    rows."""
    svc = _service(_Sniffer())

    class _Broken:
        def predict_log_proba(self, frame):
            raise RuntimeError("no")

    svc.sniffer.path_only_model = _Broken()
    assert svc.score_margin("https://a.example/story") is None

    delattr(svc.sniffer, "path_only_model")
    assert svc.score_margin("https://a.example/story") is None


def test_it_scores_the_path_not_the_whole_url():
    """The path is the only feature a pre-fetch model may use, and it is
    what the model was fitted on."""
    svc = _service(_Sniffer())
    model = _Model([-1.0, 1.0])
    svc.sniffer.path_only_model = model

    svc.score_margin("https://a.example/news/story?utm=1")

    frame = model.seen[0]
    assert list(frame["path"]) == ["/news/story"]


def test_the_margin_is_recorded_on_every_row(monkeypatch):
    """From the first row, so the labels can later say whether it ranks
    better than the mechanisms' disagreement does."""
    svc = _service(_Sniffer())
    svc.sniffer.path_only_model = _Model([-2.0, 2.0])
    _rows(svc, [_Row("c1", "https://a.example/one", "not_article", False)], monkeypatch)
    written = []
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(
        svc, "_write_backfilled", lambda rows: written.extend(rows) or len(rows)
    )

    svc.backfill_decisions()

    assert written[0].verification_confidence == pytest.approx(4.0)


# --- what storysniffer is judged against --------------------------------------


def test_wire_is_not_a_storysniffer_error(monkeypatch):
    """It answers one question: IS THIS AN ARTICLE. A wire story is an
    article, so admitting it was correct -- calling it wire afterwards is
    the other question and does not make the first answer wrong.

    On March Mizzou, 9,296 of 29,950 accepted links end as wire. Scoring
    those against storysniffer would invent an enormous error rate."""
    svc = _service(_Sniffer(default=True))
    _rows(
        svc,
        [_Row("c1", "https://a.example/ap", "wire", True, article_status="wire")],
        monkeypatch,
    )
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    counts = svc.backfill_decisions()

    assert counts["agree"] == 1
    assert counts["type_i"] == 0


@pytest.mark.parametrize("later", ["obituary", "opinion", "weather", "out_of_scope"])
def test_none_of_the_topic_calls_make_it_wrong(monkeypatch, later):
    """Same argument, for every other thing the content stage may decide
    an article is. They are all articles."""
    svc = _service(_Sniffer(default=True))
    _rows(
        svc,
        [_Row("c1", "https://a.example/x", "extracted", True, article_status=later)],
        monkeypatch,
    )
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    assert svc.backfill_decisions()["type_i"] == 0


def test_not_article_after_reading_the_body_is_the_type_i(monkeypatch):
    """The one verdict that does make it wrong. The content stage had the
    text and said the page is not a story -- so accepting it was a false
    positive, and it is the only kind there is.

    158 of March Mizzou's 29,950 acceptances are in this state, which is
    the 0.4% the spec predicted."""
    svc = _service(_Sniffer(default=True))
    _rows(
        svc,
        [
            _Row(
                "c1",
                "https://a.example/section/",
                "not_article",
                True,
                article_status="not_article",
            )
        ],
        monkeypatch,
    )
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    counts = svc.backfill_decisions()

    assert counts["type_i"] == 1
    assert counts["agree"] == 0


def test_an_unfetched_link_is_judged_on_the_claim_not_the_body(monkeypatch):
    """Nothing read it, so there is no content-stage verdict to use. The
    pipeline's own call is the only claim available -- and it is a claim,
    not truth, which is what the review is for."""
    svc = _service(_Sniffer(default=True))
    _rows(svc, [_Row("c1", "https://a.example/s", "not_article", False)], monkeypatch)
    monkeypatch.setattr(svc, "_ensure_job", lambda name: "job-1")
    monkeypatch.setattr(svc, "_write_backfilled", lambda rows: len(rows))

    assert svc.backfill_decisions()["type_ii"] == 1
