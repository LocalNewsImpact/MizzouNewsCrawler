"""Shared telemetry persistence helpers."""

from __future__ import annotations

import atexit
import logging
import queue
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

DEFAULT_DATABASE_URL = "sqlite:///data/mizzou.db"


def _resolve_sqlite_path(database: str) -> str:
    if database.startswith("sqlite:///"):
        return database.replace("sqlite:///", "", 1)
    if database.startswith("sqlite://"):
        # support sqlite:///:memory:
        return database.replace("sqlite://", "", 1)
    return database


class TelemetryStore:
    """Centralized queue + connection manager for telemetry writers."""

    _STOP = object()

    def __init__(
        self,
        database: str = DEFAULT_DATABASE_URL,
        *,
        async_writes: bool = True,
        timeout: float = 30.0,
        thread_name: str = "TelemetryStoreWriter",
    ) -> None:
        self.database_url = database
        self.db_path = _resolve_sqlite_path(database)
        self.async_writes = async_writes
        self.timeout = timeout
        self._logger = logging.getLogger(__name__)

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

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def submit(
        self,
        task: Callable[[sqlite3.Connection], None],
        *,
        ensure: Sequence[str] | None = None,
    ) -> None:
        job = (task, tuple(ensure) if ensure else tuple())
        if self.async_writes and self._queue is not None:
            self._queue.put(job)
        else:
            self._execute(job)

    def flush(self) -> None:
        if self.async_writes and self._queue is not None:
            self._queue.join()

    def shutdown(self, wait: bool = False) -> None:
        if not self.async_writes or self._queue is None or not self._owns_thread:
            return

        if wait:
            self.flush()

        self._queue.put(self._STOP)
        if self._writer_thread:
            self._writer_thread.join(timeout=5)
        self._owns_thread = False

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._create_connection()
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False,
        )
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection, ddls: Sequence[str]) -> None:
        if not ddls:
            return

        with self._ddl_lock:
            cursor = conn.cursor()
            try:
                for ddl in ddls:
                    if ddl not in self._ddl_cache:
                        cursor.execute(ddl)
                        self._ddl_cache.add(ddl)
                conn.commit()
            finally:
                cursor.close()

    def _execute(
        self,
        job: tuple[Callable[[sqlite3.Connection], None], tuple[str, ...]],
    ) -> None:
        task, ddls = job
        conn = self._create_connection()
        try:
            if ddls:
                self._ensure_schema(conn, ddls)
            task(conn)
            conn.commit()
        except Exception as exc:  # pragma: no cover - logged for diagnosis
            conn.rollback()
            self._logger.exception("Telemetry write failed", exc_info=exc)
            raise
        finally:
            conn.close()

    def _worker_loop(self) -> None:
        assert self._queue is not None
        while True:
            job = self._queue.get()
            if job is self._STOP:
                self._queue.task_done()
                break
            try:
                self._execute(job)
            finally:
                self._queue.task_done()


_default_store_lock = threading.Lock()
_default_store: TelemetryStore | None = None


def get_store(database: str = DEFAULT_DATABASE_URL) -> TelemetryStore:
    """Return a process-wide shared telemetry store."""

    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = TelemetryStore(database=database)
    return _default_store
