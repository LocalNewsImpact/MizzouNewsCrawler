from __future__ import annotations

from datetime import datetime

import pytest

from src.models import (
    Article,
    ArticleEntity,
    ArticleLabel,
    CandidateLink,
    Source,
)
from src.reporting.county_report import (
    CountyReportConfig,
    _clean_counties,
    generate_county_report,
)


def _add_base_records(
    reporting_db,
    publish_date: datetime,
    status: str = "cleaned",
):
    source = Source(
        id="source-1",
        host="example.com",
        host_norm="example.com",
        county="Boone",
    )
    candidate = CandidateLink(
        id="candidate-1",
        url="https://example.com/article",
        source="Example Publisher",
        status="processed",
        source_county="Boone",
        source_id=source.id,
    )
    article = Article(
        id="article-1",
        candidate_link_id=candidate.id,
        publish_date=publish_date,
        url="https://example.com/article",
        title="Local story",
        author="Jane Doe",
        status=status,
        primary_label="baseline",
        alternate_label="baseline-alt",
    )
    reporting_db.session.add_all([source, candidate, article])
    reporting_db.session.commit()
    return article


def test_generate_county_report_includes_labels_and_entities(
    reporting_db,
    reporting_db_url,
):
    publish_date = datetime(2024, 9, 25, 12, 30, 0)
    article = _add_base_records(reporting_db, publish_date)

    label = ArticleLabel(
        article_id=article.id,
        label_version="v2",
        model_version="test-model",
        primary_label="override",
        alternate_label="override-alt",
        applied_at=datetime(2024, 9, 26, 8, 0, 0),
    )
    entity = ArticleEntity(
        article_id=article.id,
        entity_text="Columbia",
        entity_norm="columbia",
        entity_label="CITY",
        extractor_version="1.0",
    )
    reporting_db.session.add_all([label, entity])
    reporting_db.session.commit()

    config = CountyReportConfig(
        counties=["Boone"],
        start_date=datetime(2024, 9, 1, 0, 0, 0),
        label_version="v2",
        include_entities=True,
        database_url=reporting_db_url,
    )

    result = generate_county_report(config)

    assert not result.empty
    row = result.iloc[0]
    assert row["primary_label"] == "override"
    assert row["secondary_label"] == "override-alt"
    assert row["entities"] == "Columbia [CITY]"
    assert row["publish_date"] == "2024-09-25 12:30:00"


def test_generate_county_report_filters_excluded_statuses(
    reporting_db,
    reporting_db_url,
):
    publish_date = datetime(2024, 9, 25, 12, 30, 0)
    _add_base_records(reporting_db, publish_date, status="opinion")

    config = CountyReportConfig(
        counties=["Boone"],
        start_date=datetime(2024, 9, 1, 0, 0, 0),
        include_entities=False,
        database_url=reporting_db_url,
    )

    result = generate_county_report(config)

    assert result.empty
    assert list(result.columns) == [
        "article_id",
        "host",
        "publish_date",
        "author",
        "url",
        "title",
        "primary_label",
        "secondary_label",
        "entities",
    ]


def test_clean_counties_requires_non_empty_values():
    with pytest.raises(ValueError):
        _clean_counties(["", "   "])

    cleaned = _clean_counties([" Boone ", "", "Callaway"])
    assert cleaned == ["Boone", "Callaway"]
