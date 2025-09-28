"""Machine-learning analysis command for the modular CLI."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from sqlalchemy import select

from src.models import Article, ArticleLabel
from src.models.database import DatabaseManager
from src.services.classification_service import ArticleClassificationService
from src.ml.article_classifier import ArticleClassifier

logger = logging.getLogger(__name__)

EXCLUDED_STATUSES = {"opinion", "opinions", "obituary", "obits", "wire"}


def _resolve_statuses(
    raw_statuses: Iterable[str] | None,
) -> Optional[list[str]]:
    if not raw_statuses:
        return ["cleaned", "local"]

    normalized = [
        status.strip().lower()
        for status in raw_statuses
        if isinstance(status, str) and status.strip()
    ]

    if not normalized:
        return ["cleaned", "local"]

    if any(status == "all" for status in normalized):
        return None

    # Preserve input order while removing duplicates
    unique: list[str] = []
    for status in normalized:
        if status not in unique:
            unique.append(status)
    return unique


def _filtered_statuses(
    statuses: Optional[Sequence[str]],
) -> Optional[list[str]]:
    if statuses is None:
        return None

    filtered = [
        status for status in statuses if status not in EXCLUDED_STATUSES
    ]
    return filtered


def _snapshot_labels(
    session,
    label_version: str,
    statuses: Optional[Sequence[str]],
) -> Dict[str, Dict[str, Optional[str]]]:
    stmt = (
        select(
            Article.id,
            Article.url,
            ArticleLabel.primary_label,
            ArticleLabel.alternate_label,
        )
        .outerjoin(
            ArticleLabel,
            (ArticleLabel.article_id == Article.id)
            & (ArticleLabel.label_version == label_version),
        )
    )

    if statuses is None:
        stmt = stmt.where(Article.status.notin_(list(EXCLUDED_STATUSES)))
    elif not statuses:
        return {}
    else:
        stmt = stmt.where(Article.status.in_(list(statuses)))

    rows = session.execute(stmt).all()
    snapshot: Dict[str, Dict[str, Optional[str]]] = {}
    for article_id, url, primary, alternate in rows:
        snapshot[str(article_id)] = {
            "url": url,
            "primary": primary,
            "alternate": alternate,
        }

    return snapshot


def _compute_label_changes(
    before: Dict[str, Dict[str, Optional[str]]],
    after: Dict[str, Dict[str, Optional[str]]],
    label_version: str,
) -> list[Dict[str, str]]:
    changes: list[Dict[str, str]] = []
    for article_id in sorted(set(before) | set(after)):
        before_entry = before.get(article_id, {})
        after_entry = after.get(article_id, {})

        old_primary = before_entry.get("primary")
        new_primary = after_entry.get("primary")

        if old_primary == new_primary:
            continue

        old_alternate = before_entry.get("alternate")
        new_alternate = after_entry.get("alternate")
        url = after_entry.get("url") or before_entry.get("url") or ""

        changes.append(
            {
                "article_id": article_id,
                "url": url,
                "label_version": label_version,
                "old_primary_label": old_primary or "",
                "new_primary_label": new_primary or "",
                "old_alternate_label": old_alternate or "",
                "new_alternate_label": new_alternate or "",
            }
        )

    return changes


def _compute_dry_run_changes(
    before: Dict[str, Dict[str, Optional[str]]],
    proposals: Sequence[Dict[str, object]],
    label_version: str,
) -> list[Dict[str, str]]:
    changes: list[Dict[str, str]] = []
    for proposal in proposals:
        raw_id = proposal.get("article_id")
        article_id = str(raw_id) if raw_id is not None else ""
        before_entry = before.get(article_id, {})

        old_primary = before_entry.get("primary")
        old_alternate = before_entry.get("alternate")

        new_primary_obj = proposal.get("primary")
        new_primary = (
            new_primary_obj
            if isinstance(new_primary_obj, str)
            else (str(new_primary_obj) if new_primary_obj is not None else "")
        )

        new_alternate_obj = proposal.get("alternate")
        new_alternate = (
            new_alternate_obj
            if isinstance(new_alternate_obj, str)
            else (
                str(new_alternate_obj)
                if new_alternate_obj is not None
                else ""
            )
        )

        if (old_primary or "") == (new_primary or ""):
            continue

        url_obj = proposal.get("url")
        url = (
            url_obj
            if isinstance(url_obj, str)
            else (str(url_obj) if url_obj is not None else "")
        )
        if not url:
            url = before_entry.get("url") or ""

        changes.append(
            {
                "article_id": article_id,
                "url": url,
                "label_version": label_version,
                "old_primary_label": old_primary or "",
                "new_primary_label": new_primary or "",
                "old_alternate_label": old_alternate or "",
                "new_alternate_label": new_alternate or "",
            }
        )

    return changes


def _write_label_changes(
    report_path: Path,
    changes: Sequence[Dict[str, str]],
) -> Path:
    report_path = report_path.expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "article_id",
        "url",
        "label_version",
        "old_primary_label",
        "new_primary_label",
        "old_alternate_label",
        "new_alternate_label",
    ]

    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in changes:
            writer.writerow(row)

    return report_path


def add_analysis_parser(subparsers) -> None:
    """Register the ``analyze`` subcommand and its arguments."""
    parser = subparsers.add_parser(
        "analyze",
        help="Run ML analysis",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum articles to analyze",
    )
    parser.add_argument(
        "--label-version",
        default="default",
        help="Version identifier for stored labels (default: default)",
    )
    parser.add_argument(
        "--model-path",
        default=str(Path("models")),
        help="Path or identifier for the classification model",
    )
    parser.add_argument(
        "--model-version",
        help="Override model version metadata stored with labels",
    )
    parser.add_argument(
        "--statuses",
        nargs="+",
        default=["cleaned", "local"],
        help=(
            "Article statuses eligible for classification "
            "(default: cleaned local). Use 'all' to include every status."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Number of articles per classification batch (default: 16)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=2,
        help="Number of predictions to keep per article (default: 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run classification without saving results",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Reclassify articles even if labels already exist for the "
            "selected label version"
        ),
    )
    parser.add_argument(
        "--report-path",
        help=(
            "Optional CSV path for label-change report. If omitted, a "
            "timestamped report is written to the reports/ directory when "
            "labels change."
        ),
    )

    parser.set_defaults(func=handle_analysis_command)


def handle_analysis_command(args) -> int:
    """Execute the ML classification workflow."""
    logger.info("Starting ML analysis")

    label_version = (args.label_version or "default").strip() or "default"
    resolved_statuses = _resolve_statuses(args.statuses)
    filtered_statuses = _filtered_statuses(resolved_statuses)
    batch_size = max(1, args.batch_size or 16)
    top_k = max(1, args.top_k or 2)
    model_path = Path(args.model_path or "models").expanduser()
    collect_diff = bool(args.report_path)

    try:
        classifier = ArticleClassifier(model_path=model_path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to load classification model: %s", exc)
        return 1

    db = DatabaseManager()
    service = ArticleClassificationService(db.session)

    try:
        before_snapshot: Dict[str, Dict[str, Optional[str]]] = {}
        if collect_diff:
            before_snapshot = _snapshot_labels(
                db.session,
                label_version,
                filtered_statuses,
            )

        stats = service.apply_classification(
            classifier,
            label_version=label_version,
            model_version=args.model_version,
            model_path=str(model_path),
            statuses=resolved_statuses,
            limit=args.limit,
            batch_size=batch_size,
            top_k=top_k,
            dry_run=args.dry_run,
            include_existing=args.force,
        )

        print("\n=== Classification Summary ===")
        print(f"Articles eligible: {stats.processed}")
        print(f"Predictions saved: {stats.labeled}")
        print(f"Skipped (empty/no prediction): {stats.skipped}")
        print(f"Errors: {stats.errors}")
        if args.dry_run:
            print("\nDry-run mode: no labels were persisted.")

        logger.info(
            (
                "Classification complete: processed=%s labeled=%s "
                "skipped=%s errors=%s"
            ),
            stats.processed,
            stats.labeled,
            stats.skipped,
            stats.errors,
        )

        if collect_diff:
            if args.dry_run:
                changes = _compute_dry_run_changes(
                    before_snapshot,
                    stats.proposed_labels,
                    label_version,
                )
            else:
                after_snapshot = _snapshot_labels(
                    db.session,
                    label_version,
                    filtered_statuses,
                )
                changes = _compute_label_changes(
                    before_snapshot,
                    after_snapshot,
                    label_version,
                )

            report_path = Path(args.report_path).expanduser()

            if changes:
                written_path = _write_label_changes(report_path, changes)
                print("\n=== Label Change Report ===")
                print(f"Rows written: {len(changes)}")
                print(f"Location: {written_path}")
                logger.info(
                    "Label change report written to %s with %s rows",
                    written_path,
                    len(changes),
                )
            else:
                print("\n=== Label Change Report ===")
                print(
                    "No label changes detected; no CSV written because "
                    "no differences were found."
                )
        else:
            print("\n=== Label Change Report ===")
            print("Report generation skipped (use --report-path to export).")

        return 0
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Classification run failed: %s", exc)
        return 1
    finally:
        db.close()
