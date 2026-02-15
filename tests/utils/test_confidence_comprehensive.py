"""Comprehensive tests for confidence score utilities."""

import pytest

from src.utils.confidence import normalize_score, score_to_label


class TestNormalizeScore:
    """Comprehensive tests for normalize_score function."""

    def test_perfect_score(self):
        """Score equal to max should return 1.0."""
        assert normalize_score(10, 10) == 1.0
        assert normalize_score(100, 100) == 1.0
        assert normalize_score(5, 5) == 1.0

    def test_zero_score(self):
        """Zero score should return 0.0."""
        assert normalize_score(0, 10) == 0.0
        assert normalize_score(0, 100) == 0.0
        assert normalize_score(0, 1) == 0.0

    def test_half_score(self):
        """Half of max should return 0.5."""
        assert normalize_score(5, 10) == 0.5
        assert normalize_score(50, 100) == 0.5
        assert normalize_score(1, 2) == 0.5

    def test_quarter_score(self):
        """Quarter of max should return 0.25."""
        assert normalize_score(25, 100) == 0.25
        assert normalize_score(1, 4) == 0.25

    def test_three_quarters_score(self):
        """Three quarters of max should return 0.75."""
        assert normalize_score(75, 100) == 0.75
        assert normalize_score(3, 4) == 0.75

    def test_negative_score_clamped_to_zero(self):
        """Negative scores should be clamped to 0.0."""
        assert normalize_score(-5, 10) == 0.0
        assert normalize_score(-100, 100) == 0.0
        assert normalize_score(-1, 5) == 0.0

    def test_score_exceeding_max_clamped_to_one(self):
        """Scores exceeding max should be clamped to 1.0."""
        assert normalize_score(15, 10) == 1.0
        assert normalize_score(200, 100) == 1.0
        assert normalize_score(100, 50) == 1.0

    def test_zero_max_score_returns_zero(self):
        """Max score of zero should return 0.0."""
        assert normalize_score(0, 0) == 0.0
        assert normalize_score(5, 0) == 0.0
        assert normalize_score(100, 0) == 0.0

    def test_negative_max_score_returns_zero(self):
        """Negative max score should return 0.0."""
        assert normalize_score(5, -10) == 0.0
        assert normalize_score(0, -5) == 0.0

    def test_floating_point_division(self):
        """Should handle floating point division correctly."""
        result = normalize_score(1, 3)
        assert 0.333 < result < 0.334
        
        result = normalize_score(2, 3)
        assert 0.666 < result < 0.667

    def test_large_numbers(self):
        """Should handle large numbers correctly."""
        assert normalize_score(1000000, 1000000) == 1.0
        assert normalize_score(500000, 1000000) == 0.5
        assert normalize_score(0, 1000000) == 0.0

    def test_small_fractional_scores(self):
        """Should handle small fractional scores."""
        result = normalize_score(1, 1000)
        assert result == 0.001

    def test_returns_float_type(self):
        """Should always return a float."""
        result = normalize_score(5, 10)
        assert isinstance(result, float)
        
        result = normalize_score(10, 10)
        assert isinstance(result, float)

    def test_boundary_values(self):
        """Test at exact boundary conditions."""
        # Exactly at max
        assert normalize_score(10, 10) == 1.0
        # Just below max
        assert normalize_score(9, 10) == 0.9
        # Just above zero
        assert normalize_score(1, 10) == 0.1

    def test_precision_preservation(self):
        """Should preserve reasonable precision."""
        result = normalize_score(33, 100)
        assert result == 0.33
        
        result = normalize_score(67, 100)
        assert result == 0.67


class TestScoreToLabel:
    """Comprehensive tests for score_to_label function."""

    def test_high_threshold_exact_boundary(self):
        """Score of exactly 4 should be 'high'."""
        assert score_to_label(4) == "high"

    def test_high_threshold_above(self):
        """Scores above 4 should be 'high'."""
        assert score_to_label(5) == "high"
        assert score_to_label(10) == "high"
        assert score_to_label(100) == "high"
        assert score_to_label(1000) == "high"

    def test_medium_threshold_exact_boundary(self):
        """Score of exactly 2 should be 'medium'."""
        assert score_to_label(2) == "medium"

    def test_medium_threshold_range(self):
        """Scores 2-3 should be 'medium'."""
        assert score_to_label(2) == "medium"
        assert score_to_label(3) == "medium"

    def test_low_threshold_below_medium(self):
        """Scores below 2 should be 'low'."""
        assert score_to_label(0) == "low"
        assert score_to_label(1) == "low"

    def test_negative_scores_are_low(self):
        """Negative scores should be 'low'."""
        assert score_to_label(-1) == "low"
        assert score_to_label(-10) == "low"
        assert score_to_label(-100) == "low"

    def test_zero_is_low(self):
        """Zero score should be 'low'."""
        assert score_to_label(0) == "low"

    def test_boundary_between_low_and_medium(self):
        """Just below medium threshold should be low."""
        assert score_to_label(1) == "low"
        # At threshold should be medium
        assert score_to_label(2) == "medium"

    def test_boundary_between_medium_and_high(self):
        """Just below high threshold should be medium."""
        assert score_to_label(3) == "medium"
        # At threshold should be high
        assert score_to_label(4) == "high"

    def test_large_scores_are_high(self):
        """Very large scores should be 'high'."""
        assert score_to_label(1000) == "high"
        assert score_to_label(10000) == "high"

    def test_returns_string_type(self):
        """Should always return a string."""
        result = score_to_label(5)
        assert isinstance(result, str)
        
        result = score_to_label(0)
        assert isinstance(result, str)

    def test_returns_valid_labels_only(self):
        """Should only return 'high', 'medium', or 'low'."""
        valid_labels = {"high", "medium", "low"}
        
        for score in range(-10, 20):
            result = score_to_label(score)
            assert result in valid_labels

    def test_consistent_mapping(self):
        """Same score should always return same label."""
        assert score_to_label(5) == score_to_label(5)
        assert score_to_label(3) == score_to_label(3)
        assert score_to_label(1) == score_to_label(1)

    def test_all_three_labels_reachable(self):
        """All three labels should be reachable."""
        labels_seen = set()
        labels_seen.add(score_to_label(0))   # low
        labels_seen.add(score_to_label(2))   # medium
        labels_seen.add(score_to_label(4))   # high
        
        assert labels_seen == {"low", "medium", "high"}


class TestIntegration:
    """Integration tests using both functions together."""

    def test_normalize_then_interpret(self):
        """Normalized scores can guide label interpretation."""
        # High confidence
        normalized = normalize_score(90, 100)
        assert normalized >= 0.8
        
        # If raw score was high
        label = score_to_label(10)
        assert label == "high"

    def test_workflow_low_confidence(self):
        """Low raw score should normalize low and label as low."""
        raw_score = 1
        normalized = normalize_score(raw_score, 10)
        assert normalized == 0.1
        
        label = score_to_label(raw_score)
        assert label == "low"

    def test_workflow_medium_confidence(self):
        """Medium raw score should normalize appropriately."""
        raw_score = 3
        normalized = normalize_score(raw_score, 10)
        assert normalized == 0.3
        
        label = score_to_label(raw_score)
        assert label == "medium"

    def test_workflow_high_confidence(self):
        """High raw score should normalize high."""
        raw_score = 8
        normalized = normalize_score(raw_score, 10)
        assert normalized == 0.8
        
        label = score_to_label(raw_score)
        assert label == "high"

    def test_edge_case_max_score_zero(self):
        """When max_score is 0, normalized is 0 but label can vary."""
        normalized = normalize_score(5, 0)
        assert normalized == 0.0
        
        # But label is based on raw score
        label = score_to_label(5)
        assert label == "high"

    def test_consistency_across_scales(self):
        """Different scales should give similar interpretations."""
        # 50% on scale of 10
        norm1 = normalize_score(5, 10)
        # 50% on scale of 100
        norm2 = normalize_score(50, 100)
        
        assert norm1 == norm2 == 0.5

    def test_score_interpretation_independent_of_scale(self):
        """Labels are based on raw scores, not normalized."""
        # Raw score of 5 is always high
        assert score_to_label(5) == "high"
        
        # Even if normalized to 0.5
        assert normalize_score(5, 10) == 0.5
