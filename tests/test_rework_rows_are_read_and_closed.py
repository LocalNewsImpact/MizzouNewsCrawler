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


def test_extraction_asks_for_open_extract_rows_on_links():
    from src.cli.commands.extraction import _links_owed_a_fetch

    session = _session(rows=["l1", "l2"])
    assert _links_owed_a_fetch(session) == ["l1", "l2"]
    sql = _sql(session)
    assert "record_type = 'candidate_link'" in sql
    assert "stage = 'extract'" in sql
    assert "done_at IS NULL" in sql


def test_extraction_with_no_rows_returns_an_empty_list_not_none():
    """`None` reads as "no filter" to a caller. `[]` reads as nothing."""
    from src.cli.commands.extraction import _links_owed_a_fetch

    assert _links_owed_a_fetch(_session()) == []


def test_settling_nothing_touches_nothing():
    from src.cli.commands.extraction import _settle_fetches

    session = _session()
    assert _settle_fetches(session, []) == (0, 0)
    session.execute.assert_not_called()
    session.commit.assert_not_called()


def test_settling_closes_on_the_links_status_then_queues_classification():
    from src.cli.commands.extraction import _settle_fetches

    session = _session(rowcount=2)
    assert _settle_fetches(session, ["l1", "l2"]) == (2, 2)
    close, queue = _sql(session, 0), _sql(session, 1)
    # closed on what the link became, only where it left `article`
    assert "outcome = cl.status" in close
    assert "cl.status <> 'article'" in close
    assert "done_at IS NULL" in close, "a closed row is never re-closed"
    assert _params(session, 0)["ids"] == ["l1", "l2"]
    # the next stage, for the article the fetch produced
    assert "'article', a.id, 'classify'" in queue
    assert "r.outcome = 'extracted'" in queue
    assert "ON CONFLICT DO NOTHING" in queue
    session.commit.assert_called_once()


def test_a_missing_rowcount_is_zero_not_none():
    from src.cli.commands.extraction import _settle_fetches

    session = _session()
    session.execute.return_value.rowcount = None
    assert _settle_fetches(session, ["l1"]) == (0, 0)


# --- classification ---------------------------------------------------------------


def test_classification_asks_for_open_classify_rows_on_articles():
    from src.services.classification_service import ArticleClassificationService

    session = _session(rows=["a1"])
    assert ArticleClassificationService._articles_owed_a_classification(session) == [
        "a1"
    ]
    sql = _sql(session)
    assert "record_type = 'article'" in sql
    assert "stage = 'classify'" in sql
    assert "done_at IS NULL" in sql


def test_classification_settles_its_stage_and_queues_enrichment():
    from src.services.classification_service import ArticleClassificationService

    session = _session()
    ArticleClassificationService._settle_rework(session, ["a1", 7], "classified")
    close, queue = _sql(session, 0), _sql(session, 1)
    assert "stage = 'classify'" in close and "done_at IS NULL" in close
    assert _params(session, 0)["ids"] == ["a1", "7"], "ids are strings in the table"
    assert "'article', r.record_id, 'enrich'" in queue
    assert "ON CONFLICT DO NOTHING" in queue


def test_classification_settling_nothing_touches_nothing():
    from src.services.classification_service import ArticleClassificationService

    session = _session()
    ArticleClassificationService._settle_rework(session, [], "classified")
    session.execute.assert_not_called()


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


def test_enrichment_asks_for_open_enrich_rows_on_articles():
    from src.enrichment import repository

    session = _session(rows=["a1", "a2"])
    assert repository.articles_owed_enrichment(session) == ["a1", "a2"]
    sql = _sql(session)
    assert "stage = 'enrich'" in sql and "done_at IS NULL" in sql


def test_enrichment_settles_only_articles_at_a_terminal_status():
    from src.enrichment import repository

    session = _session(rowcount=1)
    assert repository.settle_enrichment_rework(session, ["a1", "a2"]) == 1
    sql = _sql(session)
    assert "outcome = a.status" in sql
    assert "a.status IN ('enriched', 'enrichment_skipped')" in sql
    assert "INSERT INTO pipeline_rework" not in sql, "the chain ends here"
    session.commit.assert_called_once()


def test_enrichment_settling_nothing_touches_nothing():
    from src.enrichment import repository

    session = _session()
    assert repository.settle_enrichment_rework(session, []) == 0
    session.execute.assert_not_called()


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
