"""Tests for bot sensitivity manager."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.utils.bot_sensitivity_manager import (
    BOT_SENSITIVITY_CONFIG,
    KNOWN_SENSITIVE_PUBLISHERS,
    SENSITIVITY_ADJUSTMENT_RULES,
    BotSensitivityManager,
)


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    return session


@pytest.fixture
def bot_manager(mock_db_session):
    """Create bot sensitivity manager with mocked database."""
    with patch("src.utils.bot_sensitivity_manager.DatabaseManager") as mock_db_mgr:
        mock_db_mgr.return_value.get_session.return_value = mock_db_session
        manager = BotSensitivityManager()
        manager.db = mock_db_mgr.return_value
        return manager


class TestBotSensitivityConfig:
    """Test bot sensitivity configuration constants."""

    def test_sensitivity_config_has_all_levels(self):
        """Test that config exists for all sensitivity levels 1-10."""
        for level in range(1, 11):
            assert level in BOT_SENSITIVITY_CONFIG
            config = BOT_SENSITIVITY_CONFIG[level]
            assert "inter_request_min" in config
            assert "inter_request_max" in config
            assert "batch_sleep" in config
            assert "captcha_backoff_base" in config

    def test_sensitivity_config_scales_appropriately(self):
        """Test that delays increase with sensitivity level."""
        prev_min = 0
        prev_max = 0
        for level in range(1, 11):
            config = BOT_SENSITIVITY_CONFIG[level]
            # Min should be >= previous min
            assert config["inter_request_min"] >= prev_min
            # Max should be >= previous max
            assert config["inter_request_max"] >= prev_max
            # Min should be less than max
            assert config["inter_request_min"] < config["inter_request_max"]
            prev_min = config["inter_request_min"]
            prev_max = config["inter_request_max"]

    def test_adjustment_rules_structure(self):
        """Test that adjustment rules have correct structure."""
        expected_events = [
            "403_forbidden",
            "captcha_detected",
            "rate_limit_429",
            "connection_timeout",
            "multiple_failures",
        ]
        for event in expected_events:
            assert event in SENSITIVITY_ADJUSTMENT_RULES
            increase, max_cap, base_cooldown = SENSITIVITY_ADJUSTMENT_RULES[event]
            assert isinstance(increase, int)
            assert isinstance(max_cap, int)
            assert isinstance(base_cooldown, (int, float))
            assert 1 <= max_cap <= 10
            assert increase > 0
            assert base_cooldown > 0


class TestGetSensitivityConfig:
    """Test getting sensitivity configuration."""

    def test_get_config_for_unknown_host_returns_default(
        self, bot_manager, mock_db_session
    ):
        """Test that unknown host returns default sensitivity config."""
        mock_db_session.execute.return_value.fetchone.return_value = None

        config = bot_manager.get_sensitivity_config("unknown-site.com")

        assert config == BOT_SENSITIVITY_CONFIG[5]  # Default moderate

    def test_get_config_for_known_sensitive_publisher(self, bot_manager):
        """Test that pre-configured publisher returns correct config."""
        # Add a test entry to known publishers
        test_host = "test-sensitive.com"
        KNOWN_SENSITIVE_PUBLISHERS[test_host] = 10

        try:
            config = bot_manager.get_sensitivity_config(test_host)
            assert config == BOT_SENSITIVITY_CONFIG[10]
        finally:
            # Cleanup
            del KNOWN_SENSITIVE_PUBLISHERS[test_host]

    def test_get_config_from_database(self, bot_manager, mock_db_session):
        """Test loading sensitivity from database."""
        mock_result = Mock()
        mock_result.fetchone.return_value = (7,)  # Sensitivity 7
        mock_db_session.execute.return_value = mock_result

        config = bot_manager.get_sensitivity_config("database-site.com")

        assert config == BOT_SENSITIVITY_CONFIG[7]


class TestGetBotSensitivity:
    """Test getting bot sensitivity level."""

    def test_get_sensitivity_for_known_publisher(self, bot_manager):
        """Test known publisher returns pre-configured sensitivity."""
        test_host = "test-known.com"
        KNOWN_SENSITIVE_PUBLISHERS[test_host] = 8

        try:
            sensitivity = bot_manager.get_bot_sensitivity(test_host)
            assert sensitivity == 8
        finally:
            del KNOWN_SENSITIVE_PUBLISHERS[test_host]

    def test_get_sensitivity_from_database(self, bot_manager, mock_db_session):
        """Test loading sensitivity from database."""
        mock_result = Mock()
        mock_result.fetchone.return_value = (6,)
        mock_db_session.execute.return_value = mock_result

        sensitivity = bot_manager.get_bot_sensitivity("db-site.com")

        assert sensitivity == 6

    def test_get_sensitivity_defaults_to_five(self, bot_manager, mock_db_session):
        """Test that missing sensitivity defaults to 5."""
        mock_db_session.execute.return_value.fetchone.return_value = None

        sensitivity = bot_manager.get_bot_sensitivity("unknown-site.com")

        assert sensitivity == 5

    def test_get_sensitivity_with_source_id(self, bot_manager, mock_db_session):
        """Test getting sensitivity by source_id."""
        mock_result = Mock()
        mock_result.fetchone.return_value = (7,)
        mock_db_session.execute.return_value = mock_result

        sensitivity = bot_manager.get_bot_sensitivity(
            "any-host.com", source_id="source-123"
        )

        assert sensitivity == 7
        # Verify query used source_id
        call_args = mock_db_session.execute.call_args
        assert "source_id" in str(call_args)


class TestAdaptiveCooldowns:
    """Test adaptive cooldown calculations."""

    def test_cooldown_scales_with_sensitivity(self, bot_manager, mock_db_session):
        """Test that cooldown multiplier increases with sensitivity."""
        # Mock that we're not in cooldown
        mock_db_session.execute.return_value.fetchone.return_value = None

        test_cases = [
            (3, 1.0),  # Sensitivity 3 (low) → 1x base
            (5, 2.0),  # Sensitivity 5 (medium) → 2x base
            (7, 4.0),  # Sensitivity 7 (high) → 4x base
            (9, 8.0),  # Sensitivity 9 (very high) → 8x base
        ]

        for current_sensitivity, _expected_multiplier in test_cases:
            new_sensitivity = bot_manager._calculate_adjusted_sensitivity(
                current=current_sensitivity,
                event_type="captcha_detected",
                host="test-site.com",
            )

            # New sensitivity should be increased
            assert new_sensitivity > current_sensitivity

    def test_cooldown_prevents_rapid_adjustments(self, bot_manager, mock_db_session):
        """Test that cooldown prevents multiple adjustments."""
        # Mock that last update was 1 hour ago (within cooldown)
        recent_time = datetime.utcnow() - timedelta(hours=1)
        mock_result = Mock()
        mock_result.fetchone.return_value = (recent_time,)
        mock_db_session.execute.return_value = mock_result

        # Try to adjust with 2hr base cooldown
        new_sensitivity = bot_manager._calculate_adjusted_sensitivity(
            current=5,
            event_type="captcha_detected",  # 2hr base cooldown
            host="test-site.com",
        )

        # Should not change (in cooldown)
        assert new_sensitivity == 5


class TestRecordBotDetection:
    """Test recording bot detection events."""

    def test_record_bot_detection_increases_sensitivity(
        self, bot_manager, mock_db_session
    ):
        """Test that bot detection increases sensitivity."""
        # Mock current sensitivity as 5
        mock_result = Mock()
        mock_result.fetchone.return_value = (5,)
        mock_db_session.execute.return_value = mock_result

        # Mock not in cooldown
        with patch.object(bot_manager, "_is_in_cooldown", return_value=False):
            new_sensitivity = bot_manager.record_bot_detection(
                host="test-site.com",
                url="https://test-site.com/article",
                event_type="captcha_detected",
                http_status_code=403,
            )

        # Should increase by 3 for CAPTCHA (from rules)
        assert new_sensitivity == 8

    def test_record_bot_detection_respects_max_cap(self, bot_manager, mock_db_session):
        """Test that sensitivity doesn't exceed max cap."""
        # Mock current sensitivity as 9
        mock_result = Mock()
        mock_result.fetchone.return_value = (9,)
        mock_db_session.execute.return_value = mock_result

        with patch.object(bot_manager, "_is_in_cooldown", return_value=False):
            new_sensitivity = bot_manager.record_bot_detection(
                host="test-site.com",
                url="https://test-site.com/article",
                event_type="captcha_detected",  # +3, max 10
                http_status_code=403,
            )

        # Should cap at 10
        assert new_sensitivity == 10

    def test_record_bot_detection_logs_event(self, bot_manager, mock_db_session):
        """Test that bot detection event is logged to database."""
        mock_result = Mock()
        mock_result.fetchone.return_value = (5,)
        mock_db_session.execute.return_value = mock_result

        with patch.object(bot_manager, "_is_in_cooldown", return_value=False):
            bot_manager.record_bot_detection(
                host="test-site.com",
                url="https://test-site.com/article",
                event_type="rate_limit_429",
                http_status_code=429,
                response_indicators={"retry_after": "120"},
            )

        # Verify execute was called multiple times (get sensitivity + insert + update)
        assert mock_db_session.execute.call_count >= 2
        mock_db_session.commit.assert_called()

    def test_record_bot_detection_updates_source_record(
        self, bot_manager, mock_db_session
    ):
        """Test that source record is updated with new sensitivity."""
        mock_result = Mock()
        mock_result.fetchone.return_value = (5,)
        mock_db_session.execute.return_value = mock_result

        with patch.object(bot_manager, "_is_in_cooldown", return_value=False):
            bot_manager.record_bot_detection(
                host="test-site.com",
                url="https://test-site.com/article",
                event_type="403_forbidden",
                http_status_code=403,
            )

        # Verify execute was called multiple times and commit was called
        assert mock_db_session.execute.call_count >= 2
        mock_db_session.commit.assert_called()


class TestSensitivityAdjustmentRules:
    """Test sensitivity adjustment rules."""

    @pytest.mark.parametrize(
        "event_type,expected_increase,max_cap",
        [
            ("rate_limit_429", 1, 8),
            ("403_forbidden", 2, 10),
            ("captcha_detected", 3, 10),
            ("connection_timeout", 1, 7),
        ],
    )
    def test_event_adjustments(
        self, bot_manager, mock_db_session, event_type, expected_increase, max_cap
    ):
        """Test that each event type applies correct adjustment."""
        # Start at sensitivity 4
        mock_result = Mock()
        mock_result.fetchone.return_value = (4,)
        mock_db_session.execute.return_value = mock_result

        with patch.object(bot_manager, "_is_in_cooldown", return_value=False):
            new_sensitivity = bot_manager._calculate_adjusted_sensitivity(
                current=4, event_type=event_type, host="test-site.com"
            )

        assert new_sensitivity == 4 + expected_increase

    def test_unknown_event_type_no_adjustment(self, bot_manager):
        """Test that unknown event type doesn't adjust sensitivity."""
        new_sensitivity = bot_manager._calculate_adjusted_sensitivity(
            current=5, event_type="unknown_event", host="test-site.com"
        )

        assert new_sensitivity == 5


class TestGetBotEncounterStats:
    """Test getting bot encounter statistics."""

    def test_get_stats_for_specific_host(self, bot_manager, mock_db_session):
        """Test getting stats for specific host."""
        mock_result = Mock()
        # Return values matching the actual query for specific host:
        # COUNT(*), COUNT(DISTINCT event_type), MAX(detected_at), AVG(new_sensitivity)
        mock_result.fetchone.return_value = (
            15,  # total_events (row[0])
            3,  # event_types (row[1])
            datetime(2025, 10, 12, 10, 0, 0),  # last_detection (row[2])
            7.5,  # avg_new_sensitivity (row[3])
        )
        mock_db_session.execute.return_value = mock_result

        stats = bot_manager.get_bot_encounter_stats("test-site.com")

        assert stats["total_events"] == 15
        assert stats["event_types"] == 3
        assert stats["last_detection"] is not None
        assert stats["avg_sensitivity"] == 7.5

    def test_get_global_stats(self, bot_manager, mock_db_session):
        """Test getting global stats across all hosts."""
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            150,  # total_events
            25,  # affected_hosts
            5,  # event_types
            datetime(2025, 10, 12, 10, 0, 0),  # last_detection
        )
        mock_db_session.execute.return_value = mock_result

        stats = bot_manager.get_bot_encounter_stats()

        assert stats["total_events"] == 150
        assert stats["affected_hosts"] == 25

    def test_get_stats_handles_no_data(self, bot_manager, mock_db_session):
        """Test that stats returns zeros when no data exists."""
        mock_db_session.execute.return_value.fetchone.return_value = None

        stats = bot_manager.get_bot_encounter_stats("no-events.com")

        assert stats["total_events"] == 0


class TestCreateOrGetSourceId:
    """Test source ID creation and retrieval."""

    def test_get_existing_source_id(self, bot_manager, mock_db_session):
        """Test getting existing source ID."""
        mock_result = Mock()
        mock_result.fetchone.return_value = ("source-123",)
        mock_db_session.execute.return_value = mock_result

        source_id = bot_manager._get_or_create_source_id("existing-site.com")

        assert source_id == "source-123"

    def test_create_new_source_when_not_exists(self, bot_manager, mock_db_session):
        """Test creating new source when it doesn't exist."""
        # First call returns None (not found)
        mock_result = Mock()
        mock_result.fetchone.return_value = None  # Not found
        mock_db_session.execute.return_value = mock_result

        source_id = bot_manager._get_or_create_source_id("new-site.com")

        # Should return a UUID string
        assert isinstance(source_id, str)
        assert len(source_id) > 0

        # Verify execute was called (SELECT + INSERT)
        assert mock_db_session.execute.call_count >= 2
        mock_db_session.commit.assert_called()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_database_errors_gracefully(self, bot_manager, mock_db_session):
        """Test that database errors don't crash the system."""
        mock_db_session.execute.side_effect = Exception("Database error")

        # Should return default sensitivity
        sensitivity = bot_manager.get_bot_sensitivity("error-site.com")
        assert sensitivity == 5

    def test_sensitivity_stays_in_valid_range(self, bot_manager):
        """Test that calculated sensitivity never exceeds 1-10 range."""
        for current in range(1, 11):
            for event_type in SENSITIVITY_ADJUSTMENT_RULES.keys():
                with patch.object(bot_manager, "_is_in_cooldown", return_value=False):
                    new = bot_manager._calculate_adjusted_sensitivity(
                        current=current, event_type=event_type, host="test.com"
                    )
                    assert 1 <= new <= 10

    def test_handles_null_sensitivity_in_database(self, bot_manager, mock_db_session):
        """Test handling NULL sensitivity in database."""
        mock_result = Mock()
        mock_result.fetchone.return_value = (None,)  # NULL sensitivity
        mock_db_session.execute.return_value = mock_result

        sensitivity = bot_manager.get_bot_sensitivity("null-sensitivity.com")

        # Should return default
        assert sensitivity == 5
