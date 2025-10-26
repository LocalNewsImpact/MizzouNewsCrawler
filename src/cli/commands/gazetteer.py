"""Gazetteer population command for the modular CLI."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.models.database import DatabaseManager
from src.utils.process_tracker import ProcessContext

logger = logging.getLogger(__name__)

# scripts/ is at the project root, not in src/
# __file__ is src/cli/commands/gazetteer.py, so parents[3] gets us to project root
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:  # pragma: no cover - import side effect
    from populate_gazetteer import (
        main as run_gazetteer_population,  # type: ignore[import-not-found]
    )
except Exception as exc:  # pragma: no cover - import failure logging
    run_gazetteer_population = None
    logger.warning(
        "populate_gazetteer module unavailable (scripts dir: %s): %s",
        _SCRIPTS_DIR,
        exc,
    )


def add_gazetteer_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the populate-gazetteer command."""
    parser = subparsers.add_parser(
        "populate-gazetteer",
        help="Populate gazetteer from publisher locations",
    )
    parser.add_argument(
        "--dataset",
        help="Dataset slug to process (optional)",
    )
    parser.add_argument(
        "--address",
        help="Explicit address to geocode and query (optional)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        help="Coverage radius in miles (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to DB; just print results",
    )
    parser.add_argument(
        "--publisher",
        help="Publisher UUID for on-demand OSM enrichment",
    )
    parser.set_defaults(func=handle_gazetteer_command)


def handle_gazetteer_command(args: argparse.Namespace) -> int:
    """Run the gazetteer population workflow."""
    if run_gazetteer_population is None:
        print(
            "populate_gazetteer script not available; ensure scripts "
            "directory is on the PYTHONPATH"
        )
        return 1

    logger.info("Starting gazetteer population")

    db = DatabaseManager()
    database_url = str(db.engine.url)

    metadata: dict[str, object] = {
        "database_url": database_url,
        "auto_triggered": False,
    }
    dataset_slug: str | None = getattr(args, "dataset", None)
    if dataset_slug:
        metadata["dataset_slug"] = dataset_slug

    publisher_uuid: str | None = getattr(args, "publisher", None)
    if publisher_uuid:
        metadata["publisher_uuid"] = publisher_uuid
        metadata["processing_mode"] = "on_demand_publisher"
    elif dataset_slug:
        metadata["processing_mode"] = "bulk_dataset"

    if getattr(args, "address", None):
        metadata["test_address"] = args.address
        metadata["processing_mode"] = "test_address"

    if getattr(args, "radius", None) is not None:
        metadata["radius_miles"] = args.radius

    if getattr(args, "dry_run", False):
        metadata["dry_run"] = True

    command_parts = ["populate-gazetteer"]
    if dataset_slug:
        command_parts.extend(["--dataset", dataset_slug])
    if getattr(args, "address", None):
        command_parts.extend(["--address", args.address])
    if getattr(args, "radius", None) is not None:
        command_parts.extend(["--radius", str(args.radius)])
    if getattr(args, "dry_run", False):
        command_parts.append("--dry-run")
    if publisher_uuid:
        command_parts.extend(["--publisher", publisher_uuid])

    dataset_id: str | None = None
    if dataset_slug:
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import sessionmaker

            from src.models import Dataset
            from src.models.database import safe_session_execute

            Session = sessionmaker(bind=db.engine)
            with Session() as session:
                dataset = safe_session_execute(
                    session, select(Dataset).where(Dataset.slug == dataset_slug)
                ).scalar_one_or_none()
                if dataset:
                    metadata["dataset_id"] = str(dataset.id)
                    metadata["dataset_name"] = dataset.name
                    dataset_id = str(dataset.id)
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.warning("Could not resolve dataset metadata: %s", exc)

    with ProcessContext(
        process_type="gazetteer_population",
        command=" ".join([sys.executable, "-m", "src.cli.cli_modular", *command_parts]),
        dataset_id=dataset_id,
        source_id=publisher_uuid,
        metadata=metadata,
    ) as process:
        logger.info("Registered gazetteer process: %s", process.id)
        try:
            run_gazetteer_population(
                database_url=database_url,
                dataset_slug=dataset_slug,
                address=getattr(args, "address", None),
                radius_miles=getattr(args, "radius", None),
                dry_run=getattr(args, "dry_run", False),
                publisher=publisher_uuid,
            )
        except Exception as exc:  # pragma: no cover - passthrough logging
            logger.exception("Gazetteer population failed")
            print(f"Gazetteer population failed: {exc}")
            return 1

    logger.info("Gazetteer population completed successfully")
    print("Gazetteer population completed successfully")
    return 0
