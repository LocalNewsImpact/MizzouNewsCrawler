"""I/O utilities for the pipeline.

Provides helpers for building standardized output paths, and for
performing atomic writes of JSON and CSV artifacts so downstream jobs
never see partially-written files.

Keep this module small and dependency-light; pandas is imported only in
helpers that explicitly need it.
"""

import atexit
import csv
import json
import os
import queue
import sqlite3
import tempfile
import threading
import time
from datetime import datetime

try:
    import pandas as pd  # optional dependency used when available
except Exception:
    pd = None
 

try:
    import sqlalchemy
    from sqlalchemy import create_engine
except Exception:
    # When SQLAlchemy isn't available at runtime we keep the names but
    # assign None so runtime imports gracefully degrade. Use a narrow
    # type-ignore instead of cast to keep static checkers happy.
    sqlalchemy = None  # type: ignore[assignment]
    create_engine = None  # type: ignore[assignment]


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def timestamp_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")


def build_output_path(
    processed_dir: str,
    phase: int,
    name: str,
    host: str | None = None,
    ext: str = "csv",
) -> str:
    """Build a semantic output filename in `processed/phase_{phase}`.

    Example: processed/phase_1/articleurls_2025-09-14T20-00-00Z.csv
    If `host` is provided the host will be included in the filename.
    """
    out_dir = os.path.join(processed_dir, f"phase_{phase}")
    ensure_dir(out_dir)
    ts = timestamp_now()
    safe_name = name.replace(" ", "_")
    if host:
        # make host filesystem-safe (simple replacement)
        host_safe = host.replace("://", "_").replace("/", "_")
        filename = f"{safe_name}_{host_safe}_{ts}.{ext}"
    else:
        filename = f"{safe_name}_{ts}.{ext}"
    return os.path.join(out_dir, filename)


def atomic_write_json(obj, out_path: str, ensure_ascii: bool = False) -> str:
    """Write `obj` as JSON to `out_path` atomically and return the path.

    The function writes to a temporary file in the same directory and then
    atomically moves it into place using ``os.replace``.
    """
    ensure_dir(os.path.dirname(out_path) or ".")
    dirpath = os.path.dirname(out_path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=dirpath, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=ensure_ascii)
        os.replace(tmp_path, out_path)
    finally:
        # if something went wrong and the tmp file still exists, remove it
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    return out_path


def atomic_write_text(text: str, out_path: str, encoding: str = "utf8") -> str:
    ensure_dir(os.path.dirname(out_path) or ".")
    dirpath = os.path.dirname(out_path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=dirpath, text=True)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
        os.replace(tmp_path, out_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    return out_path


def atomic_write_lines(lines, out_path: str, encoding: str = "utf8") -> str:
    ensure_dir(os.path.dirname(out_path) or ".")
    dirpath = os.path.dirname(out_path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=dirpath, text=True)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            for row in lines:
                fh.write(f"{row}\n")
        os.replace(tmp_path, out_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    return out_path


def atomic_write_csv(
    df_or_rows,
    out_path: str,
    index: bool = False,
    encoding: str = "utf8",
) -> str:
    """Atomically write a CSV file.

    `df_or_rows` can be a pandas.DataFrame (preferred) or an iterable of
    dict-like rows. The function writes to a temporary file in the same
    directory and then moves it into place.
    """
    ensure_dir(os.path.dirname(out_path) or ".")
    dirpath = os.path.dirname(out_path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=dirpath, text=True)
    try:
        # pandas path (fast and robust)
        if pd is not None and isinstance(df_or_rows, pd.DataFrame):
            with os.fdopen(fd, "w", encoding=encoding) as fh:
                df_or_rows.to_csv(fh, index=index)
        else:
            # assume iterable of dict-like rows
            it = iter(df_or_rows)
            try:
                first = next(it)
            except StopIteration:
                # empty iterator -> write empty file
                with os.fdopen(fd, "w", encoding=encoding) as fh:
                    fh.write("")
                os.replace(tmp_path, out_path)
                return out_path

            # determine header
            if isinstance(first, dict):
                fieldnames = list(first.keys())
                with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow(first)
                    for row in it:
                        writer.writerow(row)
            else:
                # assume sequence rows
                with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
                    for row in [first] + list(it):
                        fh.write(",".join(str(x) for x in row) + "\n")
        os.replace(tmp_path, out_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    return out_path


def save_df_to_sql(
    df,
    db_path: str,
    table_name: str,
    if_exists: str = "append",
) -> None:
    """Save a DataFrame or iterable of dicts to a sqlite table.

    This implementation avoids depending on SQLAlchemy by using plain
    sqlite3. It infers a basic column schema from the first row's Python
    types and creates the table if it does not exist. All columns are one
    of INTEGER, REAL, or TEXT.
    If `sqlalchemy` is installed and `df` is a pandas DataFrame, this
    function will automatically use a SQLAlchemy engine + ``df.to_sql``
    with ``method='multi'`` and ``chunksize`` for better performance.
    """
    # If SQLAlchemy + pandas are available and df is a DataFrame, prefer
    # to use pandas.to_sql with a SQLAlchemy engine for efficiency.
    try:
        if (
            sqlalchemy is not None
            and create_engine is not None
            and pd is not None
            and hasattr(df, "to_sql")
        ):
            ensure_dir(os.path.dirname(db_path) or ".")
            engine = create_engine(f"sqlite:///{os.path.abspath(db_path)}")
            # pandas will create the table if needed; use multi-insert for perf
            df.to_sql(
                table_name,
                engine,
                if_exists=if_exists,
                index=False,
                method="multi",
                chunksize=500,
            )
            return
    except Exception:
        # fallback to sqlite3 implementation below on any failure
        import traceback

        traceback.print_exc()

    # Fallback: normalize rows -> list of dicts and use sqlite3 directly
    if pd is not None and hasattr(df, "to_dict"):
        rows = df.to_dict(orient="records")
    else:
        rows = list(df)

    ensure_dir(os.path.dirname(db_path) or ".")
    conn = sqlite3.connect(db_path)
    try:
        if not rows:
            return

        first = rows[0]
        if not isinstance(first, dict):
            raise RuntimeError("save_df_to_sql expects rows as dict-like objects")

        def _sqlite_type(pyval):
            if isinstance(pyval, int) and not isinstance(pyval, bool):
                return "INTEGER"
            if isinstance(pyval, float):
                return "REAL"
            return "TEXT"

        cols = list(first.keys())
        col_types = {c: _sqlite_type(first.get(c)) for c in cols}
        col_defs = ", ".join(f'"{c}" {col_types[c]}' for c in cols)
        create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})'
        cur = conn.cursor()
        cur.execute(create_sql)

        placeholders = ",".join("?" for _ in cols)
        quoted_cols = ",".join('"%s"' % c for c in cols)
        insert_sql = (
            'INSERT INTO "'
            + table_name
            + '" ('
            + quoted_cols
            + ") VALUES ("
            + placeholders
            + ")"
        )
        values = [tuple(row.get(c) for c in cols) for row in rows]
        cur.executemany(insert_sql, values)
        conn.commit()
    finally:
        conn.close()


# --- Background DB writer -------------------------------------------------
# A single-threaded writer that consumes a queue of (df, db_path, table_name,
# if_exists) requests and writes them serially. This avoids sqlite "database is
# locked" errors when multiple threads/processes attempt concurrent writes.

_db_write_queue: "queue.Queue[tuple]" = queue.Queue()
_db_writer_thread: threading.Thread | None = None
_db_writer_stop = threading.Event()


def _db_writer_loop():
    while not _db_writer_stop.is_set() or not _db_write_queue.empty():
        try:
            item = _db_write_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        try:
            df, db_path, table_name, if_exists = item
            save_df_to_sql(df, db_path, table_name, if_exists=if_exists)
        except Exception:
            # Don't let a single failed write kill the loop; log to stderr.
            import traceback

            traceback.print_exc()
        finally:
            _db_write_queue.task_done()


def start_db_writer_thread():
    """Start the background DB writer thread if not already running."""
    global _db_writer_thread
    if _db_writer_thread is not None and _db_writer_thread.is_alive():
        return
    _db_writer_stop.clear()
    _db_writer_thread = threading.Thread(target=_db_writer_loop, daemon=True)
    _db_writer_thread.start()


def stop_db_writer_thread(
    wait: bool = True,
    timeout: float | None = None,
) -> None:
    """Signal the writer thread to stop and optionally wait for queue flush."""
    _db_writer_stop.set()
    if wait:
        try:
            _db_write_queue.join()
        except Exception:
            pass
        if _db_writer_thread is not None:
            _db_writer_thread.join(timeout=timeout)


def enqueue_df_save(
    df,
    db_path: str,
    table_name: str,
    if_exists: str = "append",
) -> None:
    """Enqueue a DataFrame to be saved to sqlite by the background writer.

    The background writer will be started on first enqueue if not already
    running. This function returns immediately after enqueueing.
    """
    start_db_writer_thread()
    _db_write_queue.put((df, db_path, table_name, if_exists))


def wait_for_db_writes(timeout: float | None = None) -> bool:
    """Block until the DB write queue is empty or until `timeout` seconds.

    Returns True if queue drained, False if timed out.
    """
    start = time.time()
    while True:
        if _db_write_queue.empty():
            return True
        if timeout is not None and (time.time() - start) > timeout:
            return False
        time.sleep(0.05)


# Ensure we flush writes at process exit
def _atexit_flush():
    stop_db_writer_thread(wait=True)


atexit.register(_atexit_flush)
