"""Integration tests for the backfield enrichment schema (Phase 1).

PostgreSQL only, matching the repo's migration policy (the SQLite path is
deprecated; CI runs a postgres service container). The test upgrades through
the full chain to the enrichment revision, verifies the schema — including the
two shapes SQLite cannot represent, text[] and the GIN index — then downgrades
one revision and verifies clean removal.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).parent.parent.parent
REVISION = "f8b2d3c4e5a6"

# The revision below REVISION, named rather than reached with `-1`.
#
# `-1` is resolved against the graph, and e7a1c2b3d4f5 is a branchpoint: the
# backfield chain descends from it, and so does a7c3f9e2d481, the articles
# sort index that landed on main. Alembic refuses to walk onto a branchpoint
# relatively -- "Ambiguous walk" -- because it cannot tell which branch the
# walk is meant to end up on. Naming the revision says which.
DOWN_REVISION = "e7a1c2b3d4f5"
TABLES = (
    "article_enrichment",
    "article_places",
    "article_people",
    "article_organizations",
)


def _pg_url() -> str | None:
    url = os.environ.get("ENRICHMENT_PG_URL") or os.environ.get("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else None


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "USE_CLOUD_SQL_CONNECTOR": "false"}
    return subprocess.run(
        ["alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.mark.skipif(
    _pg_url() is None, reason="needs a PostgreSQL DATABASE_URL or ENRICHMENT_PG_URL"
)
def test_migration_roundtrip():
    url = _pg_url()
    up = _alembic(url, "upgrade", REVISION)
    assert up.returncode == 0, up.stderr[-3000:]

    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        tables = set(insp.get_table_names())
        for t in TABLES:
            assert t in tables, f"{t} missing after upgrade"

        articles = {c["name"] for c in insp.get_columns("articles")}
        assert {"enriched_at", "enrichment_attempts"} <= articles

        enrichment = {c["name"] for c in insp.get_columns("article_enrichment")}
        for col in (
            "profile_version",
            "steps_applied",
            "skip_reason",
            "backfield_commit",
            "model",
            "prompt_versions",
            "cost_usd",
            "is_news_content",
            "scope",
            "scope_confidence",
            "subject",
            "topic",
            "format",
            "timeframe",
            "user_need",
            "rationales",
            "point_place",
            "point_method",
            "point_lat",
            "point_lon",
            "point_gnis",
        ):
            assert col in enrichment, f"article_enrichment.{col} missing"

        with engine.connect() as conn:
            col_type = conn.execute(
                sa.text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='article_enrichment' AND column_name='steps_applied'"
                )
            ).scalar()
            assert col_type == "ARRAY", f"steps_applied is {col_type}, expected ARRAY"

            gin = conn.execute(
                sa.text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname='ix_article_enrichment_steps_applied'"
                )
            ).scalar()
            assert gin and "gin" in gin.lower(), "GIN index on steps_applied missing"

            # cascade: a child row must not survive its article
            conn.execute(
                sa.text(
                    "INSERT INTO candidate_links "
                    "(id, url, source, discovered_at, status, created_at) "
                    "VALUES ('enr-test-cl-1', 'https://example.test/enr-test-1', "
                    "'enr-test', now(), 'new', now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO articles "
                    "(id, status, candidate_link_id, created_at, extracted_at) "
                    "VALUES ('enr-test-1', 'labeled', 'enr-test-cl-1', now(), now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO article_people (article_id, name) "
                    "VALUES ('enr-test-1', 'Test Person')"
                )
            )
            conn.execute(sa.text("DELETE FROM articles WHERE id='enr-test-1'"))
            orphans = conn.execute(
                sa.text(
                    "SELECT count(*) FROM article_people WHERE article_id='enr-test-1'"
                )
            ).scalar()
            assert orphans == 0, "ON DELETE CASCADE did not remove the child row"
            conn.rollback()
    finally:
        engine.dispose()

    down = _alembic(url, "downgrade", DOWN_REVISION)
    assert down.returncode == 0, down.stderr[-3000:]

    # Restore the schema before leaving, whatever the assertions do.
    #
    # Every test below shares this database. This one is the only test that
    # downgrades it, and it used to get away with not putting it back: the
    # downgrade failed on "Ambiguous walk" and left the schema at head, so
    # `assert down.returncode == 0` ended the test before it could strip
    # anything. Fixing the walk made the downgrade work, and the tests after
    # it started failing on a column this test had just dropped.
    try:
        engine = sa.create_engine(url)
        try:
            insp = sa.inspect(engine)
            tables = set(insp.get_table_names())
            for t in TABLES:
                assert t not in tables, f"{t} survived downgrade"
            articles = {c["name"] for c in insp.get_columns("articles")}
            assert "enriched_at" not in articles
            assert "enrichment_attempts" not in articles
        finally:
            engine.dispose()
    finally:
        restored = _alembic(url, "upgrade", "head")

    assert restored.returncode == 0, (
        "the schema was left downgraded for every test after this one:\n"
        + restored.stderr[-3000:]
    )


# =============================================================================
# Phase 5: repository integration (real PostgreSQL, stubbed models)
# =============================================================================

from decimal import Decimal  # noqa: E402

from src.enrichment.profiles import Profile  # noqa: E402
from src.enrichment.repository import (  # noqa: E402
    persist_outcome,
    select_by_ids,
    select_candidates,
    select_reprocess_candidates,
)
from src.enrichment.types import (  # noqa: E402
    ArticleInput,
    EnrichmentOutcome,
    StepResult,
)

EXPORT_PREDICATE = "status IN ('enriched', 'enrichment_skipped')"

PROFILE = Profile(
    version=1,
    content_gate=True,
    scope=True,
    places=True,
    people=True,
    organizations=True,
    metadata_presets=("subject", "topic"),
)


def _session_factory(url):
    engine = sa.create_engine(url)
    from sqlalchemy.orm import sessionmaker

    return engine, sessionmaker(bind=engine)


def _seed_wire_local(session):
    session.execute(
        sa.text(
            "INSERT INTO candidate_links (id, url, source, source_id, discovered_at, status, created_at) "
            "VALUES ('clwl', 'https://example.test/wl', 'seed', 'src1', now(), 'new', now())"
        )
    )
    session.execute(
        sa.text(
            "INSERT INTO articles (id, candidate_link_id, status, wire_check_status, "
            " title, content, created_at, extracted_at) "
            "VALUES ('art-wl', 'clwl', 'labeled', 'local', 'WL', 'Body. ', now(), now())"
        )
    )
    session.commit()


def _seed(session, n=3, dataset="Mizzou-Missouri-State"):
    session.execute(
        sa.text(
            "INSERT INTO datasets (id, slug, label, ingested_at) "
            "VALUES ('ds1', :slug, :slug, now()) ON CONFLICT DO NOTHING"
        ),
        {"slug": dataset},
    )
    session.execute(
        sa.text(
            "INSERT INTO sources (id, host, host_norm, city) "
            "VALUES ('src1', 'example.test', 'example.test', 'Columbia') "
            "ON CONFLICT DO NOTHING"
        )
    )
    session.execute(
        sa.text(
            "INSERT INTO dataset_sources (id, dataset_id, source_id) "
            "VALUES ('dss1', 'ds1', 'src1') ON CONFLICT DO NOTHING"
        )
    )
    for i in range(n):
        session.execute(
            sa.text(
                "INSERT INTO candidate_links (id, url, source, source_id, discovered_at, status, created_at) "
                "VALUES (:cl, :url, 'seed', 'src1', now(), 'new', now())"
            ),
            {"cl": f"cl{i}", "url": f"https://example.test/{i}"},
        )
        session.execute(
            sa.text(
                "INSERT INTO articles (id, candidate_link_id, status, wire_check_status, "
                " title, content, created_at, extracted_at) "
                "VALUES (:id, :cl, 'labeled', 'complete', :t, :c, now(), now())"
            ),
            {
                "id": f"art{i}",
                "cl": f"cl{i}",
                "t": f"Title {i}",
                "c": f"Body {i}. " * 50,
            },
        )
    session.commit()


def _ok(step, payload):
    return StepResult(step, True, payload, None, 100, 10, Decimal("0.001"))


def _outcome(article_id, status, steps, results, skip=None):
    return EnrichmentOutcome(
        article_id=article_id,
        status=status,
        skip_reason=skip,
        steps_applied=steps,
        results=results,
        total_cost_usd=sum((r.cost_usd for r in results), Decimal("0")),
    )


def _persist_enriched(session, article):
    results = [
        _ok("content_gate", {"verdict": "news", "reason": "story"}),
        _ok(
            "scope",
            {"article_metadata": {"category": "city_municipality", "confidence": 0.9}},
        ),
        _ok(
            "places",
            {
                "locations": [
                    {
                        "location": {
                            "components": {"city": "Columbia", "state": {"abbr": "MO"}},
                            "full": "Columbia, MO",
                            "type": "city",
                        },
                        "description": "d",
                        "original_text": "m",
                    }
                ]
            },
        ),
        _ok(
            "subject",
            {
                "article_metadata": {
                    "category": "election",
                    "confidence": 0.95,
                    "rationale": "r",
                }
            },
        ),
        _ok("topic", {"article_metadata": {"category": "gov", "confidence": 0.9}}),
        _ok(
            "people",
            {
                "people": [
                    {
                        "name": "Jane Doe",
                        "sort_key": "doe",
                        "type": "resident",
                        "mentions": [{"text": "quoted words", "quote": True}],
                    }
                ]
            },
        ),
        _ok(
            "organizations",
            {
                "organizations": [
                    {
                        "name": "City Council",
                        "type": "government",
                        "mentions": [{"text": "x"}],
                    }
                ]
            },
        ),
    ]
    outcome = _outcome(
        article.id,
        "enriched",
        [
            "content_gate",
            "scope",
            "places",
            "subject",
            "topic",
            "people",
            "organizations",
        ],
        results,
    )
    persist_outcome(
        session,
        article,
        outcome,
        profile=PROFILE,
        model="test-model",
        backfield_commit="abc1234",
        prompt_versions={"content_gate": "content_gate-v1"},
    )


@pytest.mark.skipif(_pg_url() is None, reason="needs PostgreSQL")
class TestRepository:
    @pytest.fixture()
    def db(self):
        url = _pg_url()
        assert _alembic(url, "upgrade", REVISION).returncode == 0
        engine, factory = _session_factory(url)
        with factory() as s:
            _seed(s)
        yield factory
        with factory() as s:
            for table in (
                "article_organizations",
                "article_people",
                "article_places",
                "article_enrichment",
            ):
                s.execute(sa.text(f"DELETE FROM {table}"))
            s.execute(sa.text("DELETE FROM articles WHERE id LIKE 'art%'"))
            s.execute(sa.text("DELETE FROM candidate_links WHERE id LIKE 'cl%'"))
            s.execute(sa.text("DELETE FROM dataset_sources WHERE id='dss1'"))
            s.execute(sa.text("DELETE FROM sources WHERE id='src1'"))
            s.execute(sa.text("DELETE FROM datasets WHERE id='ds1'"))
            s.commit()
        engine.dispose()

    def test_writes_all_four_tables_and_flips_status(self, db):
        with db() as s:
            [article] = select_candidates(s, "Mizzou-Missouri-State", 1, 3)
            _persist_enriched(s, article)
        with db() as s:
            status, enriched_at = s.execute(
                sa.text("SELECT status, enriched_at FROM articles WHERE id=:id"),
                {"id": article.id},
            ).one()
            assert status == "enriched" and enriched_at is not None
            for table, expected in (
                ("article_enrichment", 1),
                ("article_places", 1),
                ("article_people", 1),
                ("article_organizations", 1),
            ):
                n = s.execute(
                    sa.text(f"SELECT count(*) FROM {table} WHERE article_id=:id"),
                    {"id": article.id},
                ).scalar()
                assert n == expected, f"{table}: {n} rows"
            row = s.execute(
                sa.text(
                    "SELECT subject, subject_confidence, point_place, point_method, "
                    " steps_applied FROM article_enrichment WHERE article_id=:id"
                ),
                {"id": article.id},
            ).one()
            assert row.subject == "election"
            assert row.point_place == "Columbia" and row.point_method == "single_city"
            assert "places" in row.steps_applied

    def test_idempotency_second_run_selects_nothing(self, db):
        with db() as s:
            articles = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
            for a in articles:
                _persist_enriched(s, a)
        with db() as s:
            assert select_candidates(s, "Mizzou-Missouri-State", 10, 3) == []

    def test_labeled_outcome_writes_only_the_attempt_counter(self, db):
        with db() as s:
            [article] = select_candidates(s, "Mizzou-Missouri-State", 1, 3)
            outcome = _outcome(
                article.id,
                "labeled",
                ["content_gate"],
                [_ok("content_gate", {"verdict": "news"})],
            )
            persist_outcome(
                s,
                article,
                outcome,
                profile=PROFILE,
                model="m",
                backfield_commit="c",
                prompt_versions={},
            )
        with db() as s:
            status, attempts = s.execute(
                sa.text(
                    "SELECT status, enrichment_attempts FROM articles WHERE id=:id"
                ),
                {"id": article.id},
            ).one()
            assert status == "labeled" and attempts == 1
            n = s.execute(
                sa.text("SELECT count(*) FROM article_enrichment WHERE article_id=:id"),
                {"id": article.id},
            ).scalar()
            assert n == 0, "a retryable failure must write no enrichment row"

    def test_export_criterion_matches_only_terminal_statuses(self, db):
        with db() as s:
            articles = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
            _persist_enriched(s, articles[0])
            skipped = _outcome(
                articles[1].id, "enrichment_skipped", [], [], skip="profile_none"
            )
            persist_outcome(
                s,
                articles[1],
                skipped,
                profile=PROFILE,
                model="m",
                backfield_commit="c",
                prompt_versions={},
            )
        with db() as s:
            exported = {
                r[0]
                for r in s.execute(
                    sa.text(
                        f"SELECT id FROM articles WHERE id LIKE 'art%' AND {EXPORT_PREDICATE}"
                    )
                )
            }
            assert exported == {articles[0].id, articles[1].id}

    def test_reprocessing_never_withdraws_rows(self, db):
        """§8's failure mode: an exportable article stays exportable at every
        point during and after reprocessing. Never skip this test."""
        with db() as s:
            articles = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
            for a in articles:
                _persist_enriched(s, a)

        def exported(s):
            return s.execute(
                sa.text(
                    f"SELECT count(*) FROM articles WHERE id LIKE 'art%' AND {EXPORT_PREDICATE}"
                )
            ).scalar()

        with db() as s:
            before = exported(s)
            assert before == len(articles)

            # a profile bump makes them candidates again — status untouched
            candidates = select_reprocess_candidates(
                s, "Mizzou-Missouri-State", profile_version=2, batch=10, max_attempts=3
            )
            assert {c.id for c in candidates} == {a.id for a in articles}
            assert exported(s) == before, "selection must not change status"

            # mid-reprocess: after re-persisting one, still exportable
            bumped = Profile(
                version=2,
                content_gate=True,
                scope=True,
                places=True,
                people=True,
                organizations=True,
                metadata_presets=("subject", "topic"),
            )
            results = [_ok("people", {"people": []})]
            outcome = _outcome(
                candidates[0].id,
                "enriched",
                [
                    "content_gate",
                    "scope",
                    "places",
                    "subject",
                    "topic",
                    "people",
                    "organizations",
                ],
                results,
            )
            persist_outcome(
                s,
                candidates[0],
                outcome,
                profile=bumped,
                model="m",
                backfield_commit="c",
                prompt_versions={},
            )
            assert exported(s) == before, "reprocessing must not withdraw rows"

            version = s.execute(
                sa.text(
                    "SELECT profile_version FROM article_enrichment WHERE article_id=:id"
                ),
                {"id": candidates[0].id},
            ).scalar()
            assert version == 2

            remaining = select_reprocess_candidates(
                s, "Mizzou-Missouri-State", profile_version=2, batch=10, max_attempts=3
            )
            assert candidates[0].id not in {c.id for c in remaining}

    def test_legacy_wire_check_local_is_a_candidate(self, db):
        """512 of the March backfill articles carry the legacy 'local' pass
        state; requiring 'complete' would drop them at Phase 7."""
        with db() as s:
            _seed_wire_local(s)
            ids = {c.id for c in select_candidates(s, "Mizzou-Missouri-State", 20, 3)}
            assert "art-wl" in ids
            report = select_by_ids(s, ["art-wl"], 3)
            assert [c.id for c in report.candidates] == ["art-wl"]
            s.execute(sa.text("DELETE FROM articles WHERE id='art-wl'"))
            s.execute(sa.text("DELETE FROM candidate_links WHERE id='clwl'"))
            s.commit()

    def test_steady_state_since_floors_the_candidates(self, db):
        """The scheduled run must not eat the historical backlog: history is
        the backfill list's job."""
        with db() as s:
            s.execute(
                sa.text(
                    "UPDATE articles SET created_at = '2026-01-01' WHERE id = 'art0'"
                )
            )
            s.commit()
            with_floor = select_candidates(
                s, "Mizzou-Missouri-State", 10, 3, since="2026-06-01"
            )
            assert "art0" not in {c.id for c in with_floor}
            without = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
            assert "art0" in {c.id for c in without}

    def test_backfill_list_accounts_for_every_id(self, db):
        with db() as s:
            articles = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
            _persist_enriched(s, articles[0])  # no longer a candidate
            report = select_by_ids(s, [articles[0].id, articles[1].id, "no-such-id"], 3)
            assert {c.id for c in report.candidates} == {articles[1].id}
            assert report.rejected[articles[0].id].startswith("status is 'enriched'")
            assert report.rejected["no-such-id"] == "not found"
            assert len(report.candidates) + len(report.rejected) == 3

    def test_partial_failure_leaves_others_committed(self, db):
        with db() as s:
            articles = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
        with db() as s:
            _persist_enriched(s, articles[0])  # committed
        with db() as s:
            try:
                bad = _outcome(
                    articles[1].id,
                    "enriched",
                    ["scope"],
                    [_ok("scope", {"article_metadata": {"category": "x"}})],
                )
                # force a failure mid-persist by violating the FK
                broken = ArticleInput(
                    "does-not-exist", "t", "c", articles[1].dataset_slug, None
                )
                persist_outcome(
                    s,
                    broken,
                    bad,
                    profile=PROFILE,
                    model="m",
                    backfield_commit="c",
                    prompt_versions={},
                )
            except Exception:
                s.rollback()
        with db() as s:
            status = s.execute(
                sa.text("SELECT status FROM articles WHERE id=:id"),
                {"id": articles[0].id},
            ).scalar()
            assert (
                status == "enriched"
            ), "the committed article survives a later failure"

    def test_out_of_scope_does_not_export_but_reprocesses(self, db):
        """A dataset flag change (profile bump) must bring excluded articles
        back as candidates — toggling the flag is reversible."""
        with db() as s:
            articles = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
            excluded = _outcome(
                articles[0].id,
                "out_of_scope",
                ["content_gate", "scope"],
                [
                    _ok("content_gate", {"verdict": "news", "reason": "story"}),
                    _ok(
                        "scope",
                        {
                            "article_metadata": {
                                "category": "international",
                                "confidence": 0.9,
                                "rationale": "global affairs",
                            }
                        },
                    ),
                ],
            )
            persist_outcome(
                s,
                articles[0],
                excluded,
                profile=PROFILE,
                model="m",
                backfield_commit="c",
                prompt_versions={},
            )
        with db() as s:
            status = s.execute(
                sa.text("SELECT status FROM articles WHERE id=:id"),
                {"id": articles[0].id},
            ).scalar()
            assert status == "out_of_scope"
            exported = s.execute(
                sa.text(
                    f"SELECT count(*) FROM articles WHERE id=:id AND {EXPORT_PREDICATE}"
                ),
                {"id": articles[0].id},
            ).scalar()
            assert exported == 0, "out_of_scope must not export"
            scope = s.execute(
                sa.text("SELECT scope FROM article_enrichment WHERE article_id=:id"),
                {"id": articles[0].id},
            ).scalar()
            assert scope == "international", "the classification is still recorded"
            # not a plain candidate...
            plain = select_candidates(s, "Mizzou-Missouri-State", 10, 3)
            assert articles[0].id not in {c.id for c in plain}
            # ...but a profile bump brings it back
            bumped = select_reprocess_candidates(
                s, "Mizzou-Missouri-State", profile_version=2, batch=10, max_attempts=3
            )
            assert articles[0].id in {c.id for c in bumped}
