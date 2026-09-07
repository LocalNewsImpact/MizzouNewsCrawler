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
    def __init__(self, id, url, status):
        self.id = id
        self.url = url
        self.status = status


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
    """The number this run exists to produce."""
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
            _Row("c1", "https://a.example/kept", "article"),
            _Row("c2", "https://a.example/rejected", "not_article"),
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


def test_it_takes_nothing_whose_verdict_was_overwritten():
    """`candidate_links.status` is the status NOW, not what verification
    concluded, and later stages overwrite it.

    Measured against production 2026-09-07 by whether a link has an
    article row -- which it can only have if verification let it through
    and something fetched it: `extracted` 96%, `paused` 89%. Those are
    acceptances whose verdict is gone, and reading their status as a
    verdict would score all 125,614 of them as rejections.
    """
    sql = _select_sql()
    for overwritten in ("extracted", "paused", "404", "paywall"):
        assert f"'{overwritten}'" not in sql


def test_the_ambiguous_statuses_need_the_article_check():
    """`wire` is 48% and `opinion` 49% article-bearing, so each is about
    half verification-stage and half content-stage, and nothing on the
    row says which. `wire` is admitted only where nothing was fetched;
    `opinion`, `obituary` and `weather` are not admitted at all."""
    sql = _select_sql()
    assert "NOT EXISTS" in sql and "articles a" in sql
    for content_stage in ("opinion", "obituary", "weather"):
        assert f"'{content_stage}'" not in sql


def test_sampled_out_is_never_in_the_queue():
    """Discovery's own budget decision, not a classification about the
    URL (DISCOVERY_REVIEW_QUEUE.md §3)."""
    assert "sampled_out" not in _select_sql()
