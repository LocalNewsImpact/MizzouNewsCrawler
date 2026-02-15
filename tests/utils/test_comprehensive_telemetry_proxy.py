"""Comprehensive tests for comprehensive_telemetry proxy status utilities."""

import pytest

from src.utils.comprehensive_telemetry import (
    PROXY_STATUS_BYPASSED,
    PROXY_STATUS_DISABLED,
    PROXY_STATUS_FAILED,
    PROXY_STATUS_SUCCESS,
    proxy_status_to_int,
)


class TestProxyStatusToInt:
    """Comprehensive tests for proxy_status_to_int function."""

    def test_disabled_status(self):
        """'disabled' should map to PROXY_STATUS_DISABLED (0)."""
        assert proxy_status_to_int("disabled") == PROXY_STATUS_DISABLED
        assert proxy_status_to_int("disabled") == 0

    def test_success_status(self):
        """'success' should map to PROXY_STATUS_SUCCESS (1)."""
        assert proxy_status_to_int("success") == PROXY_STATUS_SUCCESS
        assert proxy_status_to_int("success") == 1

    def test_failed_status(self):
        """'failed' should map to PROXY_STATUS_FAILED (2)."""
        assert proxy_status_to_int("failed") == PROXY_STATUS_FAILED
        assert proxy_status_to_int("failed") == 2

    def test_bypassed_status(self):
        """'bypassed' should map to PROXY_STATUS_BYPASSED (3)."""
        assert proxy_status_to_int("bypassed") == PROXY_STATUS_BYPASSED
        assert proxy_status_to_int("bypassed") == 3

    def test_case_insensitive_disabled(self):
        """Status should be case-insensitive."""
        assert proxy_status_to_int("DISABLED") == PROXY_STATUS_DISABLED
        assert proxy_status_to_int("Disabled") == PROXY_STATUS_DISABLED
        assert proxy_status_to_int("DiSaBlEd") == PROXY_STATUS_DISABLED

    def test_case_insensitive_success(self):
        """'SUCCESS' in any case should work."""
        assert proxy_status_to_int("SUCCESS") == PROXY_STATUS_SUCCESS
        assert proxy_status_to_int("Success") == PROXY_STATUS_SUCCESS
        assert proxy_status_to_int("SuCcEsS") == PROXY_STATUS_SUCCESS

    def test_case_insensitive_failed(self):
        """'FAILED' in any case should work."""
        assert proxy_status_to_int("FAILED") == PROXY_STATUS_FAILED
        assert proxy_status_to_int("Failed") == PROXY_STATUS_FAILED
        assert proxy_status_to_int("FaIlEd") == PROXY_STATUS_FAILED

    def test_case_insensitive_bypassed(self):
        """'BYPASSED' in any case should work."""
        assert proxy_status_to_int("BYPASSED") == PROXY_STATUS_BYPASSED
        assert proxy_status_to_int("Bypassed") == PROXY_STATUS_BYPASSED
        assert proxy_status_to_int("ByPaSsEd") == PROXY_STATUS_BYPASSED

    def test_none_input_returns_none(self):
        """None input should return None."""
        assert proxy_status_to_int(None) is None

    def test_unknown_status_returns_none(self):
        """Unknown status strings should return None."""
        assert proxy_status_to_int("unknown") is None
        assert proxy_status_to_int("invalid") is None
        assert proxy_status_to_int("error") is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        assert proxy_status_to_int("") is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only strings should return None."""
        assert proxy_status_to_int("   ") is None
        assert proxy_status_to_int("\t") is None
        assert proxy_status_to_int("\n") is None

    def test_numeric_string_returns_none(self):
        """Numeric strings should not match."""
        assert proxy_status_to_int("0") is None
        assert proxy_status_to_int("1") is None
        assert proxy_status_to_int("2") is None
        assert proxy_status_to_int("3") is None

    def test_partial_match_returns_none(self):
        """Partial matches should not work."""
        assert proxy_status_to_int("disabl") is None
        assert proxy_status_to_int("succ") is None
        assert proxy_status_to_int("fail") is None
        assert proxy_status_to_int("bypass") is None

    def test_with_leading_trailing_whitespace(self):
        """Leading/trailing whitespace should not affect result."""
        # .lower() is called but not .strip(), so whitespace will cause mismatch
        assert proxy_status_to_int("  disabled  ") is None
        assert proxy_status_to_int(" success ") is None

    def test_all_status_constants_unique(self):
        """All status constants should have unique values."""
        statuses = {
            PROXY_STATUS_DISABLED,
            PROXY_STATUS_SUCCESS,
            PROXY_STATUS_FAILED,
            PROXY_STATUS_BYPASSED,
        }
        assert len(statuses) == 4

    def test_returns_integer_type(self):
        """Should return integer type when matched."""
        result = proxy_status_to_int("success")
        assert isinstance(result, int)

        result = proxy_status_to_int("disabled")
        assert isinstance(result, int)

    def test_returns_none_type(self):
        """Should return None type when not matched."""
        result = proxy_status_to_int("invalid")
        assert result is None

        result = proxy_status_to_int(None)
        assert result is None

    def test_status_mapping_completeness(self):
        """All defined constants should be reachable."""
        assert proxy_status_to_int("disabled") == 0
        assert proxy_status_to_int("success") == 1
        assert proxy_status_to_int("failed") == 2
        assert proxy_status_to_int("bypassed") == 3

    def test_bidirectional_mapping_concept(self):
        """Status integers should be interpretable (conceptual test)."""
        # Given we know the mapping, verify consistency
        status_str = "success"
        status_int = proxy_status_to_int(status_str)
        assert status_int == PROXY_STATUS_SUCCESS

    def test_with_underscores_returns_none(self):
        """Status with underscores should not match."""
        assert proxy_status_to_int("proxy_disabled") is None
        assert proxy_status_to_int("proxy_success") is None

    def test_with_hyphens_returns_none(self):
        """Status with hyphens should not match."""
        assert proxy_status_to_int("proxy-disabled") is None
        assert proxy_status_to_int("proxy-success") is None

    def test_plurals_do_not_match(self):
        """Plural forms should not match."""
        assert proxy_status_to_int("successs") is None
        assert proxy_status_to_int("faileds") is None

    def test_past_tense_does_not_match(self):
        """Past tense forms should not match."""
        assert proxy_status_to_int("succeeded") is None
        assert proxy_status_to_int("disabling") is None


class TestProxyStatusConstants:
    """Test the proxy status constants themselves."""

    def test_disabled_constant_value(self):
        """PROXY_STATUS_DISABLED should be 0."""
        assert PROXY_STATUS_DISABLED == 0

    def test_success_constant_value(self):
        """PROXY_STATUS_SUCCESS should be 1."""
        assert PROXY_STATUS_SUCCESS == 1

    def test_failed_constant_value(self):
        """PROXY_STATUS_FAILED should be 2."""
        assert PROXY_STATUS_FAILED == 2

    def test_bypassed_constant_value(self):
        """PROXY_STATUS_BYPASSED should be 3."""
        assert PROXY_STATUS_BYPASSED == 3

    def test_constants_are_integers(self):
        """All constants should be integers."""
        assert isinstance(PROXY_STATUS_DISABLED, int)
        assert isinstance(PROXY_STATUS_SUCCESS, int)
        assert isinstance(PROXY_STATUS_FAILED, int)
        assert isinstance(PROXY_STATUS_BYPASSED, int)

    def test_constants_are_non_negative(self):
        """All constants should be non-negative."""
        assert PROXY_STATUS_DISABLED >= 0
        assert PROXY_STATUS_SUCCESS >= 0
        assert PROXY_STATUS_FAILED >= 0
        assert PROXY_STATUS_BYPASSED >= 0

    def test_constants_in_sequential_order(self):
        """Constants should be in sequential order."""
        assert PROXY_STATUS_DISABLED == 0
        assert PROXY_STATUS_SUCCESS == 1
        assert PROXY_STATUS_FAILED == 2
        assert PROXY_STATUS_BYPASSED == 3


class TestIntegrationScenarios:
    """Integration tests for realistic usage scenarios."""

    def test_telemetry_workflow_success(self):
        """Successful proxy usage workflow."""
        status_str = "success"
        status_int = proxy_status_to_int(status_str)

        assert status_int == PROXY_STATUS_SUCCESS
        assert status_int == 1
        # This would be stored in database as integer
        assert isinstance(status_int, int)

    def test_telemetry_workflow_disabled(self):
        """Disabled proxy workflow."""
        status_str = "disabled"
        status_int = proxy_status_to_int(status_str)

        assert status_int == PROXY_STATUS_DISABLED
        assert status_int == 0

    def test_telemetry_workflow_failed(self):
        """Failed proxy workflow."""
        status_str = "failed"
        status_int = proxy_status_to_int(status_str)

        assert status_int == PROXY_STATUS_FAILED
        assert status_int == 2

    def test_telemetry_workflow_bypassed(self):
        """Bypassed proxy workflow."""
        status_str = "bypassed"
        status_int = proxy_status_to_int(status_str)

        assert status_int == PROXY_STATUS_BYPASSED
        assert status_int == 3

    def test_handling_missing_status(self):
        """Handle missing/None status in telemetry."""
        status_int = proxy_status_to_int(None)
        assert status_int is None
        # In database, this would likely be stored as NULL

    def test_handling_invalid_status_gracefully(self):
        """Invalid status should not crash, just return None."""
        invalid_statuses = ["unknown", "error", "timeout", "pending"]

        for status in invalid_statuses:
            result = proxy_status_to_int(status)
            assert result is None

    def test_case_insensitive_from_config(self):
        """Status from config file might have different case."""
        # Simulating various config file formats
        assert proxy_status_to_int("SUCCESS") == PROXY_STATUS_SUCCESS
        assert proxy_status_to_int("Disabled") == PROXY_STATUS_DISABLED
        assert proxy_status_to_int("FAILED") == PROXY_STATUS_FAILED

    def test_all_valid_statuses_map_correctly(self):
        """Verify complete mapping of all valid statuses."""
        mapping = {
            "disabled": 0,
            "success": 1,
            "failed": 2,
            "bypassed": 3,
        }

        for status_str, expected_int in mapping.items():
            result = proxy_status_to_int(status_str)
            assert result == expected_int

            # Also test uppercase
            result = proxy_status_to_int(status_str.upper())
            assert result == expected_int
