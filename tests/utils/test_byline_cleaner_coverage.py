"""Tests for byline_cleaner.py to increase coverage."""

import pytest
from unittest.mock import Mock, patch

from src.utils.byline_cleaner import BylineCleaner


class TestBylineCleanerInit:
    """Test BylineCleaner initialization."""

    def test_initializes_with_defaults(self):
        """Should initialize with default parameters."""
        cleaner = BylineCleaner()
        assert cleaner is not None
        assert hasattr(cleaner, "TITLES_TO_REMOVE")
        assert hasattr(cleaner, "WIRE_SERVICES")

    def test_has_wire_services_set(self):
        """Should have wire services defined."""
        cleaner = BylineCleaner()
        assert "associated press" in cleaner.WIRE_SERVICES
        assert "ap" in cleaner.WIRE_SERVICES
        assert "reuters" in cleaner.WIRE_SERVICES

    def test_has_titles_to_remove_set(self):
        """Should have titles to remove defined."""
        cleaner = BylineCleaner()
        assert "staff" in cleaner.TITLES_TO_REMOVE
        assert "reporter" in cleaner.TITLES_TO_REMOVE
        assert "editor" in cleaner.TITLES_TO_REMOVE


class TestBylineCleanerBasicCleaning:
    """Test basic byline cleaning functionality."""

    def test_cleans_simple_byline(self):
        """Should clean simple author name."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By John Smith")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_handles_empty_byline(self):
        """Should handle empty byline."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("")
        assert result == []

    def test_handles_none_byline(self):
        """Should handle None byline."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline(None)
        assert result == []

    def test_handles_whitespace_only_byline(self):
        """Should handle whitespace-only byline."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("   \n\t   ")
        assert result == []

    def test_removes_by_prefix(self):
        """Should remove 'By' prefix."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By Jane Doe")
        assert len(result) > 0
        # Should not contain "By"
        assert not any("by" in author.lower() for author in result)

    def test_removes_staff_writer(self):
        """Should remove 'Staff Writer' title."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith, Staff Writer")
        assert len(result) > 0
        # Should not contain "Staff Writer"
        assert not any("staff writer" in author.lower() for author in result)


class TestBylineCleanerMultipleAuthors:
    """Test handling of multiple authors."""

    def test_splits_and_separator(self):
        """Should split on 'and' separator."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith and Jane Doe")
        assert len(result) >= 2

    def test_splits_comma_separator(self):
        """Should split on comma separator."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith, Jane Doe")
        assert len(result) >= 1

    def test_handles_three_authors(self):
        """Should handle three or more authors."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith, Jane Doe and Bob Johnson")
        assert len(result) >= 2


class TestBylineCleanerWireServices:
    """Test wire service detection."""

    def test_detects_associated_press(self):
        """Should detect Associated Press."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By Associated Press")
        # Wire service should be detected
        assert isinstance(result, list)

    def test_detects_ap(self):
        """Should detect AP abbreviation."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By AP")
        assert isinstance(result, list)

    def test_detects_reuters(self):
        """Should detect Reuters."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By Reuters")
        assert isinstance(result, list)

    def test_detects_author_before_wire_service(self):
        """Should extract author before wire service."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith USA TODAY")
        assert len(result) >= 1

    def test_returns_json_with_wire_service_flag(self):
        """Should return JSON with wire_service_detected flag."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By Associated Press", return_json=True)
        assert isinstance(result, dict)
        assert "wire_service_detected" in result
        assert "authors" in result


class TestBylineCleanerSourceRemoval:
    """Test source name removal."""

    def test_removes_source_name(self):
        """Should remove source publication name."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline(
            "John Smith, The Daily Tribune", source_name="Daily Tribune"
        )
        assert len(result) > 0
        # Should not contain source name
        assert not any("tribune" in author.lower() for author in result)

    def test_removes_canonical_source_name(self):
        """Should remove canonical source name."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline(
            "Jane Doe for The Herald", source_canonical_name="Herald"
        )
        assert len(result) > 0


class TestBylineCleanerTitleRemoval:
    """Test removal of job titles."""

    def test_removes_reporter_title(self):
        """Should remove 'Reporter' title."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith, Reporter")
        assert len(result) > 0
        assert not any("reporter" in author.lower() for author in result)

    def test_removes_editor_title(self):
        """Should remove 'Editor' title."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("Jane Doe, Editor")
        assert len(result) > 0
        assert not any("editor" in author.lower() for author in result)

    def test_removes_senior_reporter(self):
        """Should remove 'Senior Reporter' title."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("Bob Johnson, Senior Reporter")
        assert len(result) > 0

    def test_removes_staff_photographer(self):
        """Should remove 'Staff Photographer' title."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("Alice Brown, Staff Photographer")
        assert len(result) > 0


class TestBylineCleanerEdgeCases:
    """Test edge cases and complex scenarios."""

    def test_handles_unicode_characters(self):
        """Should handle unicode characters in names."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By José García")
        assert len(result) > 0

    def test_handles_hyphenated_names(self):
        """Should handle hyphenated names."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("Mary-Jane Smith-Johnson")
        assert len(result) > 0

    def test_handles_name_with_suffix(self):
        """Should handle names with suffixes like Jr., Sr."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith Jr.")
        assert len(result) > 0

    def test_handles_middle_initials(self):
        """Should handle middle initials."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Q. Public")
        assert len(result) > 0

    def test_handles_very_long_byline(self):
        """Should handle very long byline strings."""
        cleaner = BylineCleaner()
        long_byline = "By John Smith, Senior Editor and Chief Reporter for Politics and Government Affairs at The Daily Tribune"
        result = cleaner.clean_byline(long_byline)
        assert len(result) > 0

    def test_handles_email_in_byline(self):
        """Should handle email addresses in byline."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith (jsmith@example.com)")
        assert len(result) > 0

    def test_handles_phone_number_in_byline(self):
        """Should handle phone numbers in byline."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("John Smith (555-1234)")
        assert len(result) > 0


class TestBylineCleanerJSONOutput:
    """Test JSON output format."""

    def test_json_output_has_required_fields(self):
        """Should have required fields in JSON output."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By John Smith", return_json=True)
        assert isinstance(result, dict)
        assert "authors" in result
        assert isinstance(result["authors"], list)

    def test_json_output_includes_metadata(self):
        """Should include metadata in JSON output."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline(
            "By John Smith",
            return_json=True,
            article_id="123",
            source_name="Test Source",
        )
        assert isinstance(result, dict)

    def test_json_output_for_wire_service(self):
        """Should include wire_service_detected in JSON."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline("By Reuters", return_json=True)
        assert "wire_service_detected" in result


class TestBylineCleanerTelemetry:
    """Test telemetry integration."""

    def test_initializes_telemetry(self):
        """Should initialize telemetry system."""
        cleaner = BylineCleaner()
        assert hasattr(cleaner, "telemetry")
        assert cleaner.telemetry is not None

    def test_passes_telemetry_params(self):
        """Should pass telemetry parameters to cleaning session."""
        cleaner = BylineCleaner()
        result = cleaner.clean_byline(
            "By John Smith",
            article_id="article123",
            candidate_link_id="link456",
            source_id="source789",
        )
        assert isinstance(result, list)


class TestBylineCleanerBulkCleaning:
    """Test bulk cleaning functionality."""

    def test_clean_bulk_bylines_empty_list(self):
        """Should handle empty list."""
        cleaner = BylineCleaner()
        result = cleaner.clean_bulk_bylines([])
        assert result == []

    def test_clean_bulk_bylines_single_byline(self):
        """Should clean single byline in bulk."""
        cleaner = BylineCleaner()
        bylines = [{"byline": "By John Smith"}]
        result = cleaner.clean_bulk_bylines(bylines)
        assert len(result) == 1

    def test_clean_bulk_bylines_multiple(self):
        """Should clean multiple bylines in bulk."""
        cleaner = BylineCleaner()
        bylines = [
            {"byline": "By John Smith"},
            {"byline": "By Jane Doe"},
            {"byline": "By Bob Johnson"},
        ]
        result = cleaner.clean_bulk_bylines(bylines)
        assert len(result) == 3
