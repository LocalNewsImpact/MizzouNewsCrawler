"""One record, from the row a review decision wrote to the status the
BigQuery sync selects.

Step 8 of docs/HOUSEKEEPING_PLAN.md, and the only test that covers the
seam: datadesk writes `pipeline_rework` and the crawler reads it, and
neither repository's own tests can see the other side. Every stage here
is driven through the same functions the Argo steps call, in the order
the workflow runs them, against real PostgreSQL.

WHAT IT IS FOR. The requirement is a record disposed in a review queue
tonight being in tomorrow's export: reconciler 02:30, housekeeping 03:00,
BigQuery sync 07:00 UTC. A stage that quietly drops a record, or leaves
its row open, means the disposition is carried a day late or not at all,
and nothing reports it -- the first run of this looked healthy while
sweeping 4,802 links.
"""

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVISION = "x9y0z1a2b3c4"

#: What the crawler's BigQuery syncs select. A record that ends anywhere
#: else was not carried to the export, whatever else happened to it.
PUBLISHED = ("enriched", "enrichment_skipped")

#: What datadesk writes, verbatim: `review/reconcile.py` names the stage
#: and `_request_rework` fills these columns. The reconciler's own actor
#: is a service account, not a person, and the reason is a rule's words.
RECONCILER_ROW = {
    "record_type": "article",
    "stage": "classify",
    "reason": "review: accept, back to classification",
    "requested_by": "nightly-reconciliation",
}


def _pg_url():
    url = os.environ.get("ENRICHMENT_PG_URL") or os.environ.get("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else None


pytestmark = pytest.mark.skipif(_pg_url() is None, reason="needs PostgreSQL")


@pytest.fixture()
def db():
    url = _pg_url()
    env = {**os.environ, "DATABASE_URL": url, "USE_CLOUD_SQL_CONNECTOR": "false"}
    assert (
        subprocess.run(
            ["alembic", "upgrade", REVISION],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        ).returncode
        == 0
    )
    engine = sa.create_engine(url)
    factory = sessionmaker(bind=engine)
    yield factory
    with factory() as s:
        s.execute(sa.text("DELETE FROM pipeline_rework WHERE record_id LIKE 'e2e-%'"))
        s.execute(sa.text("DELETE FROM articles WHERE id LIKE 'e2e-%'"))
        s.execute(sa.text("DELETE FROM candidate_links WHERE id LIKE 'e2e-%'"))
        s.execute(sa.text("DELETE FROM sources WHERE id = 'e2e-src'"))
        s.commit()
    engine.dispose()


def _outstanding(session):
    """What the workflow's `anything-owed` guard step counts."""
    return session.execute(
        sa.text("SELECT count(*) FROM pipeline_rework WHERE done_at IS NULL")
    ).scalar()


@pytest.fixture()
def parked(db):
    """An article a reviewer accepted out of the extraction queue.

    `paused` with a body, which is the state 36 articles were in: parked
    by review rather than by a pipeline failure. datadesk moves it to
    `cleaned` and writes the row; this picks it up from there.
    """
    with db() as s:
        s.execute(
            sa.text(
                "INSERT INTO sources (id, host, host_norm, city) VALUES "
                "('e2e-src', 'e2e.example', 'e2e.example', 'Linn')"
            )
        )
        s.execute(
            sa.text(
                "INSERT INTO candidate_links (id, url, source, source_id, "
                "discovered_at, status, created_at) VALUES ('e2e-link', "
                "'https://e2e.example/1', 'e2e', 'e2e-src', now(), 'extracted', now())"
            )
        )
        s.execute(
            sa.text(
                "INSERT INTO articles (id, candidate_link_id, status, "
                "wire_check_status, title, text, created_at, extracted_at) VALUES "
                "('e2e-art', 'e2e-link', 'cleaned', 'local', 'A story', "
                "'A body with real words in it, about the county commission. ', "
                "now(), now())"
            )
        )
        # The row datadesk wrote when it moved the article to `cleaned`.
        s.execute(
            sa.text(
                "INSERT INTO pipeline_rework (record_type, record_id, stage, "
                "reason, requested_by) VALUES (:record_type, 'e2e-art', :stage, "
                ":reason, :requested_by)"
            ),
            RECONCILER_ROW,
        )
        s.commit()
    return db


def test_a_disposition_reaches_the_export_in_one_night(parked):
    """The whole chain, in the workflow's order, with the guard count
    checked between stages -- because "nothing owed" is what decides
    whether the next night runs at all."""
    from src.enrichment import repository
    from src.services.classification_service import ArticleClassificationService

    with parked() as s:
        # 03:00 -- the guard step sees work, so the stages run.
        assert _outstanding(s) == 1

        # classify: the stage takes the article the row names, and only it.
        owed = ArticleClassificationService._articles_owed_a_classification(s)
        assert owed == ["e2e-art"]
        s.execute(
            sa.text("UPDATE articles SET status='labeled' WHERE id = ANY(:ids)"),
            {"ids": owed},
        )
        ArticleClassificationService._settle_rework(s, owed, "classified")
        s.commit()

        # The classify row is closed and enrichment is now owed -- queued
        # by the stage that finished, not by datadesk, which cannot know
        # the article got there.
        assert _outstanding(s) == 1
        assert (
            s.execute(
                sa.text(
                    "SELECT stage FROM pipeline_rework WHERE record_id='e2e-art' "
                    "AND done_at IS NULL"
                )
            ).scalar()
            == "enrich"
        )

        # enrich: same, on the status classification just wrote.
        owed = repository.articles_owed_enrichment(s)
        assert owed == ["e2e-art"]
        s.execute(
            sa.text("UPDATE articles SET status='enriched' WHERE id = ANY(:ids)"),
            {"ids": owed},
        )
        repository.settle_enrichment_rework(s, owed)

        # 07:00 -- the record is in the export, and nothing is owed, so
        # tomorrow's run does nothing rather than doing this again.
        status = s.execute(
            sa.text("SELECT status FROM articles WHERE id='e2e-art'")
        ).scalar()
        assert status in PUBLISHED
        assert _outstanding(s) == 0

        # And the history is answerable: what was asked, by whom, and how
        # it came out.
        history = s.execute(
            sa.text(
                "SELECT stage, outcome, requested_by FROM pipeline_rework "
                "WHERE record_id='e2e-art' ORDER BY requested_at, id"
            )
        ).fetchall()
        assert [tuple(r) for r in history] == [
            ("classify", "classified", "nightly-reconciliation"),
            ("enrich", "enriched", "housekeeping"),
        ]


def test_a_stage_that_fails_leaves_the_record_for_tomorrow(parked):
    """Settled on the status, never on having been attempted. An
    enrichment that failed leaves the article at `labeled`, so the row
    stays open and the next night finds it -- rather than being closed on
    "we tried" and the disposition lost."""
    from src.enrichment import repository
    from src.services.classification_service import ArticleClassificationService

    with parked() as s:
        owed = ArticleClassificationService._articles_owed_a_classification(s)
        s.execute(
            sa.text("UPDATE articles SET status='labeled' WHERE id = ANY(:ids)"),
            {"ids": owed},
        )
        ArticleClassificationService._settle_rework(s, owed, "classified")
        s.commit()

        # Enrichment runs and fails: the article is still `labeled`.
        assert repository.settle_enrichment_rework(s, ["e2e-art"]) == 0
        assert _outstanding(s) == 1
        assert repository.articles_owed_enrichment(s) == ["e2e-art"]


def test_a_record_nobody_asked_about_is_not_carried(parked):
    """The requirement, stated as a test. A second article sits at the
    same statuses with no row, and no stage takes it."""
    from src.enrichment import repository
    from src.services.classification_service import ArticleClassificationService

    with parked() as s:
        s.execute(
            sa.text(
                "INSERT INTO candidate_links (id, url, source, source_id, "
                "discovered_at, status, created_at) VALUES ('e2e-link-2', "
                "'https://e2e.example/2', 'e2e', 'e2e-src', now(), 'extracted', now())"
            )
        )
        s.execute(
            sa.text(
                "INSERT INTO articles (id, candidate_link_id, status, "
                "wire_check_status, title, text, created_at, extracted_at) VALUES "
                "('e2e-art-2', 'e2e-link-2', 'cleaned', 'local', 'Backlog', "
                "'Another body entirely. ', now(), now())"
            )
        )
        s.commit()

        assert ArticleClassificationService._articles_owed_a_classification(s) == [
            "e2e-art"
        ]

        s.execute(sa.text("UPDATE articles SET status='labeled' WHERE id LIKE 'e2e-%'"))
        s.commit()
        assert repository.articles_owed_enrichment(s) == []


def test_an_empty_night_costs_nothing(db):
    """With no rows, the guard step's count is 0 and every stage is
    skipped. This is the difference between a quiet night and a sweep."""
    from src.cli.commands.extraction import _links_owed_a_fetch
    from src.enrichment import repository
    from src.services.classification_service import ArticleClassificationService

    with db() as s:
        s.execute(sa.text("DELETE FROM pipeline_rework"))
        s.commit()
        assert _outstanding(s) == 0
        assert _links_owed_a_fetch(s) == []
        assert ArticleClassificationService._articles_owed_a_classification(s) == []
        assert repository.articles_owed_enrichment(s) == []
