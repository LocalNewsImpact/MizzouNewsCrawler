"""Dataset versioning models and helpers.

This file defines two SQLAlchemy models:
- DatasetVersion
- DatasetDelta

It also provides a helper to create the tables.
"""

import hashlib
import logging
import os
import shutil
import uuid
from datetime import datetime

import pandas as pd
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    inspect,
    text,
)
from sqlalchemy.orm import sessionmaker

from . import Base, create_database_engine

# Optional dependency: prefer pyarrow for streaming parquet writes
try:
    import pyarrow as pa
    import pyarrow.parquet as pq

    _HAS_PYARROW = True
except Exception:
    _HAS_PYARROW = False
    logging.debug(
        "pyarrow not available; falling back to pandas for Parquet operations"
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_name = Column(String, nullable=False, index=True)
    version_tag = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by_job = Column(String, nullable=True)
    snapshot_path = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    parent_version = Column(String, nullable=True)
    # New metadata and lifecycle fields
    status = Column(
        String,
        nullable=False,
        default="pending",
        index=True,
    )  # pending|in_progress|ready|failed
    checksum = Column(String, nullable=True)
    row_count = Column(Integer, nullable=True)
    claimed_by = Column(String, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class DatasetDelta(Base):
    __tablename__ = "dataset_deltas"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_version_id = Column(
        String, ForeignKey("dataset_versions.id"), nullable=False
    )
    operation = Column(String, nullable=False)  # insert|update|delete
    record_id = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    changed_by_job = Column(String, nullable=True)


def create_versioning_tables(database_url: str = None):
    """Helper to create versioning tables.

    If `database_url` is provided, a new engine is created; otherwise
    `sqlite:///data/mizzou.db` is used by default via `create_database_engine`.
    """
    engine = create_database_engine(database_url or "sqlite:///data/mizzou.db")
    # Only create versioning-specific tables here so callers can create
    # test tables (like `candidate_links`) without collisions.
    DatasetVersion.__table__.create(engine, checkfirst=True)
    DatasetDelta.__table__.create(engine, checkfirst=True)
    return engine


def create_dataset_version(
    dataset_name: str,
    version_tag: str,
    description: str | None = None,
    parent_version: str | None = None,
    snapshot_path: str | None = None,
    created_by_job: str | None = None,
    database_url: str | None = None,
) -> DatasetVersion:
    """Create a new DatasetVersion record and return it."""
    engine = create_database_engine(database_url or "sqlite:///data/mizzou.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    dv = DatasetVersion(
        dataset_name=dataset_name,
        version_tag=version_tag,
        description=description,
        parent_version=parent_version,
        snapshot_path=snapshot_path,
        created_by_job=created_by_job,
    )

    session.add(dv)
    session.commit()
    session.refresh(dv)
    return dv


def claim_dataset_version(
    version_id: str, claimer: str = None, database_url: str = None
) -> bool:
    """Attempt to claim a DatasetVersion for snapshotting.

    Returns True if claimed.
    """
    engine = create_database_engine(database_url or "sqlite:///data/mizzou.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    # Only transition from pending -> in_progress
    rows = (
        session.query(DatasetVersion)
        .filter(DatasetVersion.id == version_id, DatasetVersion.status == "pending")
        .update(
            {
                "status": "in_progress",
                "claimed_by": claimer,
                "claimed_at": datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )

    session.commit()
    return bool(rows)


def finalize_dataset_version(
    version_id: str,
    *,
    snapshot_path: str = None,
    row_count: int = None,
    checksum: str = None,
    succeeded: bool = True,
    database_url: str = None,
) -> DatasetVersion:
    """Finalize a DatasetVersion record after snapshotting.

    Updates snapshot_path, row_count, checksum, status and finished_at.
    """
    engine = create_database_engine(database_url or "sqlite:///data/mizzou.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    dv = session.query(DatasetVersion).filter_by(id=version_id).first()
    if not dv:
        raise ValueError(f"DatasetVersion not found: {version_id}")

    dv.snapshot_path = snapshot_path or dv.snapshot_path
    if row_count is not None:
        dv.row_count = row_count
    if checksum is not None:
        dv.checksum = checksum
    dv.finished_at = datetime.utcnow()
    dv.status = "ready" if succeeded else "failed"

    session.add(dv)
    session.commit()
    session.refresh(dv)
    return dv


def _compute_file_checksum(path: str, chunk_size: int = 8192) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _is_postgres_engine(engine) -> bool:
    try:
        return getattr(engine.dialect, "name", "") == "postgresql"
    except Exception:
        return False


def _compute_advisory_lock_id(*parts: str) -> int:
    """Compute a 64-bit advisory lock id from provided string parts."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    # use first 8 bytes as unsigned bigint
    val = int.from_bytes(h.digest()[:8], "big", signed=False)
    # Postgres advisory lock accepts signed bigint; keep value in
    # signed 64-bit range
    return val & 0x7FFFFFFFFFFFFFFF


def _fsync_path(path: str) -> None:
    """Try to fsync a file and its parent directory to ensure durability.

    This is best-effort: on platforms that don't support directory fsync or
    when permissions prevent it, we silently continue.
    """
    try:
        # fsync file
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass

    try:
        # fsync parent directory
        parent = os.path.dirname(path) or "."
        dir_fd = os.open(parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        pass


def list_dataset_versions(
    dataset_name: str = None, database_url: str = None
) -> list[DatasetVersion]:
    """Return list of DatasetVersion records, optionally filtered by dataset_name."""
    engine = create_database_engine(database_url or "sqlite:///data/mizzou.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    query = session.query(DatasetVersion)
    if dataset_name:
        query = query.filter(DatasetVersion.dataset_name == dataset_name)

    return query.order_by(DatasetVersion.created_at.desc()).all()


def export_dataset_version(
    version_id: str, output_path: str, database_url: str = None
) -> str:
    """Export a version by copying its snapshot to `output_path`.

    If no snapshot_path is available, raise NotImplementedError for now.
    """
    engine = create_database_engine(database_url or "sqlite:///data/mizzou.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    dv = session.query(DatasetVersion).filter_by(id=version_id).first()
    if not dv:
        raise ValueError(f"DatasetVersion not found: {version_id}")

    if not dv.snapshot_path:
        raise NotImplementedError(
            "Export without snapshot is not implemented. Create a snapshot first."
        )

    shutil.copyfile(dv.snapshot_path, output_path)
    return output_path


def export_snapshot_for_version(
    version_id: str,
    table_name: str,
    output_path: str,
    database_url: str = None,
    chunksize: int = 10000,
    compression: str | None = None,
) -> str:
    """Create a Parquet snapshot for a given version by exporting the entire
    table `table_name` from the configured database to `output_path`, update
    the DatasetVersion.snapshot_path, and return the updated DatasetVersion.

    Uses a DB-backed claim plus an optional Postgres advisory lock to avoid
    concurrent writers. When using Postgres and the advisory lock is acquired,
    the export will run inside a REPEATABLE READ transaction to get a
    consistent snapshot.
    """
    engine = create_database_engine(database_url or "sqlite:///data/mizzou.db")
    Session = sessionmaker(bind=engine)
    session = Session()

    dv = session.query(DatasetVersion).filter_by(id=version_id).first()
    if not dv:
        raise ValueError(f"DatasetVersion not found: {version_id}")

    # Ensure table exists
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        raise ValueError(f"Table not found in database: {table_name}")

    # Ensure output dir exists
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    # Write to a temporary file in the same directory then atomically replace
    temp_path = os.path.join(
        out_dir, f".{os.path.basename(output_path)}.tmp.{uuid.uuid4()}"
    )

    # Attempt to claim the dataset version: prevent concurrent snapshotters
    claimed = claim_dataset_version(
        dv.id, claimer=dv.created_by_job, database_url=database_url
    )
    if not claimed:
        raise RuntimeError(
            f"Failed to claim DatasetVersion {dv.id}; "
            f"another process may be working on it"
        )

    pg_lock_acquired = False
    lock_id = None
    if _is_postgres_engine(engine):
        lock_id = _compute_advisory_lock_id(dv.dataset_name or "", dv.id)
        try:
            with engine.connect() as conn:
                res = conn.execute(
                    text("SELECT pg_try_advisory_lock(%(id)s)"), {"id": lock_id}
                )
                pg_lock_acquired = bool(res.scalar())
        except Exception:
            pg_lock_acquired = False

        if not pg_lock_acquired:
            # revert claim so others can try
            try:
                s = Session()
                s.query(DatasetVersion).filter(DatasetVersion.id == dv.id).update(
                    {"status": "pending", "claimed_by": None, "claimed_at": None},
                    synchronize_session=False,
                )
                s.commit()
            except Exception:
                pass

            raise RuntimeError(
                f"Failed to acquire Postgres advisory lock for DatasetVersion {dv.id}"
            )

    total_rows = 0
    try:
        if _HAS_PYARROW:
            first = True
            writer = None

            select_sql = text(f"SELECT * FROM {table_name}")

            if pg_lock_acquired and _is_postgres_engine(engine):
                # Export inside a REPEATABLE READ transaction for consistent
                # snapshot
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                        )
                        result = conn.execution_options(stream_results=True).execute(
                            select_sql
                        )
                        cols = result.keys()

                        while True:
                            rows = result.fetchmany(chunksize)
                            if not rows:
                                break

                            col_data = {c: [] for c in cols}
                            for r in rows:
                                for c, v in zip(cols, r, strict=False):
                                    col_data[c].append(v)

                            table = pa.Table.from_pydict(col_data)
                            total_rows += table.num_rows

                            if first:
                                # Pass compression if provided
                                if compression:
                                    writer = pq.ParquetWriter(
                                        temp_path,
                                        table.schema,
                                        compression=compression,
                                    )
                                else:
                                    writer = pq.ParquetWriter(temp_path, table.schema)
                                writer.write_table(table)
                                first = False
                            else:
                                writer.write_table(table)
            else:
                with engine.connect() as conn:
                    result = conn.execution_options(stream_results=True).execute(
                        select_sql
                    )
                    cols = result.keys()

                    while True:
                        rows = result.fetchmany(chunksize)
                        if not rows:
                            break

                        col_data = {c: [] for c in cols}
                        for r in rows:
                            for c, v in zip(cols, r, strict=False):
                                col_data[c].append(v)

                        table = pa.Table.from_pydict(col_data)
                        total_rows += table.num_rows

                        if first:
                            if compression:
                                writer = pq.ParquetWriter(
                                    temp_path,
                                    table.schema,
                                    compression=compression,
                                )
                            else:
                                writer = pq.ParquetWriter(temp_path, table.schema)
                            writer.write_table(table)
                            first = False
                        else:
                            writer.write_table(table)

            if writer:
                writer.close()
            else:
                empty = pa.Table.from_pydict({})
                pq.write_table(empty, temp_path, compression=compression)

            _fsync_path(temp_path)
            os.replace(temp_path, output_path)
            _fsync_path(output_path)
        else:
            # pandas fallback
            df = pd.read_sql_table(table_name, con=engine)
            total_rows = len(df)
            # pandas will accept compression=None
            df.to_parquet(temp_path, index=False, compression=compression)
            _fsync_path(temp_path)
            os.replace(temp_path, output_path)
            _fsync_path(output_path)

        # compute checksum and finalize
        try:
            checksum = _compute_file_checksum(output_path)
        except Exception:
            checksum = None

        try:
            row_count = total_rows
        except Exception:
            row_count = None

        dv = finalize_dataset_version(
            dv.id,
            snapshot_path=output_path,
            row_count=row_count,
            checksum=checksum,
            succeeded=True,
            database_url=database_url,
        )

        # release advisory lock if we held it
        if pg_lock_acquired and lock_id is not None and _is_postgres_engine(engine):
            try:
                with engine.connect() as conn:
                    conn.execute(
                        text("SELECT pg_advisory_unlock(%(id)s)"), {"id": lock_id}
                    )
            except Exception:
                # ignore unlock errors
                pass

    except Exception:
        # cleanup temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

        # release advisory lock if held
        if pg_lock_acquired and lock_id is not None and _is_postgres_engine(engine):
            try:
                with engine.connect() as conn:
                    conn.execute(
                        text("SELECT pg_advisory_unlock(%(id)s)"), {"id": lock_id}
                    )
            except Exception:
                # ignore unlock errors
                pass

        # revert claim so others may retry
        try:
            s = Session()
            s.query(DatasetVersion).filter(DatasetVersion.id == dv.id).update(
                {"status": "pending", "claimed_by": None, "claimed_at": None},
                synchronize_session=False,
            )
            s.commit()
        except Exception:
            pass

        # finalize as failed in DB
        try:
            finalize_dataset_version(dv.id, succeeded=False, database_url=database_url)
        except Exception:
            pass

        raise

    return output_path
