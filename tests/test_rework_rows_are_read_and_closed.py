"""Each housekeeping stage reads its own rows from `pipeline_rework` and
closes them when it is done -- and the statements say so.

The integration suite proves these statements against Postgres. These
run without one and pin what each function asks the session for: the
stage and record type it is scoped to, that an empty list does nothing,
that a closed row is never reopened, and that settling one stage never
touches another's rows. The user-facing rule underneath all of it: an
empty result means nothing to do, never "no filter".
"""

from unittest.mock import Mock, patch

import pytest


def _session(rows=(), rowcount=0):
    """A session whose every execute returns `rows` and `rowcount`."""
    result = Mock()
    result.fetchall.return_value = [(r,) for r in rows]
    result.rowcount = rowcount
    session = Mock()
    session.execute.return_value = result
    return session


def _sql(session, call=0):
    return str(session.execute.call_args_list[call].args[0])


def _params(session, call=0):
    args = session.execute.call_args_list[call].args
    return args[1] if len(args) > 1 else session.execute.call_args_list[call].kwargs


# --- extraction ---------------------------------------------------------------------


def test_extraction_joins_the_flag_to_the_status():
    """Flagged AND ready. The status alone is the whole backlog -- 4,802
    links sit at `article` -- and the flag alone says nothing about whether
    the record is ready for THIS stage."""
    from src.cli.commands.extraction import _links_owed_a_fetch

    session = _session(rows=["l1", "l2"])
    assert _links_owed_a_fetch(session) == ["l1", "l2"]
    sql = _sql(session)
    assert "record_type = 'candidate_link'" in sql
    assert "done_at IS NULL" in sql, "the flag"
    assert "cl.status = :fetchable" in sql, "the status"
    assert "NOT EXISTS" in sql, "a link with an article owes no fetch"
    assert "stage" not in sql, (
        "the stage column does not select: a record is carried by the join "
        "of its flag and its status, not by which stage it entered at"
    )


def test_extraction_with_no_rows_returns_an_empty_list_not_none():
    """`None` reads as "no filter" to a caller. `[]` reads as nothing."""
    from src.cli.commands.extraction import _links_owed_a_fetch

    assert _links_owed_a_fetch(_session()) == []


def test_settling_closes_a_record_that_has_left_every_stage_status():
    """A record is finished when no stage reads its status any more --
    in the export, retracted, or a kind nothing enriches. Settled on the
    status and never on having been attempted."""
    from src.pipeline.rework import settle

    session = _session(rowcount=3)
    assert settle(session) == 3
    sql = _sql(session)
    assert "outcome = s.status" in sql, "the outcome is the status it reached"
    assert "done_at IS NULL" in sql, "a closed row is never re-closed"
    assert "s.status <> ALL(:articles)" in sql
    assert "s.status <> ALL(:links)" in sql
    params = _params(session)
    assert "cleaned" in params["articles"] and "labeled" in params["articles"]
    assert params["links"] == ["article"]
    session.commit.assert_called_once()


def test_a_record_still_in_a_stage_status_keeps_its_row():
    """`cleaned` and `labeled` are statuses a stage reads, so they are NOT
    in the closing condition: an article this run moved to `labeled` keeps
    its row and the enrich step of the same run takes it. The first version
    wrote a new row for the next stage instead, and fired on a status the
    article did not hold yet -- "0 articles queued for classification"."""
    from src.pipeline.rework import settle

    session = _session()
    settle(session)
    params = _params(session)
    assert set(params["articles"]) == {"cleaned", "labeled", "local"}


def test_a_missing_rowcount_is_zero_not_none():
    from src.pipeline.rework import settle

    session = _session()
    session.execute.return_value.rowcount = None
    assert settle(session) == 0


def test_the_work_queue_path_settles_nothing_and_raises_nothing():
    """`rework_ids` is read at the end of every batch, and the work-queue
    path never enters the branch that fills it. Declared at the top of
    the batch, not in the branch: otherwise the read is an
    UnboundLocalError and the batch dies after doing the work."""
    import inspect

    from src.cli.commands import extraction

    body = inspect.getsource(extraction._process_batch)
    before_branch = body.split('if getattr(args, "rework", False) is True:')[0]
    assert "rework_ids = None" in before_branch


# --- classification ---------------------------------------------------------------


def test_classification_joins_the_flag_to_the_statuses_it_reads():
    """The statuses come from the stage, the flag from the table. 450
    articles sit at `cleaned`; 107 of them were put there by a decision."""
    from src.services.classification_service import ArticleClassificationService

    session = _session(rows=["a1"])
    owed = ArticleClassificationService._articles_owed_a_classification(
        session, ["cleaned", "local"]
    )
    assert owed == ["a1"]
    sql = _sql(session)
    assert "a.status = ANY(:statuses)" in sql, "the status"
    assert "done_at IS NULL" in sql, "the flag"
    assert _params(session)["statuses"] == ["cleaned", "local"]


def test_an_article_inherits_the_flag_from_its_link():
    """When a decision rewound a URL there was no article to name. The
    article a fetch produces is the record the remaining stages act on, so
    the flag reaches it through `candidate_link_id` -- which is what lets
    one run carry a record from fetch to enrichment with no stage writing a
    row."""
    from src.services.classification_service import ArticleClassificationService

    session = _session(rows=["a1"])
    ArticleClassificationService._articles_owed_a_classification(session, ["cleaned"])
    sql = _sql(session)
    assert "r.record_type = 'article' AND r.record_id = a.id" in sql
    assert "r.record_id = a.candidate_link_id" in sql


def test_classification_settles_by_status_and_queues_nothing():
    """It used to write an `enrich` row here. That put the handoff in two
    places and fired on a status the article might not hold yet; the join
    does it instead."""
    from src.services.classification_service import ArticleClassificationService

    session = _session(rowcount=1)
    ArticleClassificationService._settle_rework(session)
    sql = _sql(session)
    assert "outcome = s.status" in sql
    assert "INSERT INTO pipeline_rework" not in sql, "no stage queues another"


def test_classify_with_rework_selects_only_the_owed_ids():
    """The service passes the ids as `only_article_ids` under `--rework`
    and passes nothing extra otherwise, so the pipeline's own `analyze`
    and every test double of it are untouched."""
    from src.services.classification_service import ArticleClassificationService

    svc = ArticleClassificationService(_session())
    seen = {}

    def select(*args, **kwargs):
        seen.update(kwargs)
        return []

    with (
        patch.object(svc, "_select_articles", side_effect=select),
        patch.object(svc, "_articles_owed_a_classification", return_value=["a1"]),
    ):
        stats = svc.apply_classification(
            Mock(model_version="v", model_identifier="m"),
            label_version="v1",
            statuses=["cleaned"],
            limit=10,
            rework=True,
        )
    assert seen["only_article_ids"] == ["a1"]
    assert stats.labeled == 0


def test_classify_without_rework_passes_no_extra_keyword():
    from src.services.classification_service import ArticleClassificationService

    svc = ArticleClassificationService(_session())
    seen = {}

    def select(*args, **kwargs):
        seen.update(kwargs)
        return []

    with (
        patch.object(svc, "_select_articles", side_effect=select),
        patch.object(svc, "_articles_owed_a_classification") as owed,
    ):
        svc.apply_classification(
            Mock(model_version="v", model_identifier="m"),
            label_version="v1",
            statuses=["cleaned"],
            limit=10,
        )
    assert "only_article_ids" not in seen
    owed.assert_not_called()


def test_classify_with_rework_and_nothing_owed_selects_nothing():
    """Not "selects with an empty filter" -- does not select at all."""
    from src.services.classification_service import ArticleClassificationService

    svc = ArticleClassificationService(_session())
    with (
        patch.object(svc, "_select_articles", return_value=[]) as select,
        patch.object(svc, "_articles_owed_a_classification", return_value=[]),
    ):
        stats = svc.apply_classification(
            Mock(model_version="v", model_identifier="m"),
            label_version="v1",
            statuses=["cleaned"],
            limit=10,
            rework=True,
        )
    select.assert_not_called()
    assert stats.processed == 0


# --- enrichment -----------------------------------------------------------------------


def test_enrichment_joins_the_flag_to_labeled():
    from src.enrichment import repository

    session = _session(rows=["a1", "a2"])
    assert repository.articles_owed_enrichment(session) == ["a1", "a2"]
    sql = _sql(session)
    assert "a.status = ANY(:statuses)" in sql and "done_at IS NULL" in sql
    assert _params(session)["statuses"] == ["labeled"]


def test_enrichment_settles_by_status(session=None):
    """An article whose enrichment failed is still `labeled`, still owes
    the work, and tomorrow's run finds it."""
    from src.enrichment import repository

    session = _session(rowcount=1)
    assert repository.settle_enrichment_rework(session) == 1
    sql = _sql(session)
    assert "outcome = s.status" in sql
    assert "INSERT INTO pipeline_rework" not in sql, "the chain ends here"


# --- the enrich command, end to end through its branches --------------------------


def _backfill_args(**overrides):
    args = Mock()
    args.enrich_action = "backfill"
    args.dataset = None
    args.dry_run = False
    args.ids_file = None
    args.rework = True
    args.concurrency = 1
    args.limit = None
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


@pytest.fixture
def enrichment_env():
    """`handle_enrichment_command` with the database and the model out."""
    db = Mock()
    session = Mock()
    db.get_session.return_value.__enter__ = Mock(return_value=session)
    db.get_session.return_value.__exit__ = Mock(return_value=False)
    with (
        patch("src.models.database.DatabaseManager", return_value=db),
        patch("src.enrichment.repository.articles_owed_enrichment") as owed,
        patch("src.enrichment.repository.select_by_ids") as by_ids,
        patch("src.enrichment.repository.dataset_profile") as profile,
        patch("src.enrichment.repository.settle_enrichment_rework") as settle,
        patch("src.cli.commands.enrichment._process") as process,
        patch("src.utils.dataset_utils.resolve_dataset_id", return_value=None),
    ):
        yield Mock(
            db=db,
            session=session,
            owed=owed,
            by_ids=by_ids,
            profile=profile,
            settle=settle,
            process=process,
        )


def test_backfill_with_rework_and_nothing_owed_does_nothing(enrichment_env, capsys):
    from src.cli.commands.enrichment import handle_enrichment_command

    enrichment_env.owed.return_value = []
    assert handle_enrichment_command(_backfill_args()) == 0
    enrichment_env.by_ids.assert_not_called()
    enrichment_env.process.assert_not_called()
    assert "nothing owes enrichment" in capsys.readouterr().out


def test_backfill_with_rework_enriches_the_owed_ids_and_settles_them(
    enrichment_env, capsys
):
    from src.cli.commands.enrichment import handle_enrichment_command

    candidate = Mock(id="a1", dataset_slug="mo")
    enrichment_env.owed.return_value = ["a1", "a2"]
    enrichment_env.by_ids.return_value = Mock(
        candidates=[candidate], rejected={"a2": "already enriched"}
    )
    enrichment_env.process.return_value = {
        "counts": {"a1": 1},
        "spent": 0,
        "halted": False,
    }
    enrichment_env.settle.return_value = 1

    assert handle_enrichment_command(_backfill_args()) == 0

    assert enrichment_env.by_ids.call_args.args[1] == ["a1", "a2"]
    assert enrichment_env.settle.call_args.args[1] == ["a1"]
    out = capsys.readouterr().out
    assert "skip a2: already enriched" in out
    assert "rework: 1 rows settled" in out


def test_backfill_with_an_ids_file_does_not_touch_the_rework_table(
    enrichment_env, tmp_path
):
    """The file form is the hand-run tool; it must not settle rows it
    did not read."""
    from src.cli.commands.enrichment import handle_enrichment_command

    ids = tmp_path / "ids.txt"
    ids.write_text("# a comment\na9\n\n")
    enrichment_env.by_ids.return_value = Mock(candidates=[], rejected={})

    assert (
        handle_enrichment_command(_backfill_args(rework=False, ids_file=str(ids))) == 0
    )

    enrichment_env.owed.assert_not_called()
    assert enrichment_env.by_ids.call_args.args[1] == ["a9"]
    enrichment_env.settle.assert_not_called()


def test_backfill_with_neither_is_refused(enrichment_env):
    from src.cli.commands.enrichment import handle_enrichment_command

    assert handle_enrichment_command(_backfill_args(rework=False)) != 0
    enrichment_env.by_ids.assert_not_called()


# --- a rewound article is re-labelled --------------------------------------------


def test_rework_classifies_an_article_that_already_has_a_label():
    """`include_existing=False` skips an article that already carries a
    label for this version. Right for the pipeline -- it would re-label the
    corpus nightly -- and wrong for housekeeping: every rewound record was
    labelled BEFORE the reviewer sent it back, and that label is what the
    review disagreed with.

    All 107 articles in the first real run carried a `default` label. Every
    one was excluded, the stage reported `processed=0 labeled=0 skipped=0
    errors=0`, closed no rows, and the workflow called it a success."""
    import inspect

    from src.cli.commands import analysis

    source = inspect.getsource(analysis)
    assert 'include_existing=args.force or getattr(args, "rework", False) is True' in (
        source
    ), "a rework run must re-label an article it was sent back"


def test_the_pipeline_still_skips_what_it_has_already_labelled():
    """The other half: without --rework and without --force, nothing
    re-labels. A run that re-labelled the corpus every night would spend
    the whole window on work already done."""
    import inspect

    from src.services.classification_service import ArticleClassificationService

    source = inspect.getsource(ArticleClassificationService._select_articles)
    assert "if not include_existing:" in source
    assert "ArticleLabel.label_version == label_version" in source


# --- a fetched link is finished with extraction ----------------------------------


def test_a_link_whose_article_is_terminal_is_closed():
    """A link keeps the status `article` after its fetch, and that is
    extraction's INPUT status -- so closing on status alone leaves the row
    open forever, while both the queue and `links_to_fetch` correctly
    refuse to serve a link that already has an article.

    Seven rows sat in exactly that state, and a run spent its whole window
    asking the queue for them: "Work queue returned 0 articles - domains in
    cooldown, will retry", batch after batch, with 158 records of real work
    waiting behind the step."""
    from src.pipeline.rework import settle

    session = _session(rowcount=1)
    settle(session)
    sql = _sql(session)
    assert "NOT EXISTS (" in sql
    assert "a.candidate_link_id = r.record_id" in sql
    assert (
        "a.status = ANY(:articles)" in sql
    ), "closed only once the ARTICLE has nothing owing either"


def test_a_link_whose_article_still_has_work_keeps_its_row():
    """The open row is what carries the article: it inherits the flag
    through its link, which is how one run takes a record from fetch to
    enrichment. Closing it early would strand the article."""
    from src.pipeline.rework import settle

    session = _session()
    settle(session)
    sql = " ".join(_sql(session).split())
    # An article still in a stage status prevents the close: the condition
    # requires that NO article for the link holds one.
    assert (
        "AND NOT EXISTS (SELECT 1 FROM articles a "
        "WHERE a.candidate_link_id = r.record_id "
        "AND a.status = ANY(:articles))" in sql
    )


def test_extraction_stops_when_no_link_is_ready_to_fetch():
    """On the queue path the crawler never consulted the set, so an empty
    answer read as "cooldown, will retry" and the loop ran to the
    deadline."""
    import inspect

    from src.cli.commands import extraction

    body = inspect.getsource(extraction._process_batch)
    guard = body.split("if USE_WORK_QUEUE:")[0]
    assert "_links_owed_a_fetch(session)" in guard, "asked before either path runs"
    assert "no link is ready to fetch" in guard
    # And asked ONCE: the direct path reuses what the guard read.
    assert body.count("_links_owed_a_fetch(session)") == 1


def test_a_link_awaiting_its_first_fetch_keeps_its_row():
    """The close requires the article to EXIST and be finished. Testing
    only "no article has work left" is TRUE for a link that has no article
    at all, which closed every extract row before anything was fetched.
    The integration suite caught it; this pins the shape."""
    from src.pipeline.rework import settle

    session = _session()
    settle(session)
    sql = " ".join(_sql(session).split())
    assert (
        "EXISTS (SELECT 1 FROM articles a WHERE a.candidate_link_id = r.record_id)"
        in sql
    ), "the article must exist"
    assert "AND NOT EXISTS (SELECT 1 FROM articles a" in sql, "and be finished"


def test_a_run_with_nothing_to_fetch_settles_and_then_ends():
    """Two faults in one place, both found in production.

    The early exit returned BEFORE the settle, so seven rows whose links
    had been fetched the night before stayed open -- and each new run found
    them, exited, and left them again.

    And returning 0 only skipped a BATCH. In work-queue mode the loop reads
    zero articles as "domains in cooldown", sleeps and asks again, so the
    step ran to the workflow's deadline: "Batch 9 ... Batch 10 ... Batch
    11", with classify and enrich never starting."""
    import inspect

    from src.cli.commands import extraction

    body = inspect.getsource(extraction._process_batch)
    guard = body.split("if USE_WORK_QUEUE:")[0]
    assert guard.index("_settle_rework(session)") < guard.index(
        "_links_owed_a_fetch(session)"
    ), "settle before the exit, or finished rows stay open"
    assert '"nothing_owed": True' in guard

    loop = inspect.getsource(extraction.handle_extraction_command)
    assert 'result.get("nothing_owed")' in loop
    stop = loop.index('result.get("nothing_owed")')
    cooldown = loop.index("domains in cooldown, will retry")
    assert stop < cooldown, "an empty set is not a cooldown; it must end the loop"
