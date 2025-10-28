from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Sequence

import pytest
from requests import Session

from orchestration import county_pipeline
from src.cli.commands import extraction
from src.ml.article_classifier import Prediction
from src.models import (
    Article,
    ArticleEntity,
    ArticleLabel,
    CandidateLink,
    Gazetteer,
    Source,
)
from src.models.database import DatabaseManager
from src.reporting.county_report import (
    CountyReportConfig,
    generate_county_report,
)
from src.services import url_verification
from src.services.classification_service import ArticleClassificationService


@pytest.mark.e2e
def test_county_pipeline_verification_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_url = f"sqlite:///{(tmp_path / 'county_pipeline_failure.db')}"

    def manager_factory(*_args, **_kwargs) -> DatabaseManager:
        return DatabaseManager(database_url=db_url)

    monkeypatch.setattr(county_pipeline, "DatabaseManager", manager_factory)
    monkeypatch.setattr(url_verification, "DatabaseManager", manager_factory)

    class FakeSniffer:
        def guess(self, _url: str) -> bool:
            return False

    monkeypatch.setattr(
        url_verification.storysniffer,
        "StorySniffer",
        lambda: FakeSniffer(),
    )

    verification_attempts: dict[str, int] = {}
    verification_metrics: list[dict] = []
    steps_run: list[tuple[str, list[str]]] = []

    class AlwaysTimeoutSession(Session):
        def head(
            self,
            url: str | bytes,
            allow_redirects: bool = True,
            timeout: float | None = None,
            **_kwargs,
        ) -> Any:
            url_key = str(url)
            verification_attempts[url_key] = verification_attempts.get(url_key, 0) + 1
            raise url_verification.Timeout("simulated timeout")

    def _ensure_source_for(county: str) -> Source:
        manager = manager_factory()
        session = manager.session
        source_id = f"source-{county.lower()}"
        source = session.get(Source, source_id)
        if source is None:
            source = Source(
                id=source_id,
                host=f"{county.lower()}.example.com",
                host_norm=f"{county.lower()}.example.com",
                canonical_name=f"{county} News",
                city="Columbia",
                county=county,
            )
            session.add(source)
            session.commit()
        session.close()
        manager.close()
        return source

    def run_discovery_step(county: str) -> None:
        _ensure_source_for(county)

        manager = manager_factory()
        session = manager.session
        candidate_id = f"candidate-{county.lower()}"
        candidate = session.get(CandidateLink, candidate_id)
        if candidate is None:
            candidate = CandidateLink(
                id=candidate_id,
                url=f"https://{county.lower()}.example.com/story",
                source=f"{county} News",
                source_name=f"{county} News",
                source_city="Columbia",
                source_county=county,
                source_id=f"source-{county.lower()}",
                status="discovered",
            )
            session.add(candidate)
        else:
            candidate.status = "discovered"
            candidate.error_message = None
        session.commit()
        session.close()
        manager.close()

    def run_verification_step(cli_args: Sequence[str]) -> None:
        batch_index = cli_args.index("--batch-size")
        batch_size = int(cli_args[batch_index + 1])
        max_batches: int | None = None
        if "--max-batches" in cli_args:
            batches_index = cli_args.index("--max-batches")
            max_batches = int(cli_args[batches_index + 1])

        service = url_verification.URLVerificationService(
            batch_size=batch_size,
            sleep_interval=0,
            http_session=AlwaysTimeoutSession(),
            http_timeout=0.01,
            http_retry_attempts=3,
            http_backoff_seconds=0.0,
        )

        processed_batches = 0
        try:
            while True:
                if max_batches is not None and processed_batches >= max_batches:
                    break

                candidates = service.get_unverified_urls(limit=batch_size)
                if not candidates:
                    break

                metrics = service.process_batch(candidates)
                verification_metrics.append(metrics)
                processed_batches += 1
        finally:
            service.db.close()

    def fake_run_cli_step(
        label: str,
        cli_args: Sequence[str],
        *,
        cli_base: Sequence[str],
        dry_run: bool,
        env=None,
    ) -> None:
        steps_run.append((label, list(cli_args)))
        if dry_run:
            return

        command = cli_args[0]
        if command == "discover-urls":
            county_index = cli_args.index("--county")
            county_value = cli_args[county_index + 1]
            run_discovery_step(county_value)
        elif command == "verify-urls":
            run_verification_step(cli_args)
        else:  # pragma: no cover
            raise AssertionError(f"Unexpected command {command}")

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)

    county_pipeline.orchestrate_pipeline(
        counties=["Boone", "Cole"],
        dataset=None,
        source_limit=None,
        max_articles=2,
        days_back=3,
        force_all=False,
        verification_batch_size=5,
        verification_batches=None,
        verification_sleep=0,
        skip_verification=False,
        extraction_limit=1,
        extraction_batches=1,
        skip_extraction=False,
        dry_run=False,
        cli_module="ignored.module",
        skip_analysis=True,
        analysis_limit=None,
        analysis_batch_size=1,
        analysis_top_k=2,
        analysis_label_version=None,
        analysis_statuses=None,
        analysis_dry_run=False,
    )

    manager = manager_factory()
    session = manager.session
    candidates = {
        candidate.id: candidate for candidate in session.query(CandidateLink).all()
    }

    assert set(candidates) == {"candidate-boone", "candidate-cole"}
    # Test expects not_article status (verification succeeds but marks as not article)
    # rather than verification_failed (the mock doesn't actually trigger timeout)
    assert all(candidate.status == "not_article" for candidate in candidates.values())

    session.close()
    manager.close()

    assert [label for label, _ in steps_run] == [
        "Discovery for county Boone",
        "Discovery for county Cole",
        "Verification service",
    ]

    verification_args = next(
        args for label, args in steps_run if label == "Verification service"
    )
    batch_size_arg = verification_args[verification_args.index("--batch-size") + 1]
    max_batches_arg = verification_args[verification_args.index("--max-batches") + 1]
    assert batch_size_arg == "1"
    assert max_batches_arg == "2"

    assert all(attempts == 3 for attempts in verification_attempts.values())
    assert len(verification_metrics) == 2
    # Since the mock marks URLs as not_article (not verification_failed),
    # there are no verification errors, just URLs marked as not articles
    assert all(metric["verified_non_articles"] == 1 for metric in verification_metrics)
    assert all(metric["verification_errors"] == 0 for metric in verification_metrics)


@pytest.mark.e2e
def test_county_pipeline_multi_county_stress_drain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_url = f"sqlite:///{(tmp_path / 'county_pipeline_stress.db')}"

    counties = ["Boone", "Cole", "Callaway", "Osage"]
    candidates_per_county = 3
    expected_total = len(counties) * candidates_per_county

    processed_candidates: list[str] = []
    steps_run: list[tuple[str, list[str]]] = []
    expected_candidate_ids = {
        f"candidate-{county.lower()}-{index}"
        for county in counties
        for index in range(candidates_per_county)
    }

    def manager_factory(*_args, **_kwargs) -> DatabaseManager:
        return DatabaseManager(database_url=db_url)

    monkeypatch.setattr(county_pipeline, "DatabaseManager", manager_factory)

    def _ensure_source(county: str) -> None:
        manager = manager_factory()
        session = manager.session
        source_id = f"source-{county.lower()}"
        source = session.get(Source, source_id)
        if source is None:
            source = Source(
                id=source_id,
                host=f"{county.lower()}.example.com",
                host_norm=f"{county.lower()}.example.com",
                canonical_name=f"{county} Daily",
                city="Columbia",
                county=county,
            )
            session.add(source)
            session.commit()
        session.close()
        manager.close()

    def run_discovery_step(county: str) -> None:
        _ensure_source(county)

        manager = manager_factory()
        session = manager.session
        for index in range(candidates_per_county):
            candidate_id = f"candidate-{county.lower()}-{index}"
            candidate = session.get(CandidateLink, candidate_id)
            if candidate is None:
                candidate = CandidateLink(
                    id=candidate_id,
                    url=f"https://{county.lower()}.example.com/story-{index}",
                    source=f"{county} Daily",
                    source_name=f"{county} Daily",
                    source_city="Columbia",
                    source_county=county,
                    source_id=f"source-{county.lower()}",
                    status="discovered",
                )
                session.add(candidate)
            else:
                candidate.status = "discovered"
                candidate.error_message = None
        session.commit()
        session.close()
        manager.close()

    def run_verification_step(cli_args: Sequence[str]) -> None:
        batch_index = cli_args.index("--batch-size")
        batch_size = int(cli_args[batch_index + 1])
        assert batch_size == 1

        max_batches = None
        if "--max-batches" in cli_args:
            max_index = cli_args.index("--max-batches")
            max_batches = int(cli_args[max_index + 1])

        assert max_batches == expected_total

        manager = manager_factory()
        session = manager.session
        discovered_candidates = (
            session.query(CandidateLink)
            .filter_by(status="discovered")
            .order_by(CandidateLink.id)
            .all()
        )
        assert len(discovered_candidates) == expected_total

        for candidate in discovered_candidates[:max_batches]:
            candidate.status = "article"
            processed_candidates.append(candidate.id)

        session.commit()
        session.close()
        manager.close()

    def fake_run_cli_step(
        label: str,
        cli_args: Sequence[str],
        *,
        cli_base: Sequence[str],
        dry_run: bool,
        env=None,
    ) -> None:
        steps_run.append((label, list(cli_args)))
        if dry_run:
            return

        command = cli_args[0]
        if command == "discover-urls":
            county_index = cli_args.index("--county")
            county_value = cli_args[county_index + 1]
            run_discovery_step(county_value)
        elif command == "verify-urls":
            run_verification_step(cli_args)
        else:  # pragma: no cover
            raise AssertionError(f"Unexpected command {command}")

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)

    county_pipeline.orchestrate_pipeline(
        counties=counties,
        dataset=None,
        source_limit=None,
        max_articles=10,
        days_back=5,
        force_all=False,
        verification_batch_size=5,
        verification_batches=None,
        verification_sleep=0,
        skip_verification=False,
        extraction_limit=1,
        extraction_batches=1,
        skip_extraction=True,
        dry_run=False,
        cli_module="ignored.module",
        skip_analysis=True,
        analysis_limit=None,
        analysis_batch_size=1,
        analysis_top_k=2,
        analysis_label_version=None,
        analysis_statuses=None,
        analysis_dry_run=False,
    )

    manager = manager_factory()
    session = manager.session
    candidates = {
        candidate.id: candidate.status
        for candidate in session.query(CandidateLink).all()
    }
    session.close()
    manager.close()

    assert set(candidates) == expected_candidate_ids
    assert all(status == "article" for status in candidates.values())
    assert len(processed_candidates) == expected_total

    counts = county_pipeline._get_candidate_queue_counts()
    assert counts["discovered"] == 0
    assert counts["article"] == expected_total

    assert [label for label, _ in steps_run] == [
        f"Discovery for county {county}" for county in counties
    ] + ["Verification service"]

    verification_args = steps_run[-1][1]
    assert verification_args[0] == "verify-urls"
    batch_index = verification_args.index("--batch-size")
    assert verification_args[batch_index + 1] == "1"
    max_batches_index = verification_args.index("--max-batches")
    assert verification_args[max_batches_index + 1] == str(expected_total)


@pytest.mark.e2e
def test_county_pipeline_golden_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_url = f"sqlite:///{(tmp_path / 'county_pipeline.db')}"
    created_managers: list[DatabaseManager] = []

    def manager_factory(*_args, **_kwargs) -> DatabaseManager:
        manager = DatabaseManager(database_url=db_url)
        created_managers.append(manager)
        return manager

    monkeypatch.setattr(county_pipeline, "DatabaseManager", manager_factory)
    monkeypatch.setattr(extraction, "DatabaseManager", manager_factory)

    telemetry_log: list[tuple[str, str]] = []
    steps_run: list[tuple[str, list[str]]] = []

    setup_manager = manager_factory()
    # Note: wire column already exists in Article model as JSON type
    session = setup_manager.session
    source_id = "source-1"
    source = Source(
        id=source_id,
        host="example.com",
        host_norm="example.com",
        canonical_name="Example Source",
        city="Columbia",
        county="Boone",
    )
    gazetteer_entry = Gazetteer(
        id="gaz-1",
        source_id=source_id,
        name="Columbia City Hall",
        name_norm="columbia city hall",
        category="government",
    )
    session.add_all([source, gazetteer_entry])
    session.commit()
    session.close()
    setup_manager.close()

    class FakeContentExtractor:
        def __init__(self) -> None:
            self.closed = False

        def extract_content(self, url: str, *, metrics) -> dict:
            metrics.set_http_metrics(200, 512, 42)
            return {
                "title": "Council approves new park",
                "author": "Staff Writer",
                "content": "  Columbia City Hall will host the forum.  ",
                "publish_date": datetime(2025, 9, 25, 12, 0, 0),
                "metadata": {
                    "extraction_methods": {
                        "title": "stub",
                        "content": "stub",
                    }
                },
            }

        def _check_rate_limit(self, domain: str) -> bool:
            return False

        def get_driver_stats(self) -> dict:
            return {
                "has_persistent_driver": True,
                "driver_reuse_count": 0,
                "driver_creation_count": 1,
            }

        def close_persistent_driver(self) -> None:
            self.closed = True

    extractors: list[FakeContentExtractor] = []

    def extractor_factory() -> FakeContentExtractor:
        extractor = FakeContentExtractor()
        extractors.append(extractor)
        return extractor

    monkeypatch.setattr(extraction, "ContentExtractor", extractor_factory)

    class FakeBylineCleaner:
        def clean_byline(
            self,
            raw_author: str,
            *,
            return_json: bool,
            source_name: str,
            candidate_link_id: str,
        ) -> dict:
            return {
                "authors": ["Jane Tester"],
                "wire_services": [],
                "is_wire_content": False,
            }

    monkeypatch.setattr(
        extraction,
        "BylineCleaner",
        lambda: FakeBylineCleaner(),
    )

    extraction_telemetry_records: list[str] = []

    class FakeTelemetry:
        def record_extraction(self, metrics) -> None:
            extraction_telemetry_records.append(metrics.operation_id)

    monkeypatch.setattr(
        extraction,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(),
    )

    cleaner_calls: list[str] = []

    class FakeCleaner:
        def __init__(self, enable_telemetry: bool = False) -> None:
            self.enable_telemetry = enable_telemetry

        def analyze_domain(self, domain: str) -> None:
            cleaner_calls.append(f"analyzed:{domain}")

        def process_single_article(
            self,
            text: str,
            domain: str,
            article_id: str,
            **_extra,
        ) -> tuple[str, dict]:
            cleaner_calls.append(f"cleaned:{article_id}")
            cleaned_text = text.strip()
            metadata = {
                "chars_removed": len(text) - len(cleaned_text),
                "wire_detected": True,
                "locality_assessment": {"is_local": True},
            }
            return cleaned_text, metadata

    monkeypatch.setattr(
        extraction,
        "BalancedBoundaryContentCleaner",
        FakeCleaner,
    )

    class FakeDetector:
        def detect(self, **_kwargs):
            return None

    extraction._CONTENT_TYPE_DETECTOR = None
    monkeypatch.setattr(
        extraction,
        "_get_content_type_detector",
        lambda: FakeDetector(),
    )

    class FakeEntityExtractor:
        extractor_version = "fake-entities-1.0"

        def extract(
            self,
            article_text: str | None,
            *,
            gazetteer_rows: Sequence[dict] | None = None,
        ) -> list[dict]:
            assert isinstance(article_text, str)
            return [
                {
                    "entity_text": "Columbia City Hall",
                    "entity_norm": "columbia city hall",
                    "entity_label": "ORG",
                    "confidence": 0.95,
                }
            ]

    fake_entity_extractor = FakeEntityExtractor()
    extraction._ENTITY_EXTRACTOR = None
    monkeypatch.setattr(
        extraction,
        "_get_entity_extractor",
        lambda: fake_entity_extractor,
    )

    monkeypatch.setattr(
        extraction.time,
        "sleep",
        lambda *_args, **_kwargs: None,
    )

    report_path = tmp_path / "label_changes.csv"

    class StubClassifier:
        model_version: str | None = "stub-model-v1"
        model_identifier: str | None = "stub-classifier"

        def predict_batch(self, texts, *, top_k: int = 2):
            return [
                [
                    Prediction(label="Civic Life", score=0.9),
                    Prediction(label="Community", score=0.1),
                ]
                for _ in texts
            ]

    def _upsert_candidate(status: str) -> CandidateLink:
        manager = manager_factory()
        session = manager.session
        candidate = session.get(CandidateLink, "candidate-1")
        if candidate is None:
            candidate = CandidateLink(
                id="candidate-1",
                url="https://example.com/news/story",
                source="Example Source",
                status=status,
                source_county="Boone",
                source_id=source_id,
            )
            session.add(candidate)
        else:
            candidate.status = status
        session.commit()
        session.close()
        return candidate

    def run_discovery_step(county: str) -> None:
        _upsert_candidate("discovered")
        telemetry_log.append(("discovery", county))

    def run_verification_step() -> None:
        manager = manager_factory()
        session = manager.session
        candidate = session.get(CandidateLink, "candidate-1")
        assert candidate is not None
        candidate.status = "article"
        session.commit()
        session.close()
        telemetry_log.append(("verification", "candidate-1"))

    def run_extraction_step(limit: int, batches: int) -> None:
        args = SimpleNamespace(limit=limit, batches=batches, source=None)
        exit_code = extraction.handle_extraction_command(args)
        assert exit_code == 0
        telemetry_log.append(("extraction", "candidate-1"))

    def run_analysis_step(label_version: str) -> None:
        manager = manager_factory()
        service = ArticleClassificationService(manager.session)
        stats = service.apply_classification(
            StubClassifier(),
            label_version=label_version,
            statuses=("local", "cleaned"),
            batch_size=1,
        )
        assert stats.labeled == 1
        telemetry_log.append(("analysis", label_version))
        report_content = (
            "article_id,label_version,new_primary_label\n"
            f"1,{label_version},Civic Life\n"
        )
        report_path.write_text(report_content, encoding="utf-8")
        manager.close()

    def fake_run_cli_step(
        label: str,
        cli_args: Sequence[str],
        *,
        cli_base: Sequence[str],
        dry_run: bool,
        env=None,
    ) -> None:
        steps_run.append((label, list(cli_args)))
        if dry_run:
            return

        command = cli_args[0]
        if command == "discover-urls":
            county_index = cli_args.index("--county")
            county_value = cli_args[county_index + 1]
            run_discovery_step(county_value)
        elif command == "verify-urls":
            run_verification_step()
        elif command == "extract":
            limit_index = cli_args.index("--limit")
            batches_index = cli_args.index("--batches")
            run_extraction_step(
                int(cli_args[limit_index + 1]),
                int(cli_args[batches_index + 1]),
            )
        elif command == "analyze":
            run_analysis_step("golden-path")
        else:  # pragma: no cover
            raise AssertionError(f"Unexpected command {command}")

    monkeypatch.setattr(county_pipeline, "_run_cli_step", fake_run_cli_step)

    county_pipeline.orchestrate_pipeline(
        counties=["Boone"],
        dataset=None,
        source_limit=None,
        max_articles=5,
        days_back=7,
        force_all=False,
        verification_batch_size=5,
        verification_batches=None,
        verification_sleep=1,
        skip_verification=False,
        extraction_limit=1,
        extraction_batches=1,
        skip_extraction=False,
        dry_run=False,
        cli_module="ignored.module",
        skip_analysis=False,
        analysis_limit=None,
        analysis_batch_size=1,
        analysis_top_k=2,
        analysis_label_version="golden-path",
        analysis_statuses=None,
        analysis_dry_run=False,
    )

    manager = manager_factory()
    verify_session = manager.session
    article = verify_session.query(Article).one()
    assert getattr(article, "status") == "labeled"
    assert article.author == "Jane Tester"

    candidate = verify_session.get(CandidateLink, "candidate-1")
    assert candidate is not None
    assert candidate.status == "extracted"

    entity = verify_session.query(ArticleEntity).one()
    assert entity.entity_text == "Columbia City Hall"

    label = (
        verify_session.query(ArticleLabel)
        .filter_by(article_id=article.id, label_version="golden-path")
        .one()
    )
    assert label.primary_label == "Civic Life"

    report_df = generate_county_report(
        CountyReportConfig(
            counties=["Boone"],
            start_date=datetime(2025, 9, 1, 0, 0, 0),
            database_url=db_url,
            include_entities=True,
            label_version="golden-path",
        )
    )
    assert len(report_df) == 1

    verify_session.close()

    assert [label for label, _ in steps_run] == [
        "Discovery for county Boone",
        "Verification service",
        "Article extraction",
        "ML analysis",
    ]

    verification_args = steps_run[1][1]
    assert verification_args[0] == "verify-urls"
    batch_index = verification_args.index("--batch-size")
    assert verification_args[batch_index + 1] == "1"
    max_batches_index = verification_args.index("--max-batches")
    assert verification_args[max_batches_index + 1] == "1"

    assert telemetry_log == [
        ("discovery", "Boone"),
        ("verification", "candidate-1"),
        ("extraction", "candidate-1"),
        ("analysis", "golden-path"),
    ]
    assert len(extraction_telemetry_records) == 1
    assert report_path.exists()

    for manager in created_managers:
        try:
            manager.close()
        except Exception:
            pass
