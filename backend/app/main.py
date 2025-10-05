import datetime
import json
import logging
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

logger = logging.getLogger(__name__)

# Add gazetteer telemetry imports
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))
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

# Add Cloud SQL imports for migration
from src.models.database import DatabaseManager  # noqa: E402
from src.models.api_backend import (  # noqa: E402
    Review,
    DomainFeedback,
    Snapshot,
    Candidate,
    ReextractionJob,
    DedupeAudit,
)
from src.models.telemetry import (  # noqa: E402
    ExtractionTelemetryV2,
    HttpErrorSummary,
)
from src.models import Source  # noqa: E402
from sqlalchemy import func, case, desc, and_, or_  # noqa: E402
from backend.app.telemetry import verification, byline, code_review  # noqa: E402

# pydantic.Field not used here

BASE_DIR = Path(__file__).resolve().parents[2]
# point to the full processed CSV with labels and geo
ARTICLES_CSV = BASE_DIR / "processed" / "articleslabelledgeo_8.csv"
DB_PATH = BASE_DIR / "backend" / "reviews.db"

app = FastAPI(title="MizzouNewsCrawler Reviewer API")

# Initialize database connection using DatabaseManager
# This will use Cloud SQL connector if USE_CLOUD_SQL_CONNECTOR=true
from src import config as app_config
db_manager = DatabaseManager(app_config.DATABASE_URL)
logger.info(f"Database initialized: {app_config.DATABASE_URL[:50]}...")

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
    """Database initialization - now handled by Alembic migrations.
    
    This function has been converted to a no-op as part of the Cloud SQL migration.
    Database schema is now managed by Alembic migrations (see alembic/versions/).
    Tables are created automatically when DatabaseManager is first used.
    """
    # No-op: Schema creation handled by Alembic
    pass


def init_snapshot_tables():
    """Snapshot tables initialization - now handled by Alembic migrations.
    
    This function has been converted to a no-op as part of the Cloud SQL migration.
    Database schema is now managed by Alembic migrations (see alembic/versions/).
    Tables (snapshots, candidates, reextract_jobs, dedupe_audit) are created
    automatically when DatabaseManager is first used.
    """
    # No-op: Schema creation handled by Alembic
    pass


# In-process queue and worker to serialize DB writes so HTTP handlers return
# quickly instead of blocking on SQLite locks. This reduces client timeouts
# when many writers contend for the DB file.
snapshots_queue = pyqueue.Queue()
_worker_stop_event = threading.Event()
_worker_thread = None


def _db_writer_worker():
    """Background thread that serially writes snapshot rows to Cloud SQL.
    Each queue item is a dict with keys matching the snapshot insert.
    """
    while not _worker_stop_event.is_set():
        try:
            item = snapshots_queue.get(timeout=1.0)
        except Exception:
            # timeout, check stop flag again
            continue
        try:
            with db_manager.get_session() as session:
                snapshot = Snapshot(
                    id=item.get("id"),
                    host=item.get("host"),
                    url=item.get("url"),
                    path=item.get("path"),
                    pipeline_run_id=item.get("pipeline_run_id"),
                    failure_reason=item.get("failure_reason"),
                    parsed_fields=(
                        json.dumps(item.get("parsed_fields"))
                        if item.get("parsed_fields") is not None
                        else None
                    ),
                    model_confidence=item.get("model_confidence"),
                    status=item.get("status") or "pending",
                    created_at=item.get("created_at")
                )
                session.add(snapshot)
                session.commit()
        except Exception as exc:
            import traceback
            logger.exception("Snapshot write failed", exc_info=exc)
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
            _worker_thread.join(timeout=5.0)
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
def list_articles(limit: int = 20, offset: int = 0, reviewer: str | None = None):
    if not ARTICLES_CSV.exists():
        return {"count": 0, "results": []}
    df = pd.read_csv(ARTICLES_CSV)
    # replace infinite values and NaN with None for JSON safety
    df = df.replace([np.inf, -np.inf], None)
    df = df.where(pd.notnull(df), None)
    # If caller provided a reviewer, filter out articles
    # already reviewed by that reviewer
    if reviewer:
        try:
            with db_manager.get_session() as session:
                reviewed_rows = session.query(Review.article_idx).filter(
                    Review.reviewer == reviewer,
                    Review.reviewed_at.isnot(None)
                ).distinct().all()
                reviewed = {int(r.article_idx) for r in reviewed_rows if r.article_idx is not None}
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
        out[k] = sanitize_value(rec.get(k)) if k in rec else None
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
    now = datetime.datetime.utcnow()
    tags_str = ",".join(payload.tags) if payload.tags else None
    body_str = ",".join(payload.body_errors) if payload.body_errors else None
    headline_str = (
        ",".join(payload.headline_errors) if payload.headline_errors else None
    )
    author_str = ",".join(payload.author_errors) if payload.author_errors else None
    
    # Prefer an explicit article_uid if supplied in the payload
    article_uid = getattr(payload, "article_uid", None) or None
    # try to read the CSV to map idx -> id if available
    try:
        if ARTICLES_CSV.exists():
            df = pd.read_csv(ARTICLES_CSV)
            if 0 <= idx < len(df):
                article_uid = article_uid or df.iloc[idx].get("id")
    except Exception:
        pass
    
    with db_manager.get_session() as session:
        # Try to find existing review for upsert
        existing_review = None
        if article_uid:
            existing_review = session.query(Review).filter(
                Review.article_uid == article_uid,
                Review.reviewer == payload.reviewer
            ).first()
        if not existing_review:
            existing_review = session.query(Review).filter(
                Review.article_idx == idx,
                Review.reviewer == payload.reviewer
            ).first()
        
        if existing_review:
            # Update existing review
            existing_review.rating = payload.rating
            existing_review.secondary_rating = payload.secondary_rating
            existing_review.tags = tags_str
            existing_review.notes = payload.notes
            existing_review.mentioned_locations = (
                ",".join(payload.mentioned_locations) if payload.mentioned_locations else None
            )
            existing_review.missing_locations = (
                ",".join(payload.missing_locations) if getattr(payload, "missing_locations", None) else None
            )
            existing_review.incorrect_locations = (
                ",".join(payload.incorrect_locations) if getattr(payload, "incorrect_locations", None) else None
            )
            existing_review.inferred_tags = (
                ",".join(payload.inferred_tags) if getattr(payload, "inferred_tags", None) else None
            )
            existing_review.missing_tags = (
                ",".join(payload.missing_tags) if getattr(payload, "missing_tags", None) else None
            )
            existing_review.incorrect_tags = (
                ",".join(payload.incorrect_tags) if getattr(payload, "incorrect_tags", None) else None
            )
            existing_review.body_errors = body_str
            existing_review.headline_errors = headline_str
            existing_review.author_errors = author_str
            existing_review.reviewed_at = now
            review_obj = existing_review
        else:
            # Create new review
            review_obj = Review(
                article_idx=idx,
                article_uid=article_uid,
                reviewer=payload.reviewer,
                rating=payload.rating,
                secondary_rating=payload.secondary_rating,
                tags=tags_str,
                notes=payload.notes,
                mentioned_locations=(
                    ",".join(payload.mentioned_locations) if payload.mentioned_locations else None
                ),
                missing_locations=(
                    ",".join(payload.missing_locations) if getattr(payload, "missing_locations", None) else None
                ),
                incorrect_locations=(
                    ",".join(payload.incorrect_locations) if getattr(payload, "incorrect_locations", None) else None
                ),
                inferred_tags=(
                    ",".join(payload.inferred_tags) if getattr(payload, "inferred_tags", None) else None
                ),
                missing_tags=(
                    ",".join(payload.missing_tags) if getattr(payload, "missing_tags", None) else None
                ),
                incorrect_tags=(
                    ",".join(payload.incorrect_tags) if getattr(payload, "incorrect_tags", None) else None
                ),
                body_errors=body_str,
                headline_errors=headline_str,
                author_errors=author_str,
                reviewed_at=now,
                created_at=now
            )
            session.add(review_obj)
        
        session.commit()
        session.refresh(review_obj)
        
        # Convert to dict and split CSV fields
        result = review_obj.to_dict()
        
        # helper to split comma-separated stored strings into lists
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
        
        # Normalize CSV fields into arrays for API clients
        result["tags"] = _split_csv_field(result.get("tags"))
        result["body_errors"] = _split_csv_field(result.get("body_errors"))
        result["headline_errors"] = _split_csv_field(result.get("headline_errors"))
        result["author_errors"] = _split_csv_field(result.get("author_errors"))
        result["mentioned_locations"] = _split_csv_field(result.get("mentioned_locations"))
        result["missing_locations"] = _split_csv_field(result.get("missing_locations"))
        result["incorrect_locations"] = _split_csv_field(result.get("incorrect_locations"))
        result["inferred_tags"] = _split_csv_field(result.get("inferred_tags"))
        result["missing_tags"] = _split_csv_field(result.get("missing_tags"))
        result["incorrect_tags"] = _split_csv_field(result.get("incorrect_tags"))
        
        # Build canonical payload
        def build_canonical(r):
            if not r:
                return None
            primary = r.get("rating") if r.get("rating") is not None else r.get("rating")
            secondary = (
                r.get("secondary_rating")
                if r.get("secondary_rating") is not None
                else r.get("secondary_rating")
            )
            body = r.get("body_errors") or []
            headline = r.get("headline_errors") or []
            author = r.get("author_errors") or []
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
                    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
                except Exception:
                    return None
        
        # Attach canonical payload and hash
        try:
            result["canonical"] = build_canonical(result)
            result["canonical_hash"] = canonical_hash(result["canonical"])
        except Exception:
            pass
        
        return result


@app.put("/api/reviews/{rid}")
def update_review(rid: str, payload: ReviewIn):
    """Update an existing review by id.
    Returns 404 if the review does not exist.
    """
    with db_manager.get_session() as session:
        review = session.query(Review).filter(Review.id == rid).first()
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        
        # Update fields
        review.reviewer = payload.reviewer
        review.rating = payload.rating
        review.secondary_rating = payload.secondary_rating
        review.tags = ",".join(payload.tags) if payload.tags else None
        review.notes = payload.notes
        review.mentioned_locations = (
            ",".join(payload.mentioned_locations) if payload.mentioned_locations else None
        )
        review.missing_locations = (
            ",".join(payload.missing_locations) if getattr(payload, "missing_locations", None) else None
        )
        review.incorrect_locations = (
            ",".join(payload.incorrect_locations) if getattr(payload, "incorrect_locations", None) else None
        )
        review.inferred_tags = (
            ",".join(payload.inferred_tags) if getattr(payload, "inferred_tags", None) else None
        )
        review.missing_tags = (
            ",".join(payload.missing_tags) if getattr(payload, "missing_tags", None) else None
        )
        review.incorrect_tags = (
            ",".join(payload.incorrect_tags) if getattr(payload, "incorrect_tags", None) else None
        )
        review.body_errors = ",".join(payload.body_errors) if payload.body_errors else None
        review.headline_errors = ",".join(payload.headline_errors) if payload.headline_errors else None
        review.author_errors = ",".join(payload.author_errors) if payload.author_errors else None
        review.reviewed_at = datetime.datetime.utcnow()
        
        session.commit()
        return {"status": "ok", "id": rid}


@app.get("/api/reviews")
def get_reviews(article_idx: int | None = None, article_uid: str | None = None):
    with db_manager.get_session() as session:
        query = session.query(Review)
        
        if article_uid:
            query = query.filter(Review.article_uid == article_uid)
        elif article_idx is not None:
            query = query.filter(Review.article_idx == article_idx)
        else:
            query = query.limit(200)
        
        query = query.order_by(Review.id.desc())
        reviews = query.all()
        
        if not reviews:
            return []
        
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
        for review in reviews:
            d = review.to_dict()
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
            with db_manager.get_session() as session:
                snapshot = Snapshot(
                    id=sid,
                    host=payload.host,
                    url=payload.url,
                    path=path,
                    pipeline_run_id=payload.pipeline_run_id,
                    failure_reason=payload.failure_reason,
                    parsed_fields=(
                        json.dumps(payload.parsed_fields)
                        if payload.parsed_fields is not None
                        else None
                    ),
                    model_confidence=payload.model_confidence,
                    status="pending",
                    created_at=datetime.datetime.fromisoformat(now)
                )
                session.add(snapshot)
                session.commit()
    except Exception:
        # best-effort: if sync write fails, rely on background worker
        pass
    # Return accepted so clients can continue without waiting on DB
    return JSONResponse(
        status_code=202, content={"snapshot_id": sid, "path": path, "enqueued": True}
    )


@app.get("/api/snapshots/{sid}")
def get_snapshot(sid: str):
    with db_manager.get_session() as session:
        snapshot = session.query(Snapshot).filter(Snapshot.id == sid).first()
        if not snapshot:
            raise HTTPException(status_code=404, detail="snapshot not found")
        
        rec = snapshot.to_dict()
        
        # load candidates
        candidates = session.query(Candidate).filter(Candidate.snapshot_id == sid).all()
        rec["candidates"] = []
        for cand in candidates:
            obj = cand.to_dict()
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
        
        return rec


@app.get("/api/snapshots/{sid}/html")
def get_snapshot_html(sid: str):
    """Return the saved raw HTML for a snapshot if present."""
    with db_manager.get_session() as session:
        snapshot = session.query(Snapshot).filter(Snapshot.id == sid).first()
        if not snapshot:
            raise HTTPException(status_code=404, detail="snapshot not found")
        path = snapshot.path
        try:
            content = Path(path).read_text(encoding="utf-8")
            return HTMLResponse(content=content)
        except Exception:
            # failed to read the snapshot file from disk
            raise HTTPException(status_code=500, detail="failed to read snapshot html")


@app.post("/api/snapshots/{sid}/candidates")
def post_candidates(sid: str, payload: list[CandidateIn]):
    with db_manager.get_session() as session:
        now = datetime.datetime.utcnow()
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
            
            candidate = Candidate(
                id=cid,
                snapshot_id=sid,
                selector=c.selector,
                field=getattr(c, "field", None),
                score=c.score,
                words=c.words,
                snippet=getattr(c, "snippet", None),
                alts=alts_json,
                accepted=False,
                created_at=now
            )
            session.add(candidate)
            inserted.append(cid)
        
        session.commit()
        return {"inserted": inserted}


@app.get("/api/domain_issues")
def get_domain_issues():
    """Aggregate issues by host for the domain reports UI."""
    from sqlalchemy import func, distinct
    
    with db_manager.get_session() as session:
        out = {}
        
        # Find hosts that have non-accepted candidates (flagged issues)
        # Exclude snapshots that have been reviewed
        hosts = session.query(distinct(Snapshot.host)).join(
            Candidate, Candidate.snapshot_id == Snapshot.id
        ).filter(
            Candidate.accepted == False,
            (Snapshot.reviewed_at.is_(None)) | (Snapshot.reviewed_at == '')
        ).all()
        
        for (host,) in hosts:
            # aggregate candidate counts by field for this host (only non-accepted)
            field_counts = session.query(
                Candidate.field, func.count(Candidate.id)
            ).join(
                Snapshot, Candidate.snapshot_id == Snapshot.id
            ).filter(
                Snapshot.host == host,
                Candidate.accepted == False,
                (Snapshot.reviewed_at.is_(None)) | (Snapshot.reviewed_at == '')
            ).group_by(Candidate.field).all()
            
            issues = {(f if f is not None else "unknown"): c for f, c in field_counts}
            
            # count distinct snapshots (urls) for host that are not reviewed
            total_urls = session.query(func.count(distinct(Snapshot.id))).filter(
                Snapshot.host == host,
                (Snapshot.reviewed_at.is_(None)) | (Snapshot.reviewed_at == '')
            ).scalar()
            
            out[host] = {"issues": issues, "total_urls": total_urls}
        
        return out


@app.get("/api/domain_feedback")
def list_domain_feedback():
    """Return all saved domain feedback rows as a mapping keyed by host."""
    with db_manager.get_session() as session:
        feedbacks = session.query(DomainFeedback).all()
        out = {}
        for fb in feedbacks:
            out[fb.host] = fb.to_dict()
        return out


@app.get("/api/crawl_errors")
def list_crawl_errors():
    """Return snapshots that failed to fetch or parse, grouped by host and failure reason.
    Aggregates unique failure reasons per host with a sample URL and count.
    """
    with db_manager.get_session() as session:
        snapshots = session.query(Snapshot).filter(
            Snapshot.failure_reason.isnot(None),
            Snapshot.failure_reason != ''
        ).order_by(Snapshot.created_at.desc()).all()
        
        out = {}
        for snap in snapshots:
            host = snap.host
            if host not in out:
                out[host] = {"errors": {}, "total": 0}
            # normalize reason string
            r = snap.failure_reason.strip() if snap.failure_reason else "unknown"
            grp = out[host]["errors"].get(
                r, {"count": 0, "example_url": snap.url, "last_seen": snap.created_at.isoformat() if snap.created_at else None}
            )
            grp["count"] = grp.get("count", 0) + 1
            # keep the earliest example
            if not grp.get("example_url"):
                grp["example_url"] = snap.url
            # update last_seen to most recent
            current_time = snap.created_at.isoformat() if snap.created_at else ""
            grp["last_seen"] = max(grp.get("last_seen") or "", current_time)
            out[host]["errors"][r] = grp
            out[host]["total"] += 1
        
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
    """Upsert feedback for a host. Expects JSON with notes."""
    with db_manager.get_session() as session:
        feedback = session.query(DomainFeedback).filter(DomainFeedback.host == host).first()
        if feedback:
            feedback.notes = payload.get("notes")
            feedback.updated_at = datetime.datetime.utcnow()
        else:
            feedback = DomainFeedback(
                host=host,
                notes=payload.get("notes"),
                updated_at=datetime.datetime.utcnow()
            )
            session.add(feedback)
        session.commit()
        return {"status": "ok", "host": host}


@app.post("/api/migrate_domain_feedback")
def migrate_domain_feedback(dry_run: bool | None = True):
    """Migration endpoint for SQLite schema changes.
    Now a no-op since schema is managed by Alembic migrations.
    """
    return {
        "status": "noop",
        "reason": "Schema managed by Alembic migrations. No migration needed."
    }


@app.get("/api/snapshots_by_host/{host}")
def snapshots_by_host(host: str, include_reviewed: bool = False):
    """Return a short listing of snapshots for a host (id, url, status, parsed_fields, model_confidence).
    By default exclude snapshots that have been marked reviewed (reviewed_at is non-empty). Set include_reviewed=true to show all.
    """
    with db_manager.get_session() as session:
        query = session.query(Snapshot).filter(Snapshot.host == host)
        if not include_reviewed:
            query = query.filter(
                (Snapshot.reviewed_at.is_(None)) | (Snapshot.reviewed_at == '')
            )
        snapshots = query.order_by(Snapshot.created_at.desc()).all()
        
        out = []
        for snap in snapshots:
            rec = snap.to_dict()
            if rec.get("parsed_fields"):
                try:
                    rec["parsed_fields"] = json.loads(rec["parsed_fields"])
                except Exception:
                    rec["parsed_fields"] = None
            out.append(rec)
        
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
        with db_manager.get_session() as session:
            count = session.query(Candidate).filter(Candidate.accepted == False).count()
            res["candidate_issues"] = int(count)
            
            # dedupe near-misses: dedupe_audit rows where dedupe_flag is 0 and similarity > 0.7
            try:
                near_miss_count = session.query(DedupeAudit).filter(
                    (DedupeAudit.dedupe_flag.is_(None)) | (DedupeAudit.dedupe_flag == 0),
                    DedupeAudit.similarity > 0.7
                ).count()
                res["dedupe_near_misses"] = int(near_miss_count)
            except Exception:
                # if dedupe_audit missing or column types differ, ignore
                pass
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
    if not isinstance(payload, list):
        records = [payload]
    else:
        records = payload
    
    with db_manager.get_session() as session:
        now = datetime.datetime.utcnow()
        inserted = 0
        samples = []
        for r in records:
            try:
                audit = DedupeAudit(
                    article_uid=r.get("article_uid"),
                    neighbor_uid=r.get("neighbor_uid"),
                    host=r.get("host"),
                    similarity=r.get("similarity"),
                    dedupe_flag=(
                        int(r.get("dedupe_flag"))
                        if r.get("dedupe_flag") is not None
                        else None
                    ),
                    category=int(r.get("category")) if r.get("category") is not None else None,
                    stage=r.get("stage"),
                    details=(
                        json.dumps(r.get("details"))
                        if r.get("details") is not None
                        else None
                    ),
                    created_at=now
                )
                session.add(audit)
                session.flush()  # Get the ID
                inserted += 1
                samples.append(audit.id)
            except Exception:
                # skip problematic rows but continue
                continue
        
        session.commit()
        return {"inserted": inserted, "sample_ids": samples}


@app.get("/api/dedupe_records")
def get_dedupe_records(
    article_uid: str | None = None,
    host: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Query dedupe audit rows filtered by article_uid or host. Returns rows ordered by created_at desc."""
    with db_manager.get_session() as session:
        query = session.query(DedupeAudit)
        
        if article_uid:
            query = query.filter(DedupeAudit.article_uid == article_uid)
        if host:
            query = query.filter(DedupeAudit.host == host)
        
        query = query.order_by(DedupeAudit.created_at.desc()).limit(limit).offset(offset)
        records = query.all()
        
        out = []
        for record in records:
            d = record.to_dict()
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
                try:
                    with db_manager.get_session() as session:
                        now = datetime.datetime.utcnow()
                        audit = DedupeAudit(
                            article_uid=row.get("id"),
                            neighbor_uid=None,
                            host=row.get("hostname"),
                            similarity=None,
                            dedupe_flag=dup_flag,
                            category=None,
                            stage="imported_csv",
                            details=json.dumps(
                                {"url": row.get("url"), "title": row.get("title")}
                            ),
                            created_at=now
                        )
                        session.add(audit)
                        session.commit()
                except Exception:
                    pass
    summary = {"rows_seen": total, "dup_counts": dup_counts, "samples": sample_rows}
    if dry_run:
        return {"status": "dry_run", **summary}
    return {"status": "ok", **summary}


@app.post("/api/candidates/{cid}/accept")
def accept_candidate(cid: str, payload: dict | None = None):
    """Mark a candidate as accepted (accepted=1) or rejected (accepted=0).
    Payload optional: {"accepted": true|false}
    """
    val = True
    if payload is not None:
        val = payload.get("accepted", True)
    
    with db_manager.get_session() as session:
        candidate = session.query(Candidate).filter(Candidate.id == cid).first()
        if not candidate:
            raise HTTPException(status_code=404, detail="candidate not found")
        candidate.accepted = val
        session.commit()
        return {"status": "ok", "id": cid, "accepted": bool(val)}


@app.post("/api/reextract_jobs")
def create_reextract_job(payload: dict):
    """Create a re-extract job for a host. Payload: {host: str}
    Returns: {job_id}
    """
    host = payload.get("host")
    if not host:
        raise HTTPException(status_code=400, detail="host required")
    
    job_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow()
    
    with db_manager.get_session() as session:
        job = ReextractionJob(
            id=job_id,
            host=host,
            status="pending",
            created_at=now,
            updated_at=now
        )
        session.add(job)
        session.commit()
        return {"status": "ok", "job_id": job_id}


@app.get("/api/reextract_jobs/{job_id}")
def get_reextract_job(job_id: str):
    with db_manager.get_session() as session:
        job = session.query(ReextractionJob).filter(ReextractionJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        
        result_data = None
        if job.result_json:
            try:
                result_data = json.loads(job.result_json)
            except Exception:
                result_data = job.result_json
        
        return {
            "id": job.id,
            "host": job.host,
            "status": job.status,
            "result": result_data,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
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
            return {"status": "success", "message": "Address updated successfully"}
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
    days: int = 7, host: str | None = None, status_code: int | None = None
):
    """Get HTTP error statistics for dashboard monitoring."""
    try:
        with db_manager.get_session() as session:
            # Build query with filters
            query = session.query(
                HttpErrorSummary.host,
                HttpErrorSummary.status_code,
                func.sum(HttpErrorSummary.count).label('error_count'),
                func.max(HttpErrorSummary.last_seen).label('last_seen')
            )

            # Apply filters
            if days:
                cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
                query = query.filter(HttpErrorSummary.last_seen >= cutoff_date)

            if host:
                query = query.filter(HttpErrorSummary.host == host)

            if status_code:
                query = query.filter(HttpErrorSummary.status_code == status_code)

            # Group and order
            query = query.group_by(
                HttpErrorSummary.host,
                HttpErrorSummary.status_code
            ).order_by(desc('error_count'))

            results = []
            for row in query.all():
                results.append(
                    {
                        "host": row.host,
                        "status_code": row.status_code,
                        "error_count": row.error_count,
                        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                    }
                )

            return {"http_errors": results}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching HTTP errors: {str(e)}",
        )


@app.get("/api/telemetry/method-performance")
def get_method_performance(
    days: int = 7, method: str | None = None, host: str | None = None
):
    """Get extraction method performance statistics."""
    try:
        with db_manager.get_session() as session:
            # Build query with COALESCE for successful_method
            method_col = func.coalesce(ExtractionTelemetryV2.successful_method, 'failed')
            
            query = session.query(
                method_col.label('method'),
                ExtractionTelemetryV2.host,
                func.count().label('total_attempts'),
                func.sum(
                    case((ExtractionTelemetryV2.is_success == True, 1), else_=0)
                ).label('successful_attempts'),
                func.avg(ExtractionTelemetryV2.total_duration_ms).label('avg_duration'),
                func.min(ExtractionTelemetryV2.total_duration_ms).label('min_duration'),
                func.max(ExtractionTelemetryV2.total_duration_ms).label('max_duration')
            )

            # Apply filters
            if days:
                cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
                query = query.filter(ExtractionTelemetryV2.created_at >= cutoff_date)

            if method:
                query = query.filter(method_col == method)

            if host:
                query = query.filter(ExtractionTelemetryV2.host == host)

            # Group and order
            query = query.group_by(method_col, ExtractionTelemetryV2.host)
            query = query.order_by(desc('total_attempts'))

            results = []
            for row in query.all():
                total_attempts = row.total_attempts or 0
                successful_attempts = row.successful_attempts or 0
                success_rate = (successful_attempts / total_attempts * 100) if total_attempts > 0 else 0
                
                results.append(
                    {
                        "method": row.method,
                        "host": row.host,
                        "total_attempts": total_attempts,
                        "successful_attempts": successful_attempts,
                        "success_rate": round(success_rate, 2),
                        "avg_duration": round(row.avg_duration, 2) if row.avg_duration else 0,
                        "min_duration": round(row.min_duration, 2) if row.min_duration else 0,
                        "max_duration": round(row.max_duration, 2) if row.max_duration else 0,
                    }
                )

            return {"method_performance": results}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching method performance: {str(e)}",
        )


@app.get("/api/telemetry/publisher-stats")
def get_publisher_stats(days: int = 7, host: str | None = None, min_attempts: int = 5):
    """Get publisher performance statistics."""
    try:
        with db_manager.get_session() as session:
            method_col = func.coalesce(ExtractionTelemetryV2.successful_method, 'failed')
            
            query = session.query(
                ExtractionTelemetryV2.host,
                func.count().label('total_extractions'),
                func.sum(
                    case((ExtractionTelemetryV2.is_success == True, 1), else_=0)
                ).label('successful_extractions'),
                func.avg(ExtractionTelemetryV2.total_duration_ms).label('avg_duration'),
                func.count(func.distinct(method_col)).label('methods_used'),
                func.max(ExtractionTelemetryV2.created_at).label('last_attempt')
            )

            # Apply filters
            if days:
                cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
                query = query.filter(ExtractionTelemetryV2.created_at >= cutoff_date)

            if host:
                query = query.filter(ExtractionTelemetryV2.host == host)

            # Group by host and apply HAVING clause
            query = query.group_by(ExtractionTelemetryV2.host)
            query = query.having(func.count() >= min_attempts)
            query = query.order_by(desc('total_extractions'))

            results = []
            for row in query.all():
                total = row.total_extractions or 0
                successful = row.successful_extractions or 0
                success_rate = (successful / total * 100) if total > 0 else 0
                
                if success_rate < 50:
                    status = "poor"
                elif success_rate > 80:
                    status = "good"
                else:
                    status = "fair"

                results.append(
                    {
                        "host": row.host,
                        "total_extractions": total,
                        "successful_extractions": successful,
                        "success_rate": round(success_rate, 2),
                        "avg_duration": round(row.avg_duration, 2) if row.avg_duration else 0,
                        "methods_used": row.methods_used,
                        "last_attempt": row.last_attempt.isoformat() if row.last_attempt else None,
                        "status": status,
                    }
                )

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
    host: str | None = None,
):
    """Get field-level extraction statistics."""
    try:
        with db_manager.get_session() as session:
            # Build query
            query = session.query(
                ExtractionTelemetryV2.field_extraction,
                ExtractionTelemetryV2.methods_attempted,
                ExtractionTelemetryV2.successful_method
            )

            # Apply filters
            if days:
                cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
                query = query.filter(ExtractionTelemetryV2.created_at >= cutoff_date)

            if host:
                query = query.filter(ExtractionTelemetryV2.publisher == host)

            # Process results to calculate field extraction stats
            method_field_stats = {}
            
            for row in query.all():
                field_extraction_json = row.field_extraction
                methods_json = row.methods_attempted
                
                try:
                    methods = json.loads(methods_json) if methods_json else []
                    field_data = json.loads(field_extraction_json) if field_extraction_json else {}
                except (json.JSONDecodeError, TypeError):
                    continue

                for method_name in methods:
                    if method and method_name != method:
                        continue

                    stats = method_field_stats.setdefault(
                        method_name,
                        {
                            "count": 0,
                            "title_success": 0,
                            "author_success": 0,
                            "content_success": 0,
                            "date_success": 0,
                        },
                    )

                    stats["count"] += 1
                    method_fields = field_data.get(method_name, {})
                    if method_fields.get("title"):
                        stats["title_success"] += 1
                    if method_fields.get("author"):
                        stats["author_success"] += 1
                    if method_fields.get("content"):
                        stats["content_success"] += 1
                    if method_fields.get("publish_date"):
                        stats["date_success"] += 1

            # Format results
            results = []
            for method_name, stats in method_field_stats.items():
                count = stats["count"]
                denominator = count if count else 1
                entry = {
                    "method": method_name,
                    "count": count,
                    "title_success_rate": stats["title_success"] / denominator,
                    "author_success_rate": stats["author_success"] / denominator,
                    "content_success_rate": stats["content_success"] / denominator,
                    "date_success_rate": stats["date_success"] / denominator,
                }
                
                # Filter by field if specified
                if field:
                    field_counts = {
                        "title": stats["title_success"],
                        "author": stats["author_success"],
                        "content": stats["content_success"],
                        "publish_date": stats["date_success"],
                    }
                    if field_counts.get(field, 0) > 0:
                        results.append(entry)
                else:
                    results.append(entry)

            results.sort(key=lambda item: item["count"], reverse=True)
            return {"field_extraction_stats": results}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching field extraction stats: {str(e)}",
        )


@app.get("/api/telemetry/poor-performers")
def get_poor_performing_sites(
    days: int = 7, min_attempts: int = 10, max_success_rate: float = 50.0
):
    """Get sites with poor performance that may need attention."""
    try:
        with db_manager.get_session() as session:
            method_col = func.coalesce(ExtractionTelemetryV2.successful_method, 'failed')
            
            # Calculate success rate in the query
            success_rate_calc = (
                func.sum(case((ExtractionTelemetryV2.is_success == True, 1), else_=0)) * 100.0
                / func.count()
            )
            
            query = session.query(
                ExtractionTelemetryV2.host,
                func.count().label('total_attempts'),
                func.sum(
                    case((ExtractionTelemetryV2.is_success == True, 1), else_=0)
                ).label('successful_attempts'),
                success_rate_calc.label('success_rate'),
                func.avg(ExtractionTelemetryV2.total_duration_ms).label('avg_duration'),
                func.max(ExtractionTelemetryV2.created_at).label('last_attempt'),
                func.count(func.distinct(method_col)).label('methods_tried')
            )

            # Apply filters
            cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
            query = query.filter(ExtractionTelemetryV2.created_at >= cutoff_date)

            # Group by host and apply HAVING clauses
            query = query.group_by(ExtractionTelemetryV2.host)
            query = query.having(and_(
                func.count() >= min_attempts,
                success_rate_calc <= max_success_rate
            ))
            query = query.order_by(
                success_rate_calc.asc(),
                desc('total_attempts')
            )

            results = []
            for row in query.all():
                success_rate = row.success_rate or 0
                results.append(
                    {
                        "host": row.host,
                        "total_attempts": row.total_attempts,
                        "successful_attempts": row.successful_attempts or 0,
                        "success_rate": round(success_rate, 2),
                        "avg_duration": round(row.avg_duration, 2) if row.avg_duration else 0,
                        "last_attempt": row.last_attempt.isoformat() if row.last_attempt else None,
                        "methods_tried": row.methods_tried,
                        "recommendation": "pause" if success_rate < 25 else "monitor",
                    }
                )

            return {"poor_performers": results}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching poor performers: {str(e)}"
        )


@app.get("/api/telemetry/summary")
def get_telemetry_summary(days: int = 7):
    """Get overall telemetry summary for dashboard overview."""
    try:
        with db_manager.get_session() as session:
            cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
            
            # Overall extraction stats
            method_col = func.coalesce(ExtractionTelemetryV2.successful_method, 'failed')
            
            overall_query = session.query(
                func.count().label('total_extractions'),
                func.sum(
                    case((ExtractionTelemetryV2.is_success == True, 1), else_=0)
                ).label('successful_extractions'),
                func.count(func.distinct(ExtractionTelemetryV2.host)).label('unique_hosts'),
                func.count(func.distinct(method_col)).label('methods_used'),
                func.avg(ExtractionTelemetryV2.total_duration_ms).label('avg_duration')
            ).filter(ExtractionTelemetryV2.created_at >= cutoff_date)
            
            overall = overall_query.first()
            total = overall.total_extractions or 0
            successful = overall.successful_extractions or 0
            success_rate = (successful / total * 100) if total > 0 else 0

            # Method breakdown
            method_query = session.query(
                method_col.label('method'),
                func.count().label('count'),
                func.sum(
                    case((ExtractionTelemetryV2.is_success == True, 1), else_=0)
                ).label('successful')
            ).filter(
                ExtractionTelemetryV2.created_at >= cutoff_date
            ).group_by(method_col).order_by(desc('count'))

            method_stats = []
            for row in method_query.all():
                count = row.count or 0
                successful_count = row.successful or 0
                method_success_rate = (successful_count / count * 100) if count > 0 else 0
                method_stats.append(
                    {
                        "method": row.method,
                        "attempts": count,
                        "successful": successful_count,
                        "success_rate": round(method_success_rate, 2),
                    }
                )

            # HTTP error counts
            error_query = session.query(
                HttpErrorSummary.status_code,
                func.sum(HttpErrorSummary.count).label('count')
            ).filter(
                HttpErrorSummary.last_seen >= cutoff_date
            ).group_by(
                HttpErrorSummary.status_code
            ).order_by(desc('count')).limit(10)

            http_errors = [
                {"status_code": row.status_code, "count": row.count}
                for row in error_query.all()
            ]

            return {
                "summary": {
                    "total_extractions": total,
                    "successful_extractions": successful,
                    "success_rate": round(success_rate, 2),
                    "unique_hosts": overall.unique_hosts or 0,
                    "methods_used": overall.methods_used or 0,
                    "avg_duration": round(overall.avg_duration, 2) if overall.avg_duration else 0,
                    "method_breakdown": method_stats,
                    "top_http_errors": http_errors,
                }
            }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching telemetry summary: {str(e)}"
        )


# Site Management API endpoints
class SiteManagementRequest(BaseModel):
    host: str
    reason: str | None = None


@app.post("/api/site-management/pause")
def pause_site(request: SiteManagementRequest):
    """Pause a site from further crawling due to poor performance."""
    try:
        with db_manager.get_session() as session:
            # Try to find existing source
            source = session.query(Source).filter(Source.host == request.host).first()
            
            now = datetime.datetime.utcnow()
            reason = request.reason or "Poor performance detected"
            
            if source:
                # Update existing source
                source.status = 'paused'
                source.paused_at = now
                source.paused_reason = reason
            else:
                # Create new source
                source = Source(
                    id=str(uuid.uuid4()),
                    host=request.host,
                    host_norm=request.host.lower(),
                    status='paused',
                    paused_at=now,
                    paused_reason=reason
                )
                session.add(source)
            
            session.commit()

            return {
                "status": "success",
                "message": f"Site {request.host} has been paused",
                "paused_at": now.isoformat(),
                "reason": reason,
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error pausing site: {str(e)}")


@app.post("/api/site-management/resume")
def resume_site(request: SiteManagementRequest):
    """Resume a previously paused site."""
    try:
        with db_manager.get_session() as session:
            # Find the source
            source = session.query(Source).filter(Source.host == request.host).first()

            if not source:
                raise HTTPException(
                    status_code=404, detail=f"Site {request.host} not found"
                )

            # Update the source status
            source.status = 'active'
            source.paused_at = None
            source.paused_reason = None
            
            session.commit()

            return {"status": "success", "message": f"Site {request.host} has been resumed"}

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
        with db_manager.get_session() as session:
            paused_sources = session.query(Source).filter(
                Source.status == 'paused'
            ).order_by(desc(Source.paused_at)).all()

            paused_sites = []
            for source in paused_sources:
                paused_sites.append({
                    "host": source.host,
                    "paused_at": source.paused_at.isoformat() if source.paused_at else None,
                    "reason": source.paused_reason
                })

            return {"paused_sites": paused_sites}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching paused sites: {str(e)}"
        )


@app.get("/api/site-management/status/{host}")
def get_site_status(host: str):
    """Get the current status of a specific site."""
    try:
        with db_manager.get_session() as session:
            source = session.query(Source).filter(Source.host == host).first()

            if source:
                return {
                    "host": host,
                    "status": source.status or "active",
                    "paused_at": source.paused_at.isoformat() if source.paused_at else None,
                    "paused_reason": source.paused_reason,
                }
            else:
                return {
                    "host": host,
                    "status": "active",
                    "paused_at": None,
                    "paused_reason": None,
                }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching site status: {str(e)}"
        )


# ============================================================================
# Telemetry API Endpoints (Cloud SQL Migration)
# ============================================================================


@app.get("/api/telemetry/verification/pending")
async def get_pending_verification_reviews(limit: int = 50):
    """Get URL verifications that need human review."""
    try:
        return {"items": verification.get_pending_verification_reviews(limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching verification reviews: {str(e)}"
        )


@app.post("/api/telemetry/verification/feedback")
async def submit_verification_feedback(feedback: dict):
    """Submit human feedback for a URL verification result."""
    try:
        verification.submit_verification_feedback(feedback)
        return {"status": "success", "message": "Feedback submitted"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error submitting feedback: {str(e)}"
        )


@app.get("/api/telemetry/verification/stats")
async def get_verification_stats(days: int = 30):
    """Get verification telemetry statistics."""
    try:
        return verification.get_verification_telemetry_stats(days)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching verification stats: {str(e)}"
        )


@app.get("/api/telemetry/verification/labeled_training_data")
async def get_verification_training_data(limit: int = 1000):
    """Get labeled verification data for model training."""
    try:
        return {"data": verification.get_labeled_verification_training_data(limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching training data: {str(e)}"
        )


@app.post("/api/telemetry/verification/enhance")
async def enhance_verification_with_content(verification_id: str):
    """Enhance verification record with article content."""
    try:
        verification.enhance_verification_with_content(verification_id)
        return {"status": "success", "message": "Verification enhanced"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error enhancing verification: {str(e)}"
        )


# Byline Telemetry Endpoints


@app.get("/api/telemetry/byline/pending")
async def get_pending_byline_reviews(limit: int = 50):
    """Get byline extractions that need human review."""
    try:
        return {"items": byline.get_pending_byline_reviews(limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching byline reviews: {str(e)}"
        )


@app.post("/api/telemetry/byline/feedback")
async def submit_byline_feedback(feedback: dict):
    """Submit human feedback for a byline cleaning result."""
    try:
        byline.submit_byline_feedback(feedback)
        return {"status": "success", "message": "Feedback submitted"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error submitting feedback: {str(e)}"
        )


@app.get("/api/telemetry/byline/stats")
async def get_byline_stats(days: int = 30):
    """Get byline telemetry statistics."""
    try:
        return byline.get_byline_telemetry_stats(days)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching byline stats: {str(e)}"
        )


@app.get("/api/telemetry/byline/labeled_training_data")
async def get_byline_training_data(limit: int = 1000):
    """Get labeled byline data for model training."""
    try:
        return {"data": byline.get_labeled_training_data(limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching training data: {str(e)}"
        )


# Code Review Telemetry Endpoints


@app.get("/api/telemetry/code_review/pending")
async def get_pending_code_reviews(limit: int = 50):
    """Get code review items that need attention."""
    try:
        return {"items": code_review.get_pending_code_reviews(limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching code reviews: {str(e)}"
        )


@app.post("/api/telemetry/code_review/feedback")
async def submit_code_review_feedback(feedback: dict):
    """Submit feedback for a code review item."""
    try:
        code_review.submit_code_review_feedback(feedback)
        return {"status": "success", "message": "Feedback submitted"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error submitting feedback: {str(e)}"
        )


@app.get("/api/telemetry/code_review/stats")
async def get_code_review_stats():
    """Get code review telemetry statistics."""
    try:
        return code_review.get_code_review_stats()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching code review stats: {str(e)}"
        )


@app.post("/api/telemetry/code_review/add")
async def add_code_review_item(item: dict):
    """Add a new code review item."""
    try:
        code_review.add_code_review_item(item)
        return {"status": "success", "message": "Code review item added"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error adding code review item: {str(e)}"
        )
