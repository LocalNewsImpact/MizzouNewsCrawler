import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import text

try:
    from src.crawler import ContentExtractor
    from src.utils.comprehensive_telemetry import ExtractionMetrics
    from src.models.database import DatabaseManager
except Exception:
    # Attempt to add /app to PYTHONPATH when running the script from /tmp or other locations
    import os
    app_dir = "/app"
    if os.path.isdir(app_dir) and app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        from src.crawler import ContentExtractor
        from src.utils.comprehensive_telemetry import ExtractionMetrics
        from src.models.database import DatabaseManager
    except Exception as exc:
        print(f"Error importing dependencies: {exc}", file=sys.stderr)
        sys.exit(2)


def _query_candidates(
    session,
    source_exact: Optional[str],
    source_like: Optional[str],
    hours: int,
    limit: int,
    statuses: Optional[List[str]] = None,
    include_extracted: bool = False,
) -> List[Tuple[str, str, str]]:
    since_ts = datetime.utcnow() - timedelta(hours=hours)
    where_clauses = ["cl.discovered_at >= :since"]
    params = {"since": since_ts, "limit": limit}

    # Status filter list (optional)
    if statuses:
        st_params = {}
        st_placeholders = []
        for i, st in enumerate(statuses):
            key = f"st{i}"
            st_params[key] = st
            st_placeholders.append(f":{key}")
        params.update(st_params)
        where_clauses.append(f"cl.status IN ({', '.join(st_placeholders)})")

    # Source filter: exact OR pattern
    if source_like:
        where_clauses.append("(cl.source ILIKE :source_like OR cl.url ILIKE :source_like)")
        params["source_like"] = source_like
    elif source_exact:
        where_clauses.append("cl.source = :source_exact")
        params["source_exact"] = source_exact

    where_sql = "\n          AND ".join(where_clauses)
    not_exists_clause = "" if include_extracted else (
        "\n          AND NOT EXISTS (\n            SELECT 1 FROM articles a WHERE a.candidate_link_id = cl.id\n          )\n"
    )
    q = text(
        f"""
                SELECT cl.id, cl.url, cl.source
        FROM candidate_links cl
        WHERE {where_sql}{not_exists_clause}
        ORDER BY cl.discovered_at DESC
        LIMIT :limit
        """
    )
    rows = session.execute(q, params).fetchall()
    return [(str(r[0]), r[1], r[2]) for r in rows]


def _query_source_flags(session, source: str):
    row = session.execute(
        text(
            """
            SELECT extraction_method, bot_protection_type, selenium_only
            FROM sources WHERE host = :host
            """
        ),
        {"host": source},
    ).fetchone()
    if not row:
        return {"extraction_method": None, "bot_protection_type": None, "selenium_only": None}
    return {
        "extraction_method": row[0],
        "bot_protection_type": row[1],
        "selenium_only": bool(row[2]) if row[2] is not None else None,
    }


def run_diagnostic(
    sources: List[str],
    hours: int,
    per_source_limit: int,
    force_all_methods: bool = False,
    statuses: Optional[List[str]] = None,
    include_extracted: bool = False,
):
    db = DatabaseManager()
    extractor = ContentExtractor(selenium_mode=None)

    # Optional override to try HTTP methods even when domain is flagged
    if force_all_methods:
        try:
            # Prefer HTTP methods first during diagnostics and allow unblock fallback
            setattr(extractor, "_selenium_primary_strategy", "http-first")
            setattr(extractor, "_allow_unblock_after_selenium_fail", True)
        except Exception:
            pass

    results = []
    with db.get_session() as session:
        for src in sources:
            # Treat values containing '%' as patterns for ILIKE
            is_pattern = "%" in src
            flags = _query_source_flags(session, src) if not is_pattern else {
                "extraction_method": None,
                "bot_protection_type": None,
                "selenium_only": None,
            }
            candidates = _query_candidates(
                session,
                source_exact=None if is_pattern else src,
                source_like=src if is_pattern else None,
                hours=hours,
                limit=per_source_limit,
                statuses=statuses,
                include_extracted=include_extracted,
            )
            for (cid, url, host) in candidates:
                op_id = f"diag_{cid}"
                art_id = f"diag_{cid}"
                metrics = ExtractionMetrics(op_id, art_id, url, host)
                try:
                    content = extractor.extract_content(url, metrics=metrics)
                except Exception as exc:
                    content = {}
                    metrics.error_message = str(exc)
                    metrics.error_type = type(exc).__name__
                finally:
                    metrics.finalize(content or {})

                results.append(
                    {
                        "candidate_id": cid,
                        "url": url,
                        "source": host,
                        "source_flags": flags,
                        "methods_attempted": metrics.methods_attempted,
                        "method_success": metrics.method_success,
                        "method_errors": metrics.method_errors,
                        "successful_method": metrics.successful_method,
                        "final_field_attribution": metrics.final_field_attribution,
                        "is_success": metrics.is_success,
                        "http_status_code": metrics.http_status_code,
                        "error": metrics.error_message,
                    }
                )
    return results


def main():
    parser = argparse.ArgumentParser(description="Diagnose extraction methods per source")
    parser.add_argument("--source", action="append", help="Source host or ILIKE pattern (can repeat)")
    parser.add_argument("--hours", type=int, default=24, help="Hours back to search candidates")
    parser.add_argument("--limit", type=int, default=5, help="Max URLs per source")
    parser.add_argument("--force-all-methods", action="store_true", help="Try HTTP methods even for selenium/unblock domains (diagnostic)")
    parser.add_argument(
        "--status",
        type=str,
        default="article,verified",
        help="Comma-separated candidate statuses (default: article,verified). Use empty to disable.",
    )
    parser.add_argument(
        "--include-extracted",
        action="store_true",
        help="Include candidates even if an article already exists (useful for site diagnostics)",
    )
    parser.add_argument("--out", type=str, default="tmp/extraction_methods_diag.json", help="Output JSON file")
    args = parser.parse_args()

    if not args.source:
        print("Please provide at least one --source host", file=sys.stderr)
        return 2

    statuses = [s.strip() for s in args.status.split(",") if s.strip()] if args.status else None
    results = run_diagnostic(
        args.source,
        args.hours,
        args.limit,
        force_all_methods=args.force_all_methods,
        statuses=statuses,
        include_extracted=args.include_extracted,
    )

    # Save JSON
    out_path = args.out
    try:
        import os
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    except Exception:
        pass

    with open(out_path, "w") as f:
        json.dump({"generated_at": datetime.utcnow().isoformat(), "results": results}, f, indent=2)

    # Print concise summary
    print("\nExtraction Methods Diagnostic Summary:\n")
    for r in results:
        status = "SUCCESS" if r["is_success"] else "FAIL"
        print(f"- {status} {r['source']} → {r['url']}")
        flags = r["source_flags"]
        print(
            f"  flags: method={flags.get('extraction_method')}, protection={flags.get('bot_protection_type')}, selenium_only={flags.get('selenium_only')}"
        )
        print(f"  attempted: {', '.join(r['methods_attempted'])}")
        if r["successful_method"]:
            print(f"  successful: {r['successful_method']}")
        if r["error"]:
            print(f"  error: {r['error']}")
    print(f"\nSaved detailed JSON: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
