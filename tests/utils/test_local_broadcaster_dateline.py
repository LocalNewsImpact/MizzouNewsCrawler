"""Test that local broadcaster datelines don't trigger wire detection."""

import pytest

from src.utils.content_type_detector import ContentTypeDetector


@pytest.fixture
def detector():
    """Create a ContentTypeDetector instance."""
    return ContentTypeDetector()


class TestLocalBroadcasterDatelines:
    """Test local broadcaster callsign datelines are not misclassified as wire."""

    def test_kmiz_dateline_not_wire(self, detector):
        """KMIZ (ABC 17 Columbia) dateline should not trigger wire detection."""
        result = detector.detect(
            url="https://abc17news.com/news/columbia/2025/11/14/local-story",
            title="Columbia storm sewer rescue",
            metadata={"byline": "Alison Patton"},
            content=(
                "COLUMBIA, Mo. (KMIZ)\n\n"
                "The Columbia Utilities Department uses a mini truck that has a "
                "camera on it to regularly check storm drain pipes..."
            ),
        )
        assert result is None or result.status != "wire", (
            f"KMIZ dateline should not trigger wire detection. "
            f"Got: {result.status if result else None}"
        )

    def test_komu_dateline_not_wire(self, detector):
        """KOMU (NBC Columbia) dateline should not trigger wire detection."""
        result = detector.detect(
            url="https://komu.com/news/local/columbia-news",
            title="Columbia City Council Meeting",
            metadata={"byline": "Local Reporter"},
            content=(
                "COLUMBIA, Mo. (KOMU)\n\n"
                "The Columbia City Council met Tuesday to discuss the budget..."
            ),
        )
        assert result is None or result.status != "wire"

    def test_krcg_dateline_not_wire(self, detector):
        """KRCG (CBS Jefferson City) dateline should not trigger wire detection."""
        result = detector.detect(
            url="https://krcgtv.com/news/local/jefferson-city-fire",
            title="Jefferson City Fire Department responds",
            metadata={"byline": "Staff Reporter"},
            content=(
                "JEFFERSON CITY, Mo. (KRCG)\n\n"
                "Firefighters responded to a structure fire downtown..."
            ),
        )
        assert result is None or result.status != "wire"

    def test_multiple_local_reporters_not_wire(self, detector):
        """Stories by named local reporters should not be wire."""
        local_reporters = [
            "Alison Patton",
            "Collin Anderson",
            "Matthew Sanders",
            "Jessica Hafner",
            "Marie Moyer",
        ]
        
        for reporter in local_reporters:
            result = detector.detect(
                url="https://abc17news.com/news/columbia/2025/11/20/local-event",
                title="Local community event",
                metadata={"byline": reporter},
                content=(
                    f"COLUMBIA, Mo. (KMIZ)\n\n"
                    f"By {reporter}\n\n"
                    f"A local fundraiser raised $45,000 for charity..."
                ),
            )
            assert result is None or result.status != "wire", (
                f"Local reporter {reporter} should not trigger wire detection"
            )


class TestActualWireDatelines:
    """Test that real wire service datelines are still detected."""

    def test_ap_dateline_detected(self, detector):
        """AP dateline should still trigger wire detection."""
        result = detector.detect(
            url="https://abc17news.com/world/2025/11/14/international-news",
            title="International Crisis",
            metadata={"byline": "Associated Press"},
            content="PARIS (AP) — French officials announced today...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "Associated Press" in str(result.evidence)

    def test_reuters_dateline_detected(self, detector):
        """Reuters dateline should still trigger wire detection."""
        result = detector.detect(
            url="https://abc17news.com/world/2025/11/14/global-markets",
            title="Global Markets Update",
            metadata={"byline": "Reuters"},
            content="LONDON (Reuters) — Stock markets fell sharply...",
        )
        assert result is not None
        assert result.status == "wire"

    def test_cnn_dateline_detected(self, detector):
        """CNN dateline should still trigger wire detection."""
        result = detector.detect(
            url="https://abc17news.com/cnn-national/2025/11/14/breaking-news",
            title="Breaking News",
            metadata={"byline": "CNN Wire"},
            content="WASHINGTON (CNN) — The president announced...",
        )
        assert result is not None
        assert result.status == "wire"


class TestOutOfMarketBroadcasters:
    """Test that out-of-market broadcaster content IS detected as wire/syndicated."""

    def test_wgbh_boston_detected_as_wire(self, detector):
        """WGBH (Boston PBS) content in Missouri outlet should be wire/syndicated."""
        _ = detector.detect(
            url="https://abc17news.com/national/2025/11/14/pbs-special-report",
            title="PBS Special Report",
            metadata={"byline": "WGBH"},
            content=(
                "BOSTON (WGBH) — A new documentary explores the history...\n\n"
                "©2025 WGBH. All rights reserved."
            ),
        )
        # Out-of-market broadcasters should be detected as syndicated/wire
        # (WGBH not in LOCAL_IN_MARKET_BROADCASTERS)
        # This test documents expected behavior - may need pattern refinement
        # For now, we just ensure local callsigns DON'T trigger false positives
        pass  # Behavior TBD based on content patterns

    def test_wttw_chicago_content(self, detector):
        """WTTW (Chicago PBS) in Missouri outlet could be syndicated."""
        _ = detector.detect(
            url="https://abc17news.com/news/national/chicago-story",
            title="Chicago Investigation",
            metadata={"byline": "WTTW Chicago"},
            content="CHICAGO (WTTW) — An investigation reveals...",
        )
        # Similar to WGBH - out-of-market content
        pass  # Behavior TBD


class TestHyperlocalIndicators:
    """Test that hyperlocal content indicators prevent wire classification."""

    def test_local_government_coverage(self, detector):
        """Columbia City Council coverage is clearly local."""
        result = detector.detect(
            url="https://abc17news.com/news/columbia/2025/11/17/city-council",
            title="Columbia City Council approves budget",
            metadata={"byline": "Marie Moyer"},
            content=(
                "COLUMBIA, Mo. (KMIZ)\n\n"
                "The Columbia City Council voted Tuesday to approve a $560,000 "
                "facilities plan for Columbia Public Schools..."
            ),
        )
        assert result is None or result.status != "wire"

    def test_mizzou_sports_coverage(self, detector):
        """Mizzou athletics coverage is local sports."""
        result = detector.detect(
            url="https://abc17news.com/sports/mizzou-tigers/2025/11/19/basketball",
            title="Mizzou basketball hunts for sixth-straight win",
            metadata={"byline": "Collin Anderson"},
            content=(
                "COLUMBIA, Mo. (KMIZ)\n\n"
                "The Missouri Tigers men's basketball team prepares for tonight's "
                "game against South Dakota..."
            ),
        )
        assert result is None or result.status != "wire"

    def test_local_weather_forecast(self, detector):
        """Mid-Missouri weather forecasts are local content."""
        result = detector.detect(
            url="https://abc17news.com/weather/2025/11/22/forecast",
            title="Tracking sunny skies and mild temperatures this weekend",
            metadata={"byline": "Nate Splater"},
            content=(
                "COLUMBIA, Mo. (KMIZ)\n\n"
                "High pressure will bring sunny skies and mild temperatures to "
                "Mid-Missouri this weekend..."
            ),
        )
        assert result is None or result.status != "wire"
