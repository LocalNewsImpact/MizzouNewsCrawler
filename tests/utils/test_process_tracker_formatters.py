"""Comprehensive tests for process tracker utility functions."""

import pytest

from src.models.database import BackgroundProcess
from src.utils.process_tracker import format_duration, format_progress


class TestFormatDuration:
    """Comprehensive tests for format_duration function."""

    def test_less_than_one_second(self):
        """Sub-second durations should show decimal seconds."""
        assert format_duration(0.5) == "0.5s"
        assert format_duration(0.123) == "0.1s"
        assert format_duration(0.999) == "1.0s"

    def test_exact_seconds(self):
        """Exact second values should format cleanly."""
        assert format_duration(1.0) == "1.0s"
        assert format_duration(5.0) == "5.0s"
        assert format_duration(30.0) == "30.0s"
        assert format_duration(59.0) == "59.0s"

    def test_fractional_seconds(self):
        """Fractional seconds should show one decimal place."""
        assert format_duration(1.5) == "1.5s"
        assert format_duration(12.3) == "12.3s"
        assert format_duration(45.7) == "45.7s"

    def test_exactly_one_minute(self):
        """Exactly 60 seconds should format as minutes."""
        result = format_duration(60.0)
        assert result == "1m 0s"

    def test_minutes_with_seconds(self):
        """Minutes with remaining seconds should show both."""
        assert format_duration(90.0) == "1m 30s"
        assert format_duration(125.0) == "2m 5s"
        assert format_duration(3599.0) == "59m 59s"

    def test_exactly_one_hour(self):
        """Exactly 3600 seconds should format as hours."""
        result = format_duration(3600.0)
        assert result == "1h 0m"

    def test_hours_with_minutes(self):
        """Hours with remaining minutes should show both."""
        assert format_duration(3660.0) == "1h 1m"
        assert format_duration(7200.0) == "2h 0m"
        assert format_duration(7380.0) == "2h 3m"

    def test_hours_with_seconds_drops_seconds(self):
        """Hours format should not show seconds."""
        # 1 hour 1 minute 30 seconds
        result = format_duration(3690.0)
        assert "h" in result
        assert "m" in result
        assert "s" not in result

    def test_multiple_hours(self):
        """Multiple hours should format correctly."""
        assert format_duration(10800.0) == "3h 0m"
        assert format_duration(36000.0) == "10h 0m"
        assert format_duration(86400.0) == "24h 0m"

    def test_zero_duration(self):
        """Zero duration should show as seconds."""
        assert format_duration(0.0) == "0.0s"

    def test_very_small_duration(self):
        """Very small durations should show with decimal."""
        assert format_duration(0.01) == "0.0s"
        assert format_duration(0.001) == "0.0s"

    def test_boundary_at_60_seconds(self):
        """Test boundary between seconds and minutes."""
        # Just under 60
        result = format_duration(59.9)
        assert result == "59.9s"
        # At 60
        result = format_duration(60.0)
        assert "m" in result
        # Just over 60
        result = format_duration(60.1)
        assert "m" in result

    def test_boundary_at_3600_seconds(self):
        """Test boundary between minutes and hours."""
        # Just under 3600
        result = format_duration(3599.0)
        assert "m" in result and "h" not in result
        # At 3600
        result = format_duration(3600.0)
        assert "h" in result
        # Just over 3600
        result = format_duration(3601.0)
        assert "h" in result

    def test_large_durations(self):
        """Very large durations should format correctly."""
        # 100 hours
        result = format_duration(360000.0)
        assert result == "100h 0m"
        # 1000 hours
        result = format_duration(3600000.0)
        assert result == "1000h 0m"

    def test_fractional_minutes(self):
        """Fractional minutes should show correct seconds."""
        # 1.5 minutes = 90 seconds
        assert format_duration(90.0) == "1m 30s"
        # 2.25 minutes = 135 seconds
        assert format_duration(135.0) == "2m 15s"

    def test_fractional_hours(self):
        """Fractional hours should show correct minutes."""
        # 1.5 hours = 90 minutes
        assert format_duration(5400.0) == "1h 30m"
        # 2.75 hours = 165 minutes
        assert format_duration(9900.0) == "2h 45m"

    def test_returns_string(self):
        """Should always return a string."""
        assert isinstance(format_duration(5.0), str)
        assert isinstance(format_duration(65.0), str)
        assert isinstance(format_duration(3700.0), str)


class TestFormatProgress:
    """Comprehensive tests for format_progress function."""

    def test_with_total_shows_fraction_and_percentage(self):
        """Progress with total should show current/total (pct%)."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=50,
            progress_total=100
        )
        process.progress_percentage = 50.0
        
        result = format_progress(process)
        assert "50/100" in result
        assert "50.0%" in result

    def test_with_total_at_zero_percent(self):
        """Zero progress should show 0.0%."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=0,
            progress_total=100
        )
        process.progress_percentage = 0.0
        
        result = format_progress(process)
        assert "0/100" in result
        assert "0.0%" in result

    def test_with_total_at_hundred_percent(self):
        """Complete progress should show 100.0%."""
        process = BackgroundProcess(
            name="test",
            status="completed",
            progress_current=100,
            progress_total=100
        )
        process.progress_percentage = 100.0
        
        result = format_progress(process)
        assert "100/100" in result
        assert "100.0%" in result

    def test_without_total_shows_count_only(self):
        """Progress without total should show 'X items'."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=50,
            progress_total=None
        )
        
        result = format_progress(process)
        assert result == "50 items"

    def test_without_total_zero_items(self):
        """Zero progress without total should show '0 items'."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=0,
            progress_total=None
        )
        
        result = format_progress(process)
        assert result == "0 items"

    def test_fractional_percentage(self):
        """Fractional percentages should show one decimal place."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=33,
            progress_total=100
        )
        process.progress_percentage = 33.333
        
        result = format_progress(process)
        assert "33.3%" in result

    def test_percentage_none_defaults_to_zero(self):
        """None percentage should default to 0."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=25,
            progress_total=100
        )
        process.progress_percentage = None
        
        result = format_progress(process)
        assert "0.0%" in result

    def test_large_numbers(self):
        """Large progress numbers should format correctly."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=50000,
            progress_total=100000
        )
        process.progress_percentage = 50.0
        
        result = format_progress(process)
        assert "50000/100000" in result
        assert "50.0%" in result

    def test_nearly_complete(self):
        """Progress near completion should show correctly."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=99,
            progress_total=100
        )
        process.progress_percentage = 99.0
        
        result = format_progress(process)
        assert "99/100" in result
        assert "99.0%" in result

    def test_with_total_zero(self):
        """Total of zero should still format without crash."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=0,
            progress_total=0
        )
        process.progress_percentage = 0.0
        
        result = format_progress(process)
        # Should handle gracefully - either show 0/0 or treat as no total
        assert result is not None

    def test_current_exceeds_total(self):
        """Current exceeding total should still format."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=150,
            progress_total=100
        )
        process.progress_percentage = 150.0
        
        result = format_progress(process)
        assert "150/100" in result
        assert "150.0%" in result

    def test_negative_current_value(self):
        """Negative current value should format (edge case)."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=-5,
            progress_total=None
        )
        
        result = format_progress(process)
        assert "-5 items" in result

    def test_returns_string(self):
        """Should always return a string."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=50,
            progress_total=100
        )
        process.progress_percentage = 50.0
        
        result = format_progress(process)
        assert isinstance(result, str)

    def test_minimal_process_object(self):
        """Should work with minimal BackgroundProcess."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=10,
            progress_total=None
        )
        
        result = format_progress(process)
        assert "10 items" in result


class TestFormatting Integration:
    """Integration tests for formatting functions."""

    def test_duration_and_progress_together(self):
        """Both formatters should work together in typical use."""
        process = BackgroundProcess(
            name="test",
            status="running",
            progress_current=500,
            progress_total=1000
        )
        process.progress_percentage = 50.0
        
        progress_str = format_progress(process)
        duration_str = format_duration(120.5)  # 2 minutes
        
        assert "500/1000" in progress_str
        assert "50.0%" in progress_str
        assert "2m" in duration_str

    def test_formats_for_display_log(self):
        """Formats should be suitable for logging."""
        process = BackgroundProcess(
            name="extraction",
            status="running",
            progress_current=250,
            progress_total=1000
        )
        process.progress_percentage = 25.0
        
        progress = format_progress(process)
        duration = format_duration(3725.0)  # 1 hour 2 minutes
        
        log_message = f"Process: {progress}, Duration: {duration}"
        assert "250/1000 (25.0%)" in log_message
        assert "1h 2m" in log_message
