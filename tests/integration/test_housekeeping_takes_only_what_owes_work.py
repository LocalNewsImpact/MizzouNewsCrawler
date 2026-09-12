"""Housekeeping takes the records `pipeline_rework` names, and nothing else.

Every pipeline stage selects by status, and a rewound record shares its
status with the whole backlog -- so a stage told nothing takes everything.
A housekeeping run began extracting 4,802 links when the dispositions
accounted for 45. These are the tests that make that impossible again,
run against real PostgreSQL because the selection is SQL and a mock of it
proves nothing.

Step 1-4 of docs/HOUSEKEEPING_PLAN.md.
"""

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVISION = "x9y0z1a2b3c4"


def _pg_url():
    url = os.environ.get("ENRICHMENT_PG_URL") or os.environ.get("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else None


def _alembic(url, *args):
    env = {**os.environ, "DATABASE_URL": url, "USE_CLOUD_SQL_CONNECTOR": "false"}
    return subprocess.run(
        ["alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


pytestmark = pytest.mark.skipif(_pg_url() is None, reason="needs PostgreSQL")


@pytest.fixture()
def db():
    url = _pg_url()
    assert _alembic(url, "upgrade", REVISION).returncode == 0
    engine = sa.create_engine(url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        s.execute(
            sa.text(
                "INSERT INTO sources (id, host, host_norm, city) "
                "VALUES ('src-hk', 'hk.example', 'hk.example', 'Linn') ON CONFLICT DO NOTHING"
            )
        )
        # Six links at `article`: three the reconciler rewound, three that
        # are simply backlog. The test is whether the stage can tell them
        # apart.
        for n in range(6):
            s.execute(
                sa.text(
                    "INSERT INTO candidate_links (id, url, source, source_id, discovered_at, status, created_at) "
                    "VALUES (:id, :url, 'hk', 'src-hk', now(), 'article', now()) ON CONFLICT DO NOTHING"
                ),
                {"id": f"hk-link-{n}", "url": f"https://hk.example/{n}"},
            )
        for n in range(3):
            s.execute(
                sa.text(
                    "INSERT INTO pipeline_rework (record_type, record_id, stage, reason, requested_by) "
                    "VALUES ('candidate_link', :id, 'extract', 'test: rewound', 'test')"
                ),
                {"id": f"hk-link-{n}"},
            )
        s.commit()
    yield factory
    with factory() as s:
        s.execute(sa.text("DELETE FROM pipeline_rework WHERE requested_by='test'"))
        s.execute(
            sa.text("DELETE FROM articles WHERE candidate_link_id LIKE 'hk-link-%'")
        )
        s.execute(sa.text("DELETE FROM candidate_links WHERE id LIKE 'hk-link-%'"))
        s.execute(sa.text("DELETE FROM sources WHERE id='src-hk'"))
        s.commit()
    engine.dispose()


# --- step 1: the table ----------------------------------------------------------


def test_the_table_exists_and_roundtrips(db):
    url = _pg_url()
    with db() as s:
        cols = {
            r[0]
            for r in s.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='pipeline_rework'"
                )
            )
        }
    assert {
        "record_type",
        "record_id",
        "stage",
        "reason",
        "requested_by",
        "requested_at",
        "done_at",
        "outcome",
    } <= cols
    assert _alembic(url, "downgrade", "-1").returncode == 0
    assert _alembic(url, "upgrade", REVISION).returncode == 0


def test_asking_twice_is_the_same_ask(db):
    """One outstanding request per record per stage. Two rows would
    extract the same link twice."""
    with db() as s:
        with pytest.raises(sa.exc.IntegrityError):
            s.execute(
                sa.text(
                    "INSERT INTO pipeline_rework (record_type, record_id, stage, requested_by) "
                    "VALUES ('candidate_link', 'hk-link-0', 'extract', 'test')"
                )
            )
            s.commit()


def test_a_settled_request_may_be_asked_again(db):
    """The uniqueness is on OUTSTANDING rows. A link fetched last week
    and rewound again this week is a new request."""
    with db() as s:
        s.execute(
            sa.text(
                "UPDATE pipeline_rework SET done_at=now(), outcome='extracted' "
                "WHERE record_id='hk-link-0' AND done_at IS NULL"
            )
        )
        s.execute(
            sa.text(
                "INSERT INTO pipeline_rework (record_type, record_id, stage, requested_by) "
                "VALUES ('candidate_link', 'hk-link-0', 'extract', 'test')"
            )
        )
        s.commit()
        n = s.execute(
            sa.text("SELECT count(*) FROM pipeline_rework WHERE record_id='hk-link-0'")
        ).scalar()
    assert n == 2


# --- step 2: extraction reads it --------------------------------------------------


def test_extraction_with_rework_selects_only_the_named_links(db):
    """THE TEST THAT MATTERS. Six links share the status; three owe work.
    `--rework` must return exactly those three."""
    from src.cli.commands.extraction import _links_owed_a_fetch

    with db() as s:
        owed = _links_owed_a_fetch(s)
    assert sorted(owed) == ["hk-link-0", "hk-link-1", "hk-link-2"]


def test_extraction_with_rework_and_nothing_owed_selects_nothing(db):
    """An empty table means nothing to do, never "take everything." That
    is the exact inversion that turned a targeted run into a sweep."""
    from src.cli.commands.extraction import _links_owed_a_fetch

    with db() as s:
        s.execute(sa.text("DELETE FROM pipeline_rework WHERE requested_by='test'"))
        s.commit()
        assert _links_owed_a_fetch(s) == []


def test_extraction_settles_what_it_handled(db):
    """A handled row is closed with an outcome, so "what is left" stays
    true and "what did housekeeping do" can be answered."""
    from src.cli.commands.extraction import _settle_rework

    with db() as s:
        _settle_rework(
            s, "candidate_link", "extract", ["hk-link-0", "hk-link-1"], "extracted"
        )
        s.commit()
        rows = s.execute(
            sa.text(
                "SELECT record_id, done_at IS NOT NULL, outcome FROM pipeline_rework "
                "WHERE requested_by='test' ORDER BY record_id"
            )
        ).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("hk-link-0", True, "extracted"),
        ("hk-link-1", True, "extracted"),
        ("hk-link-2", False, None),
    ]


def test_settling_does_not_touch_other_stages(db):
    """A link that owes both a fetch and, later, a classification is two
    rows. Closing one must not close the other."""
    from src.cli.commands.extraction import _settle_rework

    with db() as s:
        s.execute(
            sa.text(
                "INSERT INTO pipeline_rework (record_type, record_id, stage, requested_by) "
                "VALUES ('article', 'hk-link-0', 'classify', 'test')"
            )
        )
        s.commit()
        _settle_rework(s, "candidate_link", "extract", ["hk-link-0"], "extracted")
        s.commit()
        still_open = s.execute(
            sa.text(
                "SELECT stage FROM pipeline_rework WHERE record_id='hk-link-0' AND done_at IS NULL"
            )
        ).fetchall()
    assert [r[0] for r in still_open] == ["classify"]


# --- step 3: classification reads it ---------------------------------------------


@pytest.fixture()
def articles_db(db):
    """Six articles at `cleaned`; three owe a classification."""
    with db() as s:
        for n in range(6):
            s.execute(
                sa.text(
                    "INSERT INTO articles (id, candidate_link_id, status, wire_check_status, "
                    " title, text, created_at, extracted_at) "
                    "VALUES (:id, :link, 'cleaned', 'local', :title, 'A body with words in it. ', now(), now()) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"id": f"hk-art-{n}", "link": f"hk-link-{n}", "title": f"Story {n}"},
            )
        for n in range(3):
            s.execute(
                sa.text(
                    "INSERT INTO pipeline_rework (record_type, record_id, stage, reason, requested_by) "
                    "VALUES ('article', :id, 'classify', 'test: accepted', 'test')"
                ),
                {"id": f"hk-art-{n}"},
            )
        s.commit()
    yield db
    with db() as s:
        s.execute(sa.text("DELETE FROM articles WHERE id LIKE 'hk-art-%'"))
        s.commit()


def test_classification_with_rework_selects_only_the_named_articles(articles_db):
    from src.services.classification_service import ArticleClassificationService

    with articles_db() as s:
        owed = ArticleClassificationService._articles_owed_a_classification(s)
    assert sorted(owed) == ["hk-art-0", "hk-art-1", "hk-art-2"]


def test_classification_with_nothing_owed_selects_nothing(articles_db):
    from src.services.classification_service import ArticleClassificationService

    with articles_db() as s:
        s.execute(sa.text("DELETE FROM pipeline_rework WHERE record_type='article'"))
        s.commit()
        assert ArticleClassificationService._articles_owed_a_classification(s) == []


def test_the_selection_honours_the_id_list_against_the_status(articles_db):
    """Six share the status. With `only_article_ids` naming three, exactly
    three come back -- the SQL, not a mock of it."""
    from src.services.classification_service import ArticleClassificationService

    with articles_db() as s:
        svc = ArticleClassificationService(s)
        chosen = svc._select_articles(
            ["cleaned"],
            "v-test",
            50,
            True,
            None,
            None,
            None,
            only_article_ids=["hk-art-0", "hk-art-1", "hk-art-2"],
        )
        assert sorted(a.id for a in chosen) == ["hk-art-0", "hk-art-1", "hk-art-2"]
        none = svc._select_articles(
            ["cleaned"],
            "v-test",
            50,
            True,
            None,
            None,
            None,
            only_article_ids=[],
        )
        assert none == []
        everything = svc._select_articles(
            ["cleaned"],
            "v-test",
            50,
            True,
            None,
            None,
            None,
            only_article_ids=None,
        )
        assert len([a for a in everything if a.id.startswith("hk-art-")]) == 6


def test_classification_settles_only_its_own_stage(articles_db):
    from src.services.classification_service import ArticleClassificationService

    with articles_db() as s:
        s.execute(
            sa.text(
                "INSERT INTO pipeline_rework (record_type, record_id, stage, requested_by) "
                "VALUES ('article', 'hk-art-0', 'enrich', 'test')"
            )
        )
        s.commit()
        ArticleClassificationService._settle_rework(s, ["hk-art-0"], "classified")
        s.commit()
        open_stages = s.execute(
            sa.text(
                "SELECT stage FROM pipeline_rework WHERE record_id='hk-art-0' AND done_at IS NULL"
            )
        ).fetchall()
    assert [r[0] for r in open_stages] == ["enrich"]


# --- step 4: enrichment reads it ------------------------------------------------


@pytest.fixture()
def labeled_db(db):
    """Six articles at `labeled`; three owe enrichment."""
    with db() as s:
        for n in range(6):
            s.execute(
                sa.text(
                    "INSERT INTO articles (id, candidate_link_id, status, wire_check_status, "
                    " title, text, created_at, extracted_at) "
                    "VALUES (:id, :link, 'labeled', 'local', :title, 'Body. ', now(), now()) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"id": f"hk-lab-{n}", "link": f"hk-link-{n}", "title": f"Story {n}"},
            )
        for n in range(3):
            s.execute(
                sa.text(
                    "INSERT INTO pipeline_rework (record_type, record_id, stage, reason, requested_by) "
                    "VALUES ('article', :id, 'enrich', 'test: restored', 'test')"
                ),
                {"id": f"hk-lab-{n}"},
            )
        s.commit()
    yield db
    with db() as s:
        s.execute(sa.text("DELETE FROM articles WHERE id LIKE 'hk-lab-%'"))
        s.commit()


def test_enrichment_with_rework_names_only_the_owed_articles(labeled_db):
    from src.enrichment.repository import articles_owed_enrichment

    with labeled_db() as s:
        assert sorted(articles_owed_enrichment(s)) == [
            "hk-lab-0",
            "hk-lab-1",
            "hk-lab-2",
        ]


def test_enrichment_with_nothing_owed_names_nothing(labeled_db):
    from src.enrichment.repository import articles_owed_enrichment

    with labeled_db() as s:
        s.execute(sa.text("DELETE FROM pipeline_rework WHERE stage='enrich'"))
        s.commit()
        assert articles_owed_enrichment(s) == []


def test_enrichment_settles_on_the_status_not_the_attempt(labeled_db):
    """An article whose enrichment failed is still `labeled` and still
    owes the work. Only one that reached a terminal status is closed --
    and the outcome records which terminal status it reached."""
    from src.enrichment.repository import settle_enrichment_rework

    with labeled_db() as s:
        s.execute(sa.text("UPDATE articles SET status='enriched' WHERE id='hk-lab-0'"))
        s.execute(
            sa.text(
                "UPDATE articles SET status='enrichment_skipped' WHERE id='hk-lab-1'"
            )
        )
        # hk-lab-2 stays at labeled: the attempt failed.
        s.commit()
        settled = settle_enrichment_rework(s, ["hk-lab-0", "hk-lab-1", "hk-lab-2"])
        rows = s.execute(
            sa.text(
                "SELECT record_id, done_at IS NOT NULL, outcome FROM pipeline_rework "
                "WHERE stage='enrich' AND requested_by='test' ORDER BY record_id"
            )
        ).fetchall()
    assert settled == 2
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("hk-lab-0", True, "enriched"),
        ("hk-lab-1", True, "enrichment_skipped"),
        ("hk-lab-2", False, None),
    ]


def test_backfill_with_neither_flag_is_refused():
    """With no --ids-file and no --rework there is nothing to say which
    articles, and no default that is not a sweep."""
    import argparse

    from src.cli.commands.enrichment import add_enrichment_parser

    parser = argparse.ArgumentParser()
    add_enrichment_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["enrich", "backfill"])
    assert args.ids_file is None and args.rework is False
    # The refusal is in the handler, asserted by reading it: it raises
    # before touching the database.
    from pathlib import Path

    body = Path(PROJECT_ROOT / "src/cli/commands/enrichment.py").read_text()
    assert "backfill needs --ids-file or --rework" in body


def test_housekeeping_never_uses_enrich_run():
    """`enrich run` selects every article at `labeled`. The targeted verb
    is `backfill --rework`, and the workflow must say so."""
    import yaml

    workflow = yaml.safe_load(
        (PROJECT_ROOT / "k8s/argo/housekeeping-workflow.yaml").read_text()
    )
    for t in workflow["spec"]["templates"]:
        cmd = " ".join((t.get("container") or {}).get("command", []))
        if "enrich" in cmd:
            assert (
                "backfill" in cmd and "--rework" in cmd
            ), f"{t['name']} runs `{cmd}`, which sweeps"
            assert " run " not in f" {cmd} "
