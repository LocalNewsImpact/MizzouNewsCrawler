from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable

import pytest

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
from src.services.classification_service import ArticleClassificationService


@dataclass
class ExtractionTestContext:
    """Container for extraction test harness state."""

    db_url: str
    manager_factory: Callable[..., DatabaseManager]
    created_managers: list[DatabaseManager]
    telemetry_records: list[dict[str, Any]]
    cleaner_calls: list[str]
    created_extractors: list[Any]


def _setup_extraction_test_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    extractor_factory: Callable[[], Any],
    byline_payload: dict[str, Any],
    cleaner_metadata_factory: Callable[..., dict[str, Any]],
    entity_extractor: Any,
) -> ExtractionTestContext:
    db_url = f"sqlite:///{(tmp_path / 'golden_pipeline.db')}"
    created_managers: list[DatabaseManager] = []

    def manager_factory(*_args, **_kwargs) -> DatabaseManager:
        manager = DatabaseManager(database_url=db_url)
        created_managers.append(manager)
        return manager

    monkeypatch.setattr(extraction, "DatabaseManager", manager_factory)

    telemetry_records: list[dict[str, Any]] = []

    class FakeTelemetry:
        def record_extraction(self, metrics) -> None:
            telemetry_records.append(
                {
                    "operation_id": metrics.operation_id,
                    "error_type": getattr(metrics, "error_type", None),
                    "error_message": getattr(metrics, "error_message", None),
                    "http_status": getattr(metrics, "http_status_code", None),
                    "status": getattr(metrics, "is_success", None),
                }
            )

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
        ) -> tuple[str, dict[str, Any]]:
            cleaner_calls.append(f"cleaned:{article_id}")
            cleaned_text = text.strip()
            metadata = cleaner_metadata_factory(
                text=text,
                cleaned_text=cleaned_text,
                domain=domain,
                article_id=article_id,
            )
            return cleaned_text, metadata

    monkeypatch.setattr(
        extraction,
        "BalancedBoundaryContentCleaner",
        FakeCleaner,
    )

    class FakeBylineCleaner:
        def clean_byline(
            self,
            raw_author: str,
            *,
            return_json: bool,
            source_name: str,
            candidate_link_id: str,
        ) -> dict[str, Any]:
            return byline_payload

    monkeypatch.setattr(
        extraction,
        "BylineCleaner",
        lambda: FakeBylineCleaner(),
    )

    created_extractors: list[Any] = []

    def wrapped_extractor_factory() -> Any:
        extractor_instance = extractor_factory()
        created_extractors.append(extractor_instance)
        return extractor_instance

    monkeypatch.setattr(
        extraction,
        "ContentExtractor",
        wrapped_extractor_factory,
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

    extraction._ENTITY_EXTRACTOR = None
    monkeypatch.setattr(
        extraction,
        "_get_entity_extractor",
        lambda: entity_extractor,
    )

    monkeypatch.setattr(
        extraction.time,
        "sleep",
        lambda *_args, **_kwargs: None,
    )

    return ExtractionTestContext(
        db_url=db_url,
        manager_factory=manager_factory,
        created_managers=created_managers,
        telemetry_records=telemetry_records,
        cleaner_calls=cleaner_calls,
        created_extractors=created_extractors,
    )


@pytest.mark.e2e
def test_extraction_pipeline_through_analysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class HappyContentExtractor:
        def __init__(self) -> None:
            self.closed = False

        def extract_content(self, url: str, *, metrics) -> dict[str, Any]:
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

        def get_driver_stats(self) -> dict[str, Any]:
            return {
                "has_persistent_driver": True,
                "driver_reuse_count": 0,
                "driver_creation_count": 1,
            }

        def close_persistent_driver(self) -> None:
            self.closed = True

    def metadata_factory(**kwargs) -> dict[str, Any]:
        text = kwargs["text"]
        cleaned_text = kwargs["cleaned_text"]
        return {
            "chars_removed": len(text) - len(cleaned_text),
            "wire_detected": True,
            "locality_assessment": {"is_local": True},
        }

    class FakeEntityExtractor:
        extractor_version = "fake-entities-1.0"

        def extract(
            self,
            text: str | None,
            *,
            gazetteer_rows=None,
        ) -> list[dict[str, Any]]:
            assert text is not None
            return [
                {
                    "entity_text": "Columbia City Hall",
                    "entity_norm": "columbia city hall",
                    "entity_label": "ORG",
                    "confidence": 0.95,
                }
            ]

    ctx = _setup_extraction_test_environment(
        monkeypatch,
        tmp_path,
        extractor_factory=HappyContentExtractor,
        byline_payload={
            "authors": ["Jane Tester"],
            "wire_services": [],
            "is_wire_content": False,
        },
        cleaner_metadata_factory=metadata_factory,
        entity_extractor=FakeEntityExtractor(),
    )

    setup_manager = ctx.manager_factory()
    session = setup_manager.session
    source = Source(
        id="source-1",
        host="example.com",
        host_norm="example.com",
        canonical_name="Example Source",
        city="Columbia",
        county="Boone",
    )
    candidate = CandidateLink(
        id="candidate-1",
        url="https://example.com/news/story",
        source="Example Source",
        status="article",
        source_county="Boone",
        source_id=source.id,
    )
    gazetteer_entry = Gazetteer(
        id="gaz-1",
        source_id=source.id,
        name="Columbia City Hall",
        name_norm="columbia city hall",
        category="government",
    )
    session.add_all([source, candidate, gazetteer_entry])
    session.commit()
    setup_manager.close()

    try:
        args = SimpleNamespace(batches=1, limit=1, source=None)
        exit_code = extraction.handle_extraction_command(args)
        assert exit_code == 0
        assert ctx.telemetry_records == [
            {
                "operation_id": "ex_1_candidate-1",
                "error_type": None,
                "error_message": None,
                "http_status": 200,
                "status": True,
            }
        ]
        assert ctx.created_extractors and ctx.created_extractors[0].closed

        verify_manager = DatabaseManager(database_url=ctx.db_url)
        ctx.created_managers.append(verify_manager)
        verify_session = verify_manager.session

        article = verify_session.query(Article).one()
        assert article.status == "local"
        assert article.author == "Jane Tester"
        assert article.content == "Columbia City Hall will host the forum."
        assert article.wire is None

        candidate_row = verify_session.get(CandidateLink, "candidate-1")
        assert candidate_row is not None
        assert candidate_row.status == "extracted"

        entities = verify_session.query(ArticleEntity).all()
        assert len(entities) == 1
        entity = entities[0]
        assert entity.entity_text == "Columbia City Hall"
        assert entity.matched_gazetteer_id == "gaz-1"

        assert "analyzed:example.com" in ctx.cleaner_calls
        assert f"cleaned:{article.id}" in ctx.cleaner_calls

        classifier = ArticleClassificationService(verify_session)

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

        stats = classifier.apply_classification(
            StubClassifier(),
            label_version="golden-path",
            statuses=("local",),
            batch_size=1,
        )
        assert stats.labeled == 1

        verify_session.expire_all()
        label_record = (
            verify_session.query(ArticleLabel)
            .filter_by(article_id=article.id, label_version="golden-path")
            .one()
        )
        assert label_record.primary_label == "Civic Life"

        config = CountyReportConfig(
            counties=["Boone"],
            start_date=datetime(2025, 9, 1, 0, 0, 0),
            database_url=ctx.db_url,
            include_entities=True,
            label_version="golden-path",
        )
        report_df = generate_county_report(config)

        assert len(report_df) == 1
        row = report_df.iloc[0]
        assert row["primary_label"] == "Civic Life"
        assert row["publish_date"] == "2025-09-25 12:00:00"
        assert "Columbia City Hall [ORG]" in row["entities"]
    finally:
        for manager in ctx.created_managers:
            try:
                manager.close()
            except Exception:
                pass


@pytest.mark.e2e
def test_extraction_pipeline_handles_failure_and_gazetteer_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FlakyContentExtractor:
        def __init__(self) -> None:
            self.closed = False
            self.calls = 0

        def extract_content(self, url: str, *, metrics) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                metrics.set_http_metrics(500, 0, 0)
                raise RuntimeError("Network down")
            metrics.set_http_metrics(200, 256, 21)
            return {
                "title": "County budget hearing set",
                "author": "Staff Reporter",
                "content": "  The county commission will meet Monday.  ",
                "publish_date": datetime(2025, 9, 26, 15, 30, 0),
                "metadata": {
                    "extraction_methods": {
                        "title": "stub",
                        "content": "stub",
                    }
                },
            }

        def _check_rate_limit(self, domain: str) -> bool:
            return False

        def get_driver_stats(self) -> dict[str, Any]:
            return {
                "has_persistent_driver": True,
                "driver_reuse_count": 0,
                "driver_creation_count": 1,
            }

        def close_persistent_driver(self) -> None:
            self.closed = True

    def miss_metadata_factory(**kwargs) -> dict[str, Any]:
        text = kwargs["text"]
        cleaned_text = kwargs["cleaned_text"]
        return {
            "chars_removed": len(text) - len(cleaned_text),
            "wire_detected": False,
            "locality_assessment": {},
        }

    class GazetteerlessExtractor:
        extractor_version = "fake-entities-2.0"

        def extract(
            self,
            text: str | None,
            *,
            gazetteer_rows=None,
        ) -> list[dict[str, Any]]:
            assert text is not None
            return [
                {
                    "entity_text": "Unknown Park",
                    "entity_norm": "unknown park",
                    "entity_label": "ORG",
                    "confidence": 0.7,
                }
            ]

    ctx = _setup_extraction_test_environment(
        monkeypatch,
        tmp_path,
        extractor_factory=FlakyContentExtractor,
        byline_payload={
            "authors": ["Casey Chronicler"],
            "wire_services": [],
            "is_wire_content": False,
        },
        cleaner_metadata_factory=miss_metadata_factory,
        entity_extractor=GazetteerlessExtractor(),
    )

    setup_manager = ctx.manager_factory()
    session = setup_manager.session
    source = Source(
        id="source-2",
        host="county.example.com",
        host_norm="county.example.com",
        canonical_name="County Example",
        city="Ashland",
        county="Boone",
    )
    candidate_error = CandidateLink(
        id="candidate-error",
        url="https://county.example.com/failure",
        source="County Example",
        status="article",
        source_county="Boone",
        source_id=source.id,
    )
    candidate_success = CandidateLink(
        id="candidate-success",
        url="https://county.example.com/success",
        source="County Example",
        status="article",
        source_county="Boone",
        source_id=source.id,
    )
    session.add_all([source, candidate_error, candidate_success])
    session.commit()
    setup_manager.close()

    try:
        args = SimpleNamespace(
            batches=1, limit=2, source=None, dataset=None, exhaust_queue=False
        )
        exit_code = extraction.handle_extraction_command(args)
        assert exit_code == 0

        telemetry_records = ctx.telemetry_records
        assert len(telemetry_records) == 2
        failure_entry, success_entry = telemetry_records
        assert failure_entry["error_type"] == "exception"
        assert "Network down" in str(failure_entry["error_message"])
        assert failure_entry["http_status"] == 500
        assert success_entry["error_type"] is None
        assert success_entry["http_status"] == 200
        assert success_entry["status"] is True

        _, _, failure_candidate_id = failure_entry["operation_id"].split(
            "_",
            2,
        )
        _, _, success_candidate_id = success_entry["operation_id"].split(
            "_",
            2,
        )

        verify_manager = DatabaseManager(database_url=ctx.db_url)
        ctx.created_managers.append(verify_manager)
        verify_session = verify_manager.session

        articles = verify_session.query(Article).all()
        assert len(articles) == 1
        article = articles[0]
        assert article.candidate_link_id == success_candidate_id
        assert article.status in {"cleaned", "extracted"}
        assert article.wire is None

        failure_candidate_row = verify_session.get(
            CandidateLink,
            failure_candidate_id,
        )
        success_candidate_row = verify_session.get(
            CandidateLink,
            success_candidate_id,
        )
        assert failure_candidate_row is not None
        assert success_candidate_row is not None
        assert failure_candidate_row.status == "article"
        assert success_candidate_row.status == "extracted"

        entities = verify_session.query(ArticleEntity).all()
        assert len(entities) == 1
        assert entities[0].matched_gazetteer_id is None

        extractors = ctx.created_extractors
        assert extractors and extractors[0].closed
        assert any(call.startswith("cleaned:") for call in ctx.cleaner_calls)
    finally:
        for manager in ctx.created_managers:
            try:
                manager.close()
            except Exception:
                pass
