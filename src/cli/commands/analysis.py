"""Machine-learning analysis command for the modular CLI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from src.models.database import DatabaseManager
from src.services.classification_service import ArticleClassificationService
from src.ml.article_classifier import ArticleClassifier

logger = logging.getLogger(__name__)


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
            "(default: cleaned local)"
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

    parser.set_defaults(func=handle_analysis_command)


def handle_analysis_command(args) -> int:
    """Execute the ML classification workflow."""
    logger.info("Starting ML analysis")

    label_version = (args.label_version or "default").strip() or "default"
    statuses: Iterable[str] = args.statuses or ["cleaned", "local"]
    batch_size = max(1, args.batch_size or 16)
    top_k = max(1, args.top_k or 2)
    model_path = Path(args.model_path or "models").expanduser()

    try:
        classifier = ArticleClassifier(model_path=model_path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to load classification model: %s", exc)
        return 1

    db = DatabaseManager()
    service = ArticleClassificationService(db.session)

    try:
        stats = service.apply_classification(
            classifier,
            label_version=label_version,
            model_version=args.model_version,
            model_path=str(model_path),
            statuses=list(statuses),
            limit=args.limit,
            batch_size=batch_size,
            top_k=top_k,
            dry_run=args.dry_run,
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
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Classification run failed: %s", exc)
        return 1
    finally:
        db.close()
