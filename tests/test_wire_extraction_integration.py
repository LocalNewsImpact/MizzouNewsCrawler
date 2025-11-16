"""Integration tests for wire service detection in article extraction.

Tests the integration between ContentTypeDetector and article database storage,
validating that wire detection results are correctly persisted.

CRITICAL: Uses PostgreSQL features and cloud_sql_session fixture.
Must run with @pytest.mark.integration and @pytest.mark.postgres markers.
"""

import json
from datetime import datetime, timezone

import pytest

from src.models import Article, CandidateLink, Source
from src.utils.content_type_detector import ContentTypeDetector


def _build_wire_payload(result):
    """Build wire service JSON payload from ContentTypeDetector result.

    Matches production code format in src/cli/commands/extraction.py where
    wire field is set to json.dumps(wire_services) - a JSON string of a list.

    Args:
        result: ContentTypeResult with status="wire" and evidence dict

    Returns:
        JSON string (like '["AFP", "Reuters"]') or None for non-wire content
    """
    if not result or result.status != "wire":
        return None

    # Extract detected services from evidence
    detected_services = result.evidence.get("detected_services", [])
    if not detected_services:
        return None

    # Return JSON string of the services list (matching production format)
    return json.dumps(detected_services)


@pytest.mark.integration
@pytest.mark.postgres
class TestWireDetectionDatabaseIntegration:
    """Integration tests for wire detection → database storage flow."""

    def test_wire_detection_stores_result_in_article(self, cloud_sql_session):
        """Test wire detection result is stored when creating Article.

        Validates the complete flow:
        1. CandidateLink created with wire service indicators
        2. ContentTypeDetector detects wire service
        3. Article created with wire field set correctly
        4. Data persists in database
        """
        # Create unique source
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        host = f"news-{timestamp}.com"
        source = Source(
            host=host,
            host_norm=host.lower(),
            canonical_name=f"News {timestamp}",
            status="active",
        )
        cloud_sql_session.add(source)
        cloud_sql_session.commit()

        # Create candidate link with AFP author
        url = f"https://news-{timestamp}.com/world/story"
        metadata = {"byline": "Afp Afp", "title": "Breaking News"}
        candidate = CandidateLink(
            url=url,
            source=host,
            status="article",
            discovered_at=datetime.now(timezone.utc),
            meta=metadata,
        )
        cloud_sql_session.add(candidate)
        cloud_sql_session.commit()
        candidate_id = candidate.id

        # Run wire detection
        detector = ContentTypeDetector()
        result = detector.detect(
            url=url,
            title=metadata.get("title"),
            metadata=metadata,
            content=None,
        )

        # Verify detection worked
        assert result is not None, "ContentTypeDetector should detect AFP"
        assert result.status == "wire"

        # Create article with wire detection result (JSON format)
        wire_payload = _build_wire_payload(result)
        article = Article(
            candidate_link_id=candidate_id,
            url=url,
            wire=wire_payload,
            extracted_at=datetime.now(timezone.utc),
        )
        cloud_sql_session.add(article)
        cloud_sql_session.commit()

        # Verify article persisted with correct wire data
        retrieved = (
            cloud_sql_session.query(Article)
            .filter_by(candidate_link_id=candidate.id)
            .first()
        )
        assert retrieved is not None, "Article should be in database"
        assert retrieved.wire is not None, "Article.wire should not be None for AFP"
        # SQLAlchemy JSON column deserializes to list
        assert isinstance(
            retrieved.wire, (list, str)
        ), "wire should be list or JSON string"
        if isinstance(retrieved.wire, list):
            assert "AFP" in retrieved.wire or any(
                "afp" in s.lower() for s in retrieved.wire
            )

    def test_non_wire_article_stores_false(self, cloud_sql_session):
        """Test non-wire content stores wire=False correctly."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        host = f"local-{timestamp}.com"
        source = Source(
            host=host,
            host_norm=host.lower(),
            canonical_name=f"Local {timestamp}",
            status="active",
        )
        cloud_sql_session.add(source)
        cloud_sql_session.commit()

        url = f"https://local-{timestamp}.com/news/story"
        metadata = {"byline": "Jane Reporter", "title": "City Council Meeting"}
        candidate = CandidateLink(
            url=url,
            source=host,
            status="article",
            discovered_at=datetime.now(timezone.utc),
            meta=metadata,
        )
        cloud_sql_session.add(candidate)
        cloud_sql_session.commit()
        candidate_id = candidate.id

        # Run wire detection
        detector = ContentTypeDetector()
        content = "The city council met yesterday to discuss the budget..."
        result = detector.detect(
            url=url,
            title=metadata.get("title"),
            metadata=metadata,
            content=content,
        )

        # Verify detection did not trigger
        assert result is None or result.status != "wire", "Should not detect wire"

        # Create article with no wire data (None for non-wire content)
        wire_payload = _build_wire_payload(result)
        article = Article(
            candidate_link_id=candidate_id,
            url=url,
            wire=wire_payload,
            extracted_at=datetime.now(timezone.utc),
        )
        cloud_sql_session.add(article)
        cloud_sql_session.commit()

        # Verify article persisted with wire=None for non-wire content
        retrieved = (
            cloud_sql_session.query(Article)
            .filter_by(candidate_link_id=candidate.id)
            .first()
        )
        assert retrieved is not None
        assert retrieved.wire is None, "Article.wire should be None for local content"

    def test_ap_dateline_detection_integration(self, cloud_sql_session):
        """Test AP dateline detection integrates with database storage."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        host = f"paper-{timestamp}.com"
        source = Source(
            host=host,
            host_norm=host.lower(),
            canonical_name=f"Paper {timestamp}",
            status="active",
        )
        cloud_sql_session.add(source)
        cloud_sql_session.commit()

        url = f"https://paper-{timestamp}.com/national/politics"
        metadata = {"title": "Political Update"}
        candidate = CandidateLink(
            url=url,
            source=host,
            status="article",
            discovered_at=datetime.now(timezone.utc),
            meta=metadata,
        )
        cloud_sql_session.add(candidate)
        cloud_sql_session.commit()
        candidate_id = candidate.id

        detector = ContentTypeDetector()
        content = "WASHINGTON (AP) — The president announced new policies..."
        result = detector.detect(
            url=url,
            title=metadata.get("title"),
            metadata=metadata,
            content=content,
        )

        assert result is not None, "Should detect AP dateline"
        assert result.status == "wire"

        wire_payload = _build_wire_payload(result)
        article = Article(
            candidate_link_id=candidate_id,
            url=url,
            wire=wire_payload,
            extracted_at=datetime.now(timezone.utc),
        )
        cloud_sql_session.add(article)
        cloud_sql_session.commit()

        retrieved = (
            cloud_sql_session.query(Article)
            .filter_by(candidate_link_id=candidate.id)
            .first()
        )
        assert retrieved.wire is not None, "Article.wire should not be None for AP"
        assert isinstance(
            retrieved.wire, (list, str)
        ), "wire should be list or JSON string"

    def test_reuters_byline_detection_integration(self, cloud_sql_session):
        """Test Reuters byline detection integrates with database storage."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        host = f"outlet-{timestamp}.com"
        source = Source(
            host=host,
            host_norm=host.lower(),
            canonical_name=f"Outlet {timestamp}",
            status="active",
        )
        cloud_sql_session.add(source)
        cloud_sql_session.commit()

        url = f"https://outlet-{timestamp}.com/world/markets"
        metadata = {"byline": "By Reuters", "title": "Market Update"}
        candidate = CandidateLink(
            url=url,
            source=host,
            status="article",
            discovered_at=datetime.now(timezone.utc),
            meta=metadata,
        )
        cloud_sql_session.add(candidate)
        cloud_sql_session.commit()
        candidate_id = candidate.id

        detector = ContentTypeDetector()
        content = "LONDON (Reuters) — Markets rose today..."
        result = detector.detect(
            url=url,
            title=metadata.get("title"),
            metadata=metadata,
            content=content,
        )

        assert result is not None, "Should detect Reuters"
        assert result.status == "wire"

        wire_payload = _build_wire_payload(result)
        article = Article(
            candidate_link_id=candidate_id,
            url=url,
            wire=wire_payload,
            extracted_at=datetime.now(timezone.utc),
        )
        cloud_sql_session.add(article)
        cloud_sql_session.commit()

        retrieved = (
            cloud_sql_session.query(Article)
            .filter_by(candidate_link_id=candidate.id)
            .first()
        )
        assert retrieved.wire is not None, "Article.wire should not be None for Reuters"
        assert isinstance(
            retrieved.wire, (list, str)
        ), "wire should be list or JSON string"

    def test_told_afp_attribution_integration(self, cloud_sql_session):
        """Test 'told AFP' attribution pattern integrates with database."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        host = f"media-{timestamp}.com"
        source = Source(
            host=host,
            host_norm=host.lower(),
            canonical_name=f"Media {timestamp}",
            status="active",
        )
        cloud_sql_session.add(source)
        cloud_sql_session.commit()

        url = f"https://media-{timestamp}.com/world/interview"
        metadata = {"title": "Official Interview"}
        candidate = CandidateLink(
            url=url,
            source=host,
            status="article",
            discovered_at=datetime.now(timezone.utc),
            meta=metadata,
        )
        cloud_sql_session.add(candidate)
        cloud_sql_session.commit()
        candidate_id = candidate.id

        detector = ContentTypeDetector()
        content = "The official told AFP in an exclusive interview that..."
        result = detector.detect(
            url=url,
            title=metadata.get("title"),
            metadata=metadata,
            content=content,
        )

        assert result is not None, "Should detect 'told AFP' attribution"
        assert result.status == "wire"

        wire_payload = _build_wire_payload(result)
        article = Article(
            candidate_link_id=candidate_id,
            url=url,
            wire=wire_payload,
            extracted_at=datetime.now(timezone.utc),
        )
        cloud_sql_session.add(article)
        cloud_sql_session.commit()

        retrieved = (
            cloud_sql_session.query(Article)
            .filter_by(candidate_link_id=candidate.id)
            .first()
        )
        assert (
            retrieved.wire is not None
        ), "Article.wire should not be None for 'told AFP'"
        assert isinstance(
            retrieved.wire, (list, str)
        ), "wire should be list or JSON string"
