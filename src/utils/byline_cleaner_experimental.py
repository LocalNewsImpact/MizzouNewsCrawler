#!/usr/bin/env python3
"""
Experimental multi-strategy byline cleaner with confidence scoring.

This module implements a parallel approach to byline cleaning that:
1. Tries multiple extraction strategies simultaneously
2. Scores each result based on confidence and quality metrics
3. Returns the highest-scoring result

This can be tested alongside the current BylineCleaner to compare effectiveness.
"""

import logging
from typing import List, Dict, Optional, Union
from dataclasses import dataclass

# Import the existing cleaner for comparison
from .byline_cleaner import BylineCleaner

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result from a single extraction strategy."""
    authors: List[str]
    strategy_name: str
    confidence: float
    quality_score: float
    overall_score: float
    metadata: Dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ExperimentalBylineCleaner:
    """
    Multi-strategy byline cleaner with confidence scoring.

    This experimental cleaner tries multiple approaches in parallel
    and uses scoring to select the best result.
    """

    def __init__(self, enable_telemetry: bool = True):
        """Initialize the experimental cleaner."""
        # Use the existing cleaner as a base for shared functionality
        self.base_cleaner = BylineCleaner(enable_telemetry=enable_telemetry)

        # Strategy weights for final scoring
        self.strategy_weights = {
            'special_contributor': 1.0,
            'wire_service': 0.9,
            'standard_original': 0.8,
            'standard_source_removed': 0.7,
            'smart_parsing': 0.6,
            'fallback': 0.3
        }

    def clean_byline_multi_strategy(
        self,
        byline: str,
        source_name: Optional[str] = None,
        return_comparison: bool = False
    ) -> Union[List[str], Dict]:
        """
        Clean byline using multiple strategies and return the best result.

        Args:
            byline: Raw byline text
            source_name: Optional source/publication name
            return_comparison: If True, return detailed comparison of all strategies

        Returns:
            Best author list or comparison dict if return_comparison=True
        """
        if not byline or not byline.strip():
            return [] if not return_comparison else {
                'best_result': [],
                'strategy_used': 'empty_input',
                'all_results': [],
                'comparison_scores': {}
            }

        # Try all strategies
        strategies = [
            self._strategy_special_contributor,
            self._strategy_wire_service,
            self._strategy_standard_original,
            self._strategy_standard_source_removed,
            self._strategy_smart_parsing,
            self._strategy_fallback
        ]

        results = []
        for strategy in strategies:
            try:
                result = strategy(byline, source_name)
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"Strategy {strategy.__name__} failed: {e}")
                continue

        if not results:
            empty_result = ExtractionResult(
                authors=[],
                strategy_name='no_strategies_worked',
                confidence=0.0,
                quality_score=0.0,
                overall_score=0.0
            )
            results = [empty_result]

        # Find best result
        best_result = max(results, key=lambda x: x.overall_score)

        if return_comparison:
            return {
                'best_result': best_result.authors,
                'strategy_used': best_result.strategy_name,
                'confidence': best_result.confidence,
                'quality_score': best_result.quality_score,
                'overall_score': best_result.overall_score,
                'all_results': [
                    {
                        'authors': r.authors,
                        'strategy': r.strategy_name,
                        'confidence': r.confidence,
                        'quality': r.quality_score,
                        'overall': r.overall_score,
                        'metadata': r.metadata
                    }
                    for r in results
                ],
                'comparison_scores': {
                    r.strategy_name: r.overall_score for r in results
                }
            }

        return best_result.authors

    def _strategy_special_contributor(
        self,
        byline: str,
        source_name: Optional[str] = None
    ) -> Optional[ExtractionResult]:
        """Strategy: Extract special contributor patterns."""
        special_extracted = self.base_cleaner._extract_special_contributor(byline)

        if not special_extracted:
            return None

        # Clean the extracted name
        cleaned_name = self.base_cleaner._clean_author_name(special_extracted)
        if not cleaned_name:
            return None

        authors = [cleaned_name]

        # High confidence for special patterns since they're very specific
        confidence = 0.9
        quality_score = self._calculate_quality_score(authors)
        strategy_weight = self.strategy_weights['special_contributor']
        overall_score = (confidence * 0.6 + quality_score * 0.4) * strategy_weight

        return ExtractionResult(
            authors=authors,
            strategy_name='special_contributor',
            confidence=confidence,
            quality_score=quality_score,
            overall_score=overall_score,
            metadata={'extracted_raw': special_extracted}
        )

    def _strategy_wire_service(
        self,
        byline: str,
        source_name: Optional[str] = None
    ) -> Optional[ExtractionResult]:
        """Strategy: Handle wire service content."""
        if self.base_cleaner._is_wire_service(byline):
            # For wire services, we typically preserve the byline as-is
            authors = [byline.strip()]

            confidence = 0.8  # High confidence for wire service detection
            quality_score = 0.5  # Lower quality since it's not a personal name
            strategy_weight = self.strategy_weights['wire_service']
            overall_score = (confidence * 0.6 + quality_score * 0.4) * strategy_weight

            return ExtractionResult(
                authors=authors,
                strategy_name='wire_service',
                confidence=confidence,
                quality_score=quality_score,
                overall_score=overall_score,
                metadata={'wire_services': self.base_cleaner._detected_wire_services}
            )

        return None

    def _strategy_standard_original(
        self,
        byline: str,
        source_name: Optional[str] = None
    ) -> Optional[ExtractionResult]:
        """Strategy: Standard pattern matching on original text."""
        # Use the base cleaner's pattern matching on original text
        text = byline.lower().strip()
        extracted_text = None
        pattern_used = None

        for i, pattern in enumerate(self.base_cleaner.compiled_patterns[:4]):
            match = pattern.search(text)
            if match:
                if match.groups():
                    extracted_text = match.group(1).strip()
                else:
                    extracted_text = match.group(0).strip()
                pattern_used = f"pattern_{i}"
                break

        if not extracted_text:
            return None

        # Clean and extract authors
        cleaned_text = self.base_cleaner._remove_patterns(extracted_text)
        authors = self.base_cleaner._extract_authors(cleaned_text)

        if not authors:
            return None

        # Clean each author
        cleaned_authors = []
        for author in authors:
            cleaned = self.base_cleaner._clean_author_name(author)
            if cleaned:
                cleaned_authors.append(cleaned)

        if not cleaned_authors:
            return None

        # Calculate scores
        confidence = 0.7 if pattern_used != "no_pattern" else 0.4
        quality_score = self._calculate_quality_score(cleaned_authors)
        strategy_weight = self.strategy_weights['standard_original']
        overall_score = (confidence * 0.6 + quality_score * 0.4) * strategy_weight

        return ExtractionResult(
            authors=cleaned_authors,
            strategy_name='standard_original',
            confidence=confidence,
            quality_score=quality_score,
            overall_score=overall_score,
            metadata={'pattern_used': pattern_used, 'raw_extracted': extracted_text}
        )

    def _strategy_standard_source_removed(
        self,
        byline: str,
        source_name: Optional[str] = None
    ) -> Optional[ExtractionResult]:
        """Strategy: Standard pattern matching after source removal."""
        if not source_name:
            return None

        # Remove source name first
        cleaned_byline = self.base_cleaner._remove_source_name(byline, source_name)

        if not cleaned_byline or cleaned_byline == byline:
            return None  # No source removal happened

        # Apply standard processing to source-removed text
        text = cleaned_byline.lower().strip()
        extracted_text = None
        pattern_used = None

        for i, pattern in enumerate(self.base_cleaner.compiled_patterns[:4]):
            match = pattern.search(text)
            if match:
                if match.groups():
                    extracted_text = match.group(1).strip()
                else:
                    extracted_text = match.group(0).strip()
                pattern_used = f"pattern_{i}"
                break

        if not extracted_text:
            extracted_text = cleaned_byline.strip()
            pattern_used = "no_pattern"

        # Clean and extract authors
        cleaned_text = self.base_cleaner._remove_patterns(extracted_text)
        authors = self.base_cleaner._extract_authors(cleaned_text)

        if not authors:
            return None

        # Clean each author
        cleaned_authors = []
        for author in authors:
            cleaned = self.base_cleaner._clean_author_name(author)
            if cleaned:
                cleaned_authors.append(cleaned)

        if not cleaned_authors:
            return None

        # Calculate scores
        confidence = 0.6 if pattern_used != "no_pattern" else 0.3
        quality_score = self._calculate_quality_score(cleaned_authors)
        strategy_weight = self.strategy_weights['standard_source_removed']
        overall_score = (confidence * 0.6 + quality_score * 0.4) * strategy_weight

        return ExtractionResult(
            authors=cleaned_authors,
            strategy_name='standard_source_removed',
            confidence=confidence,
            quality_score=quality_score,
            overall_score=overall_score,
            metadata={
                'pattern_used': pattern_used,
                'source_removed': True,
                'cleaned_byline': cleaned_byline
            }
        )

    def _strategy_smart_parsing(
        self,
        byline: str,
        source_name: Optional[str] = None
    ) -> Optional[ExtractionResult]:
        """Strategy: Smart parsing with multiple separators and heuristics."""
        # Try different separators and parsing approaches
        possible_authors = []

        # Basic cleaning first
        cleaned = self.base_cleaner._basic_cleaning(byline)

        # Try different separators
        separators = [' and ', ', ', ' & ', ' with ', ' + ']
        for sep in separators:
            if sep in cleaned.lower():
                parts = cleaned.split(sep)
                for part in parts:
                    cleaned_part = self.base_cleaner._clean_author_name(part.strip())
                    if cleaned_part and len(cleaned_part.split()) >= 2:
                        possible_authors.append(cleaned_part)

        # If no separators worked, try the whole thing
        if not possible_authors:
            cleaned_whole = self.base_cleaner._clean_author_name(cleaned)
            if cleaned_whole and len(cleaned_whole.split()) >= 2:
                possible_authors.append(cleaned_whole)

        if not possible_authors:
            return None

        # Remove duplicates
        unique_authors = list(dict.fromkeys(possible_authors))

        # Calculate scores
        confidence = 0.5  # Lower confidence for smart parsing
        quality_score = self._calculate_quality_score(unique_authors)
        strategy_weight = self.strategy_weights['smart_parsing']
        overall_score = (confidence * 0.6 + quality_score * 0.4) * strategy_weight

        return ExtractionResult(
            authors=unique_authors,
            strategy_name='smart_parsing',
            confidence=confidence,
            quality_score=quality_score,
            overall_score=overall_score,
            metadata={'separators_found': [sep for sep in separators if sep in cleaned.lower()]}
        )

    def _strategy_fallback(
        self,
        byline: str,
        source_name: Optional[str] = None
    ) -> Optional[ExtractionResult]:
        """Strategy: Fallback - basic cleaning only."""
        cleaned = self.base_cleaner._basic_cleaning(byline)

        if not cleaned:
            return None

        # Try to clean as a single author name
        cleaned_name = self.base_cleaner._clean_author_name(cleaned)

        if not cleaned_name:
            return None

        authors = [cleaned_name]

        # Low confidence for fallback
        confidence = 0.2
        quality_score = self._calculate_quality_score(authors)
        strategy_weight = self.strategy_weights['fallback']
        overall_score = (confidence * 0.6 + quality_score * 0.4) * strategy_weight

        return ExtractionResult(
            authors=authors,
            strategy_name='fallback',
            confidence=confidence,
            quality_score=quality_score,
            overall_score=overall_score,
            metadata={'basic_cleaned': cleaned}
        )

    def _calculate_quality_score(self, authors: List[str]) -> float:
        """
        Calculate quality score for extracted authors.

        Higher scores for:
        - Multiple words (first + last name)
        - Proper capitalization
        - Reasonable length
        - No organizational terms
        """
        if not authors:
            return 0.0

        total_score = 0.0

        for author in authors:
            score = 0.0
            words = author.split()

            # Multiple words bonus (first + last name)
            if len(words) >= 2:
                score += 0.4
            elif len(words) == 1:
                score += 0.1  # Single names are less likely to be correct

            # Proper capitalization
            if author.istitle():
                score += 0.2

            # Reasonable length
            if 5 <= len(author) <= 30:
                score += 0.2

            # No organizational terms
            author_lower = author.lower()
            org_terms = ['news', 'press', 'media', 'staff', 'reporter', 'editor']
            if not any(term in author_lower for term in org_terms):
                score += 0.2

            total_score += score

        # Average score across all authors
        return min(total_score / len(authors), 1.0)


def compare_cleaning_methods(
    bylines: List[str],
    source_names: Optional[List[str]] = None
) -> Dict:
    """
    Compare current vs experimental cleaning methods on a list of bylines.

    Args:
        bylines: List of bylines to test
        source_names: Optional list of source names (same length as bylines)

    Returns:
        Comparison results with statistics
    """
    current_cleaner = BylineCleaner(enable_telemetry=False)
    experimental_cleaner = ExperimentalBylineCleaner(enable_telemetry=False)

    if source_names is None:
        source_names = [None] * len(bylines)

    results = []

    for i, byline in enumerate(bylines):
        source_name = source_names[i] if i < len(source_names) else None

        # Current method
        current_result = current_cleaner.clean_byline(byline, source_name=source_name)

        # Experimental method with detailed comparison
        experimental_result = experimental_cleaner.clean_byline_multi_strategy(
            byline, source_name=source_name, return_comparison=True
        )

        results.append({
            'byline': byline,
            'source_name': source_name,
            'current_result': current_result,
            'experimental_result': experimental_result['best_result'],
            'experimental_strategy': experimental_result['strategy_used'],
            'experimental_confidence': experimental_result['confidence'],
            'experimental_quality': experimental_result['quality_score'],
            'experimental_overall': experimental_result['overall_score'],
            'match': current_result == experimental_result['best_result'],
            'all_strategies': experimental_result['all_results']
        })

    # Calculate statistics
    total_tests = len(results)
    matches = sum(1 for r in results if r['match'])
    match_percentage = (matches / total_tests * 100) if total_tests > 0 else 0

    # Strategy usage statistics
    strategy_usage = {}
    for result in results:
        strategy = result['experimental_strategy']
        strategy_usage[strategy] = strategy_usage.get(strategy, 0) + 1

    return {
        'results': results,
        'statistics': {
            'total_tests': total_tests,
            'matches': matches,
            'match_percentage': match_percentage,
            'strategy_usage': strategy_usage
        }
    }
