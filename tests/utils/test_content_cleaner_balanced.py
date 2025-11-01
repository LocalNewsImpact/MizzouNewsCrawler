import sqlite3
from typing import Optional
from unittest.mock import MagicMock, patch

from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def _build_share_header_text():
    share_header = "Facebook Twitter WhatsApp SMS Email • Share this article"
    body = "This is the article content.\nMore informative text follows."
    # Include a blank line so the cleaner drops empty padding after removal.
    return f"{share_header}\n\n{body}"


def test_process_single_article_removes_social_share_header():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    original_text = _build_share_header_text()
    cleaned_text, metadata = cleaner.process_single_article(
        original_text, domain="example.com"
    )

    assert "Share this article" not in cleaned_text
    assert cleaned_text.startswith("This is the article content.")
    assert metadata["social_share_header_removed"] is True
    assert "social_share_header" in metadata["patterns_matched"]
    assert metadata["persistent_removals"] == 0
    assert metadata["wire_detected"] is None
    assert metadata["chars_removed"] > 0


class _StubTelemetry:
    def __init__(self, patterns):
        self._patterns = patterns
        self.log_summary = {
            "sessions": [],
            "segments": [],
            "finalized": None,
            "wire": [],
        }

    def start_cleaning_session(self, domain, **kwargs):
        self.log_summary["sessions"].append((domain, kwargs))
        return "session"

    def get_persistent_patterns(self, domain):
        return self._patterns

    def log_wire_detection(self, **kwargs):
        self.log_summary["wire"].append(kwargs)

    def log_segment_detection(self, **kwargs):
        self.log_summary["segments"].append(kwargs)

    def finalize_cleaning_session(self, **kwargs):
        self.log_summary["finalized"] = kwargs


def test_process_single_article_removes_persistent_patterns():
    pattern_text = "Persistent boilerplate " * 8  # 184 characters
    article_body = "Important local reporting remains."
    full_text = f"Intro lead. {pattern_text}{article_body}"

    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")
    telemetry_stub = _StubTelemetry(
        patterns=[
            {
                "text_content": pattern_text,
                "pattern_type": "persistent_sidebar",
                "confidence_score": 0.95,
                "occurrences_total": 17,
                "removal_reason": "Stored persistent pattern",
            }
        ]
    )
    cleaner.telemetry = telemetry_stub  # type: ignore[assignment]

    cleaned_text, metadata = cleaner.process_single_article(
        full_text,
        domain="example.com",
    )

    assert pattern_text not in cleaned_text
    assert cleaned_text.endswith(article_body)
    assert metadata["persistent_removals"] == 1
    assert metadata["social_share_header_removed"] is False
    assert "persistent_sidebar" in metadata["patterns_matched"]
    assert metadata["chars_removed"] == len(pattern_text)
    assert metadata["wire_detected"] is None

    # Telemetry should record the removal when enabled.
    assert telemetry_stub.log_summary["segments"], "segment log missing"
    logged_segment = telemetry_stub.log_summary["segments"][0]
    assert logged_segment["segment_text"] == pattern_text
    assert logged_segment["was_removed"] is True


def test_assess_locality_detects_city_and_county_signals():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    context: dict[str, Optional[str]] = {
        "publisher_city": "Jefferson City",
        "publisher_county": "Cole",
        "publisher_name": "Jefferson City Tribune",
        "canonical_name": "Mid-Missouri Tribune",
        "publisher_slug": "jefferson-city-tribune",
    }

    text = (
        "The Jefferson City Tribune reports on Cole County elections, "
        "bringing Jefferson City residents the latest updates."
    )

    result = cleaner._assess_locality(text, context, domain="example.com")

    assert result is not None
    assert result["is_local"] is True
    assert result["confidence"] >= 0.6
    signal_types = {signal["type"] for signal in result["signals"]}
    assert "city" in signal_types
    assert "county_phrase" in signal_types
    assert "publisher_name" in signal_types
    assert "publisher_primary_token" in signal_types
    assert result["raw_score"] >= result["confidence"] - 0.01


def test_assess_locality_requires_text_and_context():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    assert (
        cleaner._assess_locality(
            "",
            {"publisher_city": "Jefferson"},  # type: ignore[arg-type]
            "example.com",
        )
        is None
    )
    assert (
        cleaner._assess_locality(
            "Wire copy without context",
            {},  # type: ignore[arg-type]
            "example.com",
        )
        is None
    )


class _ExplodingConnectorCleaner(BalancedBoundaryContentCleaner):
    def _connect_to_db(self):  # type: ignore[override]
        raise sqlite3.OperationalError("boom")


def test_get_article_source_context_handles_errors_gracefully():
    cleaner = _ExplodingConnectorCleaner(db_path=":memory:")

    context = cleaner._get_article_source_context("42")

    assert context == {}


def test_normalize_navigation_token_strips_punctuation():
    token = "\u2022Sports!!"

    normalized = BalancedBoundaryContentCleaner._normalize_navigation_token(token)

    assert normalized == "sports"


def test_extract_navigation_prefix_detects_navigation_cluster():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    nav_tokens = [
        "News",
        "Local",
        "Sports",
        "Obituaries",
        "Business",
        "Opinion",
        "Religion",
        "Events",
        "Photos",
        "Videos",
        "Lifestyle",
        "Calendar",
        "Sections",
        "Contact",
    ]
    content = "   " + " ".join(nav_tokens) + "\nTop story follows."

    prefix = cleaner._extract_navigation_prefix(content)

    assert prefix is not None
    assert prefix.split()[:3] == ["News", "Local", "Sports"]
    assert "Contact" in prefix


def test_extract_navigation_prefix_requires_required_tokens():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    nav_tokens = [
        "News",
        "Local",
        "Sports",
        "Obituaries",
        "Business",
        "Opinion",
        "Religion",
        "Events",
        "Photos",
        "Videos",
        "Lifestyle",
        "Calendar",
    ]
    content = "   " + " ".join(nav_tokens) + "\nMore content."

    assert cleaner._extract_navigation_prefix(content) is None


def test_filter_with_balanced_boundaries_accepts_best_candidates():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )
    telemetry_stub = _StubTelemetry(patterns=[])
    cleaner.telemetry = telemetry_stub  # type: ignore[assignment]

    good_text = "Sign up today to receive daily headlines and newsletters."
    bad_fragment = "and partial fragment without boundary"

    articles = [
        {
            "id": 1,
            "content": f"Intro. {good_text} Closing remarks. {bad_fragment}.",
        },
        {
            "id": 2,
            "content": f"{good_text} Additional coverage. {bad_fragment}.",
        },
    ]

    rough_candidates = {
        good_text: {"1", "2"},
        bad_fragment: {"1", "2"},
    }

    segments = cleaner._filter_with_balanced_boundaries(
        articles,
        rough_candidates,
        min_occurrences=2,
        telemetry_id="session",
    )

    assert len(segments) == 1
    segment = segments[0]
    assert segment["text"] == good_text
    assert segment["pattern_type"] == "sidebar"
    assert segment["occurrences"] == 2
    assert segment["position_consistency"] > 0
    assert "Newsletter signup prompts" in segment["removal_reason"]
    assert "appears 2x" in segment["removal_reason"]

    logged = telemetry_stub.log_summary["segments"]
    assert any(
        entry["was_removed"] for entry in logged if entry["segment_text"] == good_text
    )
    assert any(
        not entry["was_removed"]
        for entry in logged
        if entry["segment_text"] == bad_fragment
    )


def test_assess_boundary_quality_scores_sidebar_and_penalizes_fragments():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    sidebar_score = cleaner._assess_boundary_quality(
        "Watch this discussion about the latest updates."
    )
    fragment_score = cleaner._assess_boundary_quality("fragment and more")

    assert sidebar_score > fragment_score
    assert sidebar_score >= 0.7
    assert fragment_score < 0.3


def test_calculate_position_consistency_measures_variance():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    articles = {
        "1": {"content": "a" * 100},
        "2": {"content": "b" * 100},
        "3": {"content": "c" * 100},
    }
    matches = {
        "1": [(10, 20)],
        "2": [(15, 25)],
        "3": [(50, 60)],
    }

    consistency = cleaner._calculate_position_consistency(matches, articles)
    assert 0 < consistency < 1
    assert cleaner._calculate_position_consistency({"1": [(0, 10)]}, articles) == 0


def test_classify_pattern_identifies_common_categories():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    assert (
        cleaner._classify_pattern("Watch this discussion and post a comment right now")
        == "sidebar"
    )
    assert (
        cleaner._classify_pattern("News Sports Obituaries Subscribe Contact Business")
        == "navigation"
    )
    assert cleaner._classify_pattern("All rights reserved Privacy Policy") == "footer"
    assert (
        cleaner._classify_pattern("Print subscriber account setup help")
        == "subscription"
    )
    assert (
        cleaner._classify_pattern("Trending now: Popular stories today") == "trending"
    )
    assert cleaner._classify_pattern("Local team defeats rival in finals") == "other"


def test_generate_removal_reason_covers_patterns_and_confidence():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    sidebar_reason = cleaner._generate_removal_reason(
        "Watch this discussion now",
        "sidebar",
        boundary_score=0.85,
        occurrences=3,
    )
    assert "high confidence" in sidebar_reason
    assert "Discussion prompts" in sidebar_reason

    subscription_reason = cleaner._generate_removal_reason(
        "Print subscriber account login",
        "subscription",
        boundary_score=0.65,
        occurrences=2,
    )
    assert "medium confidence" in subscription_reason
    assert "Print subscriber" in subscription_reason

    navigation_reason = cleaner._generate_removal_reason(
        "News Business Opinion",
        "navigation",
        boundary_score=0.4,
        occurrences=4,
    )
    assert "low confidence" in navigation_reason
    assert "Site navigation menu" in navigation_reason

    footer_reason = cleaner._generate_removal_reason(
        "All rights reserved",
        "footer",
        boundary_score=0.9,
        occurrences=1,
    )
    assert "Page footer content" in footer_reason

    trending_reason = cleaner._generate_removal_reason(
        "Trending now: Most read stories",
        "trending",
        boundary_score=0.7,
        occurrences=5,
    )
    assert "Trending/recommended" in trending_reason

    other_reason = cleaner._generate_removal_reason(
        "Team A defeated Team B, city celebrates",
        "other",
        boundary_score=0.5,
        occurrences=6,
    )
    assert "low confidence" in other_reason
    assert "appears 6x" in other_reason


def test_calculate_domain_stats_summarizes_segments():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    articles = [
        {"id": 1, "content": "A" * 200},
        {"id": 2, "content": "B" * 150},
    ]
    segments = [
        {
            "text_content": "Sign up today for newsletters.",
            "length": 30,
            "occurrences": 2,
            "article_ids": [1, 2],
        },
        {
            "text_content": "Watch this discussion",
            "length": 20,
            "occurrences": 1,
            "article_ids": [1],
        },
    ]

    stats = cleaner._calculate_domain_stats(articles, segments)
    assert stats["total_articles"] == 2
    assert stats["affected_articles"] == 2
    assert stats["total_segments"] == 2
    assert stats["total_removable_chars"] == 80
    assert stats["total_content_chars"] == 350
    assert stats["removal_percentage"] > 0


def test_remove_persistent_patterns_respects_length_and_confidence():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=True,
    )

    short_pattern = "Share this article"
    long_pattern = "Newsletter signup prompt " * 6

    telemetry_stub = _StubTelemetry(
        patterns=[
            {
                "text_content": short_pattern,
                "pattern_type": "sidebar",
                "confidence_score": 0.9,
                "occurrences_total": 10,
                "removal_reason": "Short social CTA",
            },
            {
                "text_content": long_pattern,
                "pattern_type": "sidebar",
                "confidence_score": 0.8,
                "occurrences_total": 8,
                "removal_reason": "Long CTA",
            },
        ]
    )
    cleaner.telemetry = telemetry_stub  # type: ignore[assignment]

    with (
        patch.object(
            cleaner,
            "_detect_wire_service_in_pattern",
            return_value={
                "provider": "AP",
                "confidence": 0.9,
                "detection_method": "stub",
            },
        ),
        patch.object(
            cleaner,
            "_is_high_confidence_boilerplate",
            side_effect=lambda value: value == short_pattern,
        ),
    ):
        result = cleaner._remove_persistent_patterns(
            f"Intro. {short_pattern}! {long_pattern} Remainder.",
            domain="example.com",
            article_id="123",
        )

    assert short_pattern not in result["cleaned_text"]
    assert long_pattern not in result["cleaned_text"]
    assert result["removals"], "removals should include detected patterns"
    assert result["wire_detected"] is not None


def test_social_share_helpers_detect_clusters():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    prefix_end = cleaner._detect_social_share_prefix_end(
        "• Facebook Twitter WhatsApp Email"
    )
    assert prefix_end is not None
    assert cleaner._is_social_share_cluster("Facebook Twitter WhatsApp Email")

    result = cleaner._remove_social_share_header(
        "Facebook Twitter WhatsApp Email\n\nStory starts here"
    )
    assert result["removed_text"] is not None
    assert result["cleaned_text"].startswith("Story starts here")


def test_is_high_confidence_boilerplate_matches_patterns():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    assert cleaner._is_high_confidence_boilerplate(
        "Subscribe to our newsletter for updates"
    )

    repetitive = "Promo promo promo message"
    assert cleaner._is_high_confidence_boilerplate(repetitive)


def test_detect_wire_service_in_pattern_uses_regex_and_domain_guard():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    detection = cleaner._detect_wire_service_in_pattern(
        "Story from The Associated Press", domain="example.com"
    )
    assert detection is not None
    assert detection["provider"] == "The Associated Press"

    # Domain guard filters out when provider matches domain (own source).
    no_guard_trigger = cleaner._detect_wire_service_in_pattern(
        "Story from The Associated Press",
        domain="associatedpress.com",
    )
    assert no_guard_trigger is None


def test_detect_local_byline_override_filters_wire_authors(monkeypatch):
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    monkeypatch.setattr(
        cleaner,
        "_get_article_authors",
        MagicMock(return_value=["Jane Doe", "Reuters", "AP"]),
    )

    class _WireDetectorStub:
        def __init__(self):
            self._detected_wire_services = []

        def _is_wire_service(self, byline: str) -> bool:
            return byline.lower() in {"reuters", "ap"}

        def _is_wire_service_from_own_source(
            self,
            service: str,
            domain: str,
        ) -> bool:
            return False

    cleaner.wire_detector = _WireDetectorStub()  # type: ignore[assignment]

    override = cleaner._detect_local_byline_override("42")

    assert override is not None
    assert override["local_authors"] == ["Jane Doe"]


def test_contains_term_matches_with_and_without_spaces():
    assert (
        BalancedBoundaryContentCleaner._contains_term(
            "the city of jefferson reports", "Jefferson"
        )
        is True
    )
    assert (
        BalancedBoundaryContentCleaner._contains_term(
            "the city of jefferson reports", "city of jefferson"
        )
        is True
    )
    assert (
        BalancedBoundaryContentCleaner._contains_term(
            "the city of jefferson reports", "springfield"
        )
        is False
    )


def test_detect_inline_wire_indicators_matches_provider():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    detection = cleaner._detect_inline_wire_indicators(
        "(AP) — Local story continues here.",
        domain="example.com",
    )
    assert detection is not None
    assert detection["provider"] == "The Associated Press"
