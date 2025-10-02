import contextlib
import csv
import fcntl
import html
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from web import sqlite_store
from web.byline_telemetry_api import (
    BylineFeedback,
    get_byline_telemetry_stats,
    get_labeled_training_data,
    get_pending_byline_reviews,
    submit_byline_feedback,
)
from web.code_review_telemetry_api import (
    CodeReviewFeedback,
    CodeReviewItem,
    add_code_review_item,
    get_code_review_stats,
    get_pending_code_reviews,
    init_code_review_tables,
    submit_code_review_feedback,
)
from web.verification_telemetry_api import (
    VerificationFeedback,
    enhance_verification_with_content,
    get_labeled_verification_training_data,
    get_pending_verification_reviews,
    get_verification_telemetry_stats,
    submit_verification_feedback,
)

ROOT = Path(__file__).resolve().parents[1]
# Prefer pipeline/processed when running from project root.
# Fall back to `processed/` in the repository root.
PIPELINE_PROCESSED = Path(ROOT) / "pipeline" / "processed"
PROCESSED = PIPELINE_PROCESSED if PIPELINE_PROCESSED.exists() else (ROOT / "processed")
ARTICLES_CSV = PROCESSED / "articleslabelled_7.csv"
FEEDBACK_CSV = PROCESSED / "feedback.csv"

# initialize sqlite DB and migrate existing CSVs (idempotent)
try:
    sqlite_store.migrate_from_csvs()
except Exception:
    # migration is best-effort; failures should not block the API
    pass

app = FastAPI(title="Reviewer API")

# Allow local frontend origins by default (adjust in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Feedback(BaseModel):
    id: str
    field: str
    old_value: str | None = None
    new_value: str | None = None
    comment: str | None = None
    reviewer: str | None = None


class ReviewAction(BaseModel):
    action: str  # 'accept' or 'reject'
    candidate_selector: str | None = None
    reviewer: str | None = None
    comment: str | None = None


def read_articles(limit: int | None = None, offset: int = 0):
    # Prefer SQLite store if available (provides transactional reads).
    try:
        from web import sqlite_store

        rows = sqlite_store.get_articles(limit=limit, offset=offset)
        return rows
    except Exception:
        # fallback to CSV for portability
        if not ARTICLES_CSV.exists():
            raise FileNotFoundError(str(ARTICLES_CSV))
        # Increase csv field size limit to handle very large HTML/text fields.
        try:
            csv.field_size_limit(sys.maxsize)
        except OverflowError:
            # Some platforms don't accept sys.maxsize; fall back to
            # a large value.
            csv.field_size_limit(10 * 1024 * 1024)

        try:
            with open(ARTICLES_CSV, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
        except csv.Error as e:
            logging.exception("Failed to parse articles CSV")
            # Raise a runtime error which the caller will map to a 500 response
            raise RuntimeError(f"Failed to parse CSV: {e}")
        if limit is None:
            return rows[offset:]
        return rows[offset : offset + limit]


@app.get("/api/articles", response_model=list[dict])
def clean_html_to_text(html_text: str) -> str:
    """Convert HTML to safe plain text by removing scripts/styles and tags.

    This removes JavaScript, CSS, or HTML markup so the API does not expose
    raw HTML. It returns readable article text only.
    """
    if not html_text:
        return ""
    try:
        # Remove script/style blocks (case-insensitive, dot matches newlines)
        html_text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
        html_text = re.sub(r"(?is)<style.*?>.*?</style>", " ", html_text)
        # Remove HTML comments
        html_text = re.sub(r"(?is)<!--.*?-->", " ", html_text)
        # Remove all tags
        html_text = re.sub(r"(?is)<[^>]+>", " ", html_text)
        # Unescape HTML entities and collapse whitespace
        text = html.unescape(html_text)
        text = " ".join(text.split())
        return text
    except Exception:
        # Fallback: strip tags roughly and return a trimmed string
        try:
            text = re.sub(r"<[^>]+>", " ", html_text)
            return " ".join(html.unescape(text).split())
        except Exception:
            return html_text[:1000]


def get_articles(
    limit: int | None = 50,
    offset: int = 0,
    full_text: bool = False,
    preview_chars: int = 500,
):
    """Return a page of labelled articles as JSON for the reviewer UI.

    The API will not return raw HTML. Each article will include an
    `article_text` (cleaned plain text). By default the response contains
    a short `news_preview` (plain-text, preview_chars long). Set
    `full_text=true` to get the full cleaned article text instead.
    """
    try:
        rows = read_articles(limit=limit, offset=offset)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="articles CSV not found")
    except Exception as exc:
        # Unexpected errors (for example, CSV parsing limits) should return
        # HTTP 500 with the exception detail.
        raise HTTPException(status_code=500, detail=str(exc))
    # Process each row to avoid returning huge HTML blobs by default.
    processed = []
    tag_re = re.compile(r"<[^>]+>")
    for r in rows:
        row = dict(r)
        news = row.get("news") or ""
        if full_text:
            # caller requested the full cleaned text
            processed.append(row)
            continue
        # create a small plain-text preview: unescape entities and remove tags
        try:
            text = html.unescape(news)
            text = tag_re.sub(" ", text)
            text = " ".join(text.split())
        except Exception:
            text = (news[:preview_chars] + "...") if len(news) > preview_chars else news
        preview = text[:preview_chars]
        row["news_preview"] = preview
        row["news_truncated"] = len(news) > len(preview)
        # remove the heavy raw HTML so responses stay small by default
        if "news" in row:
            row["news"] = ""
        processed.append(row)
    return processed


# --- Domain issues / feedback endpoints ---


def _load_json(path: Path):
    try:
        with open(path, encoding="utf8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _read_csv_rows(path: Path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def _write_csv_rows(path: Path, rows, fieldnames):
    # Use a per-file lock and atomic replace to avoid races across processes.
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")

    @contextlib.contextmanager
    def _file_lock(p: Path):
        # ensure lock file exists and acquire exclusive lock
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = open(p, "w", encoding="utf8")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield fh
        finally:
            try:
                fcntl.flock(fh, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                fh.close()
            except Exception:
                pass

    def _atomic_replace(target: Path, write_rows, flds):
        # write to temporary file in same directory then fsync+replace
        fd, tmp_path = tempfile.mkstemp(prefix=target.name, dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf8") as fh:
                writer = csv.DictWriter(fh, fieldnames=flds)
                writer.writeheader()
                for r in write_rows:
                    writer.writerow(r)
                fh.flush()
                os.fsync(fh.fileno())
            # backup existing file if present
            try:
                bak = target.with_suffix(target.suffix + ".bak")
                if target.exists():
                    shutil.copy2(target, bak)
            except Exception:
                pass
            os.replace(tmp_path, str(target))
        finally:
            # cleanup stray tmp if it still exists
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    # Acquire lock then atomically replace file
    with _file_lock(lock_path):
        _atomic_replace(path, rows, fieldnames)


def _promote_selector_to_site_specs(domain: str, selector: str):
    """Add or update a row in lookups/site_specs.csv setting
    `body_selector` to `selector`.

    This makes a minimal, conservative edit: it will update an existing
    domain row's `body_selector` if present; otherwise it will append a
    new stub row.
    """
    # Prefer SQLite upsert for atomic, transactional promotion.
    try:
        sqlite_store.upsert_site_spec(
            domain,
            {
                "body_selector": selector,
                "url_pattern": f".*{domain}.*",
                "last_tested": datetime.utcnow().isoformat() + "Z",
            },
        )
        # also keep CSV export in sync for portability
        try:
            lookups_dir = ROOT / "lookups"
            path = lookups_dir / "site_specs.csv"
            sqlite_store.export_site_specs_csv(path)
        except Exception:
            # non-fatal: DB update succeeded, CSV export best-effort
            pass
    except Exception:
        # fallback: best-effort CSV update if DB path is unavailable
        lookups_dir = ROOT / "lookups"
        path = lookups_dir / "site_specs.csv"
        rows = _read_csv_rows(path)
        if rows:
            fieldnames = list(rows[0].keys())
        else:
            fieldnames = [
                "domain",
                "url_pattern",
                "headline_selector",
                "author_selector",
                "date_selector",
                "body_selector",
                "tags_selector",
                "use_jsonld",
                "requires_js",
                "last_tested",
                "skip_patterns",
                "force_include_patterns",
            ]

        updated = False
        for r in rows:
            if r.get("domain") == domain:
                r["body_selector"] = selector
                r["last_tested"] = datetime.utcnow().isoformat() + "Z"
                updated = True
                break

        if not updated:
            newrow = dict.fromkeys(fieldnames, "")
            newrow["domain"] = domain
            newrow["url_pattern"] = f".*{domain}.*"
            newrow["body_selector"] = selector
            newrow["last_tested"] = datetime.utcnow().isoformat() + "Z"
            rows.append(newrow)

        _write_csv_rows(path, rows, fieldnames)


@app.get("/api/domain_issues")
def api_domain_issues():
    p = PROCESSED / "domain_issues.json"
    data = _load_json(p)
    if data is None:
        raise HTTPException(status_code=404, detail="domain_issues.json not found")
    return data


@app.get("/api/domain_review/{host}")
def api_domain_review(host: str):
    """Return the per-domain review artifact JSON produced under
    `processed/domain_flags/{host}.json`. This lets the frontend fetch
    detailed parity examples and any saved snapshots or candidate rule
    suggestions for a domain.
    """
    # sanitize host to a filename-safe single component
    if "/" in host or "\\" in host or ".." in host:
        raise HTTPException(status_code=400, detail="invalid host")
    p = PROCESSED / "domain_flags" / f"{host}.json"
    data = _load_json(p)
    if data is None:
        raise HTTPException(status_code=404, detail="domain artifact not found")
    return data


@app.post("/api/domain_review/{host}/action")
def api_domain_review_action(host: str, payload: ReviewAction):
    """Handle reviewer actions for a domain artifact.

    Payload.action must be 'accept' or 'reject'. If 'accept', the
    provided candidate_selector will be promoted into `lookups/site_specs.csv`
    via the existing helper and the domain artifact will be updated with
    an `accepted_rule` entry and reviewer metadata. If 'reject', a
    rejection record is appended to `rejections` in the artifact.
    """
    # sanitize host to a filename-safe single component
    if "/" in host or "\\" in host or ".." in host:
        raise HTTPException(status_code=400, detail="invalid host")

    p = PROCESSED / "domain_flags" / f"{host}.json"
    data = _load_json(p)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="domain artifact not found",
        )

    action = (payload.action or "").strip().lower()
    reviewer = (payload.reviewer or "").strip() or "unknown"
    now = datetime.utcnow().isoformat() + "Z"

    # Ensure container fields exist
    if "review_history" not in data:
        data["review_history"] = []
    if "rejections" not in data:
        data["rejections"] = []

    if action == "accept":
        selector = (payload.candidate_selector or "").strip()
        if not selector:
            raise HTTPException(
                status_code=400,
                detail="candidate_selector required for accept",
            )

        # Try to find candidate metadata in artifact (if present)
        candidate_meta = None
        rs = data.get("rule_stub") or {}
        for c in rs.get("candidates", []) or []:
            if c.get("selector") == selector:
                candidate_meta = c.copy()
                break

        accepted = candidate_meta or {"selector": selector}
        accepted.update(
            {
                "reviewer": reviewer,
                "reviewed_at": now,
                "comment": payload.comment or "",
            }
        )

        # Persist accepted rule to artifact
        data["accepted_rule"] = accepted
        data["review_status"] = "accepted"
        data["review_history"].append(
            {
                "action": "accept",
                "selector": selector,
                "reviewer": reviewer,
                "at": now,
                "comment": payload.comment or "",
            }
        )

        # Promote into lookups/site_specs.csv (conservative backup is created)
        try:
            _promote_selector_to_site_specs(host, selector)
            data["promoted_to_site_specs"] = {
                "selector": selector,
                "promoted_at": now,
            }
        except Exception as exc:
            # record failure but don't fail the whole request
            data.setdefault("promotion_errors", []).append(
                {
                    "error": str(exc),
                    "at": now,
                }
            )

    elif action == "reject":
        selector = (payload.candidate_selector or "").strip() or ""
        rej = {
            "selector": selector,
            "reviewer": reviewer,
            "at": now,
            "comment": payload.comment or "",
        }
        data["rejections"].append(rej)
        data["review_status"] = "rejected"
        data["review_history"].append(
            {
                "action": "reject",
                "selector": selector,
                "reviewer": reviewer,
                "at": now,
                "comment": payload.comment or "",
            }
        )

    else:
        raise HTTPException(status_code=400, detail="unknown action")

    # write back artifact
    try:
        _write_json(p, data)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=("failed to persist artifact: " + str(exc)),
        )

    return {
        "status": "ok",
        "host": host,
        "review_status": data.get("review_status"),
        "artifact": data,
    }


@app.get("/api/domain_feedback")
def api_domain_feedback():
    p = PROCESSED / "domain_feedback.json"
    data = _load_json(p)
    if data is not None:
        return data
    # generate a skeleton from domain_issues.json if present
    issues_p = PROCESSED / "domain_issues.json"
    issues = _load_json(issues_p) or {}
    skeleton = {
        h: {
            "priority": "low",
            "needs_dev": False,
            "notes": "",
            "assigned_to": "",
        }
        for h in issues.keys()
    }
    _write_json(p, skeleton)
    return skeleton


@app.post("/api/domain_feedback/{host}")
def api_post_domain_feedback(host: str, payload: dict):
    """Update feedback for a host. Payload should be a dict with
    keys: priority, needs_dev, notes, assigned_to
    """
    p = PROCESSED / "domain_feedback.json"
    data = _load_json(p) or {}
    # normalize incoming payload
    entry = {
        "priority": payload.get("priority", "low"),
        "needs_dev": bool(payload.get("needs_dev", False)),
        "notes": payload.get("notes", "") or "",
        "assigned_to": payload.get("assigned_to", "") or "",
    }
    data[host] = entry
    _write_json(p, data)
    return {"status": "ok", "host": host, "saved": entry}


@app.post("/api/feedback")
def post_feedback(f: Feedback):
    """Accept reviewer feedback and append it to processed/feedback.csv."""
    # persist into SQLite feedback table (transactional)
    PROCESSED.mkdir(exist_ok=True)
    row = {
        "id": f.id,
        "field": f.field,
        "old_value": f.old_value or "",
        "new_value": f.new_value or "",
        "comment": f.comment or "",
        "reviewer": f.reviewer or "",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    try:
        sqlite_store.append_feedback(row)
    except Exception:
        # fallback: append to CSV for portability
        header = ["id", "field", "old_value", "new_value", "comment", "reviewer"]
        write_header = not FEEDBACK_CSV.exists()
        with open(FEEDBACK_CSV, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if write_header:
                writer.writerow(header)
            writer.writerow(
                [
                    f.id,
                    f.field,
                    f.old_value or "",
                    f.new_value or "",
                    f.comment or "",
                    f.reviewer or "",
                ]
            )
    return {"status": "ok", "saved_to": str(FEEDBACK_CSV)}


# --- Byline Telemetry Endpoints ---


@app.get("/api/byline_telemetry/pending")
def api_get_pending_bylines(limit: int = 50):
    """Get byline extractions that need human review."""
    try:
        items = get_pending_byline_reviews(limit=limit)
        return {
            "status": "ok",
            "count": len(items),
            "items": [item.dict() for item in items],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/byline_telemetry/feedback")
def api_submit_byline_feedback(feedback: BylineFeedback):
    """Submit human feedback for a byline cleaning result."""
    try:
        success = submit_byline_feedback(feedback)
        if success:
            return {"status": "ok", "telemetry_id": feedback.telemetry_id}
        else:
            raise HTTPException(status_code=404, detail="Telemetry record not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/byline_telemetry/stats")
def api_get_byline_stats():
    """Get summary statistics for byline telemetry."""
    try:
        stats = get_byline_telemetry_stats()
        return stats.dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/byline_telemetry/training_data")
def api_get_training_data(min_confidence: float = 0.0, format: str = "json"):
    """Export labeled training data for ML."""
    try:
        data = get_labeled_training_data(min_confidence=min_confidence)
        if format == "csv":
            # Return CSV format for download
            import csv
            import io

            output = io.StringIO()
            if data:
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            return {
                "status": "ok",
                "format": "csv",
                "content": output.getvalue(),
                "count": len(data),
            }
        else:
            return {"status": "ok", "format": "json", "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/telemetry/queue")
def api_telemetry_queue():
    """Legacy endpoint for existing TelemetryQueue component."""
    try:
        stats = get_byline_telemetry_stats()
        return {
            "queue_size": stats.pending_review,
            "worker_alive": True,  # Assume worker is alive if API is responding
            "total_processed": stats.total_extractions,
            "accuracy_rate": (
                (
                    stats.reviewed_correct
                    / max(
                        stats.reviewed_correct
                        + stats.reviewed_incorrect
                        + stats.reviewed_partial,
                        1,
                    )
                )
                if (
                    stats.reviewed_correct
                    + stats.reviewed_incorrect
                    + stats.reviewed_partial
                )
                > 0
                else 0
            ),
        }
    except Exception:
        return {
            "queue_size": 0,
            "worker_alive": False,
            "total_processed": 0,
            "accuracy_rate": 0,
        }


# --- URL Verification Telemetry Endpoints ---


@app.get("/api/verification_telemetry/pending")
def api_get_pending_verifications(limit: int = 50):
    """Get URL verifications that need human review."""
    try:
        items = get_pending_verification_reviews(limit=limit)
        return {
            "status": "ok",
            "count": len(items),
            "items": [item.dict() for item in items],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/verification_telemetry/feedback")
def api_submit_verification_feedback(feedback: VerificationFeedback):
    """Submit human feedback for a URL verification result."""
    try:
        success = submit_verification_feedback(feedback)
        if success:
            return {"status": "ok", "verification_id": feedback.verification_id}
        else:
            raise HTTPException(status_code=404, detail="Verification record not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/verification_telemetry/stats")
def api_get_verification_stats():
    """Get summary statistics for verification telemetry."""
    try:
        stats = get_verification_telemetry_stats()
        return stats.dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/verification_telemetry/training_data")
def api_get_verification_training_data(
    min_confidence: float = 0.0, format: str = "json"
):
    """Export labeled verification training data for ML."""
    try:
        data = get_labeled_verification_training_data(min_confidence=min_confidence)
        if format == "csv":
            # Return CSV format for download
            import csv
            import io

            output = io.StringIO()
            if data:
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            return {
                "status": "ok",
                "format": "csv",
                "content": output.getvalue(),
                "count": len(data),
            }
        else:
            return {"status": "ok", "format": "json", "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/verification_telemetry/enhance")
def api_enhance_verification(
    verification_id: str, headline: str = "", excerpt: str = ""
):
    """Add article content to verification for human review."""
    try:
        success = enhance_verification_with_content(verification_id, headline, excerpt)
        if success:
            return {"status": "ok", "verification_id": verification_id}
        else:
            raise HTTPException(status_code=404, detail="Verification record not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Code Review Telemetry Endpoints ---


@app.get("/api/code_review_telemetry/pending")
def api_get_pending_code_reviews(limit: int = 50):
    """Get code review items that need human review."""
    try:
        # Initialize tables if they don't exist
        init_code_review_tables()

        items = get_pending_code_reviews(limit=limit)
        return {
            "status": "ok",
            "count": len(items),
            "items": [item.dict() for item in items],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/code_review_telemetry/feedback")
def api_submit_code_review_feedback(feedback: CodeReviewFeedback):
    """Submit human feedback for a code review item."""
    try:
        success = submit_code_review_feedback(feedback)
        if success:
            return {"status": "ok", "review_id": feedback.review_id}
        else:
            raise HTTPException(status_code=404, detail="Code review record not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/code_review_telemetry/stats")
def api_get_code_review_stats():
    """Get summary statistics for code review telemetry."""
    try:
        stats = get_code_review_stats()
        return stats.dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/code_review_telemetry/add")
def api_add_code_review_item(item: CodeReviewItem):
    """Add a new code review item."""
    try:
        # Initialize tables if they don't exist
        init_code_review_tables()

        success = add_code_review_item(item)
        if success:
            return {"status": "ok", "review_id": item.review_id}
        else:
            raise HTTPException(
                status_code=500, detail="Failed to add code review item"
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
