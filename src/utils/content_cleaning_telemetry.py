"""
Telemetry system for content cleaning operations.

Captures detailed information about boilerplate detection and removal decisions
for ML training data and performance analysis.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from src.config import DATABASE_URL
from src.telemetry.store import TelemetryStore, get_store


class ContentCleaningTelemetry:
    """Comprehensive telemetry collection for content cleaning operations."""

    def __init__(
        self,
        enable_telemetry: bool = True,
        store: TelemetryStore | None = None,
        database_url: str = DATABASE_URL,
    ):
        """
        Initialize telemetry collector.

        Args:
            enable_telemetry: Whether to actually collect and store telemetry
        """
        self.enable_telemetry = enable_telemetry
        self.session_id = str(uuid.uuid4())
        self.detection_counter = 0
        self._store: TelemetryStore | None = store
        self._database_url = database_url
        self._tables_initialized = False

        # Current cleaning session data
        self.current_session: dict[str, Any] | None = None
        self.detected_segments: list[dict[str, Any]] = []
        self.wire_detection_events: list[dict[str, Any]] = []
        self.locality_detection_events: list[dict[str, Any]] = []
        self._last_boundary_assessment: dict[str, Any] | None = None

    @property
    def store(self) -> TelemetryStore:
        """Lazy-load the store only when needed."""
        if not self.enable_telemetry:
            raise RuntimeError("Telemetry is disabled")
        
        if self._store is None:
            self._store = get_store(self._database_url)
        return self._store

    def start_cleaning_session(
        self,
        domain: str,
        article_count: int,
        min_occurrences: int = 3,
        min_boundary_score: float = 0.3,
    ) -> str:
        """
        Start a new content cleaning session.

        Returns:
            telemetry_id: Unique identifier for this cleaning session
        """
        if not self.enable_telemetry:
            return ""

        telemetry_id = str(uuid.uuid4())

        self.current_session = {
            "telemetry_id": telemetry_id,
            "session_id": self.session_id,
            "domain": domain,
            "article_count": article_count,
            "min_occurrences": min_occurrences,
            "min_boundary_score": min_boundary_score,
            "start_time": datetime.now(),
            "processing_time_ms": None,
            "rough_candidates_found": None,
            "segments_detected": None,
            "total_removable_chars": None,
            "removal_percentage": None,
        }

        # Reset counters and state
        self.detection_counter = 0
        self.detected_segments = []
        self.wire_detection_events = []
        self.locality_detection_events = []

        return telemetry_id

    def log_wire_detection(
        self,
        provider: str,
        detection_method: str,
        pattern_text: str,
        confidence: float,
        detection_stage: str,
        article_ids: list[str] | None = None,
        domain: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log when wire service attribution is detected in boilerplate."""
        if not self.enable_telemetry or not self.current_session:
            return

        event = {
            "id": str(uuid.uuid4()),
            "telemetry_id": self.current_session["telemetry_id"],
            "session_id": self.current_session["session_id"],
            "domain": domain or self.current_session["domain"],
            "provider": provider,
            "detection_method": detection_method,
            "detection_stage": detection_stage,
            "confidence": confidence,
            "pattern_text": pattern_text,
            "pattern_text_hash": hash(pattern_text),
            "article_ids_json": json.dumps(article_ids or []),
            "metadata_json": json.dumps(extra_metadata or {}),
            "timestamp": datetime.now(),
        }

        self.wire_detection_events.append(event)

    def log_locality_detection(
        self,
        provider: str | None,
        detection_method: str | None,
        article_id: str | None,
        domain: str | None,
        locality: dict[str, Any],
        source_context: dict[str, Any] | None = None,
    ) -> None:
        """Record when a wire article is determined to be locally focused."""
        if not self.enable_telemetry or not self.current_session:
            return

        if not locality:
            return

        event = {
            "id": str(uuid.uuid4()),
            "telemetry_id": self.current_session["telemetry_id"],
            "session_id": self.current_session["session_id"],
            "domain": domain or self.current_session["domain"],
            "provider": provider,
            "detection_method": detection_method,
            "article_id": article_id,
            "is_local": bool(locality.get("is_local")),
            "confidence": locality.get("confidence"),
            "raw_score": locality.get("raw_score"),
            "threshold": locality.get("threshold"),
            "signals_json": json.dumps(locality.get("signals", [])),
            "locality_json": json.dumps(locality),
            "source_context_json": json.dumps(source_context or {}),
            "timestamp": datetime.now(),
        }

        self.locality_detection_events.append(event)

    def log_segment_detection(
        self,
        segment_text: str,
        boundary_score: float,
        occurrences: int,
        pattern_type: str,
        position_consistency: float,
        segment_length: int,
        article_ids: list[str],
        was_removed: bool = False,
        removal_reason: str | None = None,
    ):
        """Log detection of a potential content segment."""
        if not self.enable_telemetry or not self.current_session:
            return

        self.detection_counter += 1

        segment_data = {
            "id": str(uuid.uuid4()),
            "telemetry_id": self.current_session["telemetry_id"],
            "detection_number": self.detection_counter,
            "segment_text": segment_text,
            "segment_text_hash": hash(segment_text),
            "boundary_score": boundary_score,
            "occurrences": occurrences,
            "pattern_type": pattern_type,
            "position_consistency": position_consistency,
            "segment_length": segment_length,
            "affected_article_count": len(article_ids),
            "was_removed": was_removed,
            "removal_reason": removal_reason,
            "timestamp": datetime.now(),
            "article_ids_json": json.dumps(article_ids),
        }

        self.detected_segments.append(segment_data)

    def log_boundary_assessment(
        self,
        text: str,
        score: float,
        score_breakdown: dict[str, float],
        detected_patterns: list[str],
    ):
        """Log detailed boundary assessment for analysis."""
        if not self.enable_telemetry or not self.current_session:
            return

        # Store boundary assessment data (could be used for ML training)
        self._last_boundary_assessment = {
            "text": text,
            "final_score": score,
            "score_breakdown": score_breakdown,
            "detected_patterns": detected_patterns,
            "text_length": len(text),
            "starts_uppercase": text[0].isupper() if text else False,
            "ends_with_punctuation": (
                text.endswith((".", "!", "?")) if text else False
            ),
        }

        # For now, just add to current segment if being tracked
        # In a full implementation, this could be stored separately

    def finalize_cleaning_session(
        self,
        rough_candidates_found: int,
        segments_detected: int,
        total_removable_chars: int,
        removal_percentage: float,
        processing_time_ms: float | None = None,
    ):
        """Finalize and save the cleaning session."""
        if not self.enable_telemetry or not self.current_session:
            return

        # Update session with final metrics
        self.current_session.update(
            {
                "end_time": datetime.now(),
                "processing_time_ms": processing_time_ms,
                "rough_candidates_found": rough_candidates_found,
                "segments_detected": segments_detected,
                "total_removable_chars": total_removable_chars,
                "removal_percentage": removal_percentage,
            }
        )

        payload = self._build_payload_snapshot()

        # Save asynchronously (or synchronously if queue is disabled)
        self._enqueue_payload(payload)

        # Reset session state to avoid leaking data across runs
        self._reset_session_state()

    def _build_payload_snapshot(self) -> dict[str, Any]:
        """Create a snapshot of the current session for deferred writing."""
        return {
            "session": dict(self.current_session or {}),
            "segments": [dict(segment) for segment in self.detected_segments],
            "wire_events": [dict(event) for event in self.wire_detection_events],
            "locality_events": [
                dict(event) for event in self.locality_detection_events
            ],
        }

    def _enqueue_payload(self, payload: dict[str, Any]) -> None:
        if not self.enable_telemetry:
            return

        def writer(conn: sqlite3.Connection) -> None:
            self._write_payload_to_database(conn, payload)

        try:
            self.store.submit(writer)
        except RuntimeError:
            # Telemetry disabled or not supported
            pass

    def flush(self) -> None:
        """Block until all queued telemetry writes have been processed."""
        if self.enable_telemetry:
            try:
                self.store.flush()
            except RuntimeError:
                # Telemetry disabled or not supported
                pass

    def shutdown(self, wait: bool = False) -> None:
        """Signal the writer thread to terminate and optionally wait for it."""
        if wait:
            self.flush()

    def _reset_session_state(self) -> None:
        """Clear session-specific telemetry buffers."""
        self.current_session = None
        self.detected_segments = []
        self.wire_detection_events = []
        self.locality_detection_events = []
        self.detection_counter = 0

    def _update_persistent_patterns_in_db(
        self,
        conn: sqlite3.Connection,
        session: dict[str, Any],
        segments: list[dict[str, Any]],
    ) -> None:
        """Update persistent pattern library using the active DB cursor."""
        if not session or not segments:
            return

        persistent_pattern_types = {
            "subscription",
            "navigation",
            "footer",
            "social_share_header",
        }
        dynamic_pattern_types = {"sidebar", "trending", "other"}
        all_saveable_types = persistent_pattern_types.union(dynamic_pattern_types)

        domain = session.get("domain")
        if not domain:
            return

        self._ensure_persistent_patterns_table(conn)

        cursor = conn.cursor()
        try:
            for segment in segments:
                if not segment.get("was_removed"):
                    continue

                if segment.get("pattern_type") not in all_saveable_types:
                    continue

                if segment.get("boundary_score", 0) < 0.5:
                    continue

                is_ml_eligible = segment.get("pattern_type") in persistent_pattern_types
                text_hash = segment.get("segment_text_hash")

                cursor.execute(
                    """
                    SELECT id, occurrences_total, last_seen
                    FROM persistent_boilerplate_patterns
                    WHERE domain = ? AND text_hash = ?
                    """,
                    (domain, text_hash),
                )

                existing = cursor.fetchone()

                if existing:
                    cursor.execute(
                        """
                        UPDATE persistent_boilerplate_patterns
                        SET occurrences_total = occurrences_total + ?,
                            last_seen = ?,
                            confidence_score = MAX(confidence_score, ?),
                            is_ml_training_eligible = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            segment.get("occurrences"),
                            datetime.now(),
                            segment.get("boundary_score"),
                            is_ml_eligible,
                            existing[0],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO persistent_boilerplate_patterns (
                            id, domain, pattern_type, text_content,
                            text_hash, confidence_score,
                            occurrences_total, first_seen,
                            last_seen, removal_reason, is_active,
                            is_ml_training_eligible
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            domain,
                            segment.get("pattern_type"),
                            segment.get("segment_text"),
                            text_hash,
                            segment.get("boundary_score"),
                            segment.get("occurrences"),
                            datetime.now(),
                            datetime.now(),
                            segment.get("removal_reason"),
                            True,
                            is_ml_eligible,
                        ),
                    )
        finally:
            cursor.close()

    def _ensure_persistent_patterns_table(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        """Ensure the persistent boilerplate patterns table exists."""
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS persistent_boilerplate_patterns (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                pattern_type TEXT NOT NULL,
                text_content TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                confidence_score REAL NOT NULL,
                occurrences_total INTEGER DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                removal_reason TEXT,
                is_active BOOLEAN DEFAULT 1,
                is_ml_training_eligible BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
            )

            # Create indexes
            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_persistent_patterns_domain
            ON persistent_boilerplate_patterns(domain, is_active)
        """
            )

            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_persistent_patterns_hash
            ON persistent_boilerplate_patterns(domain, text_hash)
        """
            )

            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_persistent_patterns_type
            ON persistent_boilerplate_patterns(pattern_type, confidence_score)
        """
            )

            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_persistent_patterns_ml_eligible
            ON persistent_boilerplate_patterns(is_ml_training_eligible, domain)
        """
            )
        finally:
            cursor.close()

    def get_persistent_patterns(self, domain: str) -> list[dict]:
        """Get persistent boilerplate patterns for a domain."""
        try:
            store = self.store
        except RuntimeError:
            # Telemetry disabled or not supported
            return []
        
        try:
            with store.connection() as conn:
                self._ensure_persistent_patterns_table(conn)
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        """
                        SELECT pattern_type, text_content, confidence_score,
                               occurrences_total, removal_reason,
                               is_ml_training_eligible
                        FROM persistent_boilerplate_patterns
                        WHERE domain = ? AND is_active IS TRUE
                        ORDER BY confidence_score DESC, occurrences_total DESC
                        """,
                        (domain,),
                    )

                    patterns = []
                    for row in cursor.fetchall():
                        patterns.append(
                            {
                                "pattern_type": row[0],
                                "text_content": row[1],
                                "confidence_score": row[2],
                                "occurrences_total": row[3],
                                "removal_reason": row[4],
                                "is_ml_training_eligible": bool(row[5]),
                            }
                        )
                finally:
                    cursor.close()

            return patterns

        except Exception as e:
            print(f"Error retrieving persistent patterns: {e}")
            return []

    def get_ml_training_patterns(self, domain: str | None = None) -> list[dict]:
        """Get ML training patterns (excludes dynamic ones)."""
        try:
            with self.store.connection() as conn:
                self._ensure_persistent_patterns_table(conn)
                cursor = conn.cursor()
                try:
                    if domain:
                        cursor.execute(
                            """
                            SELECT domain, pattern_type, text_content,
                                   confidence_score, occurrences_total,
                                   removal_reason
                            FROM persistent_boilerplate_patterns
                    WHERE domain = ? AND is_active IS TRUE
                        AND is_ml_training_eligible IS TRUE
                    ORDER BY confidence_score DESC,
                         occurrences_total DESC
                            """,
                            (domain,),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT domain, pattern_type, text_content,
                                   confidence_score, occurrences_total,
                                   removal_reason
                            FROM persistent_boilerplate_patterns
                            WHERE is_active IS TRUE AND is_ml_training_eligible IS TRUE
                            ORDER BY domain, confidence_score DESC,
                                     occurrences_total DESC
                            """
                        )

                    patterns = []
                    for row in cursor.fetchall():
                        patterns.append(
                            {
                                "domain": row[0],
                                "pattern_type": row[1],
                                "text_content": row[2],
                                "confidence_score": row[3],
                                "occurrences_total": row[4],
                                "removal_reason": row[5],
                            }
                        )
                finally:
                    cursor.close()

            return patterns

        except Exception as e:
            print(f"Error retrieving ML training patterns: {e}")
            return []

    def get_telemetry_patterns(
        self,
        domain: str | None = None,
        include_dynamic: bool = True,
    ) -> list[dict]:
        """Get telemetry patterns, optionally including dynamic types."""
        try:
            with self.store.connection() as conn:
                self._ensure_persistent_patterns_table(conn)
                cursor = conn.cursor()
                try:
                    base_query = """
                  SELECT domain, pattern_type, text_content, confidence_score,
                      occurrences_total, removal_reason,
                      is_ml_training_eligible
                        FROM persistent_boilerplate_patterns
                        WHERE is_active IS TRUE
                    """

                    params: list[str] = []
                    if domain:
                        base_query += " AND domain = ?"
                        params.append(domain)

                    if not include_dynamic:
                        base_query += " AND is_ml_training_eligible = 1"

                    base_query += (
                        " ORDER BY domain, confidence_score DESC,"
                        " occurrences_total DESC"
                    )

                    cursor.execute(base_query, params)

                    patterns = []
                    for row in cursor.fetchall():
                        patterns.append(
                            {
                                "domain": row[0],
                                "pattern_type": row[1],
                                "text_content": row[2],
                                "confidence_score": row[3],
                                "occurrences_total": row[4],
                                "removal_reason": row[5],
                                "is_ml_training_eligible": bool(row[6]),
                                "pattern_category": (
                                    "persistent" if row[6] else "dynamic"
                                ),
                            }
                        )
                finally:
                    cursor.close()

            return patterns

        except Exception as e:
            print(f"Error retrieving telemetry patterns: {e}")
            return []

    def _write_payload_to_database(
        self,
        conn: sqlite3.Connection,
        payload: dict[str, Any],
    ) -> None:
        """Persist a telemetry payload composed of session and event data."""
        session = payload.get("session") or {}
        if not session:
            return

        segments = payload.get("segments") or []
        wire_events = payload.get("wire_events") or []
        locality_events = payload.get("locality_events") or []

        cursor = conn.cursor()
        try:
            self._ensure_tables_exist(conn)

            cursor.execute(
                """
                INSERT INTO content_cleaning_sessions (
                    telemetry_id, session_id, domain, article_count,
                    min_occurrences, min_boundary_score, start_time, end_time,
                    processing_time_ms, rough_candidates_found,
                    segments_detected, total_removable_chars,
                    removal_percentage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.get("telemetry_id"),
                    session.get("session_id"),
                    session.get("domain"),
                    session.get("article_count"),
                    session.get("min_occurrences"),
                    session.get("min_boundary_score"),
                    session.get("start_time"),
                    session.get("end_time"),
                    session.get("processing_time_ms"),
                    session.get("rough_candidates_found"),
                    session.get("segments_detected"),
                    session.get("total_removable_chars"),
                    session.get("removal_percentage"),
                ),
            )

            for segment in segments:
                cursor.execute(
                    """
                    INSERT INTO content_cleaning_segments (
                        id, telemetry_id, detection_number, segment_text,
                        segment_text_hash, boundary_score, occurrences,
                        pattern_type, position_consistency, segment_length,
                        affected_article_count, was_removed, removal_reason,
                        timestamp, article_ids_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        segment.get("id"),
                        segment.get("telemetry_id"),
                        segment.get("detection_number"),
                        segment.get("segment_text"),
                        segment.get("segment_text_hash"),
                        segment.get("boundary_score"),
                        segment.get("occurrences"),
                        segment.get("pattern_type"),
                        segment.get("position_consistency"),
                        segment.get("segment_length"),
                        segment.get("affected_article_count"),
                        segment.get("was_removed"),
                        segment.get("removal_reason"),
                        segment.get("timestamp"),
                        segment.get("article_ids_json"),
                    ),
                )

            for event in wire_events:
                cursor.execute(
                    """
                    INSERT INTO content_cleaning_wire_events (
                        id, telemetry_id, session_id, domain, provider,
                        detection_method, detection_stage, confidence,
                        pattern_text, pattern_text_hash, article_ids_json,
                        metadata_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.get("id"),
                        event.get("telemetry_id"),
                        event.get("session_id"),
                        event.get("domain"),
                        event.get("provider"),
                        event.get("detection_method"),
                        event.get("detection_stage"),
                        event.get("confidence"),
                        event.get("pattern_text"),
                        event.get("pattern_text_hash"),
                        event.get("article_ids_json"),
                        event.get("metadata_json"),
                        event.get("timestamp"),
                    ),
                )

            for event in locality_events:
                cursor.execute(
                    """
                    INSERT INTO content_cleaning_locality_events (
                        id, telemetry_id, session_id, domain, provider,
                        detection_method, article_id, is_local, confidence,
                        raw_score, threshold, signals_json, locality_json,
                        source_context_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.get("id"),
                        event.get("telemetry_id"),
                        event.get("session_id"),
                        event.get("domain"),
                        event.get("provider"),
                        event.get("detection_method"),
                        event.get("article_id"),
                        1 if event.get("is_local") else 0,
                        event.get("confidence"),
                        event.get("raw_score"),
                        event.get("threshold"),
                        event.get("signals_json"),
                        event.get("locality_json"),
                        event.get("source_context_json"),
                        event.get("timestamp"),
                    ),
                )

            self._update_persistent_patterns_in_db(conn, session, segments)

        except Exception as exc:  # pylint: disable=broad-except
            print(f"Error saving content cleaning telemetry: {exc}")
        finally:
            cursor.close()

    def _ensure_tables_exist(self, conn: sqlite3.Connection) -> None:
        """Create telemetry tables if they don't exist."""

        cursor = conn.cursor()
        try:
            # Sessions table
            cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS content_cleaning_sessions (
                telemetry_id TEXT PRIMARY KEY,
                session_id TEXT,
                domain TEXT,
                article_count INTEGER,
                min_occurrences INTEGER,
                min_boundary_score REAL,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                processing_time_ms REAL,
                rough_candidates_found INTEGER,
                segments_detected INTEGER,
                total_removable_chars INTEGER,
                removal_percentage REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
            )

            # Segments table
            cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS content_cleaning_segments (
                id TEXT PRIMARY KEY,
                telemetry_id TEXT,
                detection_number INTEGER,
                segment_text TEXT,
                segment_text_hash INTEGER,
                boundary_score REAL,
                occurrences INTEGER,
                pattern_type TEXT,
                position_consistency REAL,
                segment_length INTEGER,
                affected_article_count INTEGER,
                was_removed BOOLEAN,
                removal_reason TEXT,
                timestamp TIMESTAMP,
                article_ids_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telemetry_id)
                    REFERENCES content_cleaning_sessions(telemetry_id)
            )
        """
            )

            # Wire detection events table
            cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS content_cleaning_wire_events (
                id TEXT PRIMARY KEY,
                telemetry_id TEXT,
                session_id TEXT,
                domain TEXT,
                provider TEXT,
                detection_method TEXT,
                detection_stage TEXT,
                confidence REAL,
                pattern_text TEXT,
                pattern_text_hash INTEGER,
                article_ids_json TEXT,
                metadata_json TEXT,
                timestamp TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telemetry_id)
                    REFERENCES content_cleaning_sessions(telemetry_id)
            )
        """
            )

            # Locality detection events table
            cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS content_cleaning_locality_events (
                id TEXT PRIMARY KEY,
                telemetry_id TEXT,
                session_id TEXT,
                domain TEXT,
                provider TEXT,
                detection_method TEXT,
                article_id TEXT,
                is_local BOOLEAN,
                confidence REAL,
                raw_score REAL,
                threshold REAL,
                signals_json TEXT,
                locality_json TEXT,
                source_context_json TEXT,
                timestamp TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telemetry_id)
                    REFERENCES content_cleaning_sessions(telemetry_id)
            )
        """
            )

            # Indexes for performance
            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_content_cleaning_domain
            ON content_cleaning_sessions(domain)
        """
            )

            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_content_segments_telemetry
            ON content_cleaning_segments(telemetry_id)
        """
            )

            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_content_segments_pattern
            ON content_cleaning_segments(pattern_type)
        """
            )

            cursor.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_content_segments_boundary_score
            ON content_cleaning_segments(boundary_score)
        """
            )
        finally:
            cursor.close()

    def get_domain_telemetry_summary(self, domain: str) -> dict[str, Any]:
        """Get telemetry summary for a specific domain."""
        if not self.enable_telemetry:
            return {}

        try:
            with self.store.connection() as conn:
                self._ensure_tables_exist(conn)
                cursor = conn.cursor()
                try:
                    # Get session summary
                    cursor.execute(
                        """
                        SELECT COUNT(*) as session_count,
                               AVG(segments_detected) as avg_segments,
                               AVG(removal_percentage) as avg_removal_pct,
                               MAX(end_time) as last_analysis
                        FROM content_cleaning_sessions
                        WHERE domain = ?
                        """,
                        (domain,),
                    )

                    session_row = cursor.fetchone() or (0, None, None, None)
                    column_names = [desc[0] for desc in cursor.description]
                    session_summary = dict(zip(column_names, session_row, strict=False))

                    # Get pattern breakdown
                    cursor.execute(
                        """
                        SELECT s.pattern_type,
                               COUNT(*) as detection_count,
                               AVG(s.boundary_score) as avg_boundary_score,
                               SUM(CASE WHEN s.was_removed THEN 1 ELSE 0 END)
                                   as removed_count
                        FROM content_cleaning_segments s
                        JOIN content_cleaning_sessions sess
                            ON s.telemetry_id = sess.telemetry_id
                        WHERE sess.domain = ?
                        GROUP BY s.pattern_type
                        ORDER BY detection_count DESC
                        """,
                        (domain,),
                    )

                    pattern_breakdown = [
                        dict(zip([d[0] for d in cursor.description], row, strict=False))
                        for row in cursor.fetchall()
                    ]
                finally:
                    cursor.close()

            return {
                "domain": domain,
                "session_summary": session_summary,
                "pattern_breakdown": pattern_breakdown,
            }

        except Exception as e:
            print(f"Error retrieving telemetry summary: {e}")
            return {}
