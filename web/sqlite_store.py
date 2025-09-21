"""Lightweight SQLite store for site_specs, feedback, and articles.

This module provides helpers to initialize a DB, migrate existing CSVs,
and perform transactional upserts/queries used by the reviewer API.
"""

import csv
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = ROOT / "lookups"
PROCESSED = ROOT / "processed"
DB_PATH = LOOKUPS / "site_specs.db"


def get_conn(path: Optional[Path] = None):
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Optional[Path] = None):
    conn = get_conn(path)
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS site_specs (
                id INTEGER PRIMARY KEY,
                domain TEXT UNIQUE NOT NULL,
                url_pattern TEXT,
                headline_selector TEXT,
                author_selector TEXT,
                date_selector TEXT,
                body_selector TEXT,
                tags_selector TEXT,
                use_jsonld INTEGER DEFAULT 0,
                requires_js INTEGER DEFAULT 0,
                last_tested TEXT,
                skip_patterns TEXT,
                force_include_patterns TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                field TEXT,
                old_value TEXT,
                new_value TEXT,
                comment TEXT,
                reviewer TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articleslabelled (
                id TEXT PRIMARY KEY,
                domain TEXT,
                url TEXT,
                news TEXT,
                label TEXT
            )
            """
        )
    conn.close()


def upsert_site_spec(domain: str, data: Dict[str, Any]):
    conn = get_conn()
    with conn:
        # try to insert or update
        conn.execute(
            """
            INSERT INTO site_specs (
                domain, url_pattern, headline_selector,
                author_selector, date_selector, body_selector, tags_selector,
                use_jsonld, requires_js, last_tested, skip_patterns,
                force_include_patterns, notes
            )
            VALUES (
                :domain, :url_pattern, :headline_selector, :author_selector,
                :date_selector, :body_selector, :tags_selector, :use_jsonld,
                :requires_js, :last_tested, :skip_patterns,
                :force_include_patterns, :notes
            )
            ON CONFLICT(domain) DO UPDATE SET
                url_pattern=excluded.url_pattern,
                headline_selector=excluded.headline_selector,
                author_selector=excluded.author_selector,
                date_selector=excluded.date_selector,
                body_selector=excluded.body_selector,
                tags_selector=excluded.tags_selector,
                use_jsonld=excluded.use_jsonld,
                requires_js=excluded.requires_js,
                last_tested=excluded.last_tested,
                skip_patterns=excluded.skip_patterns,
                force_include_patterns=excluded.force_include_patterns,
                notes=excluded.notes
            """,
            {
                "domain": domain,
                "url_pattern": data.get("url_pattern", ""),
                "headline_selector": data.get("headline_selector", ""),
                "author_selector": data.get("author_selector", ""),
                "date_selector": data.get("date_selector", ""),
                "body_selector": data.get("body_selector", ""),
                "tags_selector": data.get("tags_selector", ""),
                "use_jsonld": int(bool(data.get("use_jsonld", False))),
                "requires_js": int(bool(data.get("requires_js", False))),
                "last_tested": data.get("last_tested", None),
                "skip_patterns": data.get("skip_patterns", ""),
                "force_include_patterns": data.get("force_include_patterns", ""),
                "notes": data.get("notes", ""),
            },
        )
    conn.close()


def get_site_spec(domain: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.execute("SELECT * FROM site_specs WHERE domain = ?", (domain,))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def export_site_specs_csv(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    cur = conn.execute("SELECT * FROM site_specs ORDER BY domain")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    if not rows:
        # write an empty CSV with header defaults
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
            "notes",
        ]
    else:
        fieldnames = [k for k in rows[0].keys() if k != "id"]

    with open(path, "w", newline="", encoding="utf8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            out = {k: v for k, v in r.items() if k in fieldnames}
            writer.writerow(out)


def append_feedback(row: Dict[str, Any]):
    conn = get_conn()
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO feedback (
                id, field, old_value, new_value,
                comment, reviewer, created_at
            ) VALUES (
                :id, :field, :old_value, :new_value,
                :comment, :reviewer, :created_at
            )
            """,
            {
                "id": row.get("id"),
                "field": row.get("field"),
                "old_value": row.get("old_value", ""),
                "new_value": row.get("new_value", ""),
                "comment": row.get("comment", ""),
                "reviewer": row.get("reviewer", ""),
                "created_at": row.get("created_at", None),
            },
        )
    conn.close()


def get_articles(limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM articleslabelled"
    params = []
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def migrate_from_csvs():
    """Migrate existing CSV artifacts into the DB (idempotent).

    This imports `lookups/site_specs.csv`, `processed/feedback.csv`, and
    `processed/articleslabelled_7.csv` if they exist.
    """
    init_db()
    # migrate site_specs
    site_specs_csv = LOOKUPS / "site_specs.csv"
    if site_specs_csv.exists():
        with open(site_specs_csv, newline="", encoding="utf8") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                domain = r.get("domain")
                if not domain:
                    continue
                upsert_site_spec(domain, r)
        # optional: remove or leave CSV in place

    # migrate feedback
    feedback_csv = PROCESSED / "feedback.csv"
    if feedback_csv.exists():
        with open(feedback_csv, newline="", encoding="utf8") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                row = {
                    "id": r.get("id") or r.get("article_id") or None,
                    "field": r.get("field"),
                    "old_value": r.get("old_value"),
                    "new_value": r.get("new_value"),
                    "comment": r.get("comment"),
                    "reviewer": r.get("reviewer"),
                    "created_at": r.get("created_at") or None,
                }
                append_feedback(row)

    # migrate articleslabelled_7.csv
    articles_csv = PROCESSED / "articleslabelled_7.csv"
    if articles_csv.exists():
        with open(articles_csv, newline="", encoding="utf8") as fh:
            reader = csv.DictReader(fh)
            conn = get_conn()
            with conn:
                for r in reader:
                    try:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO articleslabelled (
                                id, domain, url, news, label
                            ) VALUES (
                                :id, :domain, :url, :news, :label
                            )
                            """,
                            {
                                "id": (
                                    r.get("id") or r.get("article_id") or r.get("url")
                                ),
                                "domain": r.get("domain") or "",
                                "url": r.get("url") or "",
                                "news": r.get("news") or "",
                                "label": r.get("label") or "",
                            },
                        )
                    except Exception:
                        # skip malformed rows
                        continue
            conn.close()
