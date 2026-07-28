"""
Tests for database-driven content validation in extraction pipeline.

Tests the integration of BalancedBoundaryContentCleaner into extraction
workflow to validate articles have sufficient non-boilerplate content
before saving to the articles table.
"""

from __future__ import annotations

from argparse import Namespace
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import src.cli.commands.extraction as extraction


class TestContentValidationIntegration:
    """Test database-driven content validation in extraction command."""

    def test_content_cleaner_instantiated_in_handle_extraction_command(
        self, monkeypatch
    ):
        """Test that BalancedBoundaryContentCleaner is created with telemetry disabled."""
        instantiation_calls = []

        class FakeContentCleaner:
            def __init__(self, **kwargs):
                instantiation_calls.append(kwargs)
                self.enable_telemetry = kwargs.get("enable_telemetry", True)

        class FakeExtractor:
            def get_driver_stats(self):
                return {
                    "has_persistent_driver": False,
                    "driver_reuse_count": 0,
                    "driver_creation_count": 0,
                }

            def close_persistent_driver(self):
                pass

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        def fake_process_batch(*args, **kwargs):
            return {
                "processed": 0,
                "domains_processed": [],
                "same_domain_consecutive": 0,
            }

        def fake_domain_analysis(args, session):
            return {
                "unique_domains": 0,
                "is_single_domain": False,
                "sample_domains": [],
            }

        monkeypatch.setattr(extraction, "ContentExtractor", FakeExtractor)
        monkeypatch.setattr(extraction, "BylineCleaner", lambda: object())
        monkeypatch.setattr(
            extraction, "BalancedBoundaryContentCleaner", FakeContentCleaner
        )
        monkeypatch.setattr(
            extraction, "ComprehensiveExtractionTelemetry", lambda: FakeTelemetry()
        )
        monkeypatch.setattr(extraction, "_process_batch", fake_process_batch)
        monkeypatch.setattr(
            extraction, "_analyze_dataset_domains", fake_domain_analysis
        )

        args = Namespace(
            batches=0, limit=1, source=None, dataset=None, exhaust_queue=False
        )
        extraction.handle_extraction_command(args)

        # Verify content cleaner was instantiated with telemetry disabled
        assert len(instantiation_calls) == 1
        assert instantiation_calls[0] == {"enable_telemetry": False}

    def test_content_cleaner_passed_to_process_batch(self, monkeypatch):
        """Test that content_cleaner is passed as parameter to _process_batch."""
        process_batch_calls = []

        class FakeContentCleaner:
            def __init__(self, **kwargs):
                self.enable_telemetry = False

        class FakeExtractor:
            def get_driver_stats(self):
                return {"has_persistent_driver": False}

            def close_persistent_driver(self):
                pass

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        def fake_process_batch(
            args,
            extractor,
            byline_cleaner,
            content_cleaner,
            telemetry,
            per_batch,
            batch_num,
            host_403_tracker,
            domains_for_cleaning,
            **kwargs,
        ):
            process_batch_calls.append(
                {
                    "content_cleaner": content_cleaner,
                    "content_cleaner_type": type(content_cleaner).__name__,
                }
            )
            return {
                "processed": 0,
                "domains_processed": [],
                "same_domain_consecutive": 0,
            }

        def fake_domain_analysis(args, session):
            return {
                "unique_domains": 0,
                "is_single_domain": False,
                "sample_domains": [],
            }

        monkeypatch.setattr(extraction, "ContentExtractor", FakeExtractor)
        monkeypatch.setattr(extraction, "BylineCleaner", lambda: object())
        monkeypatch.setattr(
            extraction, "BalancedBoundaryContentCleaner", FakeContentCleaner
        )
        monkeypatch.setattr(
            extraction, "ComprehensiveExtractionTelemetry", lambda: FakeTelemetry()
        )
        monkeypatch.setattr(extraction, "_process_batch", fake_process_batch)
        monkeypatch.setattr(
            extraction, "_analyze_dataset_domains", fake_domain_analysis
        )

        args = Namespace(
            batches=1, limit=1, source=None, dataset=None, exhaust_queue=False
        )
        extraction.handle_extraction_command(args)

        # Verify content_cleaner was passed to process_batch
        assert len(process_batch_calls) >= 1
        assert process_batch_calls[0]["content_cleaner_type"] == "FakeContentCleaner"


class TestContentValidationLogic:
    """Test content validation logic in _process_batch."""

    def test_article_with_sufficient_content_after_cleaning(self, monkeypatch):
        """Test that articles with >=150 chars non-boilerplate are saved."""
        rows = [
            (
                "cand-1",
                "https://example.com/article",
                "example.com",
                "article",
                "Example Site",
            )
        ]

        class FakeSession:
            def __init__(self):
                self.insert_calls = []
                self.update_calls = []
                self.commit_calls = 0

            def execute(self, query, params=None):
                # Track INSERT INTO articles
                if hasattr(query, "text") and "INSERT INTO articles" in str(query):
                    self.insert_calls.append(params)
                # Track UPDATE candidate_links
                elif hasattr(query, "text") and "UPDATE candidate_links" in str(query):
                    self.update_calls.append(params)
                elif params and "limit_with_buffer" in params:
                    return Mock(fetchall=lambda: rows)
                return Mock(fetchall=lambda: [], scalar=lambda: None)

            def commit(self):
                self.commit_calls += 1

            def close(self):
                pass

            def expire_all(self):
                pass

            def rollback(self):
                pass

        class FakeDBManager:
            def __init__(self):
                self.session = FakeSession()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                # Real prose, not filler: the shape gate rejects a run of
                # identical capitals ("A" * 200 reads as 100% capitalised, i.e.
                # furniture), so a length-only fixture would mis-test the gate.
                return {
                    "title": "Test Article",
                    "content": (
                        "The county commission met on Monday evening to review "
                        "the annual road maintenance budget and heard from a "
                        "dozen residents who asked for repairs on rural routes. "
                        "The chair said the plan would be finalized next month."
                    ),
                    "author": "Test Author",
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {"authors": ["Test Author"], "wire_services": []}

        class FakeContentCleaner:
            def process_single_article(self, text, domain, dry_run=False):
                # Simulate removing a little boilerplate; still real prose and
                # comfortably over MIN_CONTENT_LENGTH.
                cleaned_text = text[:200] if len(text) > 200 else text
                return cleaned_text, {}

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "DatabaseManager", FakeDBManager)
        monkeypatch.setattr(extraction, "BylineCleaner", FakeBylineCleaner)
        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash123")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )
        monkeypatch.setattr(extraction, "ENABLE_MEDIACLOUD_WIRE_CHECK", True)

        db = FakeDBManager()
        args = Namespace(dump_sql=False)
        extractor = FakeExtractor()
        byline_cleaner = FakeBylineCleaner()
        content_cleaner = FakeContentCleaner()
        telemetry = FakeTelemetry()

        result = extraction._process_batch(
            args,
            extractor,
            byline_cleaner,
            content_cleaner,
            telemetry,
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=defaultdict(list),
            db=db,
        )

        # Verify article was inserted (sufficient content after cleaning)
        assert len(db.session.insert_calls) == 1
        assert db.session.insert_calls[0]["wire_check_status"] == "pending"
        assert result["processed"] == 1

    def test_wire_service_article_sets_wire_check_complete(self, monkeypatch):
        """Wire-detected articles should skip MediaCloud checks."""

        rows = [
            (
                "cand-1",
                "https://example.com/article",
                "example.com",
                "article",
                "Example Site",
            )
        ]

        class FakeSession:
            def __init__(self):
                self.insert_calls = []
                self.update_calls = []
                self.commit_calls = 0

            def execute(self, query, params=None):
                if hasattr(query, "text") and "INSERT INTO articles" in str(query):
                    self.insert_calls.append(params)
                elif hasattr(query, "text") and "UPDATE candidate_links" in str(query):
                    self.update_calls.append(params)
                elif params and "limit_with_buffer" in params:
                    return Mock(fetchall=lambda: rows)
                return Mock(fetchall=lambda: [], scalar=lambda: None)

            def commit(self):
                self.commit_calls += 1

            def close(self):
                pass

            def expire_all(self):
                pass

            def rollback(self):
                pass

        class FakeDBManager:
            def __init__(self):
                self.session = FakeSession()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                return {
                    "title": "Wire Story",
                    "content": (
                        "Federal regulators on Thursday proposed a new rule that "
                        "would require airlines to disclose baggage fees earlier "
                        "in the booking process, a change consumer advocates have "
                        "sought for years. The agency will take comments this fall."
                    ),
                    "author": "Associated Press",
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {
                    "authors": ["Associated Press"],
                    "wire_services": ["Associated Press"],
                    "is_wire_content": True,
                }

        class FakeContentCleaner:
            def process_single_article(self, text, domain, dry_run=False):
                return text, {}

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "DatabaseManager", FakeDBManager)
        monkeypatch.setattr(extraction, "BylineCleaner", FakeBylineCleaner)
        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash123")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )

        db = FakeDBManager()
        args = Namespace(dump_sql=False)
        extractor = FakeExtractor()
        byline_cleaner = FakeBylineCleaner()
        content_cleaner = FakeContentCleaner()
        telemetry = FakeTelemetry()

        extraction._process_batch(
            args,
            extractor,
            byline_cleaner,
            content_cleaner,
            telemetry,
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=defaultdict(list),
            db=db,
        )

        assert len(db.session.insert_calls) == 1
        assert db.session.insert_calls[0]["wire_check_status"] == "complete"

    def test_article_with_insufficient_content_after_cleaning_skipped(
        self, monkeypatch
    ):
        """Test that articles with <150 chars non-boilerplate are skipped."""
        rows = [
            (
                "cand-1",
                "https://stltoday.com/article",
                "stltoday.com",
                "article",
                "STL Today",
            )
        ]

        class FakeSession:
            def __init__(self):
                self.insert_calls = []
                self.update_calls = []
                self.commit_calls = 0

            def execute(self, query, params=None):
                if hasattr(query, "text") and "INSERT INTO articles" in str(query):
                    self.insert_calls.append(params)
                elif hasattr(query, "text") and "UPDATE candidate_links" in str(query):
                    self.update_calls.append(params)
                elif params and "limit_with_buffer" in params:
                    return Mock(fetchall=lambda: rows)
                return Mock(fetchall=lambda: [], scalar=lambda: None)

            def commit(self):
                self.commit_calls += 1

            def close(self):
                pass

            def expire_all(self):
                pass

            def rollback(self):
                pass

        class FakeDBManager:
            def __init__(self):
                self.session = FakeSession()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                # Return mostly boilerplate content (185 chars total)
                return {
                    "title": "DANCING WITH THE STARS",
                    "content": (
                        "Get up-to-the-minute news sent straight to your device.\n"
                        "CAPTCHA\n"
                        "Subscribe to continue reading\n"
                        "Log in to your account\n"
                        "Already a subscriber?\n"
                    ),
                    "author": "Eric Mccandless",
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {"authors": ["Eric Mccandless"], "wire_services": []}

        class FakeContentCleaner:
            def process_single_article(self, text, domain, dry_run=False):
                # Simulate aggressive boilerplate removal (only 50 chars remain)
                # This simulates the persistent_boilerplate_patterns matching
                # stltoday.com login form patterns
                cleaned_text = "DANCING WITH THE STARS\nEric Mccandless"  # 42 chars
                # Return metadata indicating subscription patterns were found
                return cleaned_text, {
                    "patterns_matched": ["subscription", "paywall"],
                    "persistent_removals": 3,
                }

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "DatabaseManager", FakeDBManager)
        monkeypatch.setattr(extraction, "BylineCleaner", FakeBylineCleaner)
        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash123")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )

        db = FakeDBManager()
        args = Namespace(dump_sql=False)
        extractor = FakeExtractor()
        byline_cleaner = FakeBylineCleaner()
        content_cleaner = FakeContentCleaner()
        telemetry = FakeTelemetry()

        result = extraction._process_batch(
            args,
            extractor,
            byline_cleaner,
            content_cleaner,
            telemetry,
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=defaultdict(list),
            db=db,
        )

        # Verify article WAS inserted with status='paywall' (new behavior)
        assert len(db.session.insert_calls) == 1
        inserted_article = db.session.insert_calls[0]
        assert inserted_article["status"] == "paywall"
        # Verify candidate_link was still marked as 'extracted' to avoid retry
        assert len(db.session.update_calls) >= 1
        assert result["processed"] == 1

    def test_content_validation_with_empty_content(self, monkeypatch):
        """Test content validation handles empty/None content gracefully."""
        rows = [
            (
                "cand-1",
                "https://example.com/article",
                "example.com",
                "article",
                "Example Site",
            )
        ]

        class FakeSession:
            def __init__(self):
                self.insert_calls = []
                self.update_calls = []

            def execute(self, query, params=None):
                if hasattr(query, "text") and "INSERT INTO articles" in str(query):
                    self.insert_calls.append(params)
                elif hasattr(query, "text") and "UPDATE candidate_links" in str(query):
                    self.update_calls.append(params)
                elif params and "limit_with_buffer" in params:
                    return Mock(fetchall=lambda: rows)
                return Mock(fetchall=lambda: [], scalar=lambda: None)

            def commit(self):
                pass

            def close(self):
                pass

            def expire_all(self):
                pass

            def rollback(self):
                pass

        class FakeDBManager:
            def __init__(self):
                self.session = FakeSession()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                # Return None for content (extraction failure)
                return {
                    "title": "Test Article",
                    "content": None,
                    "author": None,
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {"authors": [], "wire_services": []}

        class FakeContentCleaner:
            def process_single_article(self, text, domain, dry_run=False):
                # Should not be called with empty content
                return "", {}

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "DatabaseManager", FakeDBManager)
        monkeypatch.setattr(extraction, "BylineCleaner", FakeBylineCleaner)
        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash123")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )

        db = FakeDBManager()
        args = Namespace(dump_sql=False)
        extractor = FakeExtractor()
        byline_cleaner = FakeBylineCleaner()
        content_cleaner = FakeContentCleaner()
        telemetry = FakeTelemetry()

        extraction._process_batch(
            args,
            extractor,
            byline_cleaner,
            content_cleaner,
            telemetry,
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=defaultdict(list),
            db=db,
        )

        # Verify NO article was inserted (empty content)
        assert len(db.session.insert_calls) == 0
        # Verify candidate marked as extracted (don't retry empty content)
        assert len(db.session.update_calls) >= 1

    def test_insufficient_content_without_paywall_commits_and_updates(
        self, monkeypatch
    ):
        """Insufficient content without paywall should update status and commit."""

        rows = [
            (
                "cand-1",
                "https://example.com/short",
                "example.com",
                "article",
                "Example",
            )
        ]

        class FakeSession:
            def __init__(self):
                self.insert_calls = []
                self.update_calls = []
                self.commit_calls = 0

            def execute(self, query, params=None):
                query_str = str(getattr(query, "text", query))
                if "INSERT INTO articles" in query_str:
                    self.insert_calls.append(params)
                elif "UPDATE candidate_links" in query_str:
                    self.update_calls.append(params)
                elif params and "limit_with_buffer" in params:
                    return Mock(fetchall=lambda: rows)
                return Mock(fetchall=lambda: [], scalar=lambda: None)

            def commit(self):
                self.commit_calls += 1

            def close(self):
                pass

            def expire_all(self):
                pass

            def rollback(self):
                pass

        class FakeDBManager:
            def __init__(self):
                self.session = FakeSession()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                return {
                    "title": "Short Article",
                    "content": "abc",  # well under MIN_CONTENT_LENGTH after cleaning
                    "author": None,
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {"authors": [], "wire_services": []}

        class FakeContentCleaner:
            def process_single_article(self, text, domain, dry_run=False):
                # leave content untouched and under threshold with no paywall patterns
                return text, {"patterns_matched": []}

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "DatabaseManager", FakeDBManager)
        monkeypatch.setattr(extraction, "BylineCleaner", FakeBylineCleaner)
        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )

        db = FakeDBManager()
        args = Namespace(dump_sql=False)
        extractor = FakeExtractor()
        content_cleaner = FakeContentCleaner()
        telemetry = FakeTelemetry()

        result = extraction._process_batch(
            args,
            extractor,
            FakeBylineCleaner(),
            content_cleaner,
            telemetry,
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=defaultdict(list),
            db=db,
        )

        assert result["processed"] == 0
        assert db.session.insert_calls == []
        assert db.session.commit_calls == 1
        assert db.session.update_calls == [
            {
                "id": "cand-1",
                "status": "extracted",
                "error": "Insufficient content (no paywall detected)",
            }
        ]

    def test_work_queue_insufficient_content_still_commits(self, monkeypatch):
        """Ensure work-queue path also commits insufficient-content updates."""

        class FakeSession:
            def __init__(self):
                self.update_calls = []
                self.commit_calls = 0

            def execute(self, query, params=None):
                query_str = str(getattr(query, "text", query))
                if "UPDATE candidate_links" in query_str:
                    self.update_calls.append(params)
                return Mock(fetchall=lambda: [], scalar=lambda: None)

            def commit(self):
                self.commit_calls += 1

            def close(self):
                pass

            def expire_all(self):
                pass

            def rollback(self):
                pass

        class FakeDBManager:
            def __init__(self):
                self.session = FakeSession()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                return {
                    "title": "Short Queue Article",
                    "content": "tiny",
                    "author": None,
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {"authors": [], "wire_services": []}

        class FakeContentCleaner:
            def process_single_article(self, text, domain, dry_run=False):
                return text, {"patterns_matched": []}

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "DatabaseManager", FakeDBManager)
        monkeypatch.setattr(extraction, "BylineCleaner", FakeBylineCleaner)
        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )
        monkeypatch.setattr(extraction, "USE_WORK_QUEUE", True)
        monkeypatch.setattr(
            extraction,
            "_get_work_from_queue",
            lambda **_: [
                {
                    "id": "cand-queue",
                    "url": "https://queue.example.com/article",
                    "source": "queue.example.com",
                    "canonical_name": "Queue Example",
                }
            ],
        )

        db = FakeDBManager()
        args = Namespace(dump_sql=False)
        telemetry = FakeTelemetry()

        result = extraction._process_batch(
            args,
            FakeExtractor(),
            FakeBylineCleaner(),
            FakeContentCleaner(),
            telemetry,
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=defaultdict(list),
            db=db,
        )

        assert result["processed"] == 0
        assert db.session.commit_calls == 1
        assert db.session.update_calls == [
            {
                "id": "cand-queue",
                "status": "extracted",
                "error": "Insufficient content (no paywall detected)",
            }
        ]


class TestFurnitureShapeGate:
    """A long capture can still be pure furniture and must not be saved as prose.

    The length gate (< MIN_CONTENT_LENGTH) only catches *short* captures. A
    comment-form country dropdown (5,308 chars), a subscription wall wrapped in
    a nav menu, a PDF-embed shell -- all clear the length gate and were stored
    as articles. looks_like_furniture flags them by measured shape (capitalisation
    / utility-word rate), so the save gate now catches them regardless of length:
    a paywall marker -> status='paywall', otherwise status='not_article'. Both
    keep the record + metadata and drop the furniture body. Real prose -- including
    the Spanish and public-records captures that only *look* unusual on one axis
    -- is untouched.
    """

    # >150 chars each, so the length gate passes and only the shape gate can fire.
    COUNTRY_DROPDOWN = (
        "United States of America US Virgin Islands Canada Mexico Bahamas Cuba "
        "Dominican Republic Haiti Jamaica Afghanistan Albania Algeria American "
        "Samoa Andorra Angola Anguilla Antarctica Antigua Argentina Armenia Aruba "
        "Australia Austria Azerbaijan Bahrain Bangladesh Barbados Belarus Belgium"
    )
    NAV_WRAPPED_WALL = (
        "Skip to main content Log in Forecast Main menu News Local News Sports "
        "Obituaries Subscribe This article is only available to subscribers. "
        "Log in. Create an account to get 3 free articles each month. "
        "GET UNLIMITED ACCESS $1 for your first month No commitment, cancel anytime."
    )
    REAL_PROSE = (
        "The city council voted Tuesday to approve the new budget after a lengthy "
        "public hearing that drew more than fifty residents. Members said the plan "
        "preserves funding for the library and fire department while trimming "
        "costs. The measure passed on a five to two vote and takes effect in July."
    )

    def _run(self, monkeypatch, body, cleaner_metadata):
        """Drive one capture through _process_batch and return the insert params."""
        rows = [
            (
                "cand-1",
                "https://example.com/article",
                "example.com",
                "article",
                "Example Site",
            )
        ]

        class FakeSession:
            def __init__(self):
                self.insert_calls = []
                self.update_calls = []
                self.commit_calls = 0

            def execute(self, query, params=None):
                query_str = str(getattr(query, "text", query))
                if "INSERT INTO articles" in query_str:
                    self.insert_calls.append(params)
                elif "UPDATE candidate_links" in query_str:
                    self.update_calls.append(params)
                elif params and "limit_with_buffer" in params:
                    return Mock(fetchall=lambda: rows)
                return Mock(fetchall=lambda: [], scalar=lambda: None)

            def commit(self):
                self.commit_calls += 1

            def close(self):
                pass

            def expire_all(self):
                pass

            def rollback(self):
                pass

        class FakeDBManager:
            def __init__(self):
                self.session = FakeSession()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                return {
                    "title": "Headline Outside The Furniture",
                    "content": body,
                    "author": "Jane Reporter",
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {"authors": ["Jane Reporter"], "wire_services": []}

        class FakeContentCleaner:
            # The cleaner returns the body unchanged: these captures have no
            # per-segment furniture the cleaner can strip -- that IS why the
            # shape gate has to catch the whole capture.
            def process_single_article(self, text, domain, dry_run=False):
                return text, dict(cleaner_metadata)

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "DatabaseManager", FakeDBManager)
        monkeypatch.setattr(extraction, "BylineCleaner", FakeBylineCleaner)
        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash123")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )

        db = FakeDBManager()
        args = Namespace(dump_sql=False)
        extraction._process_batch(
            args,
            FakeExtractor(),
            FakeBylineCleaner(),
            FakeContentCleaner(),
            FakeTelemetry(),
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=defaultdict(list),
            db=db,
        )
        return db.session.insert_calls

    def test_country_dropdown_marked_not_article_body_dropped(self, monkeypatch):
        inserts = self._run(
            monkeypatch, self.COUNTRY_DROPDOWN, {"patterns_matched": []}
        )
        assert len(inserts) == 1
        row = inserts[0]
        assert row["status"] == "not_article"
        # The BODY is dropped -- `text` is the cleaned, consumable column and
        # that is what "body dropped" means. `content` is the canonical capture
        # and is NOT edited after capture: blanking it destroyed the only
        # durable copy of the furniture (raw HTML in GCS ages out at 30 days),
        # leaving rows that could not afterwards be re-examined to see why they
        # were rejected, or re-filed when a wall went unrecognised.
        assert row["text"] == ""
        assert row["content"] == self.COUNTRY_DROPDOWN
        # ...and the metadata captured alongside it is preserved.
        assert row["title"] == "Headline Outside The Furniture"

    def test_nav_wrapped_wall_with_paywall_pattern_marked_paywall(self, monkeypatch):
        inserts = self._run(
            monkeypatch,
            self.NAV_WRAPPED_WALL,
            {"patterns_matched": ["subscription", "paywall"]},
        )
        assert len(inserts) == 1
        row = inserts[0]
        assert row["status"] == "paywall"
        # Same rule: cleaned body dropped, canonical wall text retained so the
        # row itself still evidences WHY it was filed paywall.
        assert row["text"] == ""
        assert row["content"] != ""
        assert row["title"] == "Headline Outside The Furniture"

    def test_nav_wrapped_wall_without_pattern_falls_back_to_not_article(
        self, monkeypatch
    ):
        """A wall the cleaner did not tag still fails the shape gate (util rate),
        so it is filed as not_article rather than saved as an article body --
        the houstonherald.com case, whose phrase matches no marker."""
        inserts = self._run(
            monkeypatch, self.NAV_WRAPPED_WALL, {"patterns_matched": []}
        )
        assert len(inserts) == 1
        assert inserts[0]["status"] == "not_article"
        assert inserts[0]["text"] == ""

    def test_real_prose_is_not_gated(self, monkeypatch):
        """Ordinary reporting passes: it is neither short nor furniture-shaped."""
        inserts = self._run(monkeypatch, self.REAL_PROSE, {"patterns_matched": []})
        assert len(inserts) == 1
        row = inserts[0]
        assert row["status"] not in ("paywall", "not_article")
        # Body preserved.
        assert row["text"] == self.REAL_PROSE
        assert row["content"] == self.REAL_PROSE


@pytest.mark.postgres
@pytest.mark.integration
class TestContentValidationWithPersistentPatterns:
    """Test content validation with actual persistent_boilerplate_patterns table."""

    def test_persistent_patterns_strip_boilerplate_before_validation(
        self, cloud_sql_session
    ):
        """Test that persistent boilerplate patterns are used for content validation.

        This integration test verifies:
        1. BalancedBoundaryContentCleaner queries persistent_boilerplate_patterns
        2. Domain-specific patterns are applied during content validation
        3. Articles with insufficient non-boilerplate content are skipped
        """
        from sqlalchemy import text

        from src.models import CandidateLink, Source
        from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner

        # Create test source
        source = Source(
            id="source-test-boilerplate",
            host="testboilerplate.com",
            host_norm="testboilerplate.com",
            canonical_name="Test Boilerplate News",
            status="active",
        )
        cloud_sql_session.add(source)

        # Create candidate link
        candidate = CandidateLink(
            id="cand-test-boilerplate",
            url="https://testboilerplate.com/article",
            source="testboilerplate.com",
            source_id=source.id,
            status="article",
        )
        cloud_sql_session.add(candidate)
        cloud_sql_session.commit()

        # Insert persistent boilerplate pattern for this domain
        cloud_sql_session.execute(
            text("""
                INSERT INTO persistent_boilerplate_patterns (
                    id, domain, pattern_type, pattern_text, pattern_text_hash,
                    occurrence_count, is_active
                ) VALUES (
                    :id, :domain, :pattern_type, :pattern_text, :pattern_text_hash,
                    :occurrences, :is_active
                )
                """),
            {
                "id": "pattern-login-form",
                "domain": "testboilerplate.com",
                "pattern_type": "subscription",
                "pattern_text": "Get up-to-the-minute news sent straight to your device",
                "pattern_text_hash": 123456789,
                "occurrences": 10,
                "is_active": True,
            },
        )
        cloud_sql_session.commit()

        # Test content with mostly boilerplate
        content_text = (
            "Get up-to-the-minute news sent straight to your device\n"
            "Subscribe to continue reading\n"
            "This is actual article content but it's too short"
        )

        # Use BalancedBoundaryContentCleaner to strip boilerplate
        # Mock telemetry to return our persistent pattern
        from unittest.mock import Mock

        # Pattern must be >= 150 chars to bypass length filter in _remove_persistent_patterns
        boilerplate_pattern = (
            "Get up-to-the-minute news sent straight to your device. "
            "Subscribe to continue reading this article and get unlimited access to our premium content. "
            "Sign up today for just $9.99/month!"
        )

        mock_telemetry = Mock()
        mock_telemetry.get_persistent_patterns.return_value = [
            {
                "text_content": boilerplate_pattern,
                "pattern_type": "subscription",
                "confidence_score": 0.95,
                "occurrences_total": 10,
                "removal_reason": "Persistent subscription pattern",
            }
        ]

        # Patch ContentCleaningTelemetry to return our mock
        with patch(
            "src.utils.content_cleaner_balanced.ContentCleaningTelemetry",
            return_value=mock_telemetry,
        ):
            cleaner = BalancedBoundaryContentCleaner(enable_telemetry=True)

            # Test content with the boilerplate pattern
            content_text = (
                boilerplate_pattern + "\n"
                "This is actual article content but it's too short"
            )

            stripped_content, metadata = cleaner.process_single_article(
                text=content_text,
                domain="testboilerplate.com",
                dry_run=True,
            )

        # Verify boilerplate was removed
        assert "Get up-to-the-minute news" not in stripped_content
        # Verify remaining content is less than MIN_CONTENT_LENGTH (150)
        assert len(stripped_content.strip()) < 150

        # Verify pattern lookup was called (no article_id -> source_id is None,
        # so the reader falls back to domain-keyed patterns)
        mock_telemetry.get_persistent_patterns.assert_called_with(
            "testboilerplate.com", source_id=None
        )


@pytest.mark.postgres
@pytest.mark.integration
class TestInsufficientContentIntegration:
    """Integration test covering insufficient-content branch persistence."""

    def test_insufficient_content_without_paywall_updates_candidate(
        self, cloud_sql_session, monkeypatch
    ):
        from datetime import datetime, timezone

        from sqlalchemy import text

        from src.models import CandidateLink, Source

        dataset_id = "dataset-short-content"

        source = Source(
            id="source-short-content",
            host="shortcontent.com",
            host_norm="shortcontent.com",
            canonical_name="Short Content News",
            status="active",
        )
        cloud_sql_session.add(source)
        cloud_sql_session.flush()

        candidate = CandidateLink(
            id="cand-short-content",
            url="https://shortcontent.com/article",
            source="shortcontent.com",
            source_id=source.id,
            dataset_id=dataset_id,
            status="article",
            discovered_at=datetime.now(timezone.utc),
        )
        cloud_sql_session.add(candidate)
        cloud_sql_session.commit()

        class FakeExtractor:
            def _check_rate_limit(self, domain):
                return False

            def extract_content(self, *args, **kwargs):
                return {
                    "title": "Short Story",
                    "content": "too short",
                    "author": None,
                    "metadata": {},
                }

            def get_driver_stats(self):
                return {"has_persistent_driver": False}

        class FakeBylineCleaner:
            def clean_byline(self, *args, **kwargs):
                return {"authors": [], "wire_services": []}

        class FakeContentCleaner:
            def process_single_article(self, text, domain, dry_run=False):
                return text, {"patterns_matched": []}

        class FakeTelemetry:
            def record_extraction(self, *args, **kwargs):
                pass

        class FakeMetrics:
            def __init__(self, *args, **kwargs):
                pass

            def set_content_type_detection(self, *args):
                pass

            # **kwargs so a new finalize() argument cannot silently blow up
            # this fake: the production call now passes outcome=<status>,
            # and a TypeError here is swallowed as an extraction failure.
            def finalize(self, *args, **kwargs):
                pass

        monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
        monkeypatch.setattr(extraction, "calculate_content_hash", lambda *a: "hash")
        monkeypatch.setattr(
            extraction,
            "ContentTypeDetector",
            lambda **kw: Mock(detect=lambda **k: None),
        )

        args = Namespace(dataset=dataset_id, dump_sql=False)
        telemetry = FakeTelemetry()
        domains_for_cleaning = defaultdict(list)

        candidate_id = (
            candidate.id
        )  # _process_batch commits and detaches the original instance

        extraction._process_batch(
            args,
            FakeExtractor(),
            FakeBylineCleaner(),
            FakeContentCleaner(),
            telemetry,
            per_batch=1,
            batch_num=1,
            host_403_tracker={},
            domains_for_cleaning=domains_for_cleaning,
            db=SimpleNamespace(session=cloud_sql_session),
        )

        cloud_sql_session.expire_all()
        candidate = cloud_sql_session.get(CandidateLink, candidate_id)
        assert candidate is not None
        assert candidate.status == "extracted"
        assert candidate.error_message == "Insufficient content (no paywall detected)"

        article_count = cloud_sql_session.execute(
            text("SELECT COUNT(*) FROM articles WHERE candidate_link_id = :id"),
            {"id": candidate.id},
        ).scalar()
        assert article_count == 0
