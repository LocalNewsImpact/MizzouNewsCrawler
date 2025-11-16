"""Unit tests for wire service detection in ContentTypeDetector.

Tests cover wire detection patterns:
1. Author field patterns (e.g., "Afp Afp", "By AP")
2. /world/ and /national/ URL patterns (with strong content evidence)
3. Copyright statements with "The Associated Press"
4. Dateline patterns like "WASHINGTON (AP) —"
5. Attribution patterns like "told AFP"
"""

import pytest

from src.utils.content_type_detector import ContentTypeDetector


def _detector():
    return ContentTypeDetector()


class TestWireServiceDetection:
    """Tests for wire service detection patterns."""

    def test_detects_afp_afp_author(self):
        """Test detection of 'Afp Afp' author pattern"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/national/story",
            title="Sports Update",
            metadata={"byline": "Afp Afp"},
            content="The game ended with a final score...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence
        assert any("AFP" in m for m in result.evidence["author"])

    def test_detects_name_ending_with_afp(self):
        """Test detection of author ending with AFP"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/national/article.html",
            title="International News",
            metadata={"byline": "Susan Njanji Nicholas Roll In Abuja Afp"},
            content="Officials announced today...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence

    def test_detects_ap_staff_author(self):
        """Test detection of 'AP Staff' author"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="Breaking News",
            metadata={"byline": "AP Staff"},
            content="The announcement came early today...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence

    def test_detects_ap_dateline_pattern(self):
        """Test detection of AP dateline: 'WASHINGTON (AP) —'"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="President Announces Policy",
            metadata=None,
            content="WASHINGTON (AP) — The president announced today...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence
        assert any("Associated Press" in m for m in result.evidence["content"])

    def test_detects_reuters_dateline_pattern(self):
        """Test detection of Reuters dateline: 'LONDON (Reuters) —'"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/world/story",
            title="UK Election Results",
            metadata=None,
            content="LONDON (Reuters) — British voters went to the polls...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence

    def test_detects_states_newsroom_author(self):
        """Test detection of 'States Newsroom' author pattern"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/national/story",
            title="Local State Update",
            metadata={"byline": "States Newsroom"},
            content="Short summary of state news...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence
        assert any("States Newsroom" in m for m in result.evidence["author"])

    def test_detects_states_newsroom_author_suffix(self):
        """Test detection when author ends with 'States Newsroom'"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/national/state-update",
            title="State Policy Update",
            metadata={"byline": "Jane Doe States Newsroom"},
            content="Policy changes announced...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence

    def test_detects_copyright_the_associated_press(self):
        """Test copyright detection with 'The Associated Press'"""
        detector = _detector()
        result = detector.detect(
            url="https://localnews.com/national/story",
            title="National News Story",
            metadata=None,
            content=(
                "This is article content that discusses various topics. "
                "Copyright 2024 The Associated Press. All rights reserved."
            ),
        )
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence
        assert any("copyright" in m.lower() for m in result.evidence["content"])

    def test_detects_wave_copyright_pattern(self):
        """Test WAVE copyright in closing when hosted on other domains"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="Local Story Hosted Elsewhere",
            metadata=None,
            content=("Some news content. " "Copyright 2025 WAVE. All rights reserved."),
        )
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence
        assert any("WAVE" in m for m in result.evidence["content"]) or any(
            "copyright" in m.lower() for m in result.evidence["content"]
        )

    def test_detects_first_appeared_states_newsroom(self):
        """Test detection of 'first appeared in' with States Newsroom affiliate"""
        detector = _detector()
        content = "This story first appeared in the Kansas Reflector, a States Newsroom affiliate."
        result = detector.detect(
            url="https://example.com/news/story",
            title="Local Story Hosted Elsewhere",
            metadata=None,
            content=content,
        )
        assert result is not None
        assert result.status == "wire"
        assert "content" in result.evidence
        assert any("States Newsroom" in m for m in result.evidence["content"])

    def test_first_appeared_states_newsroom_no_detection_if_host_same(self):
        """If the host is Kansas Reflector, skip 'first appeared' syndicated detection"""
        detector = _detector()
        content = "This story first appeared in the Kansas Reflector, a States Newsroom affiliate."
        result = detector.detect(
            url="https://kansasreflector.com/news/story",
            title="Local Story On Kansas Reflector",
            metadata=None,
            content=content,
        )
        assert result is None or result.status != "wire"

    def test_detects_missouri_independent_byline_only_when_host_differs(self):
        """'The Missouri Independent' byline should be wire when hosted elsewhere"""
        detector = _detector()
        # Hosted elsewhere - should detect
        result = detector.detect(
            url="https://example.com/news/story",
            title="Local Story Hosted Elsewhere",
            metadata={
                "byline": "November 11, 2025 by The Missouri Independent , Anna Spoerre"
            },
            content="Summary of story",
        )
        assert result is not None
        assert result.status == "wire"

        # Hosted on the Missouri Independent - should NOT detect as wire
        result_own = detector.detect(
            url="https://missouriindependent.com/news/story",
            title="Local Story On Missouri Independent",
            metadata={
                "byline": "November 11, 2025 by The Missouri Independent , Anna Spoerre"
            },
            content="Summary of story",
        )
        assert result_own is None or result_own.status != "wire"

    def test_wave_copyright_not_detected_on_own_site(self):
        """If a WAVE copyright appears on wave3.com, do not mark as wire"""
        detector = _detector()
        content = "Some news content. Copyright 2025 WAVE. All rights reserved."
        result = detector.detect(
            url="https://www.wave3.com/news/story",
            title="WAVE story",
            metadata=None,
            content=content,
        )
        assert result is None or result.status != "wire"

    def test_detects_missouri_independent_byline_pattern(self):
        """Test byline that includes 'The Missouri Independent' indicates syndicated content"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="Local Story Hosted Elsewhere",
            metadata={
                "byline": "November 11, 2025 by The Missouri Independent , Anna Spoerre"
            },
            content="Summary of story",
        )
        assert result is not None
        assert result.status == "wire"
        assert "author" in result.evidence
        assert any("The Missouri Independent" in m for m in result.evidence["author"])

    def test_detects_copyright_npr_with_the(self):
        """Test NPR copyright with 'The' prefix"""
        detector = _detector()
        result = detector.detect(
            url="https://kbia.org/national/story",
            title="National Story",
            metadata=None,
            content=(
                "Article about national news topic. "
                "© 2025 The NPR. All rights reserved."
            ),
        )
        assert result is not None
        assert result.status == "wire"

    def test_world_url_pattern_with_copyright(self):
        """Test /world/ URL pattern triggers with copyright evidence"""
        detector = _detector()
        result = detector.detect(
            url="https://standard-democrat.com/world/immigration-story",
            title="Immigration Policy Changes",
            metadata=None,
            content=(
                "Details about immigration policy. "
                "Copyright 2024 The Associated Press."
            ),
        )
        assert result is not None
        assert result.status == "wire"
        assert "url" in result.evidence
        assert any("/world/" in m for m in result.evidence["url"])

    def test_national_url_pattern_with_dateline(self):
        """Test /national/ URL pattern triggers with dateline"""
        detector = _detector()
        result = detector.detect(
            url="https://newspressnow.com/national/politics",
            title="Senate Votes on Bill",
            metadata=None,
            content="WASHINGTON (AP) — The Senate voted today...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "url" in result.evidence
        assert any("/national" in m for m in result.evidence["url"])

    def test_world_url_without_content_evidence_no_detection(self):
        """Test /world/ URL alone (without strong content) doesn't trigger"""
        detector = _detector()
        result = detector.detect(
            url="https://localnews.com/world/story",
            title="Local Coverage of World Event",
            metadata=None,
            content="Our local reporter attended the conference...",
        )
        # Should NOT detect as wire without strong content evidence
        assert result is None or result.status != "wire"

    def test_national_url_without_content_evidence_no_detection(self):
        """Test /national/ URL alone doesn't trigger"""
        detector = _detector()
        result = detector.detect(
            url="https://newspaper.com/national/elections",
            title="National Election Coverage",
            metadata=None,
            content="Our coverage team reports on the election...",
        )
        # Should NOT detect as wire without strong content evidence
        assert result is None or result.status != "wire"

    def test_dateline_with_world_url_high_confidence(self):
        """Test dateline + /world/ URL = high confidence detection"""
        detector = _detector()
        result = detector.detect(
            url="https://darnews.com/world/international-summit",
            title="Global Leaders Meet",
            metadata=None,
            content="GENEVA (AP) — World leaders gathered today...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "url" in result.evidence
        assert "content" in result.evidence
        assert result.confidence in ("high", "medium")

    def test_detects_usa_today_syndicated_byline(self):
        """Detect syndicated byline like 'Name USA TODAY' in author field or top"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="Feature Story",
            metadata={"byline": "Jane Doe USA TODAY"},
            content="Summary of the feature",
        )
        assert result is not None
        assert result.status == "wire"
        assert "detected_services" in result.evidence
        assert any(
            "USA TODAY" in s or "USA Today" in s
            for s in result.evidence["detected_services"]
        )

    def test_detects_cnn_dateline_pattern(self):
        """Detect CNN dateline pattern in content"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="International Update",
            metadata=None,
            content="NEW YORK (CNN) — Coverage of the event continues...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "detected_services" in result.evidence
        assert any("CNN" in s for s in result.evidence["detected_services"])

    def test_copyright_without_the_still_works(self):
        """Test copyright detection still works without 'The' prefix"""
        detector = _detector()
        result = detector.detect(
            url="https://example.com/news/story",
            title="News Story",
            metadata=None,
            content="Article text. Copyright 2024 Associated Press.",
        )
        assert result is not None
        assert result.status == "wire"

    def test_own_source_npr_not_detected_as_wire(self):
        """Test NPR content on npr.org is NOT detected as wire"""
        detector = _detector()
        result = detector.detect(
            url="https://www.npr.org/2025/10/story",
            title="NPR Story",
            metadata=None,
            content="NPR reporting. © 2025 NPR. All rights reserved.",
        )
        # Should NOT be wire - it's from NPR's own source
        assert result is None or result.status != "wire"

    def test_own_source_ap_not_detected_as_wire(self):
        """Test AP content on apnews.com is NOT detected as wire"""
        detector = _detector()
        result = detector.detect(
            url="https://apnews.com/article/123456",
            title="AP News Story",
            metadata=None,
            content="WASHINGTON (AP) — Breaking news from AP...",
        )
        # Should NOT be wire - it's from AP's own source
        assert result is None or result.status != "wire"

    def test_multiple_wire_indicators_high_confidence(self):
        """Test multiple indicators = high confidence"""
        detector = _detector()
        result = detector.detect(
            url="https://standard-democrat.com/world/story",
            title="International News",
            metadata=None,
            content=(
                "PARIS (Reuters) — European leaders met today to discuss..."
                "Copyright 2025 Reuters."
            ),
        )
        assert result is not None
        assert result.status == "wire"
        assert result.confidence == "high"

    def test_kbia_npr_copyright_detected(self):
        """Test real-world case: KBIA with NPR copyright"""
        detector = _detector()
        result = detector.detect(
            url="https://www.kbia.org/2025-10-25/story",
            title="National Story",
            metadata=None,
            content="Article content. © 2025 NPR. All rights reserved.",
        )
        assert result is not None
        assert result.status == "wire"

    def test_standard_democrat_world_ap_detected(self):
        """Test real-world case: Standard Democrat /world/ with AP dateline"""
        detector = _detector()
        result = detector.detect(
            url="https://www.standard-democrat.com/world/immigration-story",
            title="Immigration Policy Update",
            metadata=None,
            content="WASHINGTON (AP) — New immigration rules...",
        )
        assert result is not None
        assert result.status == "wire"
        assert "url" in result.evidence
        assert "content" in result.evidence
