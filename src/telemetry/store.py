"""Shared telemetry persistence helpers."""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

_SQLITE_FALLBACK_URL = "sqlite:///data/mizzou.db"


def _determine_default_database_url() -> str:
    candidate = os.getenv("TELEMETRY_DATABASE_URL")
    if candidate:
        return candidate

    # Try to use the main application DATABASE_URL from config
    try:
        from src.config import (
            CLOUD_SQL_INSTANCE,
            DATABASE_ENGINE,
            DATABASE_HOST,
            DATABASE_NAME,
            DATABASE_PASSWORD,
        )
        from src.config import DATABASE_URL as CONFIG_DATABASE_URL
        from src.config import (
            DATABASE_USER,
            USE_CLOUD_SQL_CONNECTOR,
        )

        # If using Cloud SQL Connector, build PostgreSQL URL
        if (
            USE_CLOUD_SQL_CONNECTOR
            and CLOUD_SQL_INSTANCE
            and DATABASE_USER
            and DATABASE_NAME
        ):
            # Cloud SQL Connector handles connection
            # Telemetry needs a postgres URL for schema compatibility
            from urllib.parse import quote_plus

            user = quote_plus(DATABASE_USER)
            password = quote_plus(DATABASE_PASSWORD) if DATABASE_PASSWORD else ""
            auth = f"{user}:{password}" if password else user
            # Use instance name as host for telemetry (actual connection via connector)
            db_url = f"postgresql://{auth}@/{DATABASE_NAME}"
            return db_url

        # If DATABASE_URL is already PostgreSQL, use it
        if CONFIG_DATABASE_URL and CONFIG_DATABASE_URL.startswith("postgresql"):
            return CONFIG_DATABASE_URL

        # Try to build from individual components
        if DATABASE_HOST and DATABASE_USER and DATABASE_NAME:
            from urllib.parse import quote_plus

            user = quote_plus(DATABASE_USER)
            password = quote_plus(DATABASE_PASSWORD) if DATABASE_PASSWORD else ""
            auth = f"{user}:{password}" if password else user
            engine = DATABASE_ENGINE or "postgresql"
            db_url = f"{engine}://{auth}@{DATABASE_HOST}/{DATABASE_NAME}"
            return db_url

    except Exception as e:
        logging.debug(
            f"Could not determine PostgreSQL URL from config: {e}. "
            f"Using SQLite fallback"
        )

    return _SQLITE_FALLBACK_URL


DEFAULT_DATABASE_URL = _determine_default_database_url()


def _mask_database_url(url: str | None) -> str:
    if not url:
        return "<empty>"

    try:
        if "://" not in url:
            return url

        scheme, remainder = url.split("://", 1)
        if "@" not in remainder:
            return f"{scheme}://{remainder}"

        credentials, host = remainder.split("@", 1)
        if ":" in credentials:
            return f"{scheme}://***:***@{host}"
        return f"{scheme}://***@{host}"
    except Exception:
        return "<redacted>"


class _ConnectionWrapper:
    """Wrapper that makes SQLAlchemy Connection behave like sqlite3.Connection.

    This provides backward compatibility for telemetry code that expects
    sqlite3-style execute() calls with ? placeholders.
    """

    def __init__(self, sqlalchemy_conn: Connection):
        self._conn = sqlalchemy_conn
        self._in_transaction = False

    def execute(self, sql: str, parameters: tuple | None = None):
        """Execute SQL with sqlite3-style ? placeholders."""
        # Wrap raw SQL in text() for SQLAlchemy
        if parameters:
            # Convert tuple parameters to dict for SQLAlchemy
            # Count ? placeholders and create param dict
            param_count = sql.count("?")
            if param_count > 0 and parameters:
                # Replace ? with :param0, :param1, etc.
                adapted_sql = sql
                params_dict = {}
                for i, value in enumerate(parameters):
                    adapted_sql = adapted_sql.replace("?", f":param{i}", 1)
                    params_dict[f"param{i}"] = value
                result = self._conn.execute(text(adapted_sql), params_dict)
            else:
                result = self._conn.execute(text(sql), parameters)
        else:
            result = self._conn.execute(text(sql))

        # Wrap result to provide sqlite3-like interface
        return _ResultWrapper(result)

    def cursor(self):
        """Return a cursor-like object for compatibility."""
        return _CursorWrapper(self._conn)

    def commit(self):
        """Commit the transaction."""
        if self._in_transaction:
            self._conn.commit()
            self._in_transaction = False

    def rollback(self):
        """Rollback the transaction."""
        if self._in_transaction:
            self._conn.rollback()
            self._in_transaction = False

    def close(self):
        """Close the connection."""
        self._conn.close()


class _CursorWrapper:
    """Wrapper that makes SQLAlchemy Connection act like a cursor."""

    def __init__(self, sqlalchemy_conn: Connection):
        self._conn = sqlalchemy_conn

        self._last_result: Any = None
        self._result_wrapper: _ResultWrapper | None = None
        self._rowcount: int = -1

    def execute(self, sql: str, parameters: tuple | dict | None = None):
        """Execute SQL with sqlite3-style ? placeholders or :named placeholders."""
        if parameters:
            if isinstance(parameters, dict):
                # Named parameters: already in SQLAlchemy format
                self._last_result = self._conn.execute(text(sql), parameters)
            else:
                # Positional parameters: Replace ? with :param0, :param1, etc.
                adapted_sql = sql
                params_dict = {}
                param_count = sql.count("?")
                for i in range(param_count):
                    if i < len(parameters):
                        adapted_sql = adapted_sql.replace("?", f":param{i}", 1)
                        params_dict[f"param{i}"] = parameters[i]
                self._last_result = self._conn.execute(text(adapted_sql), params_dict)
        else:
            self._last_result = self._conn.execute(text(sql))

        # Create a wrapper that provides sqlite3-like cursor behavior
        self._result_wrapper = _ResultWrapper(self._last_result)
        self._rowcount = getattr(self._last_result, "rowcount", -1)
        return self._result_wrapper

    def fetchone(self):
        """Fetch one row from the last executed statement."""
        if self._result_wrapper is None:
            return None
        return self._result_wrapper.fetchone()

    def fetchall(self):
        """Fetch all rows from the last executed statement."""
        if self._result_wrapper is None:
            return []
        return self._result_wrapper.fetchall()

    @property
    def rowcount(self) -> int:
        """Return the rowcount of the last executed statement."""
        if self._last_result is None:
            return -1
        rowcount = getattr(self._last_result, "rowcount", None)
        if rowcount is None:
            return self._rowcount
        return rowcount

    def close(self):
        """No-op for compatibility."""
        pass


class _ResultWrapper:
    """Wrapper that makes SQLAlchemy CursorResult behave like sqlite3.Cursor."""

    def __init__(self, result):
        self._result = result
        self._cached_description = None

    @property
    def description(self):
        """Provide sqlite3-style description attribute."""
        if self._cached_description is None:
            # Get column names from the result
            if hasattr(self._result, "keys"):
                keys = self._result.keys()
                # Format as [(name, None, None, None, None, None, None), ...]
                # to match sqlite3.Cursor.description format
                self._cached_description = [
                    (key, None, None, None, None, None, None) for key in keys
                ]
            else:
                self._cached_description = []
        return self._cached_description

    def fetchone(self):
        """Fetch one row."""
        return self._result.fetchone()

    def fetchall(self):
        """Fetch all rows."""
        return self._result.fetchall()

    def close(self):
        """Close the result."""
        if hasattr(self._result, "close"):
            self._result.close()


def _resolve_sqlite_path(database: str) -> str:
    if database.startswith("sqlite:///"):
        return database.replace("sqlite:///", "", 1)
    if database.startswith("sqlite://"):
        # support sqlite:///:memory:
        return database.replace("sqlite://", "", 1)
    return database


def _configure_sqlite_engine(engine: Engine, timeout: float) -> None:
    """Enable WAL mode and pragmas for SQLite connections."""
    busy_timeout_ms = int(timeout * 1000)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class TelemetryStore:
    """Centralized queue + connection manager for telemetry writers.

    Supports both SQLite (local development) and PostgreSQL (Cloud SQL)
    via SQLAlchemy. Maintains backward compatibility with the original
    sqlite3-based interface.
    """

    _STOP = object()

    def __init__(
        self,
        database: str = DEFAULT_DATABASE_URL,
        *,
        async_writes: bool = True,
        timeout: float = 30.0,
        thread_name: str = "TelemetryStoreWriter",
        engine: Engine | None = None,
    ) -> None:
        self.database_url = database
        self.async_writes = async_writes
        self.timeout = timeout
        self._logger = logging.getLogger(__name__)

        # Use provided engine or create new one
        if engine is not None:
            self._engine = engine
            self._owns_engine = False
        else:
            self._engine = self._create_engine()
            self._owns_engine = True

        self._is_sqlite = "sqlite" in self.database_url.lower()
        self._is_postgres = "postgres" in self.database_url.lower()

        self._queue: queue.Queue | None = None
        self._writer_thread: threading.Thread | None = None
        self._owns_thread = False

        self._ddl_cache: set[str] = set()
        self._ddl_lock = threading.Lock()

        if async_writes:
            self._queue = queue.Queue()
            self._writer_thread = threading.Thread(
                target=self._worker_loop,
                name=thread_name,
                daemon=True,
            )
            self._writer_thread.start()
            self._owns_thread = True
            atexit.register(self.shutdown)

    def _create_engine(self) -> Engine:
        """Create SQLAlchemy engine based on database URL."""
        # Check if Cloud SQL connector should be used
        if self._should_use_cloud_sql_connector():
            return self._create_cloud_sql_engine()

        connect_args: dict[str, Any] = {}

        if "sqlite" in self.database_url:
            connect_args = {
                "check_same_thread": False,
                "timeout": self.timeout,
            }

        # Use NullPool for async writes to avoid connection pool issues
        engine = create_engine(
            self.database_url,
            connect_args=connect_args,
            poolclass=NullPool if self.async_writes else None,
            echo=False,
        )

        # Configure SQLite-specific settings
        if "sqlite" in self.database_url:
            _configure_sqlite_engine(engine, self.timeout)

        return engine

    def _should_use_cloud_sql_connector(self) -> bool:
        """Determine if Cloud SQL Python Connector should be used."""
        import os

        # Only use for PostgreSQL URLs
        if "postgres" not in self.database_url:
            return False

        # Check environment variable
        if os.getenv("USE_CLOUD_SQL_CONNECTOR", "").lower() in ("false", "0", "no"):
            return False

        try:
            from src.config import CLOUD_SQL_INSTANCE, USE_CLOUD_SQL_CONNECTOR

            return USE_CLOUD_SQL_CONNECTOR and bool(CLOUD_SQL_INSTANCE)
        except ImportError:
            return False

    def _create_cloud_sql_engine(self) -> Engine:
        """Create database engine using Cloud SQL Python Connector."""
        try:
            from src.config import (
                CLOUD_SQL_INSTANCE,
                DATABASE_NAME,
                DATABASE_PASSWORD,
                DATABASE_USER,
            )
            from src.models.cloud_sql_connector import create_cloud_sql_engine

            self._logger.info("TelemetryStore using Cloud SQL Python Connector")

            # Ensure all required config values are present
            if not all(
                [CLOUD_SQL_INSTANCE, DATABASE_USER, DATABASE_PASSWORD, DATABASE_NAME]
            ):
                raise ValueError("Missing required Cloud SQL configuration")

            return create_cloud_sql_engine(
                instance_connection_name=CLOUD_SQL_INSTANCE,  # type: ignore[arg-type]
                user=DATABASE_USER,  # type: ignore[arg-type]
                password=DATABASE_PASSWORD,  # type: ignore[arg-type]
                database=DATABASE_NAME,  # type: ignore[arg-type]
                driver="pg8000",
                echo=False,
                poolclass=NullPool if self.async_writes else None,
            )
        except Exception as e:
            self._logger.warning(
                "Failed to create Cloud SQL connector for telemetry, "
                "falling back to direct connection: %s",
                e,
            )
            # Fall back to the original database URL
            return create_engine(
                self.database_url,
                poolclass=NullPool if self.async_writes else None,
                echo=False,
            )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def submit(
        self,
        task: Callable[[Any], None],
        *,
        ensure: Sequence[str] | None = None,
    ) -> None:
        """Submit a task to be executed against the database.

        Args:
            task: Callable that accepts a connection-like object with execute() method
            ensure: Optional list of DDL statements to execute before task
        """
        job = (task, tuple(ensure) if ensure else tuple())
        if self.async_writes and self._queue is not None:
            self._queue.put(job)
        else:
            self._execute(job)

    def flush(self) -> None:
        """Wait for all pending async writes to complete."""
        if self.async_writes and self._queue is not None:
            self._queue.join()

    def shutdown(self, wait: bool = False) -> None:
        """Shutdown the async writer thread.

        Args:
            wait: If True, wait for pending writes to complete before shutdown
        """
        if not self.async_writes or self._queue is None or not self._owns_thread:
            return

        if wait:
            self.flush()

        self._queue.put(self._STOP)
        if self._writer_thread:
            self._writer_thread.join(timeout=5)
        self._owns_thread = False

        # Only dispose engine if we created it
        if hasattr(self, "_engine") and self._owns_engine:
            self._engine.dispose()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Context manager for database connections.

        Yields:
            Connection wrapper that provides sqlite3.Connection-compatible API
        """
        conn = self._create_connection()
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _create_connection(self) -> _ConnectionWrapper:
        """Create a database connection.

        Returns wrapped SQLAlchemy Connection that provides backward compatibility
        with sqlite3.Connection API.
        """
        sqlalchemy_conn = self._engine.connect()
        wrapper = _ConnectionWrapper(sqlalchemy_conn)
        # Begin transaction
        wrapper._in_transaction = True
        return wrapper

    def _ensure_schema(self, conn: Any, ddls: Sequence[str]) -> None:
        """Execute DDL statements to ensure schema exists.

        Args:
            conn: Database connection wrapper
            ddls: List of DDL statements to execute
        """
        if not ddls:
            return

        with self._ddl_lock:
            for ddl in ddls:
                if ddl not in self._ddl_cache:
                    # Adapt DDL for PostgreSQL if needed
                    adapted_ddl = self._adapt_ddl(ddl)

                    # Execute using cursor for DDL
                    cursor = conn.cursor()
                    try:
                        cursor.execute(adapted_ddl)
                    finally:
                        cursor.close()

                    self._ddl_cache.add(ddl)

    def _adapt_ddl(self, ddl: str) -> str:
        """Adapt DDL statement for the target database dialect.

        Args:
            ddl: Original DDL statement (typically SQLite syntax)

        Returns:
            Adapted DDL statement for the target database
        """
        if self._is_postgres:
            # Convert SQLite-specific syntax to PostgreSQL
            adapted = ddl

            # Replace AUTOINCREMENT with SERIAL
            adapted = adapted.replace("AUTOINCREMENT", "")
            adapted = adapted.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")

            # PostgreSQL uses BOOLEAN not BOOLEAN
            # (already compatible, but ensure consistency)

            # Replace TIMESTAMP without timezone to use WITH TIME ZONE
            # Only if not already specified
            if "TIMESTAMP" in adapted and "TIME ZONE" not in adapted:
                adapted = adapted.replace("TIMESTAMP", "TIMESTAMP")

            return adapted

        return ddl

    def _execute(
        self,
        job: tuple[Callable[[Any], None], tuple[str, ...]],
    ) -> None:
        """Execute a task with optional schema setup.

        Args:
            job: Tuple of (task_callable, ddl_statements)
        """
        task, ddls = job
        conn = self._create_connection()
        try:
            if ddls:
                self._ensure_schema(conn, ddls)

            # Execute the task
            task(conn)

            # Commit the transaction
            conn.commit()

        except Exception as exc:  # pragma: no cover - logged for diagnosis
            # Rollback on error
            try:
                conn.rollback()
            except Exception:
                pass

            self._logger.exception("Telemetry write failed", exc_info=exc)
            raise
        finally:
            conn.close()

    def _worker_loop(self) -> None:
        """Background worker thread that processes queued tasks."""
        assert self._queue is not None
        while True:
            job = self._queue.get()
            if job is self._STOP:
                self._queue.task_done()
                break
            try:
                self._execute(job)
            except Exception as exc:  # pragma: no cover
                # Log and continue - don't let the background thread die
                self._logger.exception(
                    "Telemetry background thread caught exception, continuing",
                    exc_info=exc,
                )
            finally:
                self._queue.task_done()


_default_store_lock = threading.Lock()
_default_store: TelemetryStore | None = None


def get_store(
    database: str = DEFAULT_DATABASE_URL,
    *,
    engine: Engine | None = None,
) -> TelemetryStore:
    """Return a process-wide shared telemetry store.

    Args:
        database: Database URL (used if engine not provided)
        engine: Optional existing SQLAlchemy engine to reuse
                (avoids creating new connections, required for Cloud SQL Connector)

    Returns:
        Shared TelemetryStore instance
    """
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = TelemetryStore(database=database, engine=engine)
    return _default_store
