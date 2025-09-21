"""Database utilities for SQLite backend with idempotent operations."""

import hashlib
import logging
import random
import time
import uuid
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, insert, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
import sqlite3

from . import Article, Base, CandidateLink, Job, Location, MLResult, Source
import json

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self, database_url: str = "sqlite:///data/mizzou.db"):
        self.database_url = database_url
        # For SQLite, set a timeout so connections wait for locks instead
        # of immediately failing with 'database is locked'. Also keep
        # check_same_thread disabled to allow multithreaded use.
        connect_args = {}
        if "sqlite" in database_url:
            connect_args = {"check_same_thread": False, "timeout": 30}

        self.engine = create_engine(
            database_url,
            connect_args=connect_args,
            echo=False,
        )
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

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

            # Merge updates (shallow)
            current.update(updates)
            src.meta = current
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
        dataset_id: Optional[str] = None,
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
                hasattr(e, "orig")
                and isinstance(getattr(e, "orig"), _sqlite.OperationalError)
            ):
                time.sleep(backoff)
                backoff *= 2
                continue
            else:
                # Non-retryable error, re-raise
                raise
    # Final attempt
    session.commit()


def upsert_candidate_links(
    self,
    df: pd.DataFrame,
    if_exists: Literal["fail", "replace", "append"] = "append",
    dataset_id: Optional[str] = None,
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
    # Check if link already exists
    existing = session.query(CandidateLink).filter_by(url=url).first()

    if existing:
        # Update existing record with new data
        for key, value in kwargs.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        # Commit with retry to mitigate transient sqlite locks
        _commit_with_retry(session)
        logger.debug(f"Updated existing candidate link: {url}")
        return existing
    else:
        # Create new record
        link = CandidateLink(url=url, source=source, **kwargs)
        session.add(link)
        # Commit with retry to mitigate transient sqlite locks
        _commit_with_retry(session)
        logger.info(f"Created new candidate link: {url}")
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
    results: List[Dict[str, Any]],
    job_id: Optional[str] = None,
) -> List[MLResult]:
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


def save_locations(
    session,
    article_id: str,
    entities: List[Dict[str, Any]],
    ner_model_version: Optional[str] = None,
) -> List[Location]:
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


def create_job_record(
    session,
    job_type: str,
    job_name: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
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
    metrics: Optional[Dict[str, Any]] = None,
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


def read_candidate_links(
    engine, filters: Optional[Dict[str, Any]] = None
) -> pd.DataFrame:
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


def read_articles(engine, filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
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
    dataset_id: Optional[str] = None,
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
                # PRAGMA table_info returns rows with columns:
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
                logger.info(f"Dropped {dup_dropped} rows with URLs already in DB")
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

                    host_map: Dict[str, str] = {}
                    if hosts:
                        # Query existing sources matching these hosts.
                        sel = select(sources_tbl.c.id, sources_tbl.c.host).where(
                            sources_tbl.c.host.in_(list(hosts))
                        )
                        res = conn.execute(sel)
                        for r in res.fetchall():
                            host_map[(r.host or "").lower()] = r.id

                        # Insert missing hosts into `sources` table.
                        missing = [h for h in hosts if h not in host_map]
                        if missing:
                            ins_rows: List[Dict[str, Any]] = []
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
                    def _resolve_row(row):
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

                    df["source_id"] = df.apply(_resolve_row, axis=1)

                    # Build `dataset_sources` rows grouped by legacy id.
                    ds_rows: List[Dict[str, Any]] = []
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
                            conn.execute(text(insert_sql), ds_rows)
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
                            "ALTER TABLE articles ADD COLUMN "
                            "candidate_link_id VARCHAR"
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
    filters: Optional[Dict[str, Any]] = None,
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
