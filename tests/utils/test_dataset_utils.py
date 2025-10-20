"""Unit tests for dataset resolution utilities."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base, Dataset
from src.utils.dataset_utils import resolve_dataset_id


@pytest.fixture
def in_memory_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_datasets(in_memory_engine):
    """Create test datasets in the database."""
    Session = sessionmaker(bind=in_memory_engine)
    session = Session()

    datasets = [
        Dataset(
            id="61ccd4d3-763f-4cc6-b85d-74b268e80a00",
            slug="mizzou-missouri-state",
            label="Mizzou Missouri State",
            name="Mizzou Missouri State Dataset",
        ),
        Dataset(
            id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            slug="test-dataset",
            label="Test Dataset",
            name="Test Dataset Name",
        ),
        Dataset(
            id="12345678-1234-1234-1234-123456789012",
            slug="dataset-with-spaces",
            label="Dataset With Spaces",
            name="Dataset With Spaces in Name",
        ),
    ]

    for dataset in datasets:
        session.add(dataset)

    session.commit()
    session.close()

    return datasets


def test_resolve_by_uuid_passthrough(in_memory_engine, test_datasets):
    """Test that a valid UUID is returned unchanged."""
    test_uuid = "61ccd4d3-763f-4cc6-b85d-74b268e80a00"
    result = resolve_dataset_id(in_memory_engine, test_uuid)
    assert result == test_uuid


def test_resolve_by_slug(in_memory_engine, test_datasets):
    """Test resolution by dataset slug."""
    result = resolve_dataset_id(in_memory_engine, "mizzou-missouri-state")
    assert result == "61ccd4d3-763f-4cc6-b85d-74b268e80a00"


def test_resolve_by_name(in_memory_engine, test_datasets):
    """Test resolution by dataset name."""
    result = resolve_dataset_id(in_memory_engine, "Mizzou Missouri State Dataset")
    assert result == "61ccd4d3-763f-4cc6-b85d-74b268e80a00"


def test_resolve_by_label(in_memory_engine, test_datasets):
    """Test resolution by dataset label."""
    result = resolve_dataset_id(in_memory_engine, "Mizzou Missouri State")
    assert result == "61ccd4d3-763f-4cc6-b85d-74b268e80a00"


def test_resolve_none_returns_none(in_memory_engine, test_datasets):
    """Test that None input returns None."""
    result = resolve_dataset_id(in_memory_engine, None)
    assert result is None


def test_resolve_empty_string_returns_none(in_memory_engine, test_datasets):
    """Test that empty string returns None."""
    result = resolve_dataset_id(in_memory_engine, "")
    assert result is None


def test_resolve_whitespace_returns_none(in_memory_engine, test_datasets):
    """Test that whitespace-only string returns None."""
    result = resolve_dataset_id(in_memory_engine, "   ")
    assert result is None


def test_resolve_with_spaces_in_slug(in_memory_engine, test_datasets):
    """Test resolution of dataset with spaces in slug."""
    result = resolve_dataset_id(in_memory_engine, "dataset-with-spaces")
    assert result == "12345678-1234-1234-1234-123456789012"


def test_resolve_with_spaces_in_name(in_memory_engine, test_datasets):
    """Test resolution of dataset with spaces in name."""
    result = resolve_dataset_id(in_memory_engine, "Dataset With Spaces in Name")
    assert result == "12345678-1234-1234-1234-123456789012"


def test_resolve_nonexistent_raises_error(in_memory_engine, test_datasets):
    """Test that non-existent dataset raises ValueError."""
    with pytest.raises(ValueError, match="Dataset not found: 'nonexistent-dataset'"):
        resolve_dataset_id(in_memory_engine, "nonexistent-dataset")


def test_resolve_strips_whitespace(in_memory_engine, test_datasets):
    """Test that leading/trailing whitespace is stripped before lookup."""
    result = resolve_dataset_id(in_memory_engine, "  mizzou-missouri-state  ")
    assert result == "61ccd4d3-763f-4cc6-b85d-74b268e80a00"


def test_resolve_multiple_datasets(in_memory_engine, test_datasets):
    """Test resolving different datasets in sequence."""
    result1 = resolve_dataset_id(in_memory_engine, "test-dataset")
    assert result1 == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    result2 = resolve_dataset_id(in_memory_engine, "mizzou-missouri-state")
    assert result2 == "61ccd4d3-763f-4cc6-b85d-74b268e80a00"


def test_resolve_uuid_with_different_case(in_memory_engine, test_datasets):
    """Test that UUID resolution is case-insensitive."""
    # UUIDs can be uppercase or lowercase
    test_uuid_upper = "61CCD4D3-763F-4CC6-B85D-74B268E80A00"
    result = resolve_dataset_id(in_memory_engine, test_uuid_upper)
    # Result should match the original UUID (lowercase)
    assert result.lower() == "61ccd4d3-763f-4cc6-b85d-74b268e80a00".lower()


def test_resolve_invalid_uuid_format_tries_lookup(in_memory_engine, test_datasets):
    """Test that invalid UUID format triggers database lookup."""
    # This looks like a UUID but has invalid characters
    invalid_uuid = "not-a-real-uuid-format"
    with pytest.raises(ValueError, match="Dataset not found"):
        resolve_dataset_id(in_memory_engine, invalid_uuid)


def test_resolve_with_hyphens_in_slug(in_memory_engine, test_datasets):
    """Test resolution of dataset with hyphens in slug."""
    result = resolve_dataset_id(in_memory_engine, "test-dataset")
    assert result == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def test_resolve_prioritizes_slug_over_name(in_memory_engine):
    """Test that slug match is preferred over name match."""
    Session = sessionmaker(bind=in_memory_engine)
    session = Session()

    # Create a dataset where slug and name might be confused
    dataset = Dataset(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        slug="my-slug",
        label="My Label",
        name="my-slug",  # Name same as another dataset's slug
    )
    session.add(dataset)

    dataset2 = Dataset(
        id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        slug="other-slug",
        label="Other Label",
        name="Other Name",
    )
    session.add(dataset2)

    session.commit()
    session.close()

    # Should find by slug first
    result = resolve_dataset_id(in_memory_engine, "my-slug")
    assert result == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_resolve_case_sensitive_name(in_memory_engine, test_datasets):
    """Test that name resolution is case-sensitive."""
    # Exact match should work
    result = resolve_dataset_id(in_memory_engine, "Test Dataset Name")
    assert result == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    # Case mismatch should fail
    with pytest.raises(ValueError, match="Dataset not found"):
        resolve_dataset_id(in_memory_engine, "test dataset name")
