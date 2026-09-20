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
    _keep_credentials_out_of_the_log()


#: Loggers that must not follow a requested DEBUG level, and why.
#:
#: `selenium.webdriver.remote.remote_connection` logs every command sent to the
#: browser, and `send_keys` carries its text as the payload. So a subscriber
#: login at DEBUG writes the password into the log as cleartext:
#:
#:     POST .../element/.../value {'text': 'Newspaper1',
#:                                'value': ['N','e','w','s','p','a','p','e','r','1']}
#:
#: Measured 2026-09-20 on the first authenticated WSU run, whose template asked
#: for DEBUG so a watched login would say whether the session took. It did not
#: need DEBUG for that -- the crawler's own INFO lines say it:
#:
#:     🔐 tdn.com - subscriber login: authenticated browser only
#:     Authenticated session established for tdn.com
#:
#: Pod logs ship to Cloud Logging, so the exposure is not confined to the pod,
#: and the account is shared across a publisher group's titles.
#:
#: This is containment, not noise reduction. `src/utils/logging_config.py`
#: quiets the same library, but the CLI calls THIS function, so that one never
#: applied to an extraction run.
_NEVER_BELOW_INFO = (
    "selenium.webdriver.remote.remote_connection",
    # urllib3 at DEBUG prints request lines, which for a login POST names the
    # form endpoint. Not a credential, but it belongs to the same request.
    "urllib3.connectionpool",
)


def _keep_credentials_out_of_the_log() -> None:
    """Hold the wire loggers at INFO whatever level was asked for.

    Not "clamp unless the operator insists": there is no level at which a
    password in a log is what the operator wanted. A run that needs the browser
    protocol can raise these two by name, deliberately, on a host with no
    credentials.
    """
    for name in _NEVER_BELOW_INFO:
        logger = logging.getLogger(name)
        # The logger's OWN level, not its effective one. Reading the effective
        # level asks "would a DEBUG record pass right now", and the answer
        # depends on the root: while the root sits at WARNING the child looks
        # safe, so nothing is set, and the child -- still NOTSET -- goes on to
        # inherit whatever the root becomes next. That is the leak, arriving one
        # step later. A NOTSET level is 0, so the comparison covers it.
        if logger.level < logging.INFO:
            logger.setLevel(logging.INFO)


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
        from typing import Any, Callable, Optional

        from sqlalchemy import select
        from sqlalchemy.orm import sessionmaker

        from src.models import Dataset

        # `safe_session_execute` is a compatibility helper defined in
        # `src.models.database`. Tests sometimes monkeypatch `src.models.database`
        # with a minimal fake that only provides `DatabaseManager`. Make the
        # safe helper optional so tests that patch the module don't fail here.
        from src.models.database import DatabaseManager

        safe_session_execute: Optional[Callable[[Any, Any], Any]]
        try:
            # optional; falls back to using session.execute below
            from src.models.database import safe_session_execute  # type: ignore
        except Exception:
            safe_session_execute = None

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
