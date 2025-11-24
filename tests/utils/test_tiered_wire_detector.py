"""Tests for tiered wire service detector."""

import csv
import pytest
from pathlib import Path

from src.utils.content_type_detector_tiered import TieredWireServiceDetector


class TestTieredWireDetector:
    """Test suite for tiered wire service detection."""

    def test_cnn_content_section_not_wire(self):
        """CNN content sections should not be flagged as wire."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://abc17news.com/sports/cnn-sports/2025/09/20/some-article/",
            content="Article content here",
            metadata={"byline": ""},
            source="ABC 17 KMIZ News",
        )
        
        assert result is None, "CNN content sections should not be detected as wire"

    def test_stacker_content_section_not_wire(self):
        """Stacker content sections should not be flagged as wire."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://example.com/stacker-money/2025/09/20/some-article/",
            content="Article content here",
            metadata={"byline": ""},
            source="Example News",
        )
        
        assert result is None, "Stacker content sections should not be detected as wire"

    def test_ap_wire_path_detected(self):
        """AP wire path patterns should be detected."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://example.com/news/ap-national/2025/09/20/some-article/",
            content="Article content here",
            metadata={"byline": ""},
            source="Example News",
        )
        
        assert result is not None, "AP wire path should be detected"
        assert result.status == "wire"
        assert result.detection_tier == 1

    def test_weather_alert_exclusion(self):
        """NWS weather alerts should not be flagged as wire."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://abc17news.com/alerts/2025/11/24/dense-fog-advisory/",
            content="Dense Fog Advisory issued by NWS Springfield MO...",
            metadata={"title": "Dense Fog Advisory issued November 24"},
            source="ABC 17 KMIZ News",
        )
        
        assert result is None, "NWS weather alerts should not be detected as wire"

    def test_local_broadcaster_byline_on_own_site_not_wire(self):
        """Local broadcaster byline on their own site should not be wire."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://abc17news.com/news/local/some-story/",
            content="Article content here",
            metadata={"byline": "KMIZ Staff"},
            source="ABC 17 KMIZ News",
        )
        
        assert result is None, "Local broadcaster on own site should not be wire"

    def test_wire_byline_detected(self):
        """Wire service byline should be detected."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://example.com/news/national/some-story/",
            content="Article content here",
            metadata={"byline": "Associated Press"},
            source="Example News",
        )
        
        assert result is not None, "Wire byline should be detected"
        assert result.status == "wire"
        assert result.detection_tier == 2

    def test_dateline_detected(self):
        """Dateline patterns should be detected."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://example.com/news/some-story/",
            content="WASHINGTON (AP) — The president announced today...",
            metadata={"byline": ""},
            source="Example News",
        )
        
        assert result is not None, "Dateline should be detected"
        assert result.status == "wire"
        assert result.detection_tier == 3

    def test_own_source_domain_not_wire(self):
        """Content on wire service's own domain should not be flagged."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://cnn.com/2025/09/20/politics/some-story/",
            content="Article content here",
            metadata={"byline": "CNN Staff"},
            source="CNN",
        )
        
        assert result is None, "Content on CNN's own domain should not be wire"


@pytest.mark.integration
@pytest.mark.postgres
class TestGroundTruthValidation:
    """Integration tests using ground truth validation dataset."""

    def test_ground_truth_accuracy(self):
        """
        Validate detector achieves 99% accuracy on ground truth dataset.
        
        The ground truth dataset contains 13,451 articles that should NOT
        be classified as wire service content.
        
        Acceptance criteria: Max 1% false positives (134 articles)
        """
        detector = TieredWireServiceDetector()
        
        # Load ground truth dataset
        ground_truth_path = Path(__file__).parent.parent.parent / "wire_stories_20251122_165127.csv"
        
        if not ground_truth_path.exists():
            pytest.skip(f"Ground truth file not found: {ground_truth_path}")
        
        false_positives = []
        total_count = 0
        
        with open(ground_truth_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_count += 1
                
                # Each row should NOT be detected as wire
                result = detector.detect_wire_service(
                    url=row['URL'],
                    content=None,  # Content not available in ground truth
                    metadata={"byline": row.get('Byline', ''), "title": row.get('Headline', '')},
                    source=row.get('Source', ''),
                )
                
                if result is not None:
                    # False positive - detected as wire when it shouldn't be
                    false_positives.append({
                        'url': row['URL'],
                        'source': row.get('Source', ''),
                        'headline': row.get('Headline', ''),
                        'detection_tier': result.detection_tier,
                        'evidence': result.evidence,
                    })
        
        # Calculate accuracy
        false_positive_count = len(false_positives)
        accuracy = (total_count - false_positive_count) / total_count * 100
        
        print(f"\n{'='*80}")
        print(f"Ground Truth Validation Results")
        print(f"{'='*80}")
        print(f"Total articles: {total_count}")
        print(f"False positives: {false_positive_count}")
        print(f"Accuracy: {accuracy:.2f}%")
        print(f"Target: 99.00% (max 134 false positives)")
        
        if false_positives:
            print(f"\nFalse Positive Examples (showing first 10):")
            for i, fp in enumerate(false_positives[:10]):
                print(f"\n  {i+1}. {fp['headline'][:60]}...")
                print(f"     URL: {fp['url']}")
                print(f"     Tier: {fp['detection_tier']}, Evidence: {fp['evidence']}")
        
        # Acceptance criteria: 99% accuracy (max 1% false positives)
        max_false_positives = int(total_count * 0.01)
        assert false_positive_count <= max_false_positives, (
            f"Failed accuracy requirement: {false_positive_count} false positives "
            f"(max allowed: {max_false_positives}, accuracy: {accuracy:.2f}%)"
        )

    def test_cnn_sections_in_ground_truth(self):
        """Verify CNN content sections are properly excluded."""
        detector = TieredWireServiceDetector()
        
        # Sample CNN section URLs from ground truth
        cnn_urls = [
            "https://abc17news.com/sports/cnn-sports/2025/09/20/some-article/",
            "https://abc17news.com/cnn-spanish/2025/09/20/some-article/",
            "https://abc17news.com/news/national-world/cnn-world/2025/09/20/some-article/",
            "https://abc17news.com/cnn-health/2025/09/20/some-article/",
        ]
        
        for url in cnn_urls:
            result = detector.detect_wire_service(
                url=url,
                content=None,
                metadata={"byline": ""},
                source="ABC 17 KMIZ News",
            )
            assert result is None, f"CNN section should not be wire: {url}"

    def test_stacker_sections_in_ground_truth(self):
        """Verify Stacker content sections are properly excluded."""
        detector = TieredWireServiceDetector()
        
        # Sample Stacker section URLs from ground truth
        stacker_urls = [
            "https://example.com/stacker-money/2025/09/20/some-article/",
            "https://example.com/stacker-lifestyle/2025/09/20/some-article/",
            "https://example.com/stacker-science/2025/09/20/some-article/",
        ]
        
        for url in stacker_urls:
            result = detector.detect_wire_service(
                url=url,
                content=None,
                metadata={"byline": ""},
                source="Example News",
            )
            assert result is None, f"Stacker section should not be wire: {url}"


class TestTierPriority:
    """Test tier priority ordering."""

    def test_tier1_strongest_signal_immediate_return(self):
        """Tier 1 strongest signals should return immediately."""
        detector = TieredWireServiceDetector()
        
        # AP wire path is tier 1 strongest
        result = detector.detect_wire_service(
            url="https://example.com/news/ap-national/some-story/",
            content="WASHINGTON (AP) — Article with dateline...",  # Would be tier 3
            metadata={"byline": ""},
            source="Example News",
        )
        
        assert result is not None
        assert result.detection_tier == 1
        assert result.confidence_level == "high"

    def test_tier2_overrides_tier4(self):
        """Tier 2 byline should be used over tier 4 content patterns."""
        detector = TieredWireServiceDetector()
        
        result = detector.detect_wire_service(
            url="https://example.com/news/national/some-story/",  # Tier 1 medium
            content="According to Reuters...",  # Would be tier 4
            metadata={"byline": "Associated Press"},  # Tier 2
            source="Example News",
        )
        
        assert result is not None
        assert result.detection_tier == 2

    def test_geographic_scope_needs_content_evidence(self):
        """Geographic scope URLs (tier 1 medium) need content evidence."""
        detector = TieredWireServiceDetector()
        
        # Geographic scope without content evidence should not detect
        result = detector.detect_wire_service(
            url="https://example.com/news/national/some-story/",
            content="Generic article content with no wire attribution",
            metadata={"byline": ""},
            source="Example News",
        )
        
        # Should not detect without strong content evidence
        assert result is None or result.detection_tier == 4
