"""Database utilities for SQLite backend with idempotent operations."""

import hashlib
import json
import logging
import random
import re
import time
import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import (
    MetaData,
    Table,
    create_engine,
    event,
    insert,
    select,
    text,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from src.utils.url_utils import normalize_url

from . import (
    Article,
    ArticleEntity,
    ArticleLabel,
    Base,
    CandidateLink,
    Job,
    Location,
    MLResult,
    Source,
)

logger = logging.getLogger(__name__)


def _is_sequence_of_sequences(obj):
    """Return True if obj is a list/tuple of non-dict sequences."""
    if not obj:
        return False
    if isinstance(obj, (list, tuple)) and obj and not isinstance(obj[0], dict):
        # ensure inner items are sequences (tuple/list)
        return all(isinstance(x, (list, tuple)) for x in obj)
    return False


def safe_execute(conn, sql, params=None):
    """Compatibility wrapper for Connection.execute to accept positional
    parameter sequences (e.g., executemany-style list of tuples) and honor
    both qmark/%s and named :param styles.

    - If `sql` is a SQLAlchemy Insert/Select object, call through.
    - If `params` is a list/tuple of sequences and SQL contains '?' or '%s',
      convert the SQL to named parameters (:p0, :p1, ...) and map each tuple
      to a dict before executing (works with executemany semantics).
    - Otherwise delegate to conn.execute(text(sql), params).
    """
    from sqlalchemy.exc import ArgumentError
    from sqlalchemy.sql import text as _text

    # Use the original execute method if available (to avoid recursion when
    # called from a patched connection)
    original_execute = getattr(conn, "_orig_execute", None) or conn.execute

    # If caller passed a SQLAlchemy Core object (Insert/Select), just execute
    if not isinstance(sql, (str,)):
        try:
            if params is not None:
                return original_execute(sql, params)
            return original_execute(sql)
        except Exception:
            # fallthrough to text wrapper
            pass

    sql_str = str(sql)

    # Handle list/tuple of tuple params for executemany-style calls where SQL
    # uses '?' (qmark) or '%s' placeholders.
    if _is_sequence_of_sequences(params) and ("?" in sql_str or "%s" in sql_str):
        # normalize placeholders: replace each ? or %s with :p{index}
        # Count the number of placeholders by counting occurrences of ? or %s
        # We assume each row has the same number of columns as placeholders.
        # Build a single-row named-parameter SQL then map each tuple to a dict.
        # Find placeholders in order
        if "?" in sql_str:
            parts = sql_str.split("?")
            ph_count = len(parts) - 1
            for i in range(ph_count):
                sql_str = sql_str.replace("?", f":p{i}", 1)
        else:
            # handle %s style
            parts = sql_str.split("%s")
            ph_count = len(parts) - 1
            for i in range(ph_count):
                sql_str = sql_str.replace("%s", f":p{i}", 1)

        named_rows = []
        for row in params:
            named_rows.append({f"p{i}": v for i, v in enumerate(row)})

        return original_execute(_text(sql_str), named_rows)

    # Otherwise try normal execution; if ArgumentError arises, try to coerce
    # positional single tuple into a named mapping.
    try:
        if params is not None:
            return original_execute(_text(sql_str), params)
        return original_execute(_text(sql_str))
    except ArgumentError:
        # If params is a single tuple/list, map to p0..pn and replace ?/%s
        if (
            isinstance(params, (list, tuple))
            and params
            and not isinstance(params[0], dict)
        ):
            row = params
            if "?" in sql_str or "%s" in sql_str:
                if "?" in sql_str:
                    for i in range(len(row)):
                        sql_str = sql_str.replace("?", f":p{i}", 1)
                else:
                    for i in range(len(row)):
                        sql_str = sql_str.replace("%s", f":p{i}", 1)
                named = {f"p{i}": v for i, v in enumerate(row)}
                return original_execute(_text(sql_str), named)
        # re-raise if we cannot coerce
        raise


def safe_session_execute(session, sql, params=None):
    """Compatibility wrapper for Session.execute that tolerates legacy
    positional parameter styles (list/tuple of tuples) and qmark/%s
    placeholders by coercing them into named-parameter forms.

    This function tries to call ``session.execute`` directly and only
    transforms parameters when SQLAlchemy raises an ArgumentError.
    """
    from sqlalchemy.exc import ArgumentError
    from sqlalchemy.sql import text as _text

    # If caller passed a SQLAlchemy Core object, try to execute directly
    if not isinstance(sql, (str,)):
        try:
            if params is not None:
                return session.execute(sql, params)
            return session.execute(sql)
        except Exception:
            # fallthrough to string-based handling
            pass

    sql_str = str(sql)

    # Handle list/tuple-of-tuples executemany with qmark/%s placeholders
    if _is_sequence_of_sequences(params) and ("?" in sql_str or "%s" in sql_str):
        # Normalize placeholders to :p0, :p1, ...
        if "?" in sql_str:
            parts = sql_str.split("?")
            ph_count = len(parts) - 1
            for i in range(ph_count):
                sql_str = sql_str.replace("?", f":p{i}", 1)
        else:
            parts = sql_str.split("%s")
            ph_count = len(parts) - 1
            for i in range(ph_count):
                sql_str = sql_str.replace("%s", f":p{i}", 1)

        named_rows = []
        for row in params:
            named_rows.append({f"p{i}": v for i, v in enumerate(row)})

        return session.execute(_text(sql_str), named_rows)

    # Otherwise try normal execution and coerce single tuple/list to mapping
    try:
        if params is not None:
            return session.execute(_text(sql_str), params)
        return session.execute(_text(sql_str))
    except ArgumentError:
        if (
            isinstance(params, (list, tuple))
            and params
            and not isinstance(params[0], dict)
        ):
            row = params
            if "?" in sql_str or "%s" in sql_str:
                if "?" in sql_str:
                    for i in range(len(row)):
                        sql_str = sql_str.replace("?", f":p{i}", 1)
                else:
                    for i in range(len(row)):
                        sql_str = sql_str.replace("%s", f":p{i}", 1)
                named = {f"p{i}": v for i, v in enumerate(row)}
                return session.execute(_text(sql_str), named)
        raise


def _configure_sqlite_engine(engine, timeout: float | None) -> None:
    """Enable WAL/unified writer settings for SQLite connections."""

    busy_timeout_ms = int((timeout or 30) * 1000)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.close()


class _ConnectionProxy:
    """Wrap a SQLAlchemy Connection to normalize execute calls.

    Only `execute` is overridden to funnel through `safe_execute`. All other
    attributes/methods are proxied to the underlying connection.
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args, **kwargs):
        """Proxy execute that accepts SQLAlchemy's execution_options kwarg.

        SQLAlchemy sometimes calls Connection.execute with additional
        keyword arguments such as `execution_options=`. Accept arbitrary
        args/kwargs, extract positional or named parameter containers, and
        forward to safe_execute. Any extra kwargs that are not parameters
        are ignored here because safe_execute only needs (conn, sql, params).
        """
        # Positional params commonly passed as first arg
        params = None
        if args:
            params = args[0]
        elif "params" in kwargs:
            params = kwargs.pop("params")
        elif "parameters" in kwargs:
            params = kwargs.pop("parameters")

        # Remove sqlalchemy-specific kwargs we don't need
        kwargs.pop("execution_options", None)
        kwargs.pop("_sa_orm_load_options", None)

        return safe_execute(self._conn, sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    # Support context manager protocol so callers can use `with engine.connect()`
    # and receive a proxied connection that still works as a context manager.
    def __enter__(self):
        # If the underlying connection supports __enter__, delegate and
        # keep the proxied wrapper pointing at the entered connection.
        enter = getattr(self._conn, "__enter__", None)
        if enter:
            entered = enter()
            # Replace underlying connection with the entered one
            self._conn = entered
        return self

    def __exit__(self, exc_type, exc, tb):
        exit_fn = getattr(self._conn, "__exit__", None)
        if exit_fn:
            return exit_fn(exc_type, exc, tb)
        # If underlying connection doesn't implement __exit__, try close()
        close_fn = getattr(self._conn, "close", None)
        if close_fn:
            try:
                close_fn()
            except Exception:
                pass


class _EngineProxy:
    """Lightweight proxy for Engine that wraps returned connections.

    This allows existing call sites that do `with engine.begin() as conn:` to
    receive a connection whose `execute` method accepts positional params.
    """

    def __init__(self, engine):
        self._engine = engine

    def begin(self, *args, **kwargs):
        ctx = self._engine.begin(*args, **kwargs)

        class _Ctx:
            def __enter__(inner_self):
                real_conn = ctx.__enter__()
                return _ConnectionProxy(real_conn)

            def __exit__(inner_self, exc_type, exc, tb):
                return ctx.__exit__(exc_type, exc, tb)

        return _Ctx()

    def __getattr__(self, name):
        return getattr(self._engine, name)

    # Expose a few common attributes pandas/sqlalchemy duck-check for so that
    # the proxy is treated like a real SQLAlchemy Engine by callers such as
    # pandas.read_sql_query which checks for SQLAlchemy connectables.
    @property
    def dialect(self):
        return getattr(self._engine, "dialect", None)

    @property
    def url(self):
        return getattr(self._engine, "url", None)

    @property
    def name(self):
        # Some code checks for engine.name; delegate if present.
        return getattr(self._engine, "name", None)

    def connect(self, *args, **kwargs):
        # Return a proxied connection so callers using engine.connect() also
        # get an execute that funnels through safe_execute when appropriate.
        real_conn = self._engine.connect(*args, **kwargs)
        return _ConnectionProxy(real_conn)


def _wrap_engine_connections(engine):
    """Mutate a SQLAlchemy Engine so its connect()/begin() return proxied
    Connection objects while leaving the Engine object itself intact.

    This preserves the real Engine for third-party libraries (pandas,
    SQLAlchemy inspection, Alembic) while ensuring any Connection obtained
    from the engine routes execute() through our safe_execute compatibility
    wrapper.
    """
    # Keep original methods
    orig_connect = engine.connect
    orig_begin = engine.begin

    import types

    def _monkeypatch_conn_execute(conn):
        """Patch a real SQLAlchemy Connection instance so its .execute
        funnels through safe_execute while keeping the object's type
        intact (so SQLAlchemy's inspection and pandas work correctly).
        This avoids returning a separate proxy object which SQLAlchemy
        inspect() may not recognize.
        """
        # Avoid double-patching
        if getattr(conn, "_safe_execute_patched", False):
            return conn

        orig_execute = getattr(conn, "execute", None)

        def _patched_execute(self, sql, *args, **kwargs):
            # Extract positional/keyword params similar to the proxy
            params = None
            if args:
                params = args[0]
            elif "params" in kwargs:
                params = kwargs.pop("params")
            elif "parameters" in kwargs:
                params = kwargs.pop("parameters")

            # Remove SQLAlchemy-only kwargs
            kwargs.pop("execution_options", None)
            kwargs.pop("_sa_orm_load_options", None)

            # Delegate to compatibility wrapper which will call the
            # original execute under the hood where appropriate.
            return safe_execute(self, sql, params)

        # Bind the patched function as a method on the instance
        conn.execute = types.MethodType(_patched_execute, conn)
        # Store original execute in case other code wants it later
        try:
            conn._orig_execute = orig_execute
        except Exception:
            pass
        conn._safe_execute_patched = True
        return conn

    def connect(*args, **kwargs):
        real_conn = orig_connect(*args, **kwargs)
        return _monkeypatch_conn_execute(real_conn)

    def begin(*args, **kwargs):
        ctx = orig_begin(*args, **kwargs)

        class _Ctx:
            def __enter__(inner_self):
                real_conn = ctx.__enter__()
                return _monkeypatch_conn_execute(real_conn)

            def __exit__(inner_self, exc_type, exc, tb):
                return ctx.__exit__(exc_type, exc, tb)

        return _Ctx()

    # Monkey-patch the engine instance methods
    engine.connect = connect
    engine.begin = begin


class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self, database_url: str | None = None):
        """
        Initialize DatabaseManager.

        If `database_url` is not provided, prefer the application's configured
        DATABASE_URL from `src.config`. This allows call sites to simply use
        `DatabaseManager()` in deployed environments while still falling back
        to the default local SQLite path for quick local runs and tests.
        """
        # Defer import to avoid import-time side effects in test/bootstrap code
        # Resolution order:
        # 1. explicit `database_url` arg
        # 2. environment variable `DATABASE_URL` (allows runtime overrides)
        # 3. environment variable `TEST_DATABASE_URL` (test environments)
        # 4. finally, fall back to configured value from `src.config`
        #
        # NOTE: SQLite fallback removed. All environments use PostgreSQL.
        # Tests use TEST_DATABASE_URL or DATABASE_URL.
        import os

        if not database_url:
            env_db = os.getenv("DATABASE_URL")
            if env_db:
                database_url = env_db
            else:
                # Check for TEST_DATABASE_URL (used in local dev and CI)
                test_db = os.getenv("TEST_DATABASE_URL")
                if test_db:
                    database_url = test_db
                else:
                    try:
                        from src.config import DATABASE_URL as _cfg_db_url

                        database_url = _cfg_db_url
                    except Exception:
                        raise RuntimeError(
                            "No PostgreSQL database URL found. "
                            "Set DATABASE_URL or TEST_DATABASE_URL."
                        )

        self.database_url = database_url

        # Check if we should use Cloud SQL Python Connector
        use_cloud_sql = self._should_use_cloud_sql_connector()

        # Validate PostgreSQL URL
        if "postgresql" not in database_url.lower():
            raise ValueError(
                f"DatabaseManager requires PostgreSQL database URL. "
                f"Got: {database_url[:50]}... "
                f"Set DATABASE_URL or TEST_DATABASE_URL environment variable."
            )

        if use_cloud_sql:
            self.engine = self._create_cloud_sql_engine()
        else:
            # Direct PostgreSQL connection
            self.engine = create_engine(
                database_url,
                connect_args={},
                echo=False,
            )

        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def _should_use_cloud_sql_connector(self) -> bool:
        """Determine if Cloud SQL Python Connector should be used."""
        import os

        # Check environment variable first (for test control)
        if os.getenv("USE_CLOUD_SQL_CONNECTOR", "").lower() in ("false", "0", "no"):
            return False

        try:
            from src.config import CLOUD_SQL_INSTANCE, USE_CLOUD_SQL_CONNECTOR

            return USE_CLOUD_SQL_CONNECTOR and bool(CLOUD_SQL_INSTANCE)
        except ImportError:
            return False

    def _create_cloud_sql_engine(self):
        """Create database engine using Cloud SQL Python Connector."""
        from src.config import (
            CLOUD_SQL_INSTANCE,
            DATABASE_NAME,
            DATABASE_PASSWORD,
            DATABASE_USER,
        )

        try:
            from src.models.cloud_sql_connector import create_cloud_sql_engine

            logger.info("Using Cloud SQL Python Connector (no proxy sidecar needed)")

            return create_cloud_sql_engine(
                instance_connection_name=CLOUD_SQL_INSTANCE,
                user=DATABASE_USER,
                password=DATABASE_PASSWORD,
                database=DATABASE_NAME,
                driver="pg8000",
                echo=False,
            )
        except ImportError as e:
            logger.warning(
                "Cloud SQL connector not available, "
                "falling back to direct connection. Error: %s",
                e,
            )
            # Fall back to direct PostgreSQL connection
            connection_url = (
                f"postgresql://{DATABASE_USER}:{DATABASE_PASSWORD}" f"@/{DATABASE_NAME}"
            )
            return create_engine(connection_url, echo=False)

    def get_session(self):
        """Context manager for getting a database session.

        Usage:
            with db_manager.get_session() as session:
                # Use session here
                pass
        """
        from contextlib import contextmanager

        @contextmanager
        def session_context():
            Session = sessionmaker(bind=self.engine)
            session = Session()
            try:
                yield session
            finally:
                session.close()

        return session_context()

    def close(self):
        """Close database connection."""
        self.session.close()
        self.engine.dispose()

    def update_source_metadata(self, source_id: str, updates: dict) -> bool:
        """Merge `updates` into the `metadata` JSON column for a Source.

        Returns True if the source existed and was updated, False otherwise.
        """
        try:
            src = self.session.query(Source).filter_by(id=source_id).first()
            if not src:
                return False

            current = src.meta or {}
            # Ensure dict form
            if isinstance(current, str):
                try:
                    current = json.loads(current)
                except Exception:
                    current = {}

            if not isinstance(current, dict):
                current = {}

            # Merge updates (shallow). Assign a new dict instance so
            # SQLAlchemy detects the change even when the JSON column
            # isn't using a mutable tracking type.
            current.update(updates)
            src.meta = dict(current)  # type: ignore[assignment]
            flag_modified(src, "meta")
            self.session.commit()
            return True
        except Exception:
            # We don't want metadata update failures to break discovery
            try:
                self.session.rollback()
            except Exception:
                pass
            return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def upsert_candidate_links(
        self,
        df: pd.DataFrame,
        if_exists: Literal["fail", "replace", "append"] = "append",
        dataset_id: str | None = None,
    ) -> int:
        """Convenience wrapper to bulk insert candidate links from a DataFrame.

        This method ensures the DataFrame has required defaults and then
        delegates to the module-level `bulk_insert_candidate_links` helper.
        """
        if df is None or df.empty:
            return 0

        try:
            rows = bulk_insert_candidate_links(
                self.engine, df, if_exists=if_exists, dataset_id=dataset_id
            )
            return rows
        except Exception as e:
            logger.error(f"Failed to bulk insert candidate links: {e}")
            raise

    def upsert_articles(
        self,
        df: pd.DataFrame,
        if_exists: Literal["fail", "replace", "append"] = "append",
    ) -> int:
        """Convenience wrapper to bulk insert articles from a DataFrame.

        The CLI expects columns like `candidate_link_id`, `url`, `title`,
        `content`, `status`, and `metadata`. This wrapper normalizes the
        DataFrame before calling the module-level `bulk_insert_articles`.
        """
        if df is None or df.empty:
            return 0

        try:
            rows = bulk_insert_articles(self.engine, df, if_exists=if_exists)
            return rows
        except Exception as e:
            logger.error(f"Failed to bulk insert articles: {e}")
            raise


def _commit_with_retry(session, retries: int = 4, backoff: float = 0.1):
    """Commit the SQLAlchemy session with retries on sqlite OperationalError.

    This avoids transient 'database is locked' errors by sleeping and retrying.
    """
    import sqlite3 as _sqlite

    for attempt in range(retries):
        try:
            session.commit()
            return
        except Exception as e:
            # Prefer to detect sqlite3.OperationalError but tolerate SQLAlchemy
            if isinstance(e, _sqlite.OperationalError) or (
                hasattr(e, "orig") and isinstance(e.orig, _sqlite.OperationalError)
            ):
                logger.warning(
                    "Commit attempt %d/%d failed with OperationalError: %s",
                    attempt + 1,
                    retries,
                    e,
                )
                try:
                    session.rollback()
                except Exception as rollback_exc:  # pragma: no cover
                    logger.error(
                        "Rollback after failed commit also failed: %s",
                        rollback_exc,
                    )
                time.sleep(backoff)
                backoff *= 2
                continue
            else:
                try:
                    session.rollback()
                except Exception as rollback_exc:  # pragma: no cover
                    logger.error(
                        ("Rollback after non-retryable commit failure failed: %s"),
                        rollback_exc,
                    )
                # Non-retryable error, re-raise
                raise
    # Final attempt
    session.commit()


def upsert_candidate_links(
    self,
    df: pd.DataFrame,
    if_exists: Literal["fail", "replace", "append"] = "append",
    dataset_id: str | None = None,
) -> int:
    """Convenience wrapper to bulk insert candidate links from a DataFrame.

    This method ensures the DataFrame has required defaults and then
    delegates to the module-level `bulk_insert_candidate_links` helper.
    """
    if df is None or df.empty:
        return 0

    # Ensure the data directory exists for SQLite DB file
    # (engine will create DB file as needed)
    try:
        rows = bulk_insert_candidate_links(
            self.engine, df, if_exists=if_exists, dataset_id=dataset_id
        )
        return rows
    except Exception as e:
        logger.error(f"Failed to bulk insert candidate links: {e}")
        raise


def upsert_articles(
    self,
    df: pd.DataFrame,
    if_exists: Literal["fail", "replace", "append"] = "append",
) -> int:
    """Convenience wrapper to bulk insert articles from a DataFrame.

    The CLI expects columns like `candidate_link_id`, `url`, `title`,
    `content`, `status`, and `metadata`. This wrapper normalizes the
    DataFrame before calling the module-level `bulk_insert_articles`.
    """
    if df is None or df.empty:
        return 0

    try:
        rows = bulk_insert_articles(self.engine, df, if_exists=if_exists)
        return rows
    except Exception as e:
        logger.error(f"Failed to bulk insert articles: {e}")
        raise


def calculate_content_hash(content: str) -> str:
    """Calculate SHA256 hash of content for deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def upsert_candidate_link(
    session,
    url: str,
    source: str,
    **kwargs,
) -> CandidateLink:
    """Insert or update candidate link (idempotent by URL)."""
    # Normalize URL for consistent deduplication
    normalized_url = normalize_url(url)

    # Check if link already exists (using normalized URL)
    existing = session.query(CandidateLink).filter_by(url=normalized_url).first()

    if existing:
        # Update existing record with new data
        for key, value in kwargs.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        # Commit with retry to mitigate transient sqlite locks
        _commit_with_retry(session)
        logger.debug(f"Updated existing candidate link: {normalized_url}")
        return existing
    else:
        # Create new record (using normalized URL)
        link = CandidateLink(url=normalized_url, source=source, **kwargs)
        session.add(link)
        # Commit with retry to mitigate transient sqlite locks
        _commit_with_retry(session)
        logger.info(f"Created new candidate link: {normalized_url}")
        return link


def upsert_article(session, candidate_id: str, text: str, **kwargs) -> Article:
    """Insert or update article (idempotent by candidate_id + text_hash)."""
    text_hash = calculate_content_hash(text)

    # Normalize parameter name to match model column `candidate_link_id`
    candidate_link_id = kwargs.pop("candidate_link_id", None) or candidate_id

    # Check if article already exists
    existing = (
        session.query(Article)
        .filter_by(candidate_link_id=candidate_link_id, text_hash=text_hash)
        .first()
    )

    if existing:
        # Update existing record
        for key, value in kwargs.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        _commit_with_retry(session)
        logger.debug(f"Updated existing article for candidate: {candidate_id}")
        return existing
    else:
        # Create new record
        article = Article(
            candidate_link_id=candidate_link_id,
            text=text,
            text_hash=text_hash,
            text_excerpt=text[:500] if text else None,
            **kwargs,
        )
        session.add(article)
        _commit_with_retry(session)
        logger.info(f"Created new article for candidate: {candidate_id}")
        return article


def save_ml_results(
    session,
    article_id: str,
    model_version: str,
    model_type: str,
    results: list[dict[str, Any]],
    job_id: str | None = None,
) -> list[MLResult]:
    """Save ML results for an article."""
    ml_records = []

    for result in results:
        ml_result = MLResult(
            article_id=article_id,
            model_version=model_version,
            model_type=model_type,
            label=result.get("label"),
            score=result.get("score"),
            confidence=result.get("confidence"),
            job_id=job_id,
            details=result,
        )
        session.add(ml_result)
        ml_records.append(ml_result)

    session.commit()
    logger.info(
        "Saved %d ML results for article: %s",
        len(ml_records),
        article_id,
    )
    return ml_records


def _prediction_to_tuple(
    prediction: Any | None,
) -> tuple[str | None, float | None]:
    """Normalize prediction objects or dicts into (label, score)."""

    if prediction is None:
        return None, None

    if hasattr(prediction, "label"):
        label = prediction.label
        score = getattr(prediction, "score", None)
        return label, score

    if isinstance(prediction, dict):
        label = prediction.get("label")
        score = prediction.get("score") or prediction.get("confidence")
        return label, score

    return None, None


def save_article_classification(
    session,
    article_id: str,
    label_version: str,
    model_version: str,
    primary_prediction: Any,
    alternate_prediction: Any | None = None,
    model_path: str | None = None,
    metadata: dict[str, Any] | None = None,
    autocommit: bool = True,
) -> ArticleLabel:
    """Persist primary/alternate labels and update article snapshot.
    
    Args:
        autocommit: If False, caller must commit. Use for batch processing.
    """

    primary_label, primary_score = _prediction_to_tuple(primary_prediction)
    alt_label, alt_score = _prediction_to_tuple(alternate_prediction)

    if primary_label is None:
        raise ValueError("Primary prediction must include a label")

    record = (
        session.query(ArticleLabel)
        .filter(
            ArticleLabel.article_id == article_id,
            ArticleLabel.label_version == label_version,
        )
        .one_or_none()
    )

    now = datetime.utcnow()

    if record:
        record.model_version = model_version
        record.model_path = model_path
        record.primary_label = primary_label
        record.primary_label_confidence = primary_score
        record.alternate_label = alt_label
        record.alternate_label_confidence = alt_score
        record.meta = metadata
        record.applied_at = now
    else:
        record = ArticleLabel(
            article_id=article_id,
            label_version=label_version,
            model_version=model_version,
            model_path=model_path,
            primary_label=primary_label,
            primary_label_confidence=primary_score,
            alternate_label=alt_label,
            alternate_label_confidence=alt_score,
            applied_at=now,
            meta=metadata,
        )
        session.add(record)

    article = session.query(Article).filter_by(id=article_id).one_or_none()
    if article:
        # Update label snapshot fields and set status to 'labeled' for BigQuery export
        article.primary_label = primary_label
        article.primary_label_confidence = primary_score
        article.alternate_label = alt_label
        article.alternate_label_confidence = alt_score
        article.label_version = label_version
        article.label_model_version = model_version
        article.labels_updated_at = now
        
        # Set status to 'labeled' for BigQuery export
        # Only update if status is 'cleaned' or 'local'
        if article.status in ('cleaned', 'local'):
            article.status = 'labeled'

    if autocommit:
        _commit_with_retry(session)
    return record


def save_locations(
    session,
    article_id: str,
    entities: list[dict[str, Any]],
    ner_model_version: str | None = None,
) -> list[Location]:
    """Save location entities for an article."""
    location_records = []

    for entity in entities:
        location = Location(
            article_id=article_id,
            entity_text=entity.get("text"),
            entity_type=entity.get("label"),
            confidence=entity.get("confidence"),
            geocoded_lat=entity.get("lat"),
            geocoded_lon=entity.get("lon"),
            geocoded_place=entity.get("place"),
            geocoding_source=entity.get("geocoding_source"),
            ner_model_version=ner_model_version,
        )
        session.add(location)
        location_records.append(location)

    session.commit()
    logger.info(
        "Saved %d locations for article: %s",
        len(location_records),
        article_id,
    )
    return location_records


def _normalize_entity_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.lower()
    normalized = normalized.replace("\u2019", "'").replace("\u2018", "'")
    normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
    normalized = re.sub(r"[^a-z0-9\s'-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def save_article_entities(
    session,
    article_id: str,
    entities: list[dict[str, Any]],
    extractor_version: str,
    article_text_hash: str | None = None,
    autocommit: bool = True,
) -> list[ArticleEntity]:
    """Replace article entities for the given extractor version.
    
    Args:
        autocommit: If False, caller must commit. Use for batch processing.
    """

    session.query(ArticleEntity).filter_by(
        article_id=article_id,
        extractor_version=extractor_version,
    ).delete()

    records: list[ArticleEntity] = []
    # Track seen combinations to avoid violating uq_article_entity.
    seen_keys: set[tuple[str, str, str]] = set()
    for entity in entities:
        entity_text = entity.get("entity_text") or entity.get("text")
        if not entity_text:
            continue

        entity_norm_value = entity.get("entity_norm")
        entity_norm: str = (
            str(entity_norm_value)
            if entity_norm_value
            else _normalize_entity_text(entity_text)
        )

        entity_label_raw = entity.get("entity_label")
        if not entity_label_raw:
            entity_label_raw = entity.get("label")
        entity_label_value: str | None
        if entity_label_raw is None:
            entity_label_value = None
        else:
            entity_label_value = str(entity_label_raw)

        extractor_used = str(entity.get("extractor_version") or extractor_version)
        dedupe_key = (entity_norm, str(entity_label_value or ""), extractor_used)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        record = ArticleEntity(
            article_id=article_id,
            article_text_hash=article_text_hash,
            entity_text=entity_text,
            entity_norm=entity_norm,
            entity_label=entity_label_value,
            osm_category=entity.get("osm_category"),
            osm_subcategory=entity.get("osm_subcategory"),
            extractor_version=extractor_used,
            confidence=entity.get("confidence"),
            matched_gazetteer_id=entity.get("matched_gazetteer_id"),
            match_score=entity.get("match_score"),
            match_name=entity.get("match_name"),
            meta=entity.get("meta"),
        )
        session.add(record)
        records.append(record)

    # If no entities extracted, add sentinel to mark extraction complete
    # This prevents infinite reprocessing of articles with no entities
    if not records:
        sentinel = ArticleEntity(
            article_id=article_id,
            article_text_hash=article_text_hash,
            entity_text="__NO_ENTITIES_FOUND__",
            entity_norm="__no_entities_found__",
            entity_label="SENTINEL",
            extractor_version=extractor_version,
            confidence=1.0,
            meta={
                "sentinel": True,
                "reason": "No location entities found in article text",
            },
        )
        session.add(sentinel)
        records.append(sentinel)

    if autocommit:
        _commit_with_retry(session)
    return records


def create_job_record(
    session,
    job_type: str,
    job_name: str | None = None,
    params: dict[str, Any] | None = None,
    **kwargs,
) -> Job:
    """Create a new job record for tracking execution."""
    job = Job(
        job_type=job_type,
        job_name=job_name,
        params=params or {},
        **kwargs,
    )
    session.add(job)
    session.commit()
    logger.info(f"Created job record: {job.id} ({job_type})")
    return job


def finish_job_record(
    session,
    job_id: str,
    exit_status: str,
    metrics: dict[str, Any] | None = None,
) -> Job:
    """Mark job as finished with final metrics."""
    job = session.query(Job).filter_by(id=job_id).first()
    if job:
        job.finished_at = pd.Timestamp.utcnow()
        job.exit_status = exit_status

        # Update metrics
        if metrics:
            for key, value in metrics.items():
                if hasattr(job, key):
                    setattr(job, key, value)

        session.commit()
        logger.info(f"Finished job: {job_id} with status: {exit_status}")
    return job


# Pandas integration for bulk operations


def read_candidate_links(engine, filters: dict[str, Any] | None = None) -> pd.DataFrame:
    """Read candidate links as DataFrame with optional filters."""
    query = "SELECT * FROM candidate_links"

    if filters:
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"{key} = '{value}'")
            else:
                conditions.append(f"{key} = {value}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

    return pd.read_sql(query, engine)


def read_articles(engine, filters: dict[str, Any] | None = None) -> pd.DataFrame:
    """Read articles as DataFrame with optional filters."""
    query = (
        "SELECT a.*, cl.url, cl.source\n"
        "FROM articles a\n"
        "JOIN candidate_links cl ON a.candidate_link_id = cl.id\n"
    )

    if filters:
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"a.{key} = '{value}'")
            else:
                conditions.append(f"a.{key} = {value}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

    return pd.read_sql(query, engine)


def bulk_insert_candidate_links(
    engine,
    df: pd.DataFrame,
    if_exists: Literal["fail", "replace", "append"] = "append",
    dataset_id: str | None = None,
) -> int:
    """Bulk insert candidate links from a DataFrame.

    This function is conservative about schema differences and will add
    missing columns using ALTER TABLE when running against SQLite. It
    also tries to avoid unique constraint failures by filtering out
    existing URLs before the bulk insert.
    """
    # Ensure required columns. Some CSVs use `source_name` instead of `source`.
    if "source" not in df.columns and "source_name" in df.columns:
        df["source"] = df["source_name"]

    required_cols = ["url", "source"]
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"DataFrame must contain columns: {required_cols}")

    # Add default values for missing columns
    if "id" not in df.columns:
        df["id"] = [str(uuid.uuid4()) for _ in range(len(df))]
    if "status" not in df.columns:
        df["status"] = "new"
    if "discovered_at" not in df.columns:
        df["discovered_at"] = pd.Timestamp.utcnow()
    if "created_at" not in df.columns:
        df["created_at"] = pd.Timestamp.utcnow()

    # Ensure the target table has the same columns. SQLite allows
    # ALTER TABLE ADD COLUMN, so we attempt to add missing columns.
    try:
        inspector_cols = []

        def _exec_table_info(tbl_name: str):
            with engine.connect() as conn:
                if "postgresql" in engine.dialect.name:
                    # PostgreSQL: Use information_schema
                    res = conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = :table_name
                            ORDER BY ordinal_position
                            """
                        ),
                        {"table_name": tbl_name},
                    )
                    return [r[0] for r in res.fetchall()]
                else:
                    # SQLite: PRAGMA table_info returns rows with columns:
                    # (cid, name, type, notnull, dflt_value, pk)
                    res = conn.execute(text(f"PRAGMA table_info({tbl_name})"))
                    return [r[1] for r in res.fetchall()]

        # Retry PRAGMA/table_info in case of transient locks.
        inspector_cols = []
        attempts = 0
        max_attempts = 5
        backoff = 0.05
        while attempts < max_attempts:
            try:
                inspector_cols = _exec_table_info("candidate_links")
                break
            except Exception as e:
                msg = str(e).lower()
                if "database is locked" in msg and attempts < max_attempts - 1:
                    time.sleep(backoff + (random.random() * backoff))
                    backoff *= 2
                    attempts += 1
                    continue
                inspector_cols = []
                break
    except Exception:
        inspector_cols = []

    # If the engine is SQLite and we inspected columns, add missing
    # columns found in the DataFrame.
    if inspector_cols and "sqlite" in engine.dialect.name:
        missing = [c for c in df.columns if c not in inspector_cols]
        with engine.connect() as conn:
            for col in missing:
                try:
                    # Add as TEXT column; keep it simple and tolerant.
                    sql = "ALTER TABLE candidate_links ADD COLUMN " + col + " TEXT"
                    conn.execute(text(sql))
                except Exception:
                    # Ignore if column can't be added. This can happen when
                    # another process created the column concurrently or the
                    # DB is locked.
                    pass
    else:
        # If we couldn't introspect, limit DataFrame to common cols to avoid
        # SQL errors by selecting only columns that exist in the table.
        if inspector_cols:
            cols = [c for c in df.columns if c in inspector_cols]
            df = pd.DataFrame(df.loc[:, cols].copy())

    # Drop rows missing values for NOT NULL-constrained columns (at
    # minimum `url`). This avoids IntegrityError when CSVs are messy.
    # Log how many rows are dropped.
    if "url" in df.columns:
        before = len(df)
        mask = df["url"].notna() & (df["url"].astype(str).str.strip() != "")
        df = pd.DataFrame(df.loc[mask, :].copy())
        dropped = before - len(df)
        if dropped:
            msg = (
                f"Dropping {dropped} candidate link rows "
                "with missing 'url' before insert"
            )
            logger.warning(msg)
    else:
        # If url column is unexpectedly missing after earlier checks, raise.
        raise ValueError("DataFrame missing required 'url' column")

    # Remove rows whose URL already exists in the target table. This
    # avoids UNIQUE constraint failures on the `url` column.
    try:
        with engine.connect() as conn:
            res = conn.execute(text("SELECT url FROM candidate_links"))
            existing_urls = {r[0] for r in res.fetchall()}
        if existing_urls:
            before = len(df)
            mask = ~df["url"].astype(str).isin(existing_urls)
            # Use a boolean ndarray for .loc to satisfy the type checker.
            df = pd.DataFrame(df.loc[mask.to_numpy(), :].copy())
            dup_dropped = before - len(df)
            if dup_dropped:
                logger.info(
                    "Dropped %d rows with URLs already in DB",
                    dup_dropped,
                )
    except Exception:
        # Table may not exist yet or the select failed; proceed and let the
        # DB raise if necessary when inserting.
        pass

    # Write to database
    # Before writing, if we have a dataset_id, resolve sources/dataset_sources
    # and populate df['source_id'] so rows reference our canonical Source UUID.
    def _retry_on_lock(fn, max_attempts: int = 5, base_delay: float = 0.05):
        """Retry helper for transient SQLite 'database is locked' errors.

        Retries the wrapped function up to max_attempts with exponential
        backoff and jitter when an OperationalError indicating a DB lock
        is encountered.
        """

        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except OperationalError as e:
                    # SQLite locks often present as 'database is locked'
                    msg = str(e).lower()
                    if "database is locked" in msg and attempt < max_attempts:
                        delay = base_delay * (2**attempt)
                        delay = delay + random.uniform(0, base_delay)
                        time.sleep(delay)
                        attempt += 1
                        continue
                    raise

        return wrapper

    if dataset_id is not None:
        try:
            # Use SQLAlchemy Core Table reflection for portable queries/inserts
            metadata = MetaData()
            sources_tbl = Table("sources", metadata, autoload_with=engine)
            ds_tbl = Table("dataset_sources", metadata, autoload_with=engine)

            @_retry_on_lock
            def _resolve_and_insert_sources():
                with engine.begin() as conn:
                    # Collect hosts from DataFrame. We consider both legacy
                    # `source_host_id` values and hosts parsed from `url`.
                    hosts = set()

                    if "source_host_id" in df.columns:
                        src_hosts = df["source_host_id"].dropna().astype(str)
                        hosts.update([str(s).lower() for s in src_hosts])

                    if "url" in df.columns:

                        def _extract(u):
                            try:
                                return urlparse(u).hostname
                            except Exception:
                                return None

                        url_series = df["url"].dropna().map(_extract).dropna()
                        url_hosts = url_series.astype(str)
                        hosts.update([str(h).lower() for h in url_hosts])

                    hosts = {h for h in hosts if h}

                    host_map: dict[str, str] = {}
                    if hosts:
                        # Query existing sources matching these hosts.
                        sel = select(
                            sources_tbl.c.id,
                            sources_tbl.c.host,
                        ).where(sources_tbl.c.host.in_(list(hosts)))
                        res = conn.execute(sel)
                        for r in res.fetchall():
                            host_map[(r.host or "").lower()] = r.id

                        # Insert missing hosts into `sources` table.
                        missing = [h for h in hosts if h not in host_map]
                        if missing:
                            ins_rows: list[dict[str, Any]] = []
                            for h in missing:
                                ins_rows.append(
                                    {
                                        "id": str(uuid.uuid4()),
                                        "host": h,
                                        "host_norm": (h or "").lower(),
                                        "canonical_name": h,
                                    }
                                )
                            conn.execute(insert(sources_tbl), ins_rows)

                            # Re-query to populate host_map with new rows.
                            res2 = conn.execute(sel)
                            for r in res2.fetchall():
                                host_map[(r.host or "").lower()] = r.id

                    # Assign source_id for rows where we can resolve a host.
                    def _resolve_row(row: pd.Series) -> Any:
                        host = None
                        if "source_host_id" in row and row["source_host_id"]:
                            host = str(row["source_host_id"]).lower()
                        elif "url" in row and row["url"]:
                            try:
                                host = urlparse(row["url"]).hostname
                                host = host and host.lower()
                            except Exception:
                                host = None
                        if host and host in host_map:
                            return host_map[host]
                        return None

                    df["source_id"] = df.apply(
                        _resolve_row,
                        axis=1,
                    )  # type: ignore[call-overload]

                    # Build `dataset_sources` rows grouped by legacy id.
                    ds_rows: list[dict[str, Any]] = []
                    if "source_host_id" in df.columns:
                        for legacy, group in df.groupby(
                            df["source_host_id"].fillna("")
                        ):
                            if not legacy:
                                continue
                            sid = group["source_id"].iloc[0]
                            if not sid:
                                continue
                            ds_rows.append(
                                {
                                    "id": str(uuid.uuid4()),
                                    "dataset_id": dataset_id,
                                    "source_id": sid,
                                    "legacy_host_id": legacy,
                                }
                            )

                    if ds_rows:
                        # Try dialect-appropriate insert for idempotency.
                        if "sqlite" in engine.dialect.name:
                            # Use raw INSERT OR IGNORE for SQLite as Core
                            # lacks a portable `ON CONFLICT DO NOTHING`.
                            insert_sql = (
                                "INSERT OR IGNORE INTO dataset_sources"
                                " (id, dataset_id, source_id, legacy_host_id)"
                                " VALUES (:id, :dataset_id, :source_id,"
                                " :legacy_host_id)"
                            )
                            safe_execute(conn, insert_sql, ds_rows)
                        else:
                            # For databases that support upsert, try a bulk
                            # insert and let the DB handle conflicts.
                            try:
                                conn.execute(insert(ds_tbl), ds_rows)
                            except Exception:
                                # Fallback: insert rows individually and ignore
                                # duplicates/errors per-row.
                                for r in ds_rows:
                                    try:
                                        conn.execute(insert(ds_tbl), r)
                                    except Exception:
                                        pass

            # Execute the resolution/insert with retry-on-lock
            _resolve_and_insert_sources()
        except Exception:
            logger.exception(
                "Failed to resolve sources/dataset_sources; proceeding"
                " without assignment"
            )

    # Use a raw DB-API connection for pandas.to_sql to avoid passing a
    # proxied Connection object into SQLAlchemy's inspection routines
    # (pandas may obtain a Connection internally which would be proxied).
    rows_inserted = 0
    try:
        raw_conn = engine.raw_connection()
        try:
            rows_inserted = df.to_sql(
                "candidate_links",
                raw_conn,
                if_exists=if_exists,
                index=False,
                method="multi",
            )
            # pandas may not auto-commit when given a raw DB-API connection,
            # so attempt to commit explicitly.
            try:
                raw_conn.commit()
            except Exception:
                pass
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass
    except Exception:
        # Fallback: try using the engine directly as a connectable.
        rows_inserted = df.to_sql(
            "candidate_links",
            engine,
            if_exists=if_exists,
            index=False,
            method="multi",
        )
    rows_inserted = int(rows_inserted or 0)

    logger.info(f"Bulk inserted {rows_inserted} candidate links")
    return rows_inserted


def bulk_insert_articles(
    engine,
    df: pd.DataFrame,
    if_exists: Literal["fail", "replace", "append"] = "append",
) -> int:
    """Bulk insert articles from a DataFrame into the articles table.

    The function will add default IDs and ensure required columns exist.
    """
    required = ["candidate_link_id", "url"]
    # Some older schema versions used `candidate_id`. Normalize to expected
    # `candidate_link_id` column name so the bulk path is tolerant.
    if "candidate_link_id" not in df.columns and "candidate_id" in df.columns:
        df["candidate_link_id"] = df["candidate_id"]

    if not all(col in df.columns for col in required):
        raise ValueError(f"DataFrame must contain columns: {required}")

    if "id" not in df.columns:
        df["id"] = [str(uuid.uuid4()) for _ in range(len(df))]
    if "status" not in df.columns:
        df["status"] = "discovered"
    if "created_at" not in df.columns:
        df["created_at"] = pd.Timestamp.utcnow()

    # Ensure articles table has expected columns. Attempt lightweight
    # migrations (rename candidate_id -> candidate_link_id and add the
    # missing `status` column).
    try:
        inspector_cols = []

        def _exec_table_info(tbl_name: str):
            with engine.connect() as conn:
                if "postgresql" in engine.dialect.name:
                    # PostgreSQL: Use information_schema
                    res = conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = :table_name
                            ORDER BY ordinal_position
                            """
                        ),
                        {"table_name": tbl_name},
                    )
                    return [r[0] for r in res.fetchall()]
                else:
                    # SQLite: PRAGMA table_info
                    res = conn.execute(text(f"PRAGMA table_info({tbl_name})"))
                    return [r[1] for r in res.fetchall()]

        # Retry PRAGMA/table_info in case of transient locks.
        attempts = 0
        max_attempts = 5
        backoff = 0.05
        while attempts < max_attempts:
            try:
                inspector_cols = _exec_table_info("articles")
                break
            except Exception as e:
                msg = str(e).lower()
                if "database is locked" in msg and attempts < max_attempts - 1:
                    time.sleep(backoff + (random.random() * backoff))
                    backoff *= 2
                    attempts += 1
                    continue
                inspector_cols = []
                break

        # If underlying table has 'candidate_id' but not
        # 'candidate_link_id', add a nullable column so the INSERT will
        # work and then copy data where possible.
        if (
            inspector_cols
            and "candidate_link_id" not in inspector_cols
            and "candidate_id" in inspector_cols
        ):
            with engine.connect() as conn:
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE articles ADD COLUMN candidate_link_id VARCHAR"
                        )
                    )
                except Exception:
                    pass

        # Ensure `status` column exists. The CLI queries
        # `articles.status` so add a TEXT column if missing.
        if inspector_cols and "status" not in inspector_cols:
            with engine.connect() as conn:
                try:
                    conn.execute(text("ALTER TABLE articles ADD COLUMN status TEXT"))
                except Exception:
                    pass

        label_columns = {
            "primary_label": "TEXT",
            "primary_label_confidence": "REAL",
            "alternate_label": "TEXT",
            "alternate_label_confidence": "REAL",
            "label_version": "TEXT",
            "label_model_version": "TEXT",
            "labels_updated_at": "TIMESTAMP",
        }

        if inspector_cols:
            for col_name, col_type in label_columns.items():
                if col_name not in inspector_cols:
                    with engine.connect() as conn:
                        try:
                            conn.execute(
                                text(
                                    "ALTER TABLE articles ADD COLUMN "
                                    f"{col_name} {col_type}"
                                )
                            )
                        except Exception:
                            pass
    except Exception:
        # If migrations can't be introspected, proceed and rely on the DB to
        # accept columns present in `df`.
        pass

    rows_inserted = df.to_sql(
        "articles", engine, if_exists=if_exists, index=False, method="multi"
    )

    rows_inserted = int(rows_inserted or 0)

    logger.info(f"Bulk inserted {rows_inserted} articles")
    return rows_inserted


def export_to_parquet(
    engine,
    table_name: str,
    output_path: str,
    filters: dict[str, Any] | None = None,
) -> str:
    """Export table data to Parquet for archival."""
    query = f"SELECT * FROM {table_name}"

    if filters:
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"{key} = '{value}'")
            else:
                conditions.append(f"{key} = {value}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

    df = pd.read_sql(query, engine)
    df.to_parquet(output_path, compression="snappy")

    logger.info(f"Exported {len(df)} rows from {table_name} to {output_path}")
    return output_path
