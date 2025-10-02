import datetime
import json
import math
import os
import queue as pyqueue
import sqlite3
import sys
import threading
import time as _time
import uuid
from pathlib import Path

import numpy as np
import pandas as _pd
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add gazetteer telemetry imports
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))
# Add comprehensive telemetry imports
from src.utils.comprehensive_telemetry import (  # noqa: E402
    ComprehensiveExtractionTelemetry,
)
from web.gazetteer_telemetry_api import (  # noqa: E402
    AddressEditRequest,
    ReprocessRequest,
    ensure_address_updates_table,
    get_failed_publishers,
    get_gazetteer_stats,
    get_publisher_telemetry,
    trigger_gazetteer_reprocess,
    update_publisher_address,
)

# pydantic.Field not used here

BASE_DIR = Path(__file__).resolve().parents[2]
# point to the full processed CSV with labels and geo
ARTICLES_CSV = BASE_DIR / "processed" / "articleslabelledgeo_8.csv"
DB_PATH = BASE_DIR / "backend" / "reviews.db"
# Main database path for telemetry data
MAIN_DB_PATH = BASE_DIR / "data" / "mizzou.db"

app = FastAPI(title="MizzouNewsCrawler Reviewer API")

# CORS configuration - allow origins can be configured via
# ALLOWED_ORIGINS env var (comma-separated)
allowed = os.environ.get("ALLOWED_ORIGINS", "*")
if allowed == "*":
    origins = ["*"]
else:
    origins = [o.strip() for o in allowed.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the simple static frontend (no build) at /web for quick local testing
try:
    web_dir = str(BASE_DIR / "web")
    app.mount("/web", StaticFiles(directory=web_dir), name="web")
except Exception:
    # ignore mounting errors in environments where filesystem access differs
    pass


class ReviewIn(BaseModel):
    reviewer: str
    article_uid: str | None = None
    rating: int | None = None
    secondary_rating: int | None = None
    tags: list[str] | None = None
    notes: str | None = None
    body_errors: list[str] | None = None
    headline_errors: list[str] | None = None
    author_errors: list[str] | None = None
    mentioned_locations: list[str] | None = None
    missing_locations: list[str] | None = None
    incorrect_locations: list[str] | None = None
    missing_tags: list[str] | None = None
    incorrect_tags: list[str] | None = None
    inferred_tags: list[str] | None = None


# Snapshot ingestion models
class SnapshotIn(BaseModel):
    url: str
    host: str
    html: str | None = None
    pipeline_run_id: str | None = None
    parsed_fields: dict | None = None
    model_confidence: float | None = None
    failure_reason: str | None = None


class CandidateIn(BaseModel):
    selector: str
    field: str | None = None
    score: float | None = None
    words: int | None = None
    snippet: str | None = None
    alts: list[str] | None = None


def init_db():
    # Use a connection with a timeout and set busy timeout to allow SQLite
    # to wait for transient locks. Retry on OperationalError 'locked'.
    attempts = 6
    backoff = 0.5
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            try:
                conn.execute("PRAGMA busy_timeout=30000")
            except Exception:
                pass
            cur = conn.cursor()
            break
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as oe:
            last_exc = oe
            if "locked" in str(oe).lower() and attempt < attempts:
                _time.sleep(backoff * (2 ** (attempt - 1)))
                continue
            raise
    if last_exc is not None and cur is None:
        # couldn't obtain DB connection
        raise last_exc
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_idx INTEGER,
                secondary_rating INTEGER,
            article_uid TEXT,
            reviewer TEXT,
            rating INTEGER,
            tags TEXT,
            notes TEXT,
            mentioned_locations TEXT,
            missing_locations TEXT,
            incorrect_locations TEXT,
            'inferred_tags TEXT',
            missing_tags TEXT,
            incorrect_tags TEXT,
            body_errors TEXT,
            headline_errors TEXT,
            author_errors TEXT,
            created_at TEXT
            ,
            UNIQUE(article_idx, reviewer)
        )
        """
    )
    # Ensure older DBs get new columns if missing
    cur.execute("PRAGMA table_info(reviews)")
    existing_cols = [r[1] for r in cur.fetchall()]
    for col in ("body_errors", "headline_errors", "author_errors"):
        if col not in existing_cols:
            try:
                cur.execute(f"ALTER TABLE reviews ADD COLUMN {col} TEXT")
            except Exception:
                pass
    # Add secondary_rating column if missing
    if "secondary_rating" not in existing_cols:
        try:
            cur.execute(
                "ALTER TABLE reviews ADD COLUMN secondary_rating INTEGER"
            )
        except Exception:
            pass
    # Add missing_locations column if missing
    if "missing_locations" not in existing_cols:
        try:
            cur.execute(
                "ALTER TABLE reviews ADD COLUMN missing_locations TEXT"
            )
        except Exception:
            pass
    # Add incorrect_locations column if missing
    if "incorrect_locations" not in existing_cols:
        try:
            cur.execute(
                "ALTER TABLE reviews ADD COLUMN incorrect_locations TEXT"
            )
        except Exception:
            pass
    # Add inferred_tags column if missing
    if "inferred_tags" not in existing_cols:
        try:
            cur.execute("ALTER TABLE reviews ADD COLUMN inferred_tags TEXT")
        except Exception:
            pass
    # Add mentioned_locations column if missing
    if "mentioned_locations" not in existing_cols:
        try:
            cur.execute(
                "ALTER TABLE reviews ADD COLUMN mentioned_locations TEXT"
            )
        except Exception:
            pass
    # Add article_uid column if missing
    # (unique identifier from CSV 'id' column)
    if "article_uid" not in existing_cols:
        try:
            cur.execute("ALTER TABLE reviews ADD COLUMN article_uid TEXT")
        except Exception:
            pass
    # Add missing_tags/incorrect_tags if missing
    if "missing_tags" not in existing_cols:
        try:
            cur.execute(
                "ALTER TABLE reviews ADD COLUMN missing_tags TEXT"
            )
        except Exception:
            pass
    if "incorrect_tags" not in existing_cols:
        try:
            cur.execute(
                "ALTER TABLE reviews ADD COLUMN incorrect_tags TEXT"
            )
        except Exception:
            pass
    # Add reviewed_at column to mark when a reviewer saved/marked
    # the article as reviewed
    if "reviewed_at" not in existing_cols:
        try:
            cur.execute("ALTER TABLE reviews ADD COLUMN reviewed_at TEXT")
        except Exception:
            pass
    # Ensure a unique index exists for (article_idx, reviewer)
    # so UPSERT targets it
    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "reviews_article_reviewer_idx "
            "ON reviews(article_idx, reviewer)"
        )
    except Exception:
        # ignore index creation errors on older SQLite versions
        pass
    # Also ensure a unique index exists for (article_uid, reviewer) for UPSERTs by uid
    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "reviews_articleuid_reviewer_idx "
            "ON reviews(article_uid, reviewer)"
        )
    except Exception:
        pass
    conn.commit()
    conn.close()

    # Ensure domain_feedback table exists to store reviewer feedback per host
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS domain_feedback (
                host TEXT PRIMARY KEY,
                priority TEXT,
                needs_dev INTEGER DEFAULT 0,
                assigned_to TEXT,
                notes TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def init_snapshot_tables():
    # create snapshots and candidates tables if missing
    # Open with a short timeout while initializing tables
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            host TEXT,
            url TEXT,
            path TEXT,
            pipeline_run_id TEXT,
            failure_reason TEXT,
            parsed_fields TEXT,
            model_confidence REAL,
            status TEXT,
            created_at TEXT,
            reviewed_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            snapshot_id TEXT,
            selector TEXT,
            field TEXT,
            score REAL,
            words INTEGER,
            snippet TEXT,
            alts TEXT,
            accepted INTEGER DEFAULT 0,
            created_at TEXT
        )
        """
    )
    # lightweight job queue for re-extraction after committing a site rule
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reextract_jobs (
            id TEXT PRIMARY KEY,
            host TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    # deduplication audit table to record pairwise similarity, flags and metadata
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_uid TEXT,
                neighbor_uid TEXT,
                host TEXT,
                similarity REAL,
                dedupe_flag INTEGER,
                category INTEGER,
                stage TEXT,
                details TEXT,
                created_at TEXT
            )
        """
        )
        # helpful index for querying by article_uid or host
        cur.execute(
            "CREATE INDEX IF NOT EXISTS dedupe_audit_article_idx "
            "ON dedupe_audit(article_uid)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS dedupe_audit_host_idx ON dedupe_audit(host)"
        )
    except Exception:
        # ignore if another process created table concurrently
        pass
    # ensure older DBs get the 'alts' column if it was added later
    try:
        cur.execute("PRAGMA table_info(candidates)")
        existing = [r[1] for r in cur.fetchall()]
        if "alts" not in existing:
            try:
                cur.execute("ALTER TABLE candidates ADD COLUMN alts TEXT")
            except Exception:
                # ignore if another process added it concurrently
                pass
    except Exception:
        pass
    conn.commit()
    # Enable WAL journal mode to reduce writer locking during concurrent access
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    conn.commit()
    conn.close()


# In-process queue and worker to serialize DB writes so HTTP handlers return
# quickly instead of blocking on SQLite locks. This reduces client timeouts
# when many writers contend for the DB file.
snapshots_queue = pyqueue.Queue()
_worker_stop_event = threading.Event()
_worker_thread = None


def _db_writer_worker():
    """Background thread that serially writes snapshot rows to SQLite.
    Each queue item is a dict with keys matching the previous insert.
    The worker performs the same retry/backoff on 'database is locked'.
    """
    while not _worker_stop_event.is_set():
        try:
            item = snapshots_queue.get(timeout=1.0)
        except Exception:
            # timeout, check stop flag again
            continue
        try:
            sid = item.get("id")
            attempts = 8
            backoff = 0.5
            last_exc = None
            for attempt in range(1, attempts + 1):
                try:
                    conn = sqlite3.connect(
                        DB_PATH, timeout=30.0
                    )
                    try:
                        conn.execute("PRAGMA journal_mode=WAL")
                    except Exception:
                        pass
                    try:
                        conn.execute("PRAGMA busy_timeout=30000")
                    except Exception:
                        pass
                    cur = conn.cursor()
                    cur.execute(
                        (
                            "INSERT INTO snapshots (id, host, url, path, pipeline_run_id, "
                            "failure_reason, parsed_fields, "
                            "model_confidence, status, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                        ),
                        (
                            sid,
                            item.get("host"),
                            item.get("url"),
                            item.get("path"),
                            item.get("pipeline_run_id"),
                            item.get("failure_reason"),
                            (
                                json.dumps(item.get("parsed_fields"))
                                if item.get("parsed_fields") is not None
                                else None
                            ),
                            item.get("model_confidence"),
                            item.get("status") or "pending",
                            item.get("created_at"),
                        ),
                    )
                    conn.commit()
                    conn.close()
                    last_exc = None
                    break
                except (sqlite3.OperationalError, sqlite3.DatabaseError) as oe:
                    last_exc = oe
                    msg = str(oe).lower()
                    if "locked" in msg and attempt < attempts:
                        _time.sleep(backoff * (2 ** (attempt - 1)))
                        continue
                    # give up on other DB errors
                    break
            if last_exc is not None:
                # Failed after retries: log to server console for diagnostics
                import traceback

                traceback.print_exc()
        finally:
            try:
                snapshots_queue.task_done()
            except Exception:
                pass


@app.on_event("startup")
def startup_writer():
    global _worker_thread
    # start the DB writer thread
    _worker_stop_event.clear()
    _worker_thread = threading.Thread(
        target=_db_writer_worker, name="db-writer", daemon=True
    )
    _worker_thread.start()


@app.on_event("shutdown")
def shutdown_writer():
    # signal worker to stop and wait a short time
    _worker_stop_event.set()
    try:
        if _worker_thread is not None:
            _worker_thread.join(
                timeout=5.0
            )
    except Exception:
        pass


@app.on_event("startup")
def startup_snap_tables():
    init_snapshot_tables()


@app.on_event("startup")
def startup():
    init_db()


@app.on_event("startup")
def startup_gazetteer_tables():
    """Initialize gazetteer telemetry tables on startup."""
    ensure_address_updates_table()


@app.get("/api/articles")
def list_articles(
    limit: int = 20, offset: int = 0, reviewer: str | None = None
):
    if not ARTICLES_CSV.exists():
        return {"count": 0, "results": []}
    df = pd.read_csv(ARTICLES_CSV)
    # replace infinite values and NaN with None for JSON safety
    df = df.replace(
        [np.inf, -np.inf], None
    )
    df = df.where(pd.notnull(df), None)
    # If caller provided a reviewer, filter out articles
    # already reviewed by that reviewer
    if reviewer:
        try:
            # use a longer timeout to wait for transient locks to clear
            conn = sqlite3.connect(DB_PATH, timeout=30.0)
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT article_idx FROM reviews WHERE reviewer=? AND reviewed_at IS NOT NULL",
                (reviewer,),
            )
            reviewed = {int(r[0]) for r in cur.fetchall() if r and r[0] is not None}
            conn.close()
        except Exception:
            reviewed = set()
        # preserve original csv indices so frontend can POST back using the CSV index
        df = df.reset_index()  # original indices in column 'index'
        df = df[~df["index"].isin(reviewed)]
        df = df.reset_index(drop=True)
        # total and slicing apply to filtered df
        total = len(df)
        selected = df.iloc[offset : offset + limit]
        rows = selected.to_dict(orient="records")
        # attach original CSV index as __idx so frontend can reference it
        safe_rows = []
        for r in rows:
            orig_idx = r.get("index") if "index" in r else None
            sr = sanitize_record(r)
            sr["__idx"] = int(orig_idx) if orig_idx is not None else None
            safe_rows.append(sr)
        return {"count": total, "results": safe_rows}
    else:
        total = len(df)
        rows = df.iloc[offset : offset + limit].to_dict(orient="records")
        safe_rows = [sanitize_record(r) for r in rows]
        # also add __idx for consistency
        for i, sr in enumerate(safe_rows):
            sr["__idx"] = offset + i
        return {"count": total, "results": safe_rows}


@app.get("/api/articles/{idx}")
def get_article(idx: int):
    if not ARTICLES_CSV.exists():
        raise HTTPException(status_code=404, detail="Articles CSV not found")
    df = pd.read_csv(ARTICLES_CSV)
    # sanitize special float values before returning
    df = df.replace([np.inf, -np.inf], None)
    df = df.where(pd.notnull(df), None)
    if idx < 0 or idx >= len(df):
        raise HTTPException(status_code=404, detail="Article not found")
    rec = df.iloc[idx].to_dict()
    return sanitize_record(rec)


def sanitize_value(v):
    # handle NaN/Inf
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    except Exception:
        pass
    # numpy numbers
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    # pandas Timestamp
    if isinstance(v, _pd.Timestamp):
        return v.isoformat()
    # numpy types with .item()
    # if it's a numpy scalar, use .item() to convert
    if isinstance(v, (np.generic,)):
        try:
            return v.item()
        except Exception:
            pass
    return v


def sanitize_record(rec: dict) -> dict:
    # Ensure the API always exposes a stable set of fields
    # mapped from the CSV.
    wanted = [
        "url",
        "title",
        "news",
        "date",
        "author",
        "hostname",
        "name",
        "inferred_tags_set1",
        "domain",
        "county",
        "predictedlabel1",
        "ALTpredictedlabel",
        "locmentions",
    ]
    out = {}
    # include requested keys with sanitized values
    # (fall back to None)
    for k in wanted:
        out[k] = (
            sanitize_value(rec.get(k)) if k in rec else None
        )
    # Also keep other keys present in the record so the frontend
    # can use them if needed
    for k, v in rec.items():
        if k not in out:
            out[k] = sanitize_value(v)
    # Normalize inferred tags into a stable `inferred_tags` array
    # so frontend code can uniformly access `article.inferred_tags`.
    try:
        # If the CSV already includes an `inferred_tags` column (array/string), prefer it.
        if "inferred_tags" in rec and rec.get("inferred_tags") is not None:
            val = rec.get("inferred_tags")
            if isinstance(val, str):
                out["inferred_tags"] = [
                    p
                    for p in [s.strip() for s in val.split(",")]
                    if p and p.upper() != "NONE"
                ]
            elif isinstance(val, (list, tuple)):
                out["inferred_tags"] = [str(p) for p in val if p]
            else:
                out["inferred_tags"] = []
        else:
            # Fallback to the `inferred_tags_set1` CSV field which is a comma-separated string
            its = rec.get("inferred_tags_set1") or rec.get("inferred_tags_set_1")
            if isinstance(its, str):
                out["inferred_tags"] = [
                    p
                    for p in [s.strip() for s in its.split(",")]
                    if p and p.upper() != "NONE"
                ]
            else:
                out["inferred_tags"] = []
    except Exception:
        out["inferred_tags"] = []
    return out


# Server-side implementation of the frontend `stableStringify` so the
# backend can produce canonical_hash values byte-for-byte compatible with
# the frontend's savedness checks. This mirrors the JS function used in
# web/frontend/src/App.jsx: sort object keys, recursively stringify arrays
# and objects, and use JSON encoding for primitives.
def stable_stringify(obj):
    # primitives
    if obj is None or not isinstance(obj, (dict, list)):
        try:
            return json.dumps(obj, separators=(",", ":"))
        except Exception:
            return json.dumps(None, separators=(",", ":"))
    # arrays
    if isinstance(obj, list):
        return "[" + ",".join(stable_stringify(v) for v in obj) + "]"
    # dicts -> sort keys
    if isinstance(obj, dict):
        keys = sorted(obj.keys())
        parts = []
        for k in keys:
            parts.append(json.dumps(k) + ":" + stable_stringify(obj[k]))
        return "{" + ",".join(parts) + "}"
    # fallback
    try:
        return json.dumps(obj, separators=(",", ":"))
    except Exception:
        return json.dumps(None, separators=(",", ":"))


@app.get("/api/options/{opt_name}")
def get_options(opt_name: str):
    """Provide simple option lists expected by the frontend for local testing.
    Frontend expects: /api/options/bodyErrors,
    /api/options/headlineErrors, /api/options/authorErrors
    Return empty lists by default so UI fallbacks still work.
    """
    # small default option sets (id,label)
    opts = {
        "bodyErrors": [
            {"id": "b1", "label": "Factual error"},
            {"id": "b2", "label": "Missing context"},
            {"id": "b3", "label": "Biased language"},
        ],
        "headlineErrors": [
            {"id": "h1", "label": "Missing"},
            {"id": "h2", "label": "Incomplete"},
            {"id": "h3", "label": "Incorrect"},
            {"id": "h4", "label": "HTML or JS"},
            {"id": "h5", "label": "Bad Characters"},
        ],
        "authorErrors": [
            {"id": "a1", "label": "Missing"},
            {"id": "a2", "label": "Incomplete"},
            {"id": "a3", "label": "Incorrect"},
            {"id": "a4", "label": "HTML or JS"},
            {"id": "a5", "label": "Bad Characters"},
        ],
    }
    return opts.get(opt_name, [])


@app.post("/api/articles/{idx}/reviews")
def post_review(idx: int, payload: ReviewIn):
    """Create or upsert a review for an article.
    The route accepts the CSV index (idx) for convenience but the payload may
    include `article_uid` to bind the review to the article's stable unique id.
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # ensure migration: reviews.reviewed_at column exists
    try:
        cur.execute("PRAGMA table_info(reviews)")
        cols = [r[1] for r in cur.fetchall()]
        if "reviewed_at" not in cols:
            try:
                cur.execute("ALTER TABLE reviews ADD COLUMN reviewed_at TEXT")
                conn.commit()
            except Exception:
                # ignore concurrent/migration failures
                pass
    except Exception:
        pass
    now = datetime.datetime.utcnow().isoformat()
    tags_str = ",".join(payload.tags) if payload.tags else None
    body_str = (
        ",".join(payload.body_errors) if payload.body_errors else None
    )
    headline_str = (
        ",".join(payload.headline_errors) if payload.headline_errors else None
    )
    author_str = (
        ",".join(payload.author_errors)
        if payload.author_errors
        else None
    )
    # Prefer an explicit article_uid if supplied in the payload;
    # otherwise attempt to map from the numeric CSV idx to the
    # article's `id` column.
    # Prefer explicit article_uid from the incoming payload
    # when provided.
    article_uid = getattr(payload, "article_uid", None) or None
    # try to read the CSV to map idx -> id if available
    try:
        if ARTICLES_CSV.exists():
            df = pd.read_csv(ARTICLES_CSV)
            if 0 <= idx < len(df):
                article_uid = article_uid or df.iloc[idx].get("id")
    except Exception:
        pass

    # DEBUG: print SQL and params length to help diagnose
    # placeholder mismatch. include reviewed_at so saving a review
    # marks it reviewed for that reviewer
    sql_stmt = (
        "INSERT INTO reviews ("
        "article_idx, article_uid, reviewer, rating, "
        "secondary_rating, tags, notes, "
        "mentioned_locations, missing_locations, "
        "incorrect_locations, inferred_tags, missing_tags, "
        "incorrect_tags, body_errors, headline_errors, "
        "author_errors, reviewed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?) "
        "ON CONFLICT(article_uid, reviewer) DO UPDATE SET "
        "rating=excluded.rating, "
        "secondary_rating=excluded.secondary_rating, "
        "tags=excluded.tags, "
        "notes=excluded.notes, "
        "mentioned_locations=excluded.mentioned_locations, "
        "missing_locations=excluded.missing_locations, "
        "incorrect_locations=excluded.incorrect_locations, "
        "inferred_tags=excluded.inferred_tags, "
        "missing_tags=excluded.missing_tags, "
        "incorrect_tags=excluded.incorrect_tags, "
        "body_errors=excluded.body_errors, "
        "headline_errors=excluded.headline_errors, "
        "author_errors=excluded.author_errors, "
        "reviewed_at=excluded.reviewed_at, "
        "created_at=excluded.created_at"
    )

    params = (
        idx,
        article_uid,
        payload.reviewer,
        payload.rating,
        payload.secondary_rating,
        tags_str,
        payload.notes,
        # store mentioned_locations as CSV text
        (
            ",".join(payload.mentioned_locations)
            if payload.mentioned_locations
            else None
        ),
        # store missing_locations as CSV text
        (
            ",".join(payload.missing_locations)
            if getattr(payload, "missing_locations", None)
            else None
        ),
        # store incorrect_locations as CSV text
        (
            ",".join(payload.incorrect_locations)
            if getattr(payload, "incorrect_locations", None)
            else None
        ),
        # store inferred_tags as CSV text
        (
            ",".join(payload.inferred_tags)
            if getattr(payload, "inferred_tags", None)
            else None
        ),
        # store missing_tags as CSV text
        (
            ",".join(payload.missing_tags)
            if getattr(payload, "missing_tags", None)
            else None
        ),
        # store incorrect_tags as CSV text
        (
            ",".join(payload.incorrect_tags)
            if getattr(payload, "incorrect_tags", None)
            else None
        ),
        body_str,
        headline_str,
        author_str,
        # reviewed_at: mark review as reviewed on save
        now,
        now,
    )

    # end debug

    cur.execute(sql_stmt, params)
    conn.commit()
    # Retrieve the canonical row for this review so callers
    # receive the authoritative, server-normalized representation
    # immediately.
    cols_sql = (
        "id, article_idx, article_uid, reviewer, rating, "
        "secondary_rating, "
        "tags, notes, mentioned_locations, missing_locations, "
        "incorrect_locations, inferred_tags, missing_tags, "
        "incorrect_tags, body_errors, headline_errors, "
        "author_errors, created_at"
    )

    # Try to use the sqlite cursor's lastrowid which points to
    # the row inserted by the most recent INSERT. This handles
    # the common case where the operation was an INSERT and we
    # can return that exact row.
    created_id = (
        cur.lastrowid if hasattr(cur, "lastrowid") else None
    )
    row = None
    if created_id:
        cur.execute(
            f"SELECT {cols_sql} FROM reviews WHERE id=?",
            (created_id,),
        )
        row = cur.fetchone()

    # If lastrowid wasn't available (e.g. the statement performed
    # an UPDATE as part of an upsert), fall back to selecting by
    # article_uid+reviewer or article_idx+reviewer.
    if not row:
        if article_uid:
            cur.execute(
                f"SELECT {cols_sql} FROM reviews "
                "WHERE article_uid=? AND reviewer=?",
                (article_uid, payload.reviewer),
            )
            row = cur.fetchone()
        if not row:
            cur.execute(
                f"SELECT {cols_sql} FROM reviews "
                "WHERE article_idx=? AND reviewer=?",
                (idx, payload.reviewer),
            )
            row = cur.fetchone()

    result = None

    # helper to split comma-separated stored strings into lists
    def _split_csv_field(s):
        if s is None:
            return []
        if not isinstance(s, str):
            return s
        s = s.strip()
        if s == "":
            return []
        # Treat literal 'NONE' or 'None' as empty as some
        # older records had that
        if s.upper() == "NONE" or s == "None":
            return []
        return [p for p in s.split(",") if p]

    if row:
        cols = cols_sql.split(", ")
        result = dict(zip(cols, row, strict=False))
        # Normalize CSV fields into arrays for API clients
        result["tags"] = _split_csv_field(result.get("tags"))
        result["body_errors"] = _split_csv_field(
            result.get("body_errors")
        )
        result["headline_errors"] = _split_csv_field(
            result.get("headline_errors")
        )
        result["author_errors"] = _split_csv_field(
            result.get("author_errors")
        )
        # normalize mentioned_locations into an array
        result["mentioned_locations"] = _split_csv_field(
            result.get("mentioned_locations")
        )
        # normalize missing_locations into an array
        result["missing_locations"] = _split_csv_field(
            result.get("missing_locations")
        )
        # normalize incorrect_locations into an array
        result["incorrect_locations"] = _split_csv_field(
            result.get("incorrect_locations")
        )
        # normalize inferred_tags
        result["inferred_tags"] = _split_csv_field(
            result.get("inferred_tags")
        )
        # normalize missing_tags/incorrect_tags
        result["missing_tags"] = _split_csv_field(
            result.get("missing_tags")
        )
        result["incorrect_tags"] = _split_csv_field(
            result.get("incorrect_tags")
        )
    else:
        # As a last resort, return the id if we can find any row
        # for this (article_idx, reviewer) pair.
        cur.execute(
            "SELECT id FROM reviews WHERE article_idx=? AND reviewer=?",
            (idx, payload.reviewer),
        )
        rid_row = cur.fetchone()
        created_id = rid_row[0] if rid_row else None
        result = {"id": created_id}

    # Build a canonical payload object that mirrors what the frontend's
    # `buildServerPayloadFromUI` expects so callers can use the server
    # authoritative representation to compute savedness/deduping.
    def build_canonical(r):
        if not r:
            return None
        # rating vs primary naming: prefer primary_rating if present on row
        primary = r.get("rating") if r.get("rating") is not None else r.get("rating")
        # Some rows may include 'secondary_rating' already
        secondary = (
            r.get("secondary_rating")
            if r.get("secondary_rating") is not None
            else r.get("secondary_rating")
        )

        # Build tags from explicit tag arrays if present, otherwise derive from error arrays
        body = r.get("body_errors") or []
        headline = r.get("headline_errors") or []
        author = r.get("author_errors") or []
        # combine and normalize tags as frontend does (dedupe, remove NONE, sort)
        tags = []
        try:
            tags = list(
                {
                    str(t)
                    for t in (
                        [*(body or []), *(headline or []), *(author or [])]
                        if True
                        else []
                    )
                    if t and str(t).upper() not in ("NONE", "None")
                }
            )
            tags.sort()
        except Exception:
            tags = []

        canonical = {
            "article_uid": r.get("article_uid"),
            "reviewer": r.get("reviewer"),
            "primary_rating": primary if primary is not None else 3,
            "secondary_rating": secondary if secondary is not None else 3,
            "body": list(body) if isinstance(body, (list, tuple)) else body or [],
            "headline": (
                list(headline)
                if isinstance(headline, (list, tuple))
                else headline or []
            ),
            "author": (
                list(author) if isinstance(author, (list, tuple)) else author or []
            ),
            "tags": tags,
            "notes": r.get("notes") or "",
            "mentioned_locations": r.get("mentioned_locations") or [],
            "missing_locations": r.get("missing_locations") or [],
            "inferred_tags": r.get("inferred_tags") or [],
            "missing_tags": r.get("missing_tags") or [],
        }
        return canonical

    def canonical_hash(obj):
        try:
            return stable_stringify(obj)
        except Exception:
            try:
                return json.dumps(
                    obj, sort_keys=True, separators=(",", ":")
                )
            except Exception:
                return None

    # Attach canonical payload and hash to the returned row so
    # the frontend can rely on a server-authoritative
    # representation for savedness checks.
    if result:
        try:
            result["canonical"] = build_canonical(result)
            result["canonical_hash"] = canonical_hash(
                result["canonical"]
            )
        except Exception:
            pass

    conn.close()
    return result


@app.put("/api/reviews/{rid}")
def update_review(rid: int, payload: ReviewIn):
    """Update an existing review by id.
    Returns 404 if the review does not exist.
    """
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="DB not found")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM reviews WHERE id=?", (rid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Review not found")
    # ensure reviewed_at column exists (no-op if present)
    try:
        cur.execute("PRAGMA table_info(reviews)")
        cols = [r[1] for r in cur.fetchall()]
        if "reviewed_at" not in cols:
            try:
                cur.execute("ALTER TABLE reviews ADD COLUMN reviewed_at TEXT")
                conn.commit()
            except Exception:
                pass
    except Exception:
        pass

    cur.execute(
        (
            "UPDATE reviews SET reviewer=?, rating=?, "
            "secondary_rating=?, tags=?, notes=?, "
            "mentioned_locations=?, missing_locations=?, "
            "incorrect_locations=?, inferred_tags=?, "
            "missing_tags=?, incorrect_tags=?, body_errors=?, "
            "headline_errors=?, author_errors=?, reviewed_at=? "
            "WHERE id=?"
        ),
        (
            payload.reviewer,
            payload.rating,
            payload.secondary_rating,
            ",".join(payload.tags) if payload.tags else None,
            payload.notes,
            (
                ",".join(payload.mentioned_locations)
                if payload.mentioned_locations
                else None
            ),
            (
                ",".join(payload.missing_locations)
                if getattr(payload, "missing_locations", None)
                else None
            ),
            (
                ",".join(payload.incorrect_locations)
                if getattr(payload, "incorrect_locations", None)
                else None
            ),
            (
                ",".join(payload.inferred_tags)
                if getattr(payload, "inferred_tags", None)
                else None
            ),
            (
                ",".join(payload.missing_tags)
                if getattr(payload, "missing_tags", None)
                else None
            ),
            (
                ",".join(payload.incorrect_tags)
                if getattr(payload, "incorrect_tags", None)
                else None
            ),
            ",".join(payload.body_errors) if payload.body_errors else None,
            ",".join(payload.headline_errors) if payload.headline_errors else None,
            ",".join(payload.author_errors) if payload.author_errors else None,
            datetime.datetime.utcnow().isoformat(),
            rid,
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "id": rid}


@app.get("/api/reviews")
def get_reviews(
    article_idx: int | None = None,
    article_uid: str | None = None
):
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cols_sql = (
        "id, article_idx, article_uid, reviewer, rating, "
        "secondary_rating, "
        "tags, notes, mentioned_locations, missing_locations, "
        "incorrect_locations, inferred_tags, missing_tags, "
        "incorrect_tags, body_errors, headline_errors, "
        "author_errors, created_at"
    )
    if article_uid:
        cur.execute(
            (
                f"SELECT {cols_sql} FROM reviews "
                "WHERE article_uid=? ORDER BY id DESC"
            ),
            (article_uid,),
        )
    elif article_idx is None:
        cur.execute(

                f"SELECT {cols_sql} FROM reviews "
                "ORDER BY id DESC LIMIT 200"

        )
    else:
        cur.execute(
            (
                f"SELECT {cols_sql} FROM reviews "
                "WHERE article_idx=? ORDER BY id DESC"
            ),
            (article_idx,),
        )
    rows = cur.fetchall()
    conn.close()

    cols = cols_sql.split(", ")

    def _split_csv_field(s):
        if s is None:
            return []
        if not isinstance(s, str):
            return s
        s = s.strip()
        if s == "":
            return []
        if s.upper() == "NONE" or s == "None":
            return []
        return [p for p in s.split(",") if p]

    results = []
    for r in rows:
        d = dict(zip(cols, r, strict=False))
        # normalize CSV-stored fields to arrays to match POST/PUT responses
        d["tags"] = _split_csv_field(d.get("tags"))
        d["body_errors"] = _split_csv_field(d.get("body_errors"))
        d["headline_errors"] = _split_csv_field(d.get("headline_errors"))
        d["author_errors"] = _split_csv_field(d.get("author_errors"))
        d["mentioned_locations"] = _split_csv_field(d.get("mentioned_locations"))
        d["inferred_tags"] = _split_csv_field(d.get("inferred_tags"))
        d["missing_locations"] = _split_csv_field(d.get("missing_locations"))
        d["incorrect_locations"] = _split_csv_field(d.get("incorrect_locations"))
        d["missing_tags"] = _split_csv_field(d.get("missing_tags"))
        d["incorrect_tags"] = _split_csv_field(d.get("incorrect_tags"))

        # Build canonical payload for each row similar to POST response
        try:
            body = d.get("body_errors") or []
            headline = d.get("headline_errors") or []
            author = d.get("author_errors") or []
            tags = []
            try:
                tags = list(
                    {
                        str(t)
                        for t in (
                            [*(body or []), *(headline or []), *(author or [])]
                            if True
                            else []
                        )
                        if t and str(t).upper() not in ("NONE", "None")
                    }
                )
                tags.sort()
            except Exception:
                tags = []
            canonical = {
                "article_uid": d.get("article_uid"),
                "reviewer": d.get("reviewer"),
                "primary_rating": d.get("rating") if d.get("rating") is not None else 3,
                "secondary_rating": (
                    d.get("secondary_rating")
                    if d.get("secondary_rating") is not None
                    else 3
                ),
                "body": list(body) if isinstance(body, (list, tuple)) else body or [],
                "headline": (
                    list(headline)
                    if isinstance(headline, (list, tuple))
                    else headline or []
                ),
                "author": (
                    list(author) if isinstance(author, (list, tuple)) else author or []
                ),
                "tags": tags,
                "notes": d.get("notes") or "",
                "mentioned_locations": d.get("mentioned_locations") or [],
                "missing_locations": d.get("missing_locations") or [],
                "inferred_tags": d.get("inferred_tags") or [],
                "missing_tags": d.get("missing_tags") or [],
            }
            # Attach canonical object and a stable canonical_hash string
            d["canonical"] = canonical
            try:
                d["canonical_hash"] = json.dumps(
                    canonical, sort_keys=True, separators=(",", ":")
                )
            except Exception:
                d["canonical_hash"] = None
        except Exception:
            d["canonical"] = None
            d["canonical_hash"] = None
        results.append(d)

    return results


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    # Log full traceback to the server console for debugging
    import traceback

    traceback.print_exc()
    # Return a JSON-friendly error so clients like `jq` can parse the response
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": str(exc),
        },
    )


# --- Snapshot ingestion API -------------------------------------------------


@app.post("/api/snapshots")
def post_snapshot(payload: SnapshotIn):
    """Ingest a snapshot: save HTML to disk and record metadata in DB.
    Enqueue the snapshot for background DB write and return 202 with snapshot id/path.
    """
    # Save HTML to disk immediately (fast filesystem op) and enqueue DB write
    init_snapshot_tables()
    sid = str(uuid.uuid4())
    host_dir = BASE_DIR / "lookups" / "snapshots" / payload.host
    host_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{sid}.html"
    path = str(host_dir / filename)
    if payload.html:
        try:
            Path(path).write_text(payload.html, encoding="utf-8")
        except Exception:
            # If disk write fails, return 500 so caller can retry
            raise
    now = datetime.datetime.utcnow().isoformat()
    item = {
        "id": sid,
        "host": payload.host,
        "url": payload.url,
        "path": path,
        "pipeline_run_id": payload.pipeline_run_id,
        "failure_reason": payload.failure_reason,
        "parsed_fields": payload.parsed_fields,
        "model_confidence": payload.model_confidence,
        "status": "pending",
        "created_at": now,
    }
    # enqueue for background DB writer (non-blocking)
    try:
        snapshots_queue.put_nowait(item)
    except Exception:
        # fall back to synchronous write if queueing fails
        snapshots_queue.put(item)
    # If the in-process background writer thread is not running (e.g. during
    # tests where startup events may not have started the worker), perform a
    # best-effort synchronous write so the snapshot is immediately queryable.
    try:
        if _worker_thread is None or not _worker_thread.is_alive():
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                (
                    "INSERT OR REPLACE INTO snapshots (id, host, url, path, pipeline_run_id, "
                    "failure_reason, parsed_fields, model_confidence, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    sid,
                    payload.host,
                    payload.url,
                    path,
                    payload.pipeline_run_id,
                    payload.failure_reason,
                    (
                        json.dumps(payload.parsed_fields)
                        if payload.parsed_fields is not None
                        else None
                    ),
                    payload.model_confidence,
                    "pending",
                    now,
                ),
            )
            conn.commit()
            conn.close()
    except Exception:
        # best-effort: if sync write fails, rely on background worker
        pass
    # Return accepted so clients can continue without waiting on DB
    return JSONResponse(
        status_code=202, content={"snapshot_id": sid, "path": path, "enqueued": True}
    )


@app.get("/api/snapshots/{sid}")
def get_snapshot(sid: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        (
            "SELECT id, host, url, path, pipeline_run_id, failure_reason, "
            "parsed_fields, model_confidence, status, created_at "
            "FROM snapshots WHERE id=?"
        ),
        (sid,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="snapshot not found")
    cols = [
        "id",
        "host",
        "url",
        "path",
        "pipeline_run_id",
        "failure_reason",
        "parsed_fields",
        "model_confidence",
        "status",
        "created_at",
    ]
    rec = dict(zip(cols, row, strict=False))
    # load candidates
    cur.execute(
        (
            "SELECT id, selector, field, score, words, snippet, accepted, "
            "created_at, alts FROM candidates WHERE snapshot_id=?"
        ),
        (sid,),
    )
    cand_rows = cur.fetchall()
    cand_cols = [
        "id",
        "selector",
        "field",
        "score",
        "words",
        "snippet",
        "accepted",
        "created_at",
        "alts",
    ]
    rec["candidates"] = []
    for r in cand_rows:
        obj = dict(zip(cand_cols, r, strict=False))
        # attempt to parse alts JSON
        if obj.get("alts"):
            try:
                obj["alts"] = json.loads(obj["alts"])
            except Exception:
                # leave raw string if parsing fails
                pass
        rec["candidates"].append(obj)
    # parse parsed_fields JSON
    if rec.get("parsed_fields"):
        try:
            rec["parsed_fields"] = json.loads(rec["parsed_fields"])
        except Exception:
            rec["parsed_fields"] = None
    conn.close()
    return rec


@app.get("/api/snapshots/{sid}/html")
def get_snapshot_html(sid: str):
    """Return the saved raw HTML for a snapshot if present."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT path FROM snapshots WHERE id=?", (sid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="snapshot not found")
    path = row[0]
    try:
        content = Path(path).read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    except Exception:
        # failed to read the snapshot file from disk
        raise HTTPException(status_code=500, detail="failed to read snapshot html")


@app.post("/api/snapshots/{sid}/candidates")
def post_candidates(sid: str, payload: list[CandidateIn]):
    init_snapshot_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    inserted = []
    for c in payload:
        cid = str(uuid.uuid4())
        # prepare alts as JSON if present
        alts_json = None
        try:
            if getattr(c, "alts", None) is not None:
                alts_json = json.dumps(c.alts)
        except Exception:
            alts_json = None
        cur.execute(
            (
                "INSERT INTO candidates (id, snapshot_id, selector, field, "
                "score, words, snippet, alts, accepted, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                cid,
                sid,
                c.selector,
                getattr(c, "field", None),
                c.score,
                c.words,
                getattr(c, "snippet", None),
                alts_json,
                0,
                now,
            ),
        )
        inserted.append(cid)
    conn.commit()
    conn.close()
    return {"inserted": inserted}


@app.get("/api/domain_issues")
def get_domain_issues():
    """Aggregate issues by host for the domain reports UI."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    out = {}
    # Find hosts that have non-accepted candidates (flagged issues)
    # Exclude snapshots that have been reviewed (snapshots.reviewed_at IS NOT NULL)
    cur.execute(

            "SELECT DISTINCT snapshots.host FROM candidates "
            "JOIN snapshots ON candidates.snapshot_id=snapshots.id "
            "WHERE candidates.accepted=0 AND (snapshots.reviewed_at IS NULL OR snapshots.reviewed_at='')"

    )
    host_rows = cur.fetchall()
    for (host,) in host_rows:
        # aggregate candidate counts by field for this host (only non-accepted)
        cur.execute(
            (
                "SELECT candidates.field, COUNT(*) "
                "FROM candidates JOIN snapshots ON candidates.snapshot_id=snapshots.id "
                "WHERE snapshots.host=? AND candidates.accepted=0 AND (snapshots.reviewed_at IS NULL OR snapshots.reviewed_at='') GROUP BY candidates.field"
            ),
            (host,),
        )
        cand_rows = cur.fetchall()
        issues = {(f if f is not None else "unknown"): c for f, c in cand_rows}
        # count distinct snapshots (urls) for host that are not reviewed
        cur.execute(
            "SELECT COUNT(DISTINCT id) FROM snapshots WHERE host=? AND (reviewed_at IS NULL OR reviewed_at='')",
            (host,),
        )
        total_urls = cur.fetchone()[0]
        out[host] = {"issues": issues, "total_urls": total_urls}
    conn.close()
    return out


@app.get("/api/domain_feedback")
def list_domain_feedback():
    """Return all saved domain feedback rows as a mapping keyed by host."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # make handler tolerant to schema changes: older schema had priority/needs_dev/assigned_to
    cur.execute("PRAGMA table_info(domain_feedback)")
    cols = [r[1] for r in cur.fetchall()]
    out = {}
    if "priority" in cols:
        cur.execute(
            "SELECT host, priority, needs_dev, assigned_to, notes, updated_at FROM domain_feedback"
        )
        rows = cur.fetchall()
        for host, priority, needs_dev, assigned_to, notes, updated_at in rows:
            out[host] = {
                "priority": priority,
                "needs_dev": bool(needs_dev),
                "assigned_to": assigned_to,
                "notes": notes,
                "updated_at": updated_at,
            }
    else:
        # new compact schema: host, notes, updated_at
        cur.execute("SELECT host, notes, updated_at FROM domain_feedback")
        rows = cur.fetchall()
        for host, notes, updated_at in rows:
            out[host] = {
                "notes": notes,
                "updated_at": updated_at,
            }
    conn.close()
    return out


@app.get("/api/crawl_errors")
def list_crawl_errors():
    """Return snapshots that failed to fetch or parse, grouped by host and failure reason.
    Aggregates unique failure reasons per host with a sample URL and count.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    out = {}
    # Select snapshots that have a non-empty failure_reason
    cur.execute(
        "SELECT host, failure_reason, url, created_at FROM snapshots WHERE failure_reason IS NOT NULL AND failure_reason!='' ORDER BY created_at DESC"
    )
    rows = cur.fetchall()
    for host, reason, url, created_at in rows:
        if host not in out:
            out[host] = {"errors": {}, "total": 0}
        # normalize reason string
        r = reason.strip() if reason else "unknown"
        grp = out[host]["errors"].get(
            r, {"count": 0, "example_url": url, "last_seen": created_at}
        )
        grp["count"] = grp.get("count", 0) + 1
        # keep the earliest example (rows are ordered by created_at desc so preserve first seen)
        if not grp.get("example_url"):
            grp["example_url"] = url
        # update last_seen to most recent
        grp["last_seen"] = max(grp.get("last_seen") or "", created_at or "")
        out[host]["errors"][r] = grp
        out[host]["total"] += 1
    conn.close()
    return out


@app.get("/api/telemetry/queue")
def telemetry_queue():
    """Return basic telemetry about the snapshot write queue for monitoring.
    Fields:
      - queue_size: current number of items waiting to be written
      - worker_alive: whether the background writer thread is alive
    """
    try:
        qsize = snapshots_queue.qsize()
    except Exception:
        qsize = None
    try:
        alive = _worker_thread.is_alive() if _worker_thread is not None else False
    except Exception:
        alive = False
    return {"queue_size": qsize, "worker_alive": bool(alive)}


@app.post("/api/domain_feedback/{host}")
def post_domain_feedback(host: str, payload: dict):
    """Upsert feedback for a host. Expects JSON with priority, needs_dev, assigned_to, notes."""
    init_db()
    now = datetime.datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Be tolerant to schema: if old columns exist, write them; otherwise write compact row
    cur.execute("PRAGMA table_info(domain_feedback)")
    cols = [r[1] for r in cur.fetchall()]
    if "priority" in cols:
        cur.execute(
            "INSERT OR REPLACE INTO domain_feedback (host, priority, needs_dev, assigned_to, notes, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                host,
                payload.get("priority"),
                1 if payload.get("needs_dev") else 0,
                payload.get("assigned_to"),
                payload.get("notes"),
                now,
            ),
        )
    else:
        cur.execute(
            "INSERT OR REPLACE INTO domain_feedback (host, notes, updated_at) VALUES (?, ?, ?)",
            (host, payload.get("notes"), now),
        )
    conn.commit()
    conn.close()
    return {"status": "ok", "host": host}


@app.post("/api/migrate_domain_feedback")
def migrate_domain_feedback(dry_run: bool | None = True):
    """Migrate existing domain_feedback columns (priority, needs_dev, assigned_to)
    into an audit table and recreate the `domain_feedback` table with only
    (host, notes, updated_at). This endpoint is idempotent and safe to run
    multiple times. By default it performs a dry-run; pass `?dry_run=false`
    to execute the migration.
    Returns a summary of actions performed.
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # check if domain_feedback exists
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='domain_feedback'"
    )
    if not cur.fetchone():
        conn.close()
        return {"status": "noop", "reason": "domain_feedback table not found"}
    # inspect columns
    cur.execute("PRAGMA table_info(domain_feedback)")
    cols = [r[1] for r in cur.fetchall()]
    # if old columns not present, nothing to do
    old_cols = {"priority", "needs_dev", "assigned_to"}
    if not (old_cols & set(cols)):
        conn.close()
        return {
            "status": "noop",
            "reason": "migration already applied or columns absent",
        }

    # count rows to be migrated
    cur.execute("SELECT COUNT(*) FROM domain_feedback")
    total_rows = cur.fetchone()[0]

    if dry_run:
        conn.close()
        return {"status": "dry_run", "rows_found": total_rows, "columns": cols}

    now = datetime.datetime.utcnow().isoformat()
    # create audit table if missing
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS domain_feedback_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
    # Ensure existing databases get the new column if missing (safe ALTER)
    try:
        cur.execute("PRAGMA table_info(snapshots)")
        cols = [r[1] for r in cur.fetchall()]
        if 'reviewed_at' not in cols:
            cur.execute('ALTER TABLE snapshots ADD COLUMN reviewed_at TEXT')
            conn.commit()
    except Exception:
        # If ALTER fails (old SQLite versions or locked db), ignore; presence check in queries will handle it
        pass
            host TEXT,
            priority TEXT,
            needs_dev INTEGER,
            assigned_to TEXT,
            notes TEXT,
            migrated_at TEXT
        )
        """
    )
    # copy existing rows into audit
    cur.execute(
        "INSERT INTO domain_feedback_audit (host, priority, needs_dev, assigned_to, notes, migrated_at) SELECT host, priority, needs_dev, assigned_to, notes, ? FROM domain_feedback",
        (now,),
    )
    # create new compact domain_feedback table
    cur.execute(
        """
        CREATE TABLE domain_feedback_new (
            host TEXT PRIMARY KEY,
            notes TEXT,
            updated_at TEXT
        )
        """
    )
    # copy host, notes, updated_at into new table
    cur.execute(
        "INSERT INTO domain_feedback_new (host, notes, updated_at) SELECT host, notes, updated_at FROM domain_feedback"
    )
    # drop old table and rename new table
    cur.execute("DROP TABLE domain_feedback")
    cur.execute("ALTER TABLE domain_feedback_new RENAME TO domain_feedback")
    conn.commit()

    # return summary counts
    cur.execute("SELECT COUNT(*) FROM domain_feedback")
    new_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM domain_feedback_audit")
    audit_count = cur.fetchone()[0]
    conn.close()
    return {"status": "ok", "migrated_rows": new_count, "audit_rows": audit_count}


@app.get("/api/snapshots_by_host/{host}")
def snapshots_by_host(host: str, include_reviewed: bool = False):
    """Return a short listing of snapshots for a host (id, url, status, parsed_fields, model_confidence).
    By default exclude snapshots that have been marked reviewed (reviewed_at is non-empty). Set include_reviewed=true to show all.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if include_reviewed:
        cur.execute(
            (
                "SELECT id, url, path, pipeline_run_id, failure_reason, parsed_fields, model_confidence, status, created_at "
                "FROM snapshots WHERE host=? ORDER BY created_at DESC"
            ),
            (host,),
        )
    else:
        cur.execute(
            (
                "SELECT id, url, path, pipeline_run_id, failure_reason, parsed_fields, model_confidence, status, created_at "
                "FROM snapshots WHERE host=? AND (reviewed_at IS NULL OR reviewed_at='') ORDER BY created_at DESC"
            ),
            (host,),
        )
    rows = cur.fetchall()
    cols = [
        "id",
        "url",
        "path",
        "pipeline_run_id",
        "failure_reason",
        "parsed_fields",
        "model_confidence",
        "status",
        "created_at",
    ]
    out = []
    for r in rows:
        rec = dict(zip(cols, r, strict=False))
        if rec.get("parsed_fields"):
            try:
                rec["parsed_fields"] = json.loads(rec["parsed_fields"])
            except Exception:
                rec["parsed_fields"] = None
        out.append(rec)
    conn.close()
    return out


@app.get("/api/ui_overview")
def ui_overview():
    """Return simple aggregated counts for dashboard UI.
    - total_articles: number of rows in processed CSV
    - wire_count: rows where wire==1
    - candidate_issues: count of non-accepted candidates
    - dedupe_near_misses: dedupe_audit rows with dedupe_flag=0 but similarity > 0.7
    """
    res = {
        "total_articles": 0,
        "wire_count": 0,
        "candidate_issues": 0,
        "dedupe_near_misses": 0,
    }
    # total and wire count from CSV
    try:
        if ARTICLES_CSV.exists():
            df = pd.read_csv(ARTICLES_CSV)
            res["total_articles"] = len(df)
            if "wire" in df.columns:
                # coerce wire truthy values (1, "1", or truthy booleans)
                res["wire_count"] = int(
                    ((df["wire"] == 1) | (df["wire"] == "1") | df["wire"]).sum()
                )
    except Exception:
        pass

    # candidate issues from DB (non-accepted)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM candidates WHERE accepted=0")
        r = cur.fetchone()
        if r:
            res["candidate_issues"] = int(r[0])
        # dedupe near-misses: dedupe_audit rows where dedupe_flag is 0 and similarity > 0.7
        try:
            cur.execute(
                "SELECT COUNT(*) FROM dedupe_audit WHERE (dedupe_flag IS NULL OR dedupe_flag=0) AND similarity>?",
                (0.7,),
            )
            rr = cur.fetchone()
            if rr:
                res["dedupe_near_misses"] = int(rr[0])
        except Exception:
            # if dedupe_audit missing or column types differ, ignore
            pass
        conn.close()
    except Exception:
        pass

    return res


@app.post("/api/dedupe_records")
def post_dedupe_records(payload: list[dict]):
    """Insert one or more dedupe audit records.
    Each record may contain: article_uid, neighbor_uid, host, similarity,
    dedupe_flag (0/1), category (int), stage (str), details (dict or str).
    Returns inserted count and sample ids.
    """
    init_snapshot_tables()
    if not isinstance(payload, list):
        records = [payload]
    else:
        records = payload
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    inserted = 0
    samples = []
    for r in records:
        try:
            cur.execute(
                "INSERT INTO dedupe_audit (article_uid, neighbor_uid, host, similarity, dedupe_flag, category, stage, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r.get("article_uid"),
                    r.get("neighbor_uid"),
                    r.get("host"),
                    r.get("similarity"),
                    (
                        int(r.get("dedupe_flag"))
                        if r.get("dedupe_flag") is not None
                        else None
                    ),
                    int(r.get("category")) if r.get("category") is not None else None,
                    r.get("stage"),
                    (
                        json.dumps(r.get("details"))
                        if r.get("details") is not None
                        else None
                    ),
                    now,
                ),
            )
            inserted += 1
            samples.append(cur.lastrowid)
        except Exception:
            # skip problematic rows but continue
            continue
    conn.commit()
    conn.close()
    return {"inserted": inserted, "sample_ids": samples}


@app.get("/api/dedupe_records")
def get_dedupe_records(
    article_uid: str | None = None,
    host: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Query dedupe audit rows filtered by article_uid or host. Returns rows ordered by created_at desc."""
    if not DB_PATH.exists():
        return {"count": 0, "results": []}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    base_sql = "SELECT id, article_uid, neighbor_uid, host, similarity, dedupe_flag, category, stage, details, created_at FROM dedupe_audit"
    params = []
    where = []
    if article_uid:
        where.append("article_uid=?")
        params.append(article_uid)
    if host:
        where.append("host=?")
        params.append(host)
    if where:
        base_sql = base_sql + " WHERE " + " AND ".join(where)
    base_sql = base_sql + " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(base_sql, tuple(params))
    rows = cur.fetchall()
    conn.close()
    cols = [
        "id",
        "article_uid",
        "neighbor_uid",
        "host",
        "similarity",
        "dedupe_flag",
        "category",
        "stage",
        "details",
        "created_at",
    ]
    out = []
    for r in rows:
        d = dict(zip(cols, r, strict=False))
        # attempt to parse details JSON
        if d.get("details"):
            try:
                d["details"] = json.loads(d["details"])
            except Exception:
                pass
        out.append(d)
    return {"count": len(out), "results": out}


@app.post("/api/import_dupes_csv")
def import_dupes_csv(payload: dict, dry_run: bool | None = True):
    """Import dedupe flags from a processed CSV into dedupe_audit.
    Payload: {csv_path: str} where csv_path is relative to processed/ directory.
    If dry_run=True, returns counts without inserting.
    """
    csv_rel = payload.get("csv_path") or "dupesflagged_6.csv"
    csv_path = BASE_DIR / "processed" / csv_rel
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="csv not found")
    import csv as _csv

    total = 0
    dup_counts = {"0": 0, "1": 0}
    sample_rows = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = _csv.DictReader(fh)
        for row in reader:
            total += 1
            dup = row.get("duplicate")
            if dup is None:
                dup_flag = None
            else:
                try:
                    dup_flag = int(dup)
                except Exception:
                    dup_flag = None
            if dup_flag is not None:
                dup_counts[str(dup_flag)] = dup_counts.get(str(dup_flag), 0) + 1
            # collect a few sample rows for reporting
            if len(sample_rows) < 5:
                sample_rows.append(
                    {
                        "id": row.get("id"),
                        "url": row.get("url"),
                        "duplicate": dup_flag,
                        "hostname": row.get("hostname"),
                        "title": row.get("title"),
                    }
                )
            # if not dry_run, insert into dedupe_audit table
            if not dry_run:
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                now = datetime.datetime.utcnow().isoformat()
                try:
                    cur.execute(
                        "INSERT INTO dedupe_audit (article_uid, neighbor_uid, host, similarity, dedupe_flag, category, stage, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row.get("id"),
                            None,
                            row.get("hostname"),
                            None,
                            dup_flag,
                            None,
                            "imported_csv",
                            json.dumps(
                                {"url": row.get("url"), "title": row.get("title")}
                            ),
                            now,
                        ),
                    )
                except Exception:
                    pass
                conn.commit()
                conn.close()
    summary = {"rows_seen": total, "dup_counts": dup_counts, "samples": sample_rows}
    if dry_run:
        return {"status": "dry_run", **summary}
    return {"status": "ok", **summary}


@app.post("/api/candidates/{cid}/accept")
def accept_candidate(cid: str, payload: dict | None = None):
    """Mark a candidate as accepted (accepted=1) or rejected (accepted=0).
    Payload optional: {"accepted": true|false}
    """
    val = 1
    if payload is not None:
        val = 1 if payload.get("accepted", True) else 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE candidates SET accepted=? WHERE id=?", (val, cid))
    conn.commit()
    conn.close()
    return {"status": "ok", "id": cid, "accepted": bool(val)}


@app.post("/api/reextract_jobs")
def create_reextract_job(payload: dict):
    """Create a re-extract job for a host. Payload: {host: str}
    Returns: {job_id}
    """
    host = payload.get("host")
    if not host:
        raise HTTPException(status_code=400, detail="host required")
    import time
    import uuid

    job_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reextract_jobs (id, host, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (job_id, host, "pending", now, now),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "job_id": job_id}


@app.get("/api/reextract_jobs/{job_id}")
def get_reextract_job(job_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, host, status, result_json, created_at, updated_at FROM reextract_jobs WHERE id=?",
        (job_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    import json

    return {
        "id": row[0],
        "host": row[1],
        "status": row[2],
        "result": json.loads(row[3]) if row[3] else None,
        "created_at": row[4],
        "updated_at": row[5],
    }


@app.post("/api/site_rules/commit")
def commit_site_rule(payload: dict):
    """Commit an accepted selector into lookups/site_rules.csv.
    Expects payload: {host: str, field: str, selector: str, source: Optional[str]}
    This will upsert the CSV row for the host, putting the selector into an appropriate column
    (author_selector, content_selector, tags_selector, date_selector, etc.) by field name.
    If the host row doesn't exist, append a new row with minimal columns filled.
    Returns the row written.
    """
    host = payload.get("host")
    field = payload.get("field")
    selector = payload.get("selector")
    if not host or not selector:
        raise HTTPException(status_code=400, detail="host and selector required")
    # map field names to CSV columns
    col_map = {
        "author": "author_selector",
        "body": "content_selector",
        "content": "content_selector",
        "tags": "tags_selector",
        "date": "date_selector",
        "article": "article_selector",
    }
    col = col_map.get(field, "content_selector")
    csv_path = BASE_DIR / "lookups" / "site_rules.csv"
    # read existing CSV
    import csv

    rows = []
    found = False
    header = None
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames
            for r in reader:
                if r.get("hostname") == host:
                    # update column, append selector if non-empty
                    existing = r.get(col) or ""
                    parts = [p for p in existing.split("|") if p]
                    if selector not in parts:
                        parts.append(selector)
                    r[col] = "|".join(parts)
                    found = True
                rows.append(r)
    # if not found, append new minimal row
    if not found:
        if header is None:
            header = [
                "hostname",
                "skip_patterns",
                "content_selector",
                "article_selector",
                "date_selector",
                "extract_method",
                "preferred_method",
                "tags_selector",
                "author_selector",
                "snapshot_example",
                "notes",
            ]
        new = dict.fromkeys(header, "")
        new["hostname"] = host
        new[col] = selector
        rows.append(new)
    # write back CSV atomically
    tmp_path = csv_path.with_suffix(".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    tmp_path.replace(csv_path)
    # enqueue a re-extraction job so the frontend can trigger and poll progress
    import time
    import uuid

    job_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reextract_jobs (id, host, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (job_id, host, "pending", now, now),
    )
    # mark snapshots as reviewed: prefer explicit snapshot_id, otherwise
    # mark ALL snapshots for the host as reviewed so the host is removed
    # from the domain issues list immediately (frontend has committed a
    # canonical selector and re-extract is enqueued).
    snapshot_id = payload.get("snapshot_id")
    try:
        if snapshot_id:
            cur.execute(
                "UPDATE snapshots SET reviewed_at=? WHERE id=?",
                (now, snapshot_id),
            )
        else:
            # mark all remaining snapshots for this host as reviewed
            cur.execute(
                "UPDATE snapshots SET reviewed_at=? WHERE host=?",
                (now, host),
            )
    except Exception:
        # don't fail the commit if marking reviewed fails
        pass

    conn.commit()
    conn.close()
    return {
        "status": "ok",
        "host": host,
        "column": col,
        "selector": selector,
        "job_id": job_id,
    }


# Gazetteer Telemetry API Endpoints

@app.get("/api/gazetteer/stats")
def get_gazetteer_telemetry_stats():
    """Get overall gazetteer telemetry statistics."""
    try:
        stats = get_gazetteer_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gazetteer/publishers")
def get_gazetteer_publishers():
    """Get per-publisher gazetteer telemetry breakdown."""
    try:
        publishers = get_publisher_telemetry()
        return publishers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gazetteer/failed")
def get_gazetteer_failed_publishers():
    """Get publishers with gazetteer failures."""
    try:
        failed_publishers = get_failed_publishers()
        return failed_publishers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/gazetteer/update_address")
def update_gazetteer_address(request: AddressEditRequest):
    """Update address information for a publisher."""
    try:
        success = update_publisher_address(request.source_id, request)
        if success:
            return {
                "status": "success",
                "message": "Address updated successfully"
            }
        else:
            raise HTTPException(status_code=404, detail="Publisher not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/gazetteer/reprocess")
def reprocess_gazetteer_sources(request: ReprocessRequest):
    """Trigger gazetteer re-processing for specific sources."""
    try:
        result = trigger_gazetteer_reprocess(
            request.source_ids, request.force_reprocess
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Telemetry API endpoints for React dashboard
@app.get("/api/telemetry/http-errors")
def get_http_errors(
    days: int = 7,
    host: str | None = None,
    status_code: int | None = None
):
    """Get HTTP error statistics for dashboard monitoring."""
    try:
        ComprehensiveExtractionTelemetry(str(MAIN_DB_PATH))

        # Build WHERE conditions based on parameters
        conditions = []
        params = []

        if days:
            conditions.append(
                f"last_seen >= datetime('now', '-{days} days')"
            )

        if host:
            conditions.append("host = ?")
            params.append(host)

        if status_code:
            conditions.append("status_code = ?")
            params.append(status_code)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        # Get error counts by status code and host
        query = f"""
        SELECT
            host,
            status_code,
            SUM(count) as error_count,
            MAX(last_seen) as last_seen
        FROM http_error_summary
        WHERE {where_clause}
        GROUP BY host, status_code
        ORDER BY error_count DESC
        """

        cur.execute(query, params)
        rows = cur.fetchall()

        results = []
        for row in rows:
            results.append({
                "host": row[0],
                "status_code": row[1],
                "error_count": row[2],
                "last_seen": row[3]
            })

        conn.close()
        return {"http_errors": results}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching HTTP errors: {str(e)}",
        )


@app.get("/api/telemetry/method-performance")
def get_method_performance(
    days: int = 7,
    method: str | None = None,
    host: str | None = None
):
    """Get extraction method performance statistics."""
    try:
        ComprehensiveExtractionTelemetry(str(MAIN_DB_PATH))

        # Build WHERE conditions
        conditions = []
        params = []

        if days:
            conditions.append(
                f"created_at >= datetime('now', '-{days} days')"
            )

        if method:
            conditions.append("method = ?")
            params.append(method)

        if host:
            conditions.append("host = ?")
            params.append(host)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        # Get method performance stats
        query = f"""
        SELECT
            COALESCE(successful_method, 'failed') as method,
            host,
            COUNT(*) as total_attempts,
            SUM(
                CASE WHEN is_success = 1 THEN 1 ELSE 0 END
            ) as successful_attempts,
            AVG(total_duration_ms) as avg_duration,
            MIN(total_duration_ms) as min_duration,
            MAX(total_duration_ms) as max_duration
        FROM extraction_telemetry_v2
        WHERE {where_clause}
        GROUP BY COALESCE(successful_method, 'failed'), host
        ORDER BY total_attempts DESC
        """

        cur.execute(query, params)
        rows = cur.fetchall()

        results = []
        for row in rows:
            success_rate = (row[3] / row[2] * 100) if row[2] > 0 else 0
            results.append({
                "method": row[0],
                "host": row[1],
                "total_attempts": row[2],
                "successful_attempts": row[3],
                "success_rate": round(success_rate, 2),
                "avg_duration": round(row[4], 2) if row[4] else 0,
                "min_duration": round(row[5], 2) if row[5] else 0,
                "max_duration": round(row[6], 2) if row[6] else 0
            })

        conn.close()
        return {"method_performance": results}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching method performance: {str(e)}",
        )


@app.get("/api/telemetry/publisher-stats")
def get_publisher_stats(
    days: int = 7,
    host: str | None = None,
    min_attempts: int = 5
):
    """Get publisher performance statistics."""
    try:
        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        # Build WHERE conditions
        conditions = []
        params = []

        if days:
            conditions.append(
                f"created_at >= datetime('now', '-{days} days')"
            )

        if host:
            conditions.append("host = ?")
            params.append(host)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Get comprehensive publisher stats
        query = f"""
        SELECT
            host,
            COUNT(*) as total_extractions,
            SUM(
                CASE WHEN is_success = 1 THEN 1 ELSE 0 END
            ) as successful_extractions,
            AVG(total_duration_ms) as avg_duration,
            COUNT(
                DISTINCT COALESCE(successful_method, 'failed')
            ) as methods_used,
            MAX(created_at) as last_attempt
        FROM extraction_telemetry_v2
        WHERE {where_clause}
        GROUP BY host
        HAVING COUNT(*) >= ?
        ORDER BY total_extractions DESC
        """

        params.append(min_attempts)
        cur.execute(query, params)
        rows = cur.fetchall()

        results = []
        for row in rows:
            success_rate = (row[2] / row[1] * 100) if row[1] > 0 else 0
            if success_rate < 50:
                status = "poor"
            elif success_rate > 80:
                status = "good"
            else:
                status = "fair"

            results.append({
                "host": row[0],
                "total_extractions": row[1],
                "successful_extractions": row[2],
                "success_rate": round(success_rate, 2),
                "avg_duration": round(row[3], 2) if row[3] else 0,
                "methods_used": row[4],
                "last_attempt": row[5],
                "status": status,
            })

        conn.close()
        return {"publisher_stats": results}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching publisher stats: {str(e)}",
        )


@app.get("/api/telemetry/field-extraction")
def get_field_extraction_stats(
    days: int = 7,
    field: str | None = None,
    method: str | None = None,
    host: str | None = None
):
    """Get field-level extraction statistics."""
    try:
        telemetry = ComprehensiveExtractionTelemetry(str(MAIN_DB_PATH))
        stats = telemetry.get_field_extraction_stats(
            publisher=host,
            method=method,
        )

        if field:
            filtered = []
            for entry in stats:
                counts = {
                    "title": entry.get("title_success", 0),
                    "author": entry.get("author_success", 0),
                    "content": entry.get("content_success", 0),
                    "publish_date": entry.get("date_success", 0),
                }
                if counts.get(field):
                    filtered.append(entry)
            stats = filtered
        return {"field_extraction_stats": stats}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching field extraction stats: {str(e)}",
        )


@app.get("/api/telemetry/poor-performers")
def get_poor_performing_sites(
    days: int = 7,
    min_attempts: int = 10,
    max_success_rate: float = 50.0
):
    """Get sites with poor performance that may need attention."""
    try:
        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        # Find sites with low success rates
        query = f"""
        SELECT
            host,
            COUNT(*) as total_attempts,
            SUM(
                CASE WHEN is_success = 1 THEN 1 ELSE 0 END
            ) as successful_attempts,
            (
                SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) * 100.0
                / COUNT(*)
            ) as success_rate,
            AVG(total_duration_ms) as avg_duration,
            MAX(created_at) as last_attempt,
            COUNT(
                DISTINCT COALESCE(successful_method, 'failed')
            ) as methods_tried
        FROM extraction_telemetry_v2
        WHERE created_at >= datetime('now', '-{days} days')
        GROUP BY host
        HAVING COUNT(*) >= ? AND success_rate <= ?
        ORDER BY success_rate ASC, total_attempts DESC
        """

        cur.execute(query, [min_attempts, max_success_rate])
        rows = cur.fetchall()

        results = []
        for row in rows:
            results.append({
                "host": row[0],
                "total_attempts": row[1],
                "successful_attempts": row[2],
                "success_rate": round(row[3], 2),
                "avg_duration": round(row[4], 2) if row[4] else 0,
                "last_attempt": row[5],
                "methods_tried": row[6],
                "recommendation": "pause" if row[3] < 25 else "monitor"
            })

        conn.close()
        return {"poor_performers": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching poor performers: {str(e)}")


@app.get("/api/telemetry/summary")
def get_telemetry_summary(days: int = 7):
    """Get overall telemetry summary for dashboard overview."""
    try:
        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        # Overall extraction stats
        cur.execute(f"""
        SELECT 
            COUNT(*) as total_extractions,
            SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) as successful_extractions,
            COUNT(DISTINCT host) as unique_hosts,
            COUNT(DISTINCT COALESCE(successful_method, 'failed')) as methods_used,
            AVG(total_duration_ms) as avg_duration
        FROM extraction_telemetry_v2 
        WHERE created_at >= datetime('now', '-{days} days')
        """)

        overall = cur.fetchone()
        success_rate = (overall[1] / overall[0] * 100) if overall[0] > 0 else 0

        # Method breakdown
        cur.execute(f"""
        SELECT 
            COALESCE(successful_method, 'failed') as method,
            COUNT(*) as count,
            SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) as successful
        FROM extraction_telemetry_v2 
        WHERE created_at >= datetime('now', '-{days} days')
        GROUP BY COALESCE(successful_method, 'failed')
        ORDER BY count DESC
        """)

        method_stats = []
        for row in cur.fetchall():
            method_success_rate = (row[2] / row[1] * 100) if row[1] > 0 else 0
            method_stats.append({
                "method": row[0],
                "attempts": row[1],
                "successful": row[2],
                "success_rate": round(method_success_rate, 2)
            })

        # HTTP error counts
        cur.execute(f"""
        SELECT
            status_code,
            SUM(count) as count
        FROM http_error_summary
        WHERE last_seen >= datetime('now', '-{days} days')
        GROUP BY status_code
        ORDER BY count DESC
        LIMIT 10
        """)

        http_errors = [{"status_code": row[0], "count": row[1]} for row in cur.fetchall()]

        conn.close()

        return {
            "summary": {
                "total_extractions": overall[0],
                "successful_extractions": overall[1],
                "success_rate": round(success_rate, 2),
                "unique_hosts": overall[2],
                "methods_used": overall[3],
                "avg_duration": round(overall[4], 2) if overall[4] else 0,
                "method_breakdown": method_stats,
                "top_http_errors": http_errors
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching telemetry summary: {str(e)}")


# Site Management API endpoints
class SiteManagementRequest(BaseModel):
    host: str
    reason: str | None = None


@app.post("/api/site-management/pause")
def pause_site(request: SiteManagementRequest):
    """Pause a site from further crawling due to poor performance."""
    try:
        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        # Add status column if it doesn't exist
        try:
            cur.execute("ALTER TABLE sources ADD COLUMN status VARCHAR DEFAULT 'active'")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        # Add paused_at and paused_reason columns if they don't exist
        try:
            cur.execute("ALTER TABLE sources ADD COLUMN paused_at TIMESTAMP")
            cur.execute("ALTER TABLE sources ADD COLUMN paused_reason TEXT")
        except sqlite3.OperationalError:
            # Columns already exist
            pass

        # Update the source status
        cur.execute("""
        UPDATE sources 
        SET status = 'paused', 
            paused_at = datetime('now'), 
            paused_reason = ?
        WHERE host = ?
        """, [request.reason or "Poor performance detected", request.host])

        if cur.rowcount == 0:
            # Source doesn't exist, create it
            cur.execute("""
            INSERT INTO sources (id, host, host_norm, status, paused_at, paused_reason)
            VALUES (?, ?, ?, 'paused', datetime('now'), ?)
            """, [request.host, request.host, request.host.lower(),
                  request.reason or "Poor performance detected"])

        conn.commit()
        conn.close()

        return {
            "status": "success",
            "message": f"Site {request.host} has been paused",
            "paused_at": "now",
            "reason": request.reason or "Poor performance detected"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error pausing site: {str(e)}")


@app.post("/api/site-management/resume")
def resume_site(request: SiteManagementRequest):
    """Resume a previously paused site."""
    try:
        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        # Update the source status
        cur.execute("""
        UPDATE sources 
        SET status = 'active', 
            paused_at = NULL, 
            paused_reason = NULL
        WHERE host = ?
        """, [request.host])

        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Site {request.host} not found")

        conn.commit()
        conn.close()

        return {
            "status": "success",
            "message": f"Site {request.host} has been resumed"
        }

    except HTTPException as exc:
        raise exc
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error resuming site: {str(e)}",
        )


@app.get("/api/site-management/paused")
def get_paused_sites():
    """Get list of currently paused sites."""
    try:
        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        cur.execute("""
        SELECT host, paused_at, paused_reason
        FROM sources
        WHERE status = 'paused'
        ORDER BY paused_at DESC
        """)

        paused_sites = []
        for row in cur.fetchall():
            paused_sites.append({
                "host": row[0],
                "paused_at": row[1],
                "reason": row[2]
            })

        conn.close()
        return {"paused_sites": paused_sites}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching paused sites: {str(e)}")


@app.get("/api/site-management/status/{host}")
def get_site_status(host: str):
    """Get the current status of a specific site."""
    try:
        conn = sqlite3.connect(str(MAIN_DB_PATH))
        cur = conn.cursor()

        cur.execute("""
        SELECT status, paused_at, paused_reason
        FROM sources
        WHERE host = ?
        """, [host])

        result = cur.fetchone()
        conn.close()

        if result:
            return {
                "host": host,
                "status": result[0] or "active",
                "paused_at": result[1],
                "paused_reason": result[2]
            }
        else:
            return {
                "host": host,
                "status": "active",
                "paused_at": None,
                "paused_reason": None
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching site status: {str(e)}")
