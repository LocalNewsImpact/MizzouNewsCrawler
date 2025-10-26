"""Shared utilities for CLI command modules."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

DEFAULT_LOG_FILE = "crawler.log"


def setup_logging(
    log_level: str = "INFO",
    log_file: str = DEFAULT_LOG_FILE,
) -> None:
    """Configure root logging for CLI commands.

    Parameters
    ----------
    log_level:
        Logging level name (e.g., ``"INFO"``).
    log_file:
        Path to the log file for persistent logs.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )


def trigger_gazetteer_population_background(
    dataset_slug: str,
    logger: logging.Logger,
) -> None:
    """Trigger gazetteer population in a background process.

    Parameters
    ----------
    dataset_slug:
        Dataset slug to populate.
    logger:
        Logger for status updates.
    """
    import subprocess

    from src.utils.process_tracker import get_tracker

    tracker = get_tracker()

    cmd = [
        sys.executable,
        "-m",
        "src.cli.cli_modular",
        "populate-gazetteer",
        "--dataset",
        dataset_slug,
    ]

    metadata = {"auto_triggered": True, "dataset_slug": dataset_slug}

    dataset_id: str | None = None
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import sessionmaker

        from src.models import Dataset

        # `safe_session_execute` is a compatibility helper defined in
        # `src.models.database`. Tests sometimes monkeypatch `src.models.database`
        # with a minimal fake that only provides `DatabaseManager`. Make the
        # safe helper optional so tests that patch the module don't fail here.
        from src.models.database import DatabaseManager

        try:
            # optional; falls back to using session.execute below
            from src.models.database import safe_session_execute  # type: ignore
        except Exception:
            safe_session_execute = None

        db = DatabaseManager()
        Session = sessionmaker(bind=db.engine)
        with Session() as session:
            if safe_session_execute is not None:
                dataset = safe_session_execute(
                    session, select(Dataset).where(Dataset.slug == dataset_slug)
                ).scalar_one_or_none()
            else:
                # fall back to direct Session.execute when the compatibility
                # helper isn't available (e.g., in lightweight test fakes)
                dataset = session.execute(
                    select(Dataset).where(Dataset.slug == dataset_slug)
                ).scalar_one_or_none()

            if dataset:
                metadata["dataset_id"] = str(dataset.id)
                metadata["dataset_name"] = dataset.name
                dataset_id = str(dataset.id)
    except Exception as exc:  # pragma: no cover - log and continue
        logger.warning("Could not look up dataset for telemetry: %s", exc)

    process = tracker.register_process(
        process_type="gazetteer_population",
        command=" ".join(cmd),
        dataset_id=dataset_id,
        metadata=metadata,
    )

    process_id = str(process.id)

    logger.info("Starting background gazetteer population: %s", " ".join(cmd))

    try:
        project_root = Path(__file__).resolve().parent.parent
        proc = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        tracker.update_progress(
            process_id,
            current=0,
            message=f"Started background process (PID: {proc.pid})",
            status="running",
        )
        logger.info("Gazetteer population started in background (PID: %s)", proc.pid)
        logger.info(
            "Track progress with: python -m src.cli.cli_modular status --process %s",
            process_id,
        )
    except Exception as exc:  # pragma: no cover - log and re-raise
        tracker.complete_process(process_id, "failed", error_message=str(exc))
        logger.error(
            "Failed to start background gazetteer population: %s",
            exc,
        )
        raise
