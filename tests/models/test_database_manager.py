"""DatabaseManager helper coverage tests."""

import contextlib
import os
import sqlite3
import tempfile
import types
from pathlib import Path
 

import pandas as pd
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from src.models import (
    Article,
    ArticleEntity,
    ArticleLabel,
    CandidateLink,
    Dataset,
    Job,
    Location,
    MLResult,
    Source,
)
from src.models.database import (
    DatabaseManager,
    _commit_with_retry,
    _normalize_entity_text,
    _prediction_to_tuple,
    bulk_insert_articles,
    bulk_insert_candidate_links,
    calculate_content_hash,
    create_job_record,
    export_to_parquet,
    finish_job_record,
    read_articles,
    read_candidate_links,
    save_article_classification,
    save_article_entities,
    save_locations,
    save_ml_results,
    upsert_article,
    upsert_candidate_link,
)


@contextlib.contextmanager
def temporary_database():
    """Yield a temporary SQLite database URL and remove it afterwards."""

    fd, path = tempfile.mkstemp(prefix="test_db_manager_", suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        yield db_url, path
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_database_manager_context_calls_close(monkeypatch):
    """Context manager should call close() exactly once on exit."""

    with temporary_database() as (db_url, _):
        close_calls = []
        original_close = DatabaseManager.close

        def fake_close(self):
            close_calls.append(True)
            return original_close(self)

        monkeypatch.setattr(DatabaseManager, "close", fake_close)

        with DatabaseManager(database_url=db_url) as db:
            # Opening the context should yield a live session
            assert db.session.bind is not None

        assert close_calls == [True]


def test_upsert_candidate_link_inserts_and_updates():
    """upsert_candidate_link should normalize URLs and update existing rows."""

    with temporary_database() as (db_url, _):
        with DatabaseManager(database_url=db_url) as db:
            first = upsert_candidate_link(
                db.session,
                url="https://example.com/story?ref=home",
                source="Test Source",
                status="new",
                source_name="Example Source",
            )

            second = upsert_candidate_link(
                db.session,
                url="https://example.com/story#section",
                source="Test Source",
                status="processed",
                source_name="Example Source",
            )

            first_id = str(first.id)
            second_id = str(second.id)
            assert first_id == second_id

            row = db.session.execute(
                select(
                    CandidateLink.id,
                    CandidateLink.url,
                    CandidateLink.status,
                )
            ).one()
            assert row.id == first_id
            assert row.url == "https://example.com/story"
            assert row.status == "processed"


def test_upsert_candidate_link_handles_single_lock(monkeypatch):
    """upsert_candidate_link retries commit after a simulated lock."""

    with temporary_database() as (db_url, _):
        with DatabaseManager(database_url=db_url) as db:
            attempts = {"count": 0}
            simulated = {"handled": False}

            def simulated_commit_with_retry(session, retries=4, backoff=0.1):
                if not simulated["handled"]:
                    simulated["handled"] = True
                    attempts["count"] += 1  # first attempt
                    pending = list(session.new)
                    session.rollback()
                    for obj in pending:
                        session.add(obj)
                    attempts["count"] += 1  # retry succeeds
                    session.commit()
                    return
                session.commit()

            monkeypatch.setattr(
                "src.models.database._commit_with_retry",
                simulated_commit_with_retry,
            )

            link = upsert_candidate_link(
                db.session,
                url="https://example.com/lock",
                source="Lock Test",
                status="new",
            )

            persisted = db.session.execute(
                select(CandidateLink.status).where(CandidateLink.id == link.id)
            ).scalar_one()
            assert persisted == "new"
            assert attempts["count"] >= 2


def test_upsert_candidate_links_deduplicates_existing_urls():
    """DatabaseManager.upsert_candidate_links should drop existing URLs."""

    with temporary_database() as (db_url, _):
        with DatabaseManager(database_url=db_url) as db:
            initial = pd.DataFrame(
                [
                    {
                        "url": "https://example.com/article",
                        "source": "Example",
                    }
                ]
            )
            inserted = db.upsert_candidate_links(initial)
            assert inserted == 1

            duplicate = pd.DataFrame(
                [
                    {
                        "url": "https://example.com/article",
                        "source": "Example",
                    }
                ]
            )

            inserted_second = db.upsert_candidate_links(duplicate)
            assert inserted_second == 0

            with db.engine.connect() as conn:
                count = conn.execute(
                    text("SELECT COUNT(*) FROM candidate_links")
                ).scalar()

            assert count == 1


def test_upsert_candidate_links_returns_zero_for_empty_dataframe():
    """Empty DataFrame inputs should short-circuit without touching the DB."""

    with temporary_database() as (db_url, _):
        with DatabaseManager(database_url=db_url) as db:
            empty = pd.DataFrame(columns=["url", "source"])
            assert db.upsert_candidate_links(empty) == 0


def test_upsert_articles_returns_zero_for_empty_dataframe():
    """Empty article DataFrames should not trigger inserts."""

    with temporary_database() as (db_url, _):
        with DatabaseManager(database_url=db_url) as db:
            empty = pd.DataFrame(columns=["candidate_link_id", "url"])
            assert db.upsert_articles(empty) == 0


def test_bulk_insert_candidate_links_requires_source_column():
    """bulk_insert_candidate_links should validate required columns."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)
        df = pd.DataFrame([{"url": "https://example.com"}])

        with pytest.raises(ValueError):
            bulk_insert_candidate_links(manager.engine, df)

        manager.close()


def test_bulk_insert_articles_requires_candidate_link_id():
    """bulk_insert_articles should validate identifying columns."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)
        df = pd.DataFrame([{"url": "https://example.com/story"}])

        with pytest.raises(ValueError):
            bulk_insert_articles(manager.engine, df)

        manager.close()


def test_bulk_insert_candidate_links_adds_missing_columns():
    """The helper should ALTER TABLE to add DataFrame-specific columns."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)
        df = pd.DataFrame(
            [
                {
                    "url": "https://example.com/extra",
                    "source": "Example",
                    "source_host_id": "example.com",
                    "custom_field_xyz": "value",
                }
            ]
        )

        inserted = bulk_insert_candidate_links(
            manager.engine, df, dataset_id="ds-extra"
        )
        assert inserted == 1

        with manager.engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info(candidate_links)"))
            column_names = [row[1] for row in cols.fetchall()]

        assert "custom_field_xyz" in column_names

        with manager.engine.connect() as conn:
            ds_rows = conn.execute(
                text("SELECT legacy_host_id FROM dataset_sources")
            ).fetchall()

        assert ds_rows == [("example.com",)]

    manager.close()


def test_bulk_insert_candidate_links_non_sqlite_dataset_insert(monkeypatch):
    """dataset_sources upsert path should work for non-SQLite dialects."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        dataset_id = "ds-non-sql"
        dataset = Dataset(
            id=dataset_id,
            slug="ds-non-sql",
            label="Non SQLite Dataset",
        )
        manager.session.add(dataset)
        manager.session.commit()

        # Simulate running against a non-SQLite backend to exercise the
        # alternative insert path that uses SQLAlchemy Core insert().
        monkeypatch.setattr(manager.engine.dialect, "name", "postgresql")

        df = pd.DataFrame(
            [
                {
                    "url": "https://example.com/non-sqlite",
                    "source": "Example Non SQLite",
                    "source_host_id": "example.com",
                }
            ]
        )

        inserted = bulk_insert_candidate_links(
            manager.engine, df, dataset_id=dataset_id
        )

        assert inserted == 1

        with manager.engine.connect() as conn:
            ds_rows = conn.execute(
                text(
                    "SELECT dataset_id, legacy_host_id, source_id FROM dataset_sources"
                )
            ).fetchall()

        assert len(ds_rows) == 1
        row = ds_rows[0]
        assert row.dataset_id == dataset_id
        assert row.legacy_host_id == "example.com"
        assert row.source_id is not None

        with manager.engine.connect() as conn:
            source_rows = conn.execute(
                text("SELECT host FROM sources WHERE host = 'example.com'")
            ).fetchall()

        assert source_rows == [("example.com",)]

        manager.close()


def test_bulk_insert_articles_adds_label_columns_and_defaults():
    """bulk_insert_articles should migrate legacy schema columns."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        # Start from a legacy table lacking modern columns
        with manager.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS articles"))
            conn.execute(
                text(
                    "CREATE TABLE articles (id TEXT, candidate_id TEXT, "
                    "url TEXT, created_at TIMESTAMP)"
                )
            )

        df = pd.DataFrame(
            [
                {
                    "candidate_id": "cand-legacy",
                    "url": "https://example.com/legacy",
                    "primary_label": "news",
                    "primary_label_confidence": 0.87,
                    "alternate_label": "alt",
                    "alternate_label_confidence": 0.33,
                    "label_version": "v1",
                    "label_model_version": "m1",
                    "labels_updated_at": pd.Timestamp("2025-09-30"),
                }
            ]
        )

        inserted = bulk_insert_articles(manager.engine, df)
        assert inserted == 1

        with manager.engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info(articles)"))
            column_names = [row[1] for row in cols.fetchall()]

        expected_columns = {
            "candidate_link_id",
            "status",
            "primary_label",
            "primary_label_confidence",
            "alternate_label",
            "alternate_label_confidence",
            "label_version",
            "label_model_version",
            "labels_updated_at",
        }
        assert expected_columns.issubset(set(column_names))

        stored = pd.read_sql("SELECT * FROM articles", manager.engine)
        record = stored.iloc[0]
        assert record["primary_label"] == "news"
        assert record["primary_label_confidence"] == pytest.approx(0.87)
        assert record["alternate_label"] == "alt"
        assert record["status"] == "discovered"

        manager.close()


def test_commit_with_retry_recovers_from_locked_session():
    """_commit_with_retry should retry until commit succeeds."""

    class FlakySession:
        def __init__(self, fail_times: int):
            self.fail_times = fail_times
            self.commit_calls = 0
            self.rollback_calls = 0

        def commit(self):
            self.commit_calls += 1
            if self.commit_calls <= self.fail_times:
                raise sqlite3.OperationalError("database is locked")

        def rollback(self):
            self.rollback_calls += 1

    session = FlakySession(fail_times=2)
    _commit_with_retry(session, retries=4, backoff=0.001)

    assert session.commit_calls == 3
    assert session.rollback_calls == 2


def test_commit_with_retry_succeeds_on_final_attempt(monkeypatch):
    """Final commit outside retry loop should execute after all retries."""

    class LateSuccessSession:
        def __init__(self):
            self.commit_calls = 0
            self.rollback_calls = 0

        def commit(self):
            self.commit_calls += 1
            if self.commit_calls <= 3:
                raise sqlite3.OperationalError("database is locked")

        def rollback(self):
            self.rollback_calls += 1

    monkeypatch.setattr("src.models.database.time.sleep", lambda *_: None)

    session = LateSuccessSession()
    _commit_with_retry(session, retries=3, backoff=0)

    assert session.commit_calls == 4
    assert session.rollback_calls == 3


def test_commit_with_retry_handles_sqlalchemy_operational_error(monkeypatch):
    """SQLAlchemy OperationalError with sqlite origin should retry."""

    class WrappedOperationalSession:
        def __init__(self):
            self.commit_calls = 0
            self.rollback_calls = 0

        def commit(self):
            self.commit_calls += 1
            if self.commit_calls == 1:
                raise OperationalError(
                    "COMMIT",
                    {},
                    sqlite3.OperationalError("database is locked"),
                )

        def rollback(self):
            self.rollback_calls += 1

    monkeypatch.setattr("src.models.database.time.sleep", lambda *_: None)

    session = WrappedOperationalSession()
    _commit_with_retry(session, retries=4, backoff=0)

    assert session.commit_calls == 2
    assert session.rollback_calls == 1


def test_commit_with_retry_propagates_non_lock_errors():
    """Non-lock exceptions should bubble out of _commit_with_retry."""

    class ExplodingSession:
        def commit(self):
            raise ValueError("boom")

        def rollback(self):
            pass

    with pytest.raises(ValueError):
        _commit_with_retry(ExplodingSession(), retries=2, backoff=0)


def test_commit_with_retry_raises_after_exhausted_attempts(monkeypatch):
    """After retries are spent, the final commit should raise the lock."""

    class AlwaysLockedSession:
        def __init__(self):
            self.commit_calls = 0
            self.rollback_calls = 0

        def commit(self):
            self.commit_calls += 1
            raise sqlite3.OperationalError("database is locked")

        def rollback(self):
            self.rollback_calls += 1

    monkeypatch.setattr("src.models.database.time.sleep", lambda *_: None)

    session = AlwaysLockedSession()
    with pytest.raises(sqlite3.OperationalError):
        _commit_with_retry(session, retries=2, backoff=0)

    assert session.commit_calls == 3
    assert session.rollback_calls == 2


def test_bulk_insert_candidate_links_retries_on_lock(monkeypatch):
    """bulk_insert_candidate_links retries dataset resolution on lock."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        # Seed required tables for dataset resolution path
        df = pd.DataFrame(
            [
                {
                    "url": "https://example.com/a",
                    "source": "Example",
                    "source_host_id": "example.com",
                }
            ]
        )

        original_begin = manager.engine.begin
        calls = {"count": 0}

        def flaky_begin(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OperationalError(
                    "BEGIN", {}, sqlite3.OperationalError("database is locked")
                )
            return original_begin(*args, **kwargs)

        monkeypatch.setattr(manager.engine, "begin", flaky_begin)

        inserted = bulk_insert_candidate_links(
            manager.engine,
            df,
            dataset_id="ds1",
        )
        assert inserted == 1
        assert calls["count"] >= 2

        with manager.engine.connect() as conn:
            ds_count = conn.execute(
                text("SELECT COUNT(*) FROM dataset_sources")
            ).scalar()

        assert ds_count == 1
        manager.close()


def test_update_source_metadata_merges_dict_and_handles_locks(monkeypatch):
    """update_source_metadata should merge JSON and survive lock failures."""

    with temporary_database() as (db_url, _):
        # Simulate lock failure on first update attempt
        with DatabaseManager(database_url=db_url) as db:
            source = Source(
                id="source-1",
                host="example.com",
                host_norm="example.com",
                canonical_name="Example",
                meta={"existing": True},
            )
            db.session.add(source)
            db.session.commit()

            rollback_calls = []
            original_commit = db.session.commit
            original_rollback = db.session.rollback
            error_triggered = {"done": False}

            def flaky_commit():
                if not error_triggered["done"]:
                    error_triggered["done"] = True
                    rollback_calls.append(True)
                    raise sqlite3.OperationalError("database is locked")
                return original_commit()

            def tracked_rollback():
                rollback_calls.append(False)
                return original_rollback()

            monkeypatch.setattr(db.session, "commit", flaky_commit)
            monkeypatch.setattr(db.session, "rollback", tracked_rollback)

            result = db.update_source_metadata(
                "source-1",
                {"existing": False, "new": "value"},
            )

            assert result is False
            assert rollback_calls == [True, False]

            base_meta = db.session.execute(
                select(Source.meta).where(Source.id == "source-1")
            ).scalar_one()
            assert base_meta == {"existing": True}

        # Retry update in a fresh session to ensure merge works after failure
        with DatabaseManager(database_url=db_url) as db:
            success = db.update_source_metadata(
                "source-1",
                {"existing": False, "new": "value", "another": 123},
            )
            assert success is True
            db.session.commit()

            meta = db.session.execute(
                select(Source.meta).where(Source.id == "source-1")
            ).scalar_one()
            raw_meta = db.session.execute(
                text("SELECT metadata FROM sources WHERE id='source-1'")
            ).scalar_one()
            assert "new" in raw_meta
            assert meta["new"] == "value"
            assert meta["another"] == 123
            assert meta["existing"] is False

            refreshed = db.session.get(Source, "source-1")
            assert refreshed is not None
            assert refreshed.meta["existing"] is False

            toggle_success = db.update_source_metadata("source-1", {"existing": True})
            assert toggle_success is True
            meta_after_toggle = db.session.execute(
                select(Source.meta).where(Source.id == "source-1")
            ).scalar_one()
            assert meta_after_toggle["existing"] is True


def test_bulk_insert_articles_migrates_schema_and_adds_defaults():
    """bulk_insert_articles should add defaults and update legacy schema."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        # Create a legacy-style table missing modern columns
        with manager.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS articles"))
            conn.execute(
                text(
                    "CREATE TABLE articles (id TEXT, candidate_id TEXT, "
                    "url TEXT, created_at TIMESTAMP)"
                )
            )

        df = pd.DataFrame(
            [
                {
                    "candidate_id": "cand-123",
                    "url": "https://example.com/article",
                }
            ]
        )

        inserted = bulk_insert_articles(manager.engine, df)
        assert inserted == 1

        with manager.engine.connect() as conn:
            row = conn.execute(
                text("SELECT candidate_link_id, status, created_at FROM articles")
            ).one()
            columns = {
                info[1] for info in conn.execute(text("PRAGMA table_info(articles)"))
            }

        assert row.candidate_link_id == "cand-123"
        assert row.status == "discovered"
        assert row.created_at is not None
        assert {"candidate_link_id", "status", "primary_label"}.issubset(columns)

        manager.close()


def test_bulk_insert_articles_requires_candidate_and_url():
    """Missing required columns should raise a ValueError."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)
        df = pd.DataFrame([{"source": "Example Only"}])

        with pytest.raises(ValueError):
            bulk_insert_articles(manager.engine, df)

        manager.close()


def test_upsert_article_handles_lock_and_updates(monkeypatch):
    """upsert_article retries on a simulated lock and updates rows."""

    with temporary_database() as (db_url, _):
        with DatabaseManager(database_url=db_url) as db:
            candidate = CandidateLink(
                id="cand-lock",
                url="https://example.com/article",
                source="Article Source",
            )
            db.session.add(candidate)
            db.session.commit()

            attempts = {"count": 0}
            simulated = {"handled": False}

            def simulated_commit_with_retry(session, retries=4, backoff=0.1):
                if not simulated["handled"]:
                    simulated["handled"] = True
                    attempts["count"] += 1
                    pending = list(session.new)
                    session.rollback()
                    for obj in pending:
                        session.add(obj)
                    attempts["count"] += 1
                    session.commit()
                    return
                session.commit()

            monkeypatch.setattr(
                "src.models.database._commit_with_retry",
                simulated_commit_with_retry,
            )

            article_text = "Breaking news content"

            article = upsert_article(
                db.session,
                candidate_id="cand-lock",
                text=article_text,
                status="processed",
                url="https://example.com/article",
            )

            article_id = str(article.id)

            stored = db.session.get(Article, article_id)
            assert stored is not None
            assert str(stored.candidate_link_id) == "cand-lock"
            assert str(stored.status) == "processed"
            assert str(stored.text_hash) == calculate_content_hash(article_text)
            assert attempts["count"] >= 2

            upsert_article(
                db.session,
                candidate_id="cand-lock",
                text=article_text,
                status="verified",
                title="Updated title",
            )

            stored_updated = db.session.get(Article, article_id)
            assert stored_updated is not None
            assert str(stored_updated.status) == "verified"
            assert str(stored_updated.title) == "Updated title"


def test_prediction_to_tuple_variants():
    class ObjectPrediction:
        label = "news"
        score = 0.87

    assert _prediction_to_tuple(ObjectPrediction()) == ("news", 0.87)
    assert _prediction_to_tuple({"label": "sports", "score": 0.42}) == (
        "sports",
        0.42,
    )
    assert _prediction_to_tuple({"label": "politics", "confidence": 0.33}) == (
        "politics",
        0.33,
    )
    assert _prediction_to_tuple(None) == (None, None)
    assert _prediction_to_tuple(object()) == (None, None)


def test_save_article_classification_creates_and_updates():
    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        article = Article(
            id="article-1",
            candidate_link_id="cand-1",
            url="https://example.com/article",
        )
        manager.session.add(article)
        manager.session.commit()

        created = save_article_classification(
            manager.session,
            article_id="article-1",
            label_version="2025.09",
            model_version="model-a",
            primary_prediction={"label": "news", "score": 0.95},
            alternate_prediction={"label": "sports", "confidence": 0.12},
            model_path="/models/a",
            metadata={"threshold": 0.9},
        )

        assert isinstance(created, ArticleLabel)
        assert created.primary_label == "news"
        assert created.alternate_label == "sports"
        assert created.primary_label_confidence == 0.95
        assert created.alternate_label_confidence == 0.12
        assert created.model_path == "/models/a"
        original_applied_at = created.applied_at

        updated = save_article_classification(
            manager.session,
            article_id="article-1",
            label_version="2025.09",
            model_version="model-b",
            primary_prediction=types.SimpleNamespace(label="metro", score=0.77),
            alternate_prediction=None,
            metadata={"threshold": 0.8},
        )

        assert updated.primary_label == "metro"
        assert updated.alternate_label is None
        assert updated.primary_label_confidence == 0.77
        assert updated.alternate_label_confidence is None
        assert updated.model_version == "model-b"
        assert updated.meta == {"threshold": 0.8}
        assert updated.applied_at >= original_applied_at

        stored = (
            manager.session.query(ArticleLabel)
            .filter_by(article_id="article-1", label_version="2025.09")
            .one()
        )
        assert stored.primary_label == "metro"
        assert stored.model_version == "model-b"

        with pytest.raises(ValueError):
            save_article_classification(
                manager.session,
                article_id="article-1",
                label_version="2025.09",
                model_version="model-c",
                primary_prediction=None,
            )

        manager.close()


def test_save_ml_results_persists_records():
    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        article = Article(
            id="article-ml",
            candidate_link_id="cand-ml",
            url="https://example.com/ml",
        )
        manager.session.add(article)
        manager.session.commit()

        records = save_ml_results(
            manager.session,
            article_id="article-ml",
            model_version="v1",
            model_type="classifier",
            results=[
                {"label": "news", "score": 0.9},
                {"label": "sports", "confidence": 0.1},
            ],
            job_id="job-123",
        )

        assert len(records) == 2
        assert {record.label for record in records} == {
            "news",
            "sports",
        }

        stored = (
            manager.session.query(MLResult)
            .filter_by(article_id="article-ml")
            .order_by(MLResult.label)
            .all()
        )

        assert len(stored) == 2
        assert stored[0].model_version == "v1"
        assert stored[0].model_type == "classifier"
        assert stored[0].details["label"] in {"news", "sports"}
        assert stored[1].details["label"] in {"news", "sports"}
        assert stored[0].job_id == "job-123"

        manager.close()


def test_normalize_entity_text_cleans_unicode():
    assert _normalize_entity_text(None) == ""
    normalized = _normalize_entity_text(" County’s – Office! ")
    assert normalized == "county's - office"


def test_save_locations_persists_records():
    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        article = Article(
            id="article-loc",
            candidate_link_id="cand-loc",
            url="https://example.com/location",
        )
        manager.session.add(article)
        manager.session.commit()

        entities = [
            {
                "text": "Boone County",
                "label": "PLACE",
                "confidence": 0.87,
                "lat": 38.95,
                "lon": -92.33,
                "place": "Boone County, MO",
                "geocoding_source": "gazetteer",
            }
        ]

        records = save_locations(
            manager.session,
            article_id="article-loc",
            entities=entities,
            ner_model_version="ner-1",
        )

        assert len(records) == 1
        stored = (
            manager.session.query(Location).filter_by(article_id="article-loc").one()
        )
        assert stored.entity_text == "Boone County"
        assert stored.ner_model_version == "ner-1"
        assert stored.geocoded_place == "Boone County, MO"

        manager.close()


def test_save_article_entities_replaces_existing():
    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        article = Article(
            id="article-entity",
            candidate_link_id="cand-entity",
            url="https://example.com/entity",
        )
        manager.session.add(article)
        manager.session.commit()

        existing = ArticleEntity(
            article_id="article-entity",
            entity_text="Old Name",
            entity_norm="old name",
            entity_label="PLACE",
            extractor_version="v1",
        )
        manager.session.add(existing)
        manager.session.commit()

        entities = [
            {
                "entity_text": "City Hall",
                "entity_label": "PLACE",
                "confidence": 0.8,
                "matched_gazetteer_id": "gaz-1",
            },
            {
                "entity_text": "County’s Park",
                "entity_label": "PLACE",
                "match_name": "County Park",
            },
            {"text": None, "entity_label": "IGNORE"},
        ]

        results = save_article_entities(
            manager.session,
            article_id="article-entity",
            entities=entities,
            extractor_version="v1",
            article_text_hash="hash-1",
        )

        assert len(results) == 2
        stored = (
            manager.session.query(ArticleEntity)
            .filter_by(article_id="article-entity", extractor_version="v1")
            .all()
        )
        assert len(stored) == 2
        norms = {entity.entity_norm for entity in stored}
        assert _normalize_entity_text("County’s Park") in norms
        assert "old name" not in norms

        manager.close()


def test_create_and_finish_job_record_updates_metrics():
    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        job = create_job_record(
            manager.session,
            job_type="extraction",
            job_name="daily",
            params={"limit": 25},
            commit_sha="abc123",
        )

        assert isinstance(job, Job)
        finished = finish_job_record(
            manager.session,
            job_id=job.id,
            exit_status="success",
            metrics={"records_processed": 7, "unknown_field": 99},
        )

        assert finished.exit_status == "success"
        assert finished.records_processed == 7
        assert not hasattr(finished, "unknown_field")

        manager.close()


def test_read_candidate_links_and_articles_filters():
    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        df = pd.DataFrame(
            [
                {
                    "url": "https://example.com/a",
                    "source": "Example",
                    "source_host_id": "example.com",
                },
                {
                    "url": "https://other.com/b",
                    "source": "Other",
                    "source_host_id": "other.com",
                },
            ]
        )

        manager.upsert_candidate_links(df)

        filtered_links = read_candidate_links(
            manager.engine, filters={"source": "Example"}
        )
        assert list(filtered_links["source"]) == ["Example"]

        candidate = (
            manager.session.query(CandidateLink).filter_by(source="Example").one()
        )

        upsert_article(
            manager.session,
            candidate_id=str(candidate.id),
            text="Breaking story",
            status="processed",
            url="https://example.com/a",
        )

        articles_df = read_articles(manager.engine, filters={"status": "processed"})

        assert len(articles_df) == 1
        assert list(articles_df["source"]) == ["Example"]
        url_values = articles_df.filter(like="url").iloc[0].tolist()
        assert "https://example.com/a" in url_values

        manager.close()


def test_export_to_parquet_emits_snappy_file(tmp_path, monkeypatch):
    """export_to_parquet should read filtered rows and write Parquet output."""

    with temporary_database() as (db_url, _):
        manager = DatabaseManager(database_url=db_url)

        df = pd.DataFrame(
            [
                {
                    "url": "https://example.com/parquet",
                    "source": "Example",
                    "status": "processed",
                }
            ]
        )
        manager.upsert_candidate_links(df)

        output_path = tmp_path / "candidate_links.parquet"
        written = {"called": False}

        def fake_to_parquet(self, path, compression=None):
            written["called"] = True
            Path(path).write_text("parquet-placeholder")
            assert compression == "snappy"
            return None

        monkeypatch.setattr(
            pd.DataFrame,
            "to_parquet",
            fake_to_parquet,
            raising=False,
        )

        result = export_to_parquet(
            manager.engine,
            "candidate_links",
            str(output_path),
            filters={"status": "processed"},
        )

        assert written["called"] is True
        assert Path(result).read_text() == "parquet-placeholder"

        manager.close()
