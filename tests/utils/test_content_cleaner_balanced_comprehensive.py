import json
import sqlite3
from typing import Optional
from unittest.mock import Mock, patch

import pytest

from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def _build_share_header_text() -> str:
    share_header = "Facebook Twitter WhatsApp SMS Email • Share this article"
    body = "This is the article content.\nMore informative text follows."
    return f"{share_header}\n\n{body}"


class _StubTelemetry:
    def __init__(self, patterns):
        self._patterns = patterns
        self.log_summary = {
            "sessions": [],
            "segments": [],
            "wire": [],
            "locality": [],
            "finalized": None,
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

    def log_locality_detection(self, **kwargs):
        self.log_summary["locality"].append(kwargs)

    def finalize_cleaning_session(self, **kwargs):
        self.log_summary["finalized"] = kwargs


def test_process_single_article_removes_social_share_header():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    original_text = _build_share_header_text()
    cleaned_text, metadata = cleaner.process_single_article(
        original_text,
        domain="example.com",
    )

    assert "Share this article" not in cleaned_text
    assert cleaned_text.startswith("This is the article content.")
    assert metadata["social_share_header_removed"] is True
    assert "social_share_header" in metadata["patterns_matched"]
    assert metadata["persistent_removals"] == 0
    assert metadata["wire_detected"] is None
    assert metadata["chars_removed"] > 0


def test_process_single_article_removes_persistent_patterns():
    pattern_text = "Persistent boilerplate " * 8
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
    assert telemetry_stub.log_summary["segments"]
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
    signal_types = {signal["type"] for signal in result["signals"]}
    assert "city" in signal_types
    assert "county_phrase" in signal_types
    assert "publisher_name" in signal_types


def test_assess_locality_requires_text_and_context():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    assert (
        cleaner._assess_locality(
            "",
            {"publisher_city": "Jefferson"},
            "example.com",
        )
        is None
    )
    assert (
        cleaner._assess_locality(
            "Wire copy without context",
            {},
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
            "content": (f"Intro. {good_text} Closing remarks. {bad_fragment}."),
        },
        {
            "id": 2,
            "content": (f"{good_text} Additional coverage. {bad_fragment}."),
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
    assert segment["occurrences"] == 2
    assert segment["pattern_type"] == "sidebar"
    assert "Newsletter signup prompts" in segment["removal_reason"]


def test_detect_wire_service_in_pattern_ap_wire():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    text = "WASHINGTON (AP) — The Associated Press reported today."

    result = cleaner._detect_wire_service_in_pattern(text, "example.com")

    assert result is not None
    assert result["provider"] == "The Associated Press"
    assert result["confidence"] >= 0.8


def test_detect_wire_service_in_pattern_no_detection():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    text = "Local reporter John Smith writes about community events."

    result = cleaner._detect_wire_service_in_pattern(text, "example.com")

    assert result is None


def test_remove_social_share_header_detection():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    text_with_header = (
        "Share on Facebook Twitter Email\n\n"
        "This is the actual article content that should remain."
    )

    result = cleaner._remove_social_share_header(text_with_header)

    assert result["removed_text"] is not None
    assert "Share on Facebook" not in result["cleaned_text"]


def test_remove_social_share_header_no_header():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    text_without_header = "This is just regular article content."

    result = cleaner._remove_social_share_header(text_without_header)

    assert result["removed_text"] is None
    assert result["cleaned_text"] == text_without_header


def test_remove_persistent_patterns_with_matches():
    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

    pattern_text = "Subscribe to our newsletter for updates"
    main_content = "This is the main article content."
    full_text = f"{pattern_text}\n\n{main_content}"

    telemetry_stub = _StubTelemetry(
        patterns=[
            {
                "text_content": pattern_text,
                "pattern_type": "newsletter_signup",
                "confidence_score": 0.9,
                "occurrences_total": 15,
                "removal_reason": "Newsletter subscription prompt",
            }
        ]
    )
    cleaner.telemetry = telemetry_stub  # type: ignore[assignment]

    result = cleaner._remove_persistent_patterns(
        full_text,
        "example.com",
        "article-1",
    )

    assert result["removals"]
    removal = result["removals"][0]
    assert removal["pattern_type"] == "newsletter_signup"
    assert main_content in result["cleaned_text"]


def test_remove_persistent_patterns_no_matches():
    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")
    telemetry_stub = _StubTelemetry(patterns=[])
    cleaner.telemetry = telemetry_stub  # type: ignore[assignment]

    result = cleaner._remove_persistent_patterns(
        "This is article content with no patterns to remove.",
        "example.com",
        "article-1",
    )

    assert result["removals"] == []
    assert result["cleaned_text"].startswith("This is article content")


def test_get_article_source_context_success():
    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (
        "link-id",
        "publisher-slug",
        "Test Publisher",
        "Test City",
        "Test County",
        "publisher-type",
        "canonical-name",
        "Canonical City",
        "Canonical County",
    )

    with patch.object(cleaner, "_connect_to_db", return_value=mock_conn):
        context = cleaner._get_article_source_context("123")

    assert context["publisher_name"] == "Test Publisher"
    assert context["publisher_slug"] == "publisher-slug"
    assert context["publisher_city"] == "Test City"
    assert context["publisher_county"] == "Test County"
    assert context["canonical_name"] == "canonical-name"


def test_get_article_source_context_no_results():
    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None

    with patch.object(cleaner, "_connect_to_db", return_value=mock_conn):
        context = cleaner._get_article_source_context("999")

    assert context == {}


def test_get_articles_for_domain_with_mocked_db():
    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        (
            1,
            "https://example.com/a",
            "Article 1 content",
            "hash1",
        ),
        (
            2,
            "https://example.com/b",
            "Article 2 content",
            "hash2",
        ),
    ]

    with patch.object(cleaner, "_connect_to_db", return_value=mock_conn):
        articles = cleaner._get_articles_for_domain("example.com")

    assert len(articles) == 2
    assert articles[0]["url"] == "https://example.com/a"
    assert articles[1]["text_hash"] == "hash2"
    mock_cursor.execute.assert_called_once()


def test_get_articles_for_domain_raises_on_error():
    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")

    with patch.object(
        cleaner,
        "_connect_to_db",
        side_effect=sqlite3.Error("boom"),
    ):
        with pytest.raises(sqlite3.Error):
            cleaner._get_articles_for_domain("example.com")


def test_get_article_authors_handles_multiple_formats(tmp_path):
    def run_case(value, suffix):
        db_path = tmp_path / f"authors_{suffix}.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE articles (id TEXT PRIMARY KEY, author BLOB)")
        conn.execute(
            "INSERT INTO articles (id, author) VALUES (?, ?)",
            ("a1", value),
        )
        conn.commit()
        conn.close()

        cleaner = BalancedBoundaryContentCleaner(
            db_path=str(db_path),
            enable_telemetry=False,
        )
        return cleaner._get_article_authors("a1")

    assert run_case("Jane Doe", "plain") == ["Jane Doe"]
    assert run_case(b"Jane Doe", "bytes") == ["Jane Doe"]
    assert run_case('["Jane Doe", "John Smith"]', "json_list") == [
        "Jane Doe",
        "John Smith",
    ]
    assert run_case('"Solo Reporter"', "json_string") == ["Solo Reporter"]
    assert run_case("Jane Doe; John Smith", "fallback") == [
        "Jane Doe",
        "John Smith",
    ]
    assert run_case(b"\xff\xfe\xfd", "decode_error") == []


def test_get_article_authors_handles_list_row():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (["Reporter A", "Reporter B"],)

    with patch.object(cleaner, "_connect_to_db", return_value=mock_conn):
        authors = cleaner._get_article_authors("77")

    assert authors == ["Reporter A", "Reporter B"]
    mock_conn.close.assert_called_once()


def test_detect_local_byline_override_filters_wire_authors():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    with patch.object(
        cleaner,
        "_get_article_authors",
        return_value=[
            "Jane Doe",
            "The Associated Press",
            "Local Contributor",
        ],
    ):
        locality = cleaner._detect_local_byline_override("456")

    assert locality is not None
    assert locality["local_authors"] == ["Jane Doe", "Local Contributor"]


def test_detect_local_byline_override_returns_none_without_locals():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    with patch.object(
        cleaner,
        "_get_article_authors",
        return_value=["AP", "Reuters"],
    ):
        locality = cleaner._detect_local_byline_override("789")

    assert locality is None


def test_detect_inline_wire_indicators_skips_own_source():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    with patch.object(
        cleaner.wire_detector,
        "_is_wire_service_from_own_source",
        return_value=True,
    ):
        result = cleaner._detect_inline_wire_indicators(
            "(AP) — Local news update.",
            domain="apnews.com",
        )

    assert result is None


def test_mark_article_as_wire_updates_payload(tmp_path):
    db_path = tmp_path / "wire.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE articles (id TEXT PRIMARY KEY, wire TEXT)")
    conn.execute(
        "INSERT INTO articles (id, wire) VALUES (?, ?)",
        ("42", json.dumps({"existing": "value"})),
    )
    conn.commit()
    conn.close()

    cleaner = BalancedBoundaryContentCleaner(
        db_path=str(db_path),
        enable_telemetry=False,
    )

    wire_info = {
        "provider": "Reuters",
        "confidence": 0.91,
        "detection_method": "inline_indicator",
    }
    locality = {
        "is_local": True,
        "confidence": 0.61,
        "signals": [{"type": "city", "value": "Columbia"}],
        "threshold": 0.6,
    }
    source_context = {
        "publisher_name": "Columbia Daily Tribune",
        "publisher_city": "Columbia",
        "publisher_county": "Boone",
        "publisher_slug": "columbia-daily",
        "extra": "ignore",
    }

    cleaner._mark_article_as_wire(
        "42",
        wire_info,
        locality=locality,
        source_context=source_context,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT wire FROM articles WHERE id = ?",
        ("42",),
    ).fetchone()
    conn.close()

    payload = json.loads(row[0])
    assert payload["provider"] == "Reuters"
    assert payload["confidence"] == pytest.approx(0.91)
    assert payload["locality"]["is_local"] is True
    assert payload["locality"]["signals"]
    assert payload["source_context"]["publisher_name"] == ("Columbia Daily Tribune")
    assert "extra" not in payload["source_context"]
    assert payload["existing"] == "value"
    assert payload.get("detected_at")


def test_mark_article_as_wire_handles_invalid_existing_payload(tmp_path):
    db_path = tmp_path / "wire_invalid.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE articles (id TEXT PRIMARY KEY, wire TEXT)")
    conn.execute(
        "INSERT INTO articles (id, wire) VALUES (?, ?)",
        ("99", "not-json"),
    )
    conn.commit()
    conn.close()

    cleaner = BalancedBoundaryContentCleaner(
        db_path=str(db_path),
        enable_telemetry=False,
    )

    cleaner._mark_article_as_wire(
        "99",
        {"provider": "NPR", "confidence": 0.8, "detection_method": "pattern"},
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT wire FROM articles WHERE id = ?",
        ("99",),
    ).fetchone()
    conn.close()

    payload = json.loads(row[0])
    assert payload["provider"] == "NPR"
    assert payload["detection_method"] == "pattern"


def test_analyze_domain_with_repeated_pattern():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )
    repeated_text = (
        "Subscribe to our newsletter to receive daily updates about local "
        "news and stay informed with alerts tailored for your community."
    )
    articles = [
        {
            "id": 1,
            "content": f"{repeated_text}\n\nMain article content 1.",
        },
        {
            "id": 2,
            "content": (f"Intro paragraph.\n\n{repeated_text}\n\nClosing thoughts."),
        },
    ]

    with (
        patch.object(
            cleaner,
            "_get_articles_for_domain",
            return_value=articles,
        ),
        patch.object(
            cleaner,
            "_get_persistent_patterns_for_domain",
            return_value=[],
        ),
    ):
        result = cleaner.analyze_domain("example.com", min_occurrences=2)

    segments = result["segments"]
    newsletter_segments = [seg for seg in segments if repeated_text in seg["text"]]
    assert newsletter_segments
    assert newsletter_segments[0]["occurrences"] >= 2


def test_analyze_domain_uses_persistent_patterns_when_available():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )
    stored_pattern = {
        "text": "Persistent navigation cluster",
        "pattern_type": "navigation",
        "boundary_score": 0.9,
        "occurrences": 1,
        "length": 32,
        "article_ids": [],
        "positions": {},
        "position_consistency": 1.0,
        "removal_reason": "Persistent navigation pattern",
    }

    with (
        patch.object(
            cleaner,
            "_get_articles_for_domain",
            return_value=[],
        ),
        patch.object(
            cleaner,
            "_get_persistent_patterns_for_domain",
            return_value=[stored_pattern],
        ),
    ):
        result = cleaner.analyze_domain("example.com")

    assert result["segments"] == [stored_pattern]


def test_process_single_article_wire_detection_integration():
    cleaner = BalancedBoundaryContentCleaner(db_path=":memory:")
    telemetry_stub = _StubTelemetry(patterns=[])
    cleaner.telemetry = telemetry_stub  # type: ignore[assignment]

    wire_text = "(AP) — Associated Press reports on national story."

    with patch.object(
        cleaner,
        "_get_article_source_context",
        return_value={
            "publisher_city": "Springfield",
            "publisher_name": "Local News",
        },
    ):
        _, metadata = cleaner.process_single_article(
            wire_text,
            domain="example.com",
            article_id="123",
        )

    wire_info = metadata["wire_detected"]
    assert wire_info is not None
    assert wire_info["provider"] == "The Associated Press"
    assert telemetry_stub.log_summary["wire"]


def test_process_single_article_without_article_id():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    text = "Simple article content without any patterns."

    cleaned_text, metadata = cleaner.process_single_article(
        text,
        domain="example.com",
    )

    assert cleaned_text == text
    assert metadata["social_share_header_removed"] is False
    assert metadata["persistent_removals"] == 0
    assert metadata["wire_detected"] is None
    assert metadata["chars_removed"] == 0


def test_process_single_article_rejects_non_string_text():
    cleaner = BalancedBoundaryContentCleaner(
        db_path=":memory:",
        enable_telemetry=False,
    )

    with pytest.raises((TypeError, AttributeError)):
        cleaner.process_single_article(  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            domain="example.com",
        )

    with pytest.raises((TypeError, AttributeError)):
        cleaner.process_single_article(  # type: ignore[arg-type]
            12345,  # type: ignore[arg-type]
            domain="example.com",
        )
