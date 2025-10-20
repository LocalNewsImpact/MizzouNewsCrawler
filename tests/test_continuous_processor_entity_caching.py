"""Tests for entity extraction model caching in continuous processor.

This test validates that the spaCy model is loaded only once and reused
across multiple batches, preventing the 288 model reloads per day issue.
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Add repo root to path
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from orchestration import continuous_processor as processor_module  # noqa: E402


@pytest.fixture(autouse=True)
def reset_cached_extractor():
    """Reset the global cached extractor before and after each test."""
    processor_module._ENTITY_EXTRACTOR = None
    yield
    processor_module._ENTITY_EXTRACTOR = None


@pytest.fixture
def mock_entity_extractor():
    """Create a mock ArticleEntityExtractor."""
    mock_extractor = Mock()
    mock_extractor.extractor_version = "test-version"
    return mock_extractor


@pytest.fixture
def mock_extractor_class(mock_entity_extractor):
    """Mock the ArticleEntityExtractor class to track instantiations."""
    with patch("src.pipeline.entity_extraction.ArticleEntityExtractor") as mock_class:
        mock_class.return_value = mock_entity_extractor
        yield mock_class


def test_get_cached_entity_extractor_loads_once(
    mock_extractor_class, mock_entity_extractor
):
    """Test that get_cached_entity_extractor loads the model only once."""
    # First call should create the extractor
    extractor1 = processor_module.get_cached_entity_extractor()
    assert extractor1 is mock_entity_extractor
    assert mock_extractor_class.call_count == 1

    # Second call should return the same cached instance
    extractor2 = processor_module.get_cached_entity_extractor()
    assert extractor2 is mock_entity_extractor
    assert extractor2 is extractor1  # Same object
    assert mock_extractor_class.call_count == 1  # Not called again!

    # Third call should also return the same cached instance
    extractor3 = processor_module.get_cached_entity_extractor()
    assert extractor3 is mock_entity_extractor
    assert extractor3 is extractor1
    assert mock_extractor_class.call_count == 1  # Still not called again!


def test_process_entity_extraction_uses_cached_extractor(
    mock_extractor_class, mock_entity_extractor
):
    """Test that process_entity_extraction uses the cached extractor."""

    with patch(
        "src.cli.commands.entity_extraction.handle_entity_extraction_command"
    ) as mock_handle:
        mock_handle.return_value = 0  # Success

        # First batch
        result1 = processor_module.process_entity_extraction(100)
        assert result1 is True
        assert mock_extractor_class.call_count == 1  # Created once
        assert mock_handle.call_count == 1

        # Verify the extractor was passed to the handler
        call_args = mock_handle.call_args
        assert call_args[1]["extractor"] is mock_entity_extractor

        # Second batch - should reuse the cached extractor
        result2 = processor_module.process_entity_extraction(200)
        assert result2 is True
        assert mock_extractor_class.call_count == 1  # NOT created again!
        assert mock_handle.call_count == 2

        # Verify the same extractor was passed again
        call_args = mock_handle.call_args
        assert call_args[1]["extractor"] is mock_entity_extractor

        # Third batch - still using cached extractor
        result3 = processor_module.process_entity_extraction(50)
        assert result3 is True
        assert mock_extractor_class.call_count == 1  # STILL not created again!
        assert mock_handle.call_count == 3


def test_process_entity_extraction_handles_zero_count():
    """Test that process_entity_extraction returns False when count is 0."""
    result = processor_module.process_entity_extraction(0)
    assert result is False


def test_process_entity_extraction_respects_batch_size_limit(mock_extractor_class):
    """Test that process_entity_extraction respects GAZETTEER_BATCH_SIZE."""

    with patch(
        "src.cli.commands.entity_extraction.handle_entity_extraction_command"
    ) as mock_handle:
        mock_handle.return_value = 0  # Success

        # Set batch size to 500 (Phase 1 change)
        original_batch_size = processor_module.GAZETTEER_BATCH_SIZE
        processor_module.GAZETTEER_BATCH_SIZE = 500

        try:
            # Process with count > batch size
            processor_module.process_entity_extraction(1000)

            # Verify limit was capped at batch size
            call_args = mock_handle.call_args
            args = call_args[0][0]  # First positional arg
            assert args.limit == 500

            # Process with count < batch size
            mock_handle.reset_mock()
            processor_module.process_entity_extraction(100)

            # Verify limit matches count
            call_args = mock_handle.call_args
            args = call_args[0][0]
            assert args.limit == 100

        finally:
            processor_module.GAZETTEER_BATCH_SIZE = original_batch_size


def test_process_entity_extraction_handles_errors(mock_extractor_class):
    """Test that process_entity_extraction handles exceptions gracefully."""

    with patch(
        "src.cli.commands.entity_extraction.handle_entity_extraction_command"
    ) as mock_handle:
        # Simulate an exception
        mock_handle.side_effect = RuntimeError("Test error")

        result = processor_module.process_entity_extraction(100)
        assert result is False


def test_process_entity_extraction_handles_nonzero_exit_code(mock_extractor_class):
    """Test that process_entity_extraction handles non-zero exit codes."""

    with patch(
        "src.cli.commands.entity_extraction.handle_entity_extraction_command"
    ) as mock_handle:
        # Simulate a failure exit code
        mock_handle.return_value = 1

        result = processor_module.process_entity_extraction(100)
        assert result is False


def test_batch_size_default_is_500():
    """Test that GAZETTEER_BATCH_SIZE default is 500 (Phase 1 change)."""
    # This test verifies the Phase 1 optimization is in place
    # The batch size should be 500 to reduce model reloads by 80%
    import os

    # Check if the environment variable is not set (default value)
    if "GAZETTEER_BATCH_SIZE" not in os.environ:
        # Need to reload the module to get the actual default
        # In practice, GAZETTEER_BATCH_SIZE is already loaded at module import
        # So we just check the current value matches the expected default
        expected_default = 500
        # Note: This might be affected by the environment, but the code
        # should have GAZETTEER_BATCH_SIZE = int(os.getenv("GAZETTEER_BATCH_SIZE", "500"))
        assert (
            processor_module.GAZETTEER_BATCH_SIZE == expected_default
            or os.getenv("GAZETTEER_BATCH_SIZE") is not None
        )


def test_entity_extraction_passes_correct_args(mock_extractor_class):
    """Test that the correct arguments are passed to the entity extraction handler."""

    with patch(
        "src.cli.commands.entity_extraction.handle_entity_extraction_command"
    ) as mock_handle:
        mock_handle.return_value = 0

        processor_module.process_entity_extraction(250)

        # Verify the call
        assert mock_handle.call_count == 1
        call_args = mock_handle.call_args

        # Check args namespace
        args = call_args[0][0]
        assert isinstance(args, Namespace)
        assert args.limit == 250
        assert args.source is None

        # Check extractor was passed
        assert "extractor" in call_args[1]
        assert call_args[1]["extractor"] is not None
