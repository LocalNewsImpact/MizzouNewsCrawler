"""
Telemetry system for byline cleaning transformations.

Captures detailed information about the cleaning process for ML training data
and performance analysis.
"""

import json
import time
import uuid
from datetime import datetime
from typing import Any

from src.config import DATABASE_URL
from src.telemetry.store import TelemetryStore, get_store


class BylineCleaningTelemetry:
    """Comprehensive telemetry collection for byline cleaning operations."""

    def __init__(
        self,
        enable_telemetry: bool = True,
        store: TelemetryStore | None = None,
        database_url: str = DATABASE_URL,
    ) -> None:
        """
        Initialize telemetry collector.

        Args:
            enable_telemetry: Whether to actually collect and store telemetry
        """
        self.enable_telemetry = enable_telemetry
        self.session_id = str(uuid.uuid4())
        self.step_counter = 0
        self._store: TelemetryStore = store or get_store(database_url)

        # Current cleaning session data
        self.current_session: dict[str, Any] | None = None
        self.transformation_steps: list[dict[str, Any]] = []

        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with self._store.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS byline_cleaning_telemetry (
                    id TEXT PRIMARY KEY,
                    article_id TEXT,
                    candidate_link_id TEXT,
                    source_id TEXT,
                    source_name TEXT,
                    raw_byline TEXT,
                    raw_byline_length INTEGER,
                    raw_byline_words INTEGER,
                    extraction_timestamp TIMESTAMP,
                    cleaning_method TEXT,
                    source_canonical_name TEXT,
                    final_authors_json TEXT,
                    final_authors_count INTEGER,
                    final_authors_display TEXT,
                    confidence_score REAL,
                    processing_time_ms REAL,
                    has_wire_service BOOLEAN,
                    has_email BOOLEAN,
                    has_title BOOLEAN,
                    has_organization BOOLEAN,
                    source_name_removed BOOLEAN,
                    duplicates_removed_count INTEGER,
                    likely_valid_authors BOOLEAN,
                    likely_noise BOOLEAN,
                    requires_manual_review BOOLEAN,
                    cleaning_errors TEXT,
                    parsing_warnings TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS byline_transformation_steps (
                    id TEXT PRIMARY KEY,
                    telemetry_id TEXT NOT NULL,
                    step_number INTEGER,
                    step_name TEXT,
                    input_text TEXT,
                    output_text TEXT,
                    transformation_type TEXT,
                    removed_content TEXT,
                    added_content TEXT,
                    confidence_delta REAL,
                    processing_time_ms REAL,
                    notes TEXT,
                    timestamp TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telemetry_id)
                        REFERENCES byline_cleaning_telemetry(id)
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_byline_steps_telemetry
                ON byline_transformation_steps(telemetry_id)
                """
            )

            conn.commit()

    def start_cleaning_session(
        self,
        raw_byline: str,
        article_id: str | None = None,
        candidate_link_id: str | None = None,
        source_id: str | None = None,
        source_name: str | None = None,
        source_canonical_name: str | None = None,
    ) -> str:
        """
        Start a new byline cleaning session.

        Returns:
            telemetry_id: Unique identifier for this cleaning session
        """
        if not self.enable_telemetry:
            return str(uuid.uuid4())

        telemetry_id = str(uuid.uuid4())
        start_time = time.time()

        self.current_session = {
            "telemetry_id": telemetry_id,
            "article_id": article_id,
            "candidate_link_id": candidate_link_id,
            "source_id": source_id,
            "source_name": source_name,
            "source_canonical_name": source_canonical_name,
            "raw_byline": raw_byline,
            "raw_byline_length": len(raw_byline) if raw_byline else 0,
            "raw_byline_words": len(raw_byline.split()) if raw_byline else 0,
            "start_time": start_time,
            "extraction_timestamp": datetime.now(),
            "has_wire_service": False,
            "has_email": False,
            "has_title": False,
            "has_organization": False,
            "source_name_removed": False,
            "duplicates_removed_count": 0,
            "cleaning_errors": [],
            "parsing_warnings": [],
            "confidence_score": 0.0,
        }

        self.transformation_steps = []
        self.step_counter = 0

        return telemetry_id

    def log_transformation_step(
        self,
        step_name: str,
        input_text: str,
        output_text: str,
        transformation_type: str = "processing",
        removed_content: str | None = None,
        added_content: str | None = None,
        confidence_delta: float = 0.0,
        notes: str | None = None,
    ):
        """Log a single transformation step in the cleaning process."""
        if not self.enable_telemetry or not self.current_session:
            return

        self.step_counter += 1
        step_start_time = time.time()

        step_data = {
            "id": str(uuid.uuid4()),
            "telemetry_id": self.current_session["telemetry_id"],
            "step_number": self.step_counter,
            "step_name": step_name,
            "input_text": input_text,
            "output_text": output_text,
            "transformation_type": transformation_type,
            "removed_content": removed_content,
            "added_content": added_content,
            "confidence_delta": confidence_delta,
            "processing_time_ms": (time.time() - step_start_time) * 1000,
            "notes": notes,
            "timestamp": datetime.now(),
        }

        self.transformation_steps.append(step_data)

        # Update session metadata based on transformation
        if step_name == "email_removal" and removed_content:
            self.current_session["has_email"] = True

        if step_name == "source_removal" and removed_content:
            self.current_session["source_name_removed"] = True

        if (
            step_name == "wire_service_detection"
            and "wire service" in str(notes).lower()
        ):
            self.current_session["has_wire_service"] = True

        if step_name == "duplicate_removal" and removed_content:
            # Count removed duplicates
            if removed_content:
                removed_count = len(
                    [item for item in removed_content.split(",") if item.strip()]
                )
                self.current_session["duplicates_removed_count"] += removed_count

        # Update running confidence score
        self.current_session["confidence_score"] += confidence_delta

    def log_error(self, error_message: str, error_type: str = "processing"):
        """Log an error during cleaning."""
        if not self.enable_telemetry or not self.current_session:
            return

        error_data = {
            "type": error_type,
            "message": error_message,
            "timestamp": datetime.now().isoformat(),
            "step": self.step_counter,
        }

        self.current_session["cleaning_errors"].append(error_data)

    def log_warning(self, warning_message: str, warning_type: str = "parsing"):
        """Log a warning during cleaning."""
        if not self.enable_telemetry or not self.current_session:
            return

        warning_data = {
            "type": warning_type,
            "message": warning_message,
            "timestamp": datetime.now().isoformat(),
            "step": self.step_counter,
        }

        self.current_session["parsing_warnings"].append(warning_data)

    def finalize_cleaning_session(
        self,
        final_authors: list[str],
        cleaning_method: str = "standard",
        likely_valid_authors: bool | None = None,
        likely_noise: bool | None = None,
        requires_manual_review: bool | None = None,
    ):
        """
        Finalize the cleaning session and store telemetry data.

        Args:
            final_authors: List of final cleaned author names
            cleaning_method: Method used for cleaning
            likely_valid_authors: Whether authors appear to be valid
            likely_noise: Whether result appears to be noise
            requires_manual_review: Whether result needs manual review
        """
        if not self.enable_telemetry or not self.current_session:
            return

        # Calculate final metrics
        total_time = (time.time() - self.current_session["start_time"]) * 1000

        # Update session with final data
        self.current_session.update(
            {
                "cleaning_method": cleaning_method,
                "final_authors_json": json.dumps(final_authors),
                "final_authors_count": len(final_authors),
                "final_authors_display": ", ".join(final_authors),
                "processing_time_ms": total_time,
                "likely_valid_authors": likely_valid_authors,
                "likely_noise": likely_noise,
                "requires_manual_review": requires_manual_review,
                "cleaning_errors": json.dumps(self.current_session["cleaning_errors"]),
                "parsing_warnings": json.dumps(
                    self.current_session["parsing_warnings"]
                ),
            }
        )

        # Store the session data
        self._store_telemetry_data()

        # Reset for next session
        self.current_session = None
        self.transformation_steps = []
        self.step_counter = 0

    def _store_telemetry_data(self):
        """Store the current session telemetry data to database."""
        if not self.current_session:
            return

        session = dict(self.current_session)
        steps = [dict(step) for step in self.transformation_steps]

        def writer(conn):
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO byline_cleaning_telemetry (
                        id, article_id, candidate_link_id, source_id,
                        source_name, raw_byline, raw_byline_length,
                        raw_byline_words, extraction_timestamp,
                        cleaning_method,
                        source_canonical_name, final_authors_json,
                        final_authors_count, final_authors_display,
                        confidence_score, processing_time_ms, has_wire_service,
                        has_email, has_title, has_organization,
                        source_name_removed, duplicates_removed_count,
                        likely_valid_authors, likely_noise,
                        requires_manual_review, cleaning_errors,
                        parsing_warnings
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                             ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session["telemetry_id"],
                        session.get("article_id"),
                        session.get("candidate_link_id"),
                        session.get("source_id"),
                        session.get("source_name"),
                        session["raw_byline"],
                        session["raw_byline_length"],
                        session["raw_byline_words"],
                        session["extraction_timestamp"],
                        session.get("cleaning_method"),
                        session.get("source_canonical_name"),
                        session.get("final_authors_json"),
                        session.get("final_authors_count"),
                        session.get("final_authors_display"),
                        session["confidence_score"],
                        session.get("processing_time_ms"),
                        session["has_wire_service"],
                        session["has_email"],
                        session["has_title"],
                        session["has_organization"],
                        session["source_name_removed"],
                        session["duplicates_removed_count"],
                        session.get("likely_valid_authors"),
                        session.get("likely_noise"),
                        session.get("requires_manual_review"),
                        session.get("cleaning_errors"),
                        session.get("parsing_warnings"),
                    ),
                )

                for step in steps:
                    cursor.execute(
                        """
                        INSERT INTO byline_transformation_steps (
                            id, telemetry_id, step_number, step_name,
                            input_text, output_text, transformation_type,
                            removed_content, added_content, confidence_delta,
                            processing_time_ms, notes, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            step["id"],
                            step["telemetry_id"],
                            step["step_number"],
                            step["step_name"],
                            step["input_text"],
                            step["output_text"],
                            step["transformation_type"],
                            step.get("removed_content"),
                            step.get("added_content"),
                            step["confidence_delta"],
                            step["processing_time_ms"],
                            step.get("notes"),
                            step["timestamp"],
                        ),
                    )
            finally:
                cursor.close()

        try:
            self._store.submit(writer)
        except Exception as exc:  # pragma: no cover - telemetry best effort
            print(f"Warning: Failed to store telemetry data: {exc}")
            # Don't fail the cleaning process due to telemetry issues

    def flush(self) -> None:
        if self.enable_telemetry:
            self._store.flush()

    def get_session_summary(self) -> dict[str, Any] | None:
        """Get a summary of the current cleaning session."""
        if not self.current_session:
            return None

        return {
            "telemetry_id": self.current_session["telemetry_id"],
            "raw_byline": self.current_session["raw_byline"],
            "steps_completed": self.step_counter,
            "confidence_score": self.current_session["confidence_score"],
            "has_errors": len(self.current_session["cleaning_errors"]) > 0,
            "has_warnings": len(self.current_session["parsing_warnings"]) > 0,
        }


# Global telemetry instance for easy use
telemetry = BylineCleaningTelemetry()
