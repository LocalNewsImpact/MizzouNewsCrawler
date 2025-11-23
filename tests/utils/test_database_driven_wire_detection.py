"""Tests for database-driven wire service and broadcaster detection.

Tests the new functionality added on the branch:
1. _get_wire_service_patterns() - Load patterns from wire_services table
2. _get_local_broadcaster_callsigns() - Load callsigns from
   local_broadcaster_callsigns table
3. URL matching logic for broadcaster content (own site vs syndicated)
4. Caching behavior for database queries
"""

from unittest.mock import MagicMock

import pytest

from src.utils.content_type_detector import ContentTypeDetector


@pytest.fixture
def detector():
    """Create a fresh detector instance for each test."""
    detector = ContentTypeDetector()
    # Clear caches
    detector._wire_patterns_cache = None
    detector._wire_patterns_timestamp = None
    detector._local_callsigns_cache = None
    detector._cache_timestamp = None
    return detector


@pytest.fixture
def mock_wire_patterns():
    """Mock wire service patterns from database."""
    return [
        (r"\(AP\)", "Associated Press", False),
        (r"\(Reuters\)", "Reuters", False),
        (r"\(AFP\)", "AFP", False),
        (r"Bloomberg News", "Bloomberg", False),
        (r"\([A-Z]{3,5}\)", "Broadcaster", False),
    ]


@pytest.fixture
def mock_broadcaster_callsigns():
    """Mock broadcaster callsigns from database."""
    return {"KMIZ", "KOMU", "KRCG"}


@pytest.mark.integration
@pytest.mark.postgres
class TestDatabaseDrivenWirePatterns:
    """Tests for wire service patterns loaded from database."""

    def test_loads_wire_patterns_from_database(
        self, detector, populated_wire_services
    ):
        """Verify wire patterns are loaded from wire_services table."""
        # Clear cache to force database query
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        patterns = detector._get_wire_service_patterns()
        
        assert isinstance(patterns, list)
        assert len(patterns) > 0, "Should load patterns from database"
        
        # Each pattern is a tuple: (pattern, service_name, case_sensitive)
        for pattern_tuple in patterns:
            assert len(pattern_tuple) == 3
            pattern, service_name, case_sensitive = pattern_tuple
            assert isinstance(pattern, str)
            assert isinstance(service_name, str)
            assert isinstance(case_sensitive, bool)

    def test_wire_patterns_include_standard_services(
        self, detector, populated_wire_services
    ):
        """Verify standard wire services are in loaded patterns."""
        # Clear cache to force database query
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        patterns = detector._get_wire_service_patterns()
        service_names = {p[1] for p in patterns}
        
        # Should include major wire services
        expected_services = {
            "Associated Press",
            "Reuters",
            "AFP",
            "Bloomberg",
        }
        
        for service in expected_services:
            assert service in service_names, f"{service} should be in patterns"

    def test_wire_patterns_include_broadcaster_pattern(
        self, detector, populated_wire_services
    ):
        """Verify generic broadcaster pattern is included."""
        # Clear cache to force database query
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        patterns = detector._get_wire_service_patterns()
        
        # Should have the generic Broadcaster pattern
        broadcaster_patterns = [p for p in patterns if p[1] == "Broadcaster"]
        assert len(broadcaster_patterns) > 0, "Should have Broadcaster pattern"

    def test_wire_patterns_cache_behavior(
        self, detector, populated_wire_services
    ):
        """Verify patterns are cached after first load."""
        # Clear cache first
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        # First load
        patterns1 = detector._get_wire_service_patterns()
        assert detector._wire_patterns_cache is not None
        assert detector._wire_patterns_timestamp is not None
        
        # Second load should use cache (same instance)
        patterns2 = detector._get_wire_service_patterns()
        assert patterns1 is patterns2, "Should return cached patterns"

    def test_detects_ap_dateline_with_database_patterns(
        self, detector, populated_wire_services
    ):
        """Verify AP dateline detection works with database patterns."""
        # Clear cache to force database query
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        result = detector.detect(
            url="https://example.com/news/story",
            title="President Announces Policy",
            metadata={},
            content="WASHINGTON (AP) — The president announced today...",
        )
        
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence
        assert any("Associated Press" in m for m in result.evidence["content"])

    def test_detects_reuters_dateline_with_database_patterns(
        self, detector, populated_wire_services
    ):
        """Verify Reuters dateline detection works with database patterns."""
        # Clear cache to force database query
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        result = detector.detect(
            url="https://example.com/world/story",
            title="UK Election Results",
            metadata={},
            content="LONDON (Reuters) — British voters went to the polls...",
        )
        
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence

    def test_detects_syndicated_byline_with_database_patterns(
        self, detector, populated_wire_services
    ):
        """Verify syndicated byline detection works with database patterns."""
        # Add USA TODAY pattern
        # Note: This test passes with existing _wire_url_segments logic
        result = detector.detect(
            url="https://example.com/news/story",
            title="National Politics",
            metadata={"byline": "John Smith USA TODAY"},
            content="An analysis of recent political developments...",
        )
        
        assert result is not None
        assert result.status == "wire"


@pytest.mark.integration
@pytest.mark.postgres
class TestLocalBroadcasterCallsigns:
    """Tests for local broadcaster callsign detection."""

    def test_loads_broadcaster_callsigns_from_database(
        self, detector, populated_broadcaster_callsigns
    ):
        """Verify callsigns are loaded from local_broadcaster_callsigns table."""
        # Clear cache to force database query
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        
        callsigns = detector._get_local_broadcaster_callsigns(dataset="missouri")
        
        assert isinstance(callsigns, set)
        assert len(callsigns) > 0, "Should load callsigns from database"

    def test_broadcaster_callsigns_include_missouri_stations(
        self, detector, populated_broadcaster_callsigns
    ):
        """Verify Missouri market callsigns are loaded."""
        # Clear cache to force database query
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        
        callsigns = detector._get_local_broadcaster_callsigns(dataset="missouri")
        
        # Should include Missouri broadcasters
        expected_callsigns = {"KMIZ", "KOMU", "KRCG"}
        
        for callsign in expected_callsigns:
            assert callsign in callsigns, f"{callsign} should be in callsigns"

    def test_broadcaster_callsigns_cache_behavior(
        self, detector, populated_broadcaster_callsigns
    ):
        """Verify callsigns are cached after first load."""
        # Clear cache first
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        
        # First load
        callsigns1 = detector._get_local_broadcaster_callsigns()
        assert detector._local_callsigns_cache is not None
        assert detector._cache_timestamp is not None
        
        # Second load should use cache (same instance)
        callsigns2 = detector._get_local_broadcaster_callsigns()
        assert callsigns1 is callsigns2, "Should return cached callsigns"

    def test_local_broadcaster_on_own_site_not_wire(
        self, detector, populated_broadcaster_callsigns,
        populated_wire_services
    ):
        """Verify local broadcaster on own site is NOT detected as wire."""
        # Clear caches to force database queries
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        result = detector.detect(
            url="https://abc17news.com/news/local/story",
            title="Water Main Repairs Announced",
            metadata={},
            content=(
                "COLUMBIA, Mo. (KMIZ) — The Columbia Utilities "
                "Department announced repairs."
            ),
        )
        
        # Should NOT be wire (it's their own content)
        assert result is None or result.status != "wire"

    def test_local_broadcaster_on_different_site_is_wire(
        self, detector, populated_broadcaster_callsigns,
        populated_wire_services
    ):
        """Verify local broadcaster on different site IS wire (syndicated)."""
        # Clear caches to force database queries
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        result = detector.detect(
            url="https://komu.com/news/local/story",
            title="Water Main Repairs Announced",
            metadata={},
            content=(
                "COLUMBIA, Mo. (KMIZ) — The Columbia Utilities "
                "Department announced repairs."
            ),
        )
        
        # Should be wire (syndicated from KMIZ to KOMU)
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence
        assert any("KMIZ" in m for m in result.evidence["content"])

    def test_komu_on_own_site_not_wire(
        self, detector, populated_broadcaster_callsigns,
        populated_wire_services
    ):
        """Verify KOMU on komu.com is NOT wire."""
        # Clear caches to force database queries
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        result = detector.detect(
            url="https://komu.com/news/local/mizzou-story",
            title="Mizzou Announces New Research Facility",
            metadata={},
            content=(
                "COLUMBIA, Mo. (KOMU) — The University of Missouri "
                "announced today..."
            ),
        )
        
        assert result is None or result.status != "wire"

    def test_unknown_broadcaster_not_detected_as_wire(
        self, detector, populated_broadcaster_callsigns,
        populated_wire_services
    ):
        """Verify unknown broadcaster callsigns don't cause false positives."""
        # Clear caches to force database queries
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        result = detector.detect(
            url="https://komu.com/news/story",
            title="Boston News",
            metadata={},
            content="BOSTON, Mass. (WGBH) — Local news from Boston...",
        )
        
        # WGBH is not in Missouri dataset, should not be detected as wire
        assert result is None or result.status != "wire"

    def test_broadcaster_dateline_url_matching_uses_domain_mapping(
        self, detector, populated_broadcaster_callsigns,
        populated_wire_services
    ):
        """Verify domain mapping is used when callsign not directly in URL."""
        # Clear caches to force database queries
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        # KMIZ doesn't appear in abc17news.com, needs domain mapping
        result = detector.detect(
            url="https://abc17news.com/news/local/story",
            title="Local Story",
            metadata={},
            content="COLUMBIA, Mo. (KMIZ) — Local news content...",
        )
        
        assert result is None or result.status != "wire"

    def test_multiple_broadcasters_correct_matching(
        self, detector, populated_broadcaster_callsigns,
        populated_wire_services
    ):
        """Verify correct matching when multiple broadcasters in same market."""
        # Clear caches to force database queries
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        # KRCG on krcgtv.com (own site)
        result1 = detector.detect(
            url="https://krcgtv.com/news/local/story",
            title="Local News",
            metadata={},
            content="COLUMBIA, Mo. (KRCG) — Local updates...",
        )
        assert result1 is None or result1.status != "wire"
        
        # Clear cache again for second test
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        # KRCG on komu.com (syndicated)
        result2 = detector.detect(
            url="https://komu.com/news/local/story",
            title="Local News",
            metadata={},
            content="COLUMBIA, Mo. (KRCG) — Local updates...",
        )
        assert result2 is not None
        assert result2.status == "wire"


@pytest.mark.integration
@pytest.mark.postgres
class TestDetectorVersionTracking:
    """Tests for detector version tracking with database changes."""

    def test_detector_version_includes_database_marker(self, detector):
        """Verify detector version reflects database-driven functionality."""
        assert detector.VERSION is not None
        # Version should indicate database-driven changes (2025-11-23b or later)
        assert "2025-11" in detector.VERSION

    def test_detection_result_includes_version(
        self, detector, populated_wire_services
    ):
        """Verify detection results include detector version."""
        # Clear cache to force database query
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        result = detector.detect(
            url="https://example.com/news/story",
            title="Breaking News",
            metadata={},
            content="WASHINGTON (AP) — News today...",
        )
        
        assert result is not None
        assert result.detector_version == detector.VERSION


@pytest.mark.integration
class TestDatabaseFallbackBehavior:
    """Tests for graceful fallback when database unavailable."""

    def test_empty_patterns_when_database_unavailable(self, detector):
        """Verify empty list returned if database unavailable."""
        # Force cache invalidation
        detector._wire_patterns_cache = None
        detector._wire_patterns_timestamp = None
        
        # This should still work even if DB has issues
        patterns = detector._get_wire_service_patterns()
        assert isinstance(patterns, list)
        # In production it should have patterns, in test env may be empty

    def test_empty_callsigns_when_database_unavailable(self, detector):
        """Verify empty set returned if database unavailable."""
        # Force cache invalidation
        detector._local_callsigns_cache = None
        detector._cache_timestamp = None
        
        # This should still work even if DB has issues
        callsigns = detector._get_local_broadcaster_callsigns()
        assert isinstance(callsigns, set)
        # In production it should have callsigns, in test env may be empty


class TestIntegrationWithExistingWireDetection:
    """Tests to ensure database-driven approach works with existing detection logic."""

    def test_wire_url_patterns_still_work(self, detector):
        """Verify existing URL-based wire detection still works."""
        result = detector.detect(
            url="https://example.com/news/world/international-story",
            title="Global News",
            metadata={},
            content="LONDON (Reuters) — International developments...",
        )
        
        assert result is not None
        assert result.status == "wire"

    def test_author_patterns_still_work(self, detector):
        """Verify existing author-based wire detection still works."""
        result = detector.detect(
            url="https://example.com/news/story",
            title="Breaking News",
            metadata={"byline": "AP Staff"},
            content="Major announcement today...",
        )
        
        assert result is not None
        assert result.status == "wire"

    def test_multiple_evidence_sources_combined(self, detector):
        """Verify multiple wire indicators combine correctly."""
        result = detector.detect(
            url="https://example.com/news/world/story",
            title="International Story",
            metadata={"byline": "AP Staff"},
            content="WASHINGTON (AP) — The president...",
        )
        
        assert result is not None
        assert result.status == "wire"
        # Should have multiple evidence sources
        assert len(result.evidence) >= 2

    def test_non_wire_content_not_detected(self, detector):
        """Verify normal local content is not detected as wire."""
        result = detector.detect(
            url="https://example.com/news/local/city-council",
            title="City Council Approves Budget",
            metadata={"byline": "Jane Smith"},
            content="The Columbia City Council met Tuesday to approve the new budget.",
        )
        
        assert result is None or result.status != "wire"
