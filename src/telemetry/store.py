"""Shared telemetry persistence helpers."""

from __future__ import annotations

import atexit
import logging
import os
import queue
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool


def _is_test_environment() -> bool:
    """Detect if running in a test environment.
    
    Returns True if:
    - Running under pytest
    - TEST_DATABASE_URL environment variable is set
    - Any test-related environment variable is set
    
    This is used to allow SQLite in tests while warning in production.
    """
    # Check for pytest in command line
    if 'pytest' in sys.argv[0] or '/test' in sys.argv[0]:
        return True
    
    # Check for test-specific environment variables
    test_env_vars = ['TEST_DATABASE_URL', 'PYTEST_CURRENT_TEST', 'PYTEST_VERSION']
    if any(os.getenv(var) for var in test_env_vars):
        return True
    
    return False


def _determine_default_database_url() -> str:
    """Determine the PostgreSQL database URL for telemetry.
    
    IMPORTANT: Telemetry MUST use PostgreSQL, never SQLite.
    SQLite fallback has been removed because:
    1. Production uses PostgreSQL (Cloud SQL)
    2. Local development uses PostgreSQL (localhost:5432)
    3. CI uses PostgreSQL (postgres-integration job)
    4. SQLite compatibility issues have caused multiple production failures
    
    If this function fails to find a database URL, it will raise an error
    rather than silently falling back to SQLite.
    """
    # First: Check explicit TELEMETRY_DATABASE_URL (set in Kubernetes)
    candidate = os.getenv("TELEMETRY_DATABASE_URL")
    if candidate:
        if not candidate.startswith("postgresql"):
            logging.error(
                f"TELEMETRY_DATABASE_URL must be PostgreSQL, got: {candidate}"
            )
            raise ValueError(
                "TELEMETRY_DATABASE_URL must start with 'postgresql'. "
                "SQLite is not supported for telemetry."
            )
        return candidate

    # Second: Try to use the main application DATABASE_URL from config
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
            from urllib.parse import quote_plus

            user = quote_plus(DATABASE_USER)
            password = quote_plus(DATABASE_PASSWORD) if DATABASE_PASSWORD else ""
            auth = f"{user}:{password}" if password else user
            db_url = f"postgresql://{auth}@/{DATABASE_NAME}"
            logging.info(f"Telemetry using Cloud SQL: {CLOUD_SQL_INSTANCE}")
            return db_url

        # If DATABASE_URL is already PostgreSQL, use it
        if CONFIG_DATABASE_URL and CONFIG_DATABASE_URL.startswith("postgresql"):
            logging.info("Telemetry using CONFIG_DATABASE_URL")
            return CONFIG_DATABASE_URL

        # Try to build from individual components
        if DATABASE_HOST and DATABASE_USER and DATABASE_NAME:
            from urllib.parse import quote_plus

            user = quote_plus(DATABASE_USER)
            password = quote_plus(DATABASE_PASSWORD) if DATABASE_PASSWORD else ""
            auth = f"{user}:{password}" if password else user
            engine = DATABASE_ENGINE or "postgresql"
            if not engine.startswith("postgresql"):
                raise ValueError(
                    f"DATABASE_ENGINE must be postgresql, got: {engine}"
                )
            db_url = f"{engine}://{auth}@{DATABASE_HOST}/{DATABASE_NAME}"
            logging.info(f"Telemetry using constructed URL: {DATABASE_HOST}")
            return db_url

    except Exception as e:
        logging.error(
            f"Failed to determine PostgreSQL URL from config: {e}. "
            f"Telemetry requires PostgreSQL. Set TELEMETRY_DATABASE_URL "
            f"environment variable or configure DATABASE_* variables."
        )
        raise RuntimeError(
            "Telemetry requires PostgreSQL connection. "
            "Set TELEMETRY_DATABASE_URL environment variable. "
            "SQLite fallback has been removed to prevent compatibility issues."
        ) from e

    # If we get here, no valid PostgreSQL URL was found
    raise RuntimeError(
        "No PostgreSQL database URL found for telemetry. "
        "Set TELEMETRY_DATABASE_URL environment variable or configure "
        "DATABASE_* variables in src.config. SQLite is not supported."
    )


# Lazy-loaded default database URL to avoid import-time connection attempts
# This is especially important for tests that need to configure environment first
_DEFAULT_DATABASE_URL_CACHE: str | None = None


def get_default_database_url() -> str:
    """Get the default database URL, with lazy initialization.
    
    This function caches the result after first call to avoid repeated
    environment variable lookups and config imports.
    
    Returns:
        PostgreSQL database URL for telemetry
        
    Raises:
        RuntimeError: If no valid PostgreSQL URL can be determined
    """
    global _DEFAULT_DATABASE_URL_CACHE
    if _DEFAULT_DATABASE_URL_CACHE is None:
        _DEFAULT_DATABASE_URL_CACHE = _determine_default_database_url()
    return _DEFAULT_DATABASE_URL_CACHE


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

    def execute(self, sql: str, parameters: tuple | dict | None = None):
        """Execute SQL with sqlite3-style ? placeholders or :named placeholders."""
        # Wrap raw SQL in text() for SQLAlchemy
        if parameters:
            if isinstance(parameters, dict):
                # Named parameters: already in SQLAlchemy format
                result = self._conn.execute(text(sql), parameters)
            else:
                # Positional parameters: Replace ? with :param0, :param1, etc.
                param_count = sql.count("?")
                if param_count > 0:
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


class _RowProxy:
    """Proxy that provides both tuple and dict-like access to SQLAlchemy Row objects.
    
    SQLAlchemy Row objects can lose their key mapping when detached from the result,
    so we capture both the tuple data and the mapping during construction.
    """

    def __init__(self, row):
        self._tuple = tuple(row)
        self._mapping = dict(row._mapping) if hasattr(row, "_mapping") else {}

    def __getitem__(self, key):
        """Support both integer (tuple) and string (dict) access."""
        if isinstance(key, int):
            return self._tuple[key]
        elif isinstance(key, str):
            return self._mapping[key]
        else:
            raise TypeError(f"indices must be integers or strings, not {type(key)}")

    def __iter__(self):
        """Iterate over tuple values."""
        return iter(self._tuple)

    def __len__(self):
        """Return length of tuple."""
        return len(self._tuple)

    def __repr__(self):
        """Show tuple representation."""
        return repr(self._tuple)

    def __eq__(self, other):
        """Support equality comparison with tuples and other _RowProxy objects."""
        if isinstance(other, _RowProxy):
            return self._tuple == other._tuple
        elif isinstance(other, tuple):
            return self._tuple == other
        return False

    def __hash__(self):
        """Make _RowProxy hashable."""
        return hash(self._tuple)


class _ResultWrapper:
    """Wrapper that makes SQLAlchemy CursorResult behave like sqlite3.Cursor.
    
    Ensures rows support dict-like access for both SQLite and PostgreSQL.
    """

    def __init__(self, result):
        self._result = result
        self._cached_description = None
        self._keys = None
        
        # Cache column names for dict conversion
        # DDL statements (CREATE TABLE, etc.) don't return rows
        if hasattr(result, "keys"):
            try:
                self._keys = list(result.keys())
            except Exception:
                # ResourceClosedError for DDL, or result doesn't return rows
                self._keys = None

    @property
    def description(self):
        """Provide sqlite3-style description attribute."""
        if self._cached_description is None:
            # Get column names from the result
            if self._keys:
                # Format as [(name, None, None, None, None, None, None), ...]
                # to match sqlite3.Cursor.description format
                self._cached_description = [
                    (key, None, None, None, None, None, None) for key in self._keys
                ]
            else:
                self._cached_description = []
        return self._cached_description

    def fetchone(self):
        """Fetch one row, preserving both integer and dict-like access."""
        row = self._result.fetchone()
        if row is not None:
            # Wrap in proxy to preserve both access patterns
            return _RowProxy(row)
        return None

    def fetchall(self):
        """Fetch all rows, preserving both integer and dict-like access."""
        # SQLAlchemy Row objects lose their key mapping when detached from result
        # Convert to _RowMapping which supports both access patterns reliably
        rows = self._result.fetchall()
        if rows:
            # Convert each Row to a custom wrapper that supports both access patterns
            return [_RowProxy(row) for row in rows]
        return rows

    def close(self):
        """Close the result."""
        if hasattr(self._result, "close"):
            self._result.close()


# SQLite support removed - these functions are no longer used
# Kept as stubs for backward compatibility with old imports only


class TelemetryStore:
    """Centralized queue + connection manager for telemetry writers.

    IMPORTANT: PostgreSQL-only. SQLite support has been removed because:
    1. Production uses PostgreSQL (Cloud SQL)
    2. Local development uses PostgreSQL (localhost:5432)
    3. CI uses PostgreSQL (postgres-integration job)
    4. SQLite compatibility issues caused multiple production failures
    
    Maintains SQLAlchemy-based interface for PostgreSQL connections.
    """

    _STOP = object()

    def __init__(
        self,
        database: str | None = None,
        *,
        async_writes: bool = True,
        timeout: float = 30.0,
        thread_name: str = "TelemetryStoreWriter",
        engine: Engine | None = None,
    ) -> None:
        # Lazy-load default database URL if not provided
        if database is None:
            database = get_default_database_url()
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

        # Warn if not using PostgreSQL (but allow SQLite for tests)
        if "postgresql" not in self.database_url.lower():
            # Only warn in production contexts, not tests
            if not _is_test_environment():
                self._logger.warning(
                    f"TelemetryStore using non-PostgreSQL database: "
                    f"{_mask_database_url(self.database_url)}. "
                    f"Production should use PostgreSQL for compatibility."
                )

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
        """Create SQLAlchemy engine based on database URL.
        
        NOTE: PostgreSQL is recommended for production. SQLite is allowed
        for test environments for speed and isolation.
        """
        # Check if Cloud SQL connector should be used (PostgreSQL only)
        if "postgresql" in self.database_url.lower():
            if self._should_use_cloud_sql_connector():
                return self._create_cloud_sql_engine()

        # Use NullPool for async writes to avoid connection pool issues
        engine = create_engine(
            self.database_url,
            connect_args={},
            poolclass=NullPool if self.async_writes else None,
            echo=False,
        )

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
        """Adapt DDL statement for PostgreSQL.

        Args:
            ddl: Original DDL statement (typically SQLite syntax)

        Returns:
            Adapted DDL statement for PostgreSQL
        """
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
    database: str | None = None,
    *,
    engine: Engine | None = None,
) -> TelemetryStore:
    """Return a process-wide shared telemetry store.

    Args:
        database: Database URL (used if engine not provided).
                  If None, uses get_default_database_url()
        engine: Optional existing SQLAlchemy engine to reuse
                (avoids creating new connections, required for Cloud SQL Connector)

    Returns:
        Shared TelemetryStore instance
    """
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            # Lazy-load default database URL if not provided
            if database is None:
                database = get_default_database_url()
            _default_store = TelemetryStore(database=database, engine=engine)
    return _default_store
