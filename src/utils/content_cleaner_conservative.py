"""
Conservative content cleaner that only removes very high-confidence boilerplate.

This version adds additional safety checks to avoid removing legitimate content
that might look like boilerplate (like related article headlines).
"""

from .content_cleaner_improved import ImprovedContentCleaner
import re
from typing import List, Tuple, Optional


class ConservativeContentCleaner(ImprovedContentCleaner):
    """
    More conservative version of content cleaner that adds additional
    safety checks to avoid removing legitimate journalistic content.
    """

    def __init__(self, db_path: str, confidence_threshold: float = 0.8):
        # Use higher default confidence threshold
        super().__init__(db_path, confidence_threshold)

    def _calculate_improved_confidence(self, text: str, occurrence_count: int,
                                     total_articles: int,
                                     positions: List[Tuple[float, float]],
                                     pattern_type: str) -> float:
        """Calculate confidence with additional conservative checks."""

        # Start with base confidence
        confidence = super()._calculate_improved_confidence(
            text, occurrence_count, total_articles, positions, pattern_type
        )

        # Apply conservative penalties
        confidence = self._apply_conservative_penalties(
            text, confidence, pattern_type)

        return confidence

    def _apply_conservative_penalties(self, text: str, base_confidence: float,
                                    pattern_type: str) -> float:
        """Apply penalties to reduce confidence for potentially legitimate content."""
        confidence = base_confidence
        text_lower = text.lower()

        # PENALTY 1: Contains journalism-related terms
        journalism_terms = [
            "county", "city", "school", "high school", "community", "local",
            "wins", "defeats", "scores", "game", "match", "tournament",
            "meeting", "council", "board", "election", "vote", "candidate",
            "injury", "accident", "fire", "police", "arrest", "court",
            "business", "company", "economic", "development", "project"
        ]

        journalism_count = sum(1 for term in journalism_terms
                             if term in text_lower)
        if journalism_count >= 2:
            confidence *= 0.6  # Significant penalty

        # PENALTY 2: Contains proper nouns (likely places/people/organizations)
        proper_noun_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b'
        proper_nouns = re.findall(proper_noun_pattern, text)
        if len(proper_nouns) >= 3:
            confidence *= 0.7

        # PENALTY 3: Contains news-style language patterns
        news_patterns = [
            r'\b\w+ wins? \w+',  # "Team wins game"
            r'\b\w+ defeats? \w+',  # "Team defeats opponent"
            r'\b\w+ places? \w+',  # "Runner places third"
            r'\binjury\b',
            r'\bsuffered\b',
            r'\bstrike[s]? in\b',
            r'\bcross country\b',
            r'\binvitational\b'
        ]

        news_pattern_matches = sum(1 for pattern in news_patterns
                                 if re.search(pattern, text_lower))
        if news_pattern_matches >= 2:
            confidence *= 0.5  # Strong penalty

        # PENALTY 4: Text structure suggests headlines/teasers
        sentences = re.split(r'[.!?]+', text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        # If multiple short sentences without periods (headline style)
        if len(sentences) >= 2:
            avg_length = sum(len(s) for s in sentences) / len(sentences)
            if avg_length < 80:  # Short sentence average
                confidence *= 0.6

        # BONUS: Strong boilerplate indicators
        strong_boilerplate_terms = [
            "subscribe", "subscription", "account", "login", "password",
            "click here", "contact us", "privacy policy", "terms of service",
            "newsletter", "e-edition", "digital subscriber"
        ]

        strong_boilerplate_count = sum(1 for term in strong_boilerplate_terms
                                     if term in text_lower)
        if strong_boilerplate_count >= 2:
            confidence = min(confidence * 1.2, 1.0)  # Boost confidence

        # PENALTY 5: Contains specific problematic patterns from hannibal.net
        problematic_patterns = [
            r'stocks market data by tradingview',
            r'has big day at the plate',
            r'cross country place',
            r'strikes in the late innings'
        ]

        for pattern in problematic_patterns:
            if re.search(pattern, text_lower):
                confidence *= 0.3  # Heavy penalty
                break

        return confidence

    def _should_skip_segment(self, text: str, pattern_type: str) -> bool:
        """Additional check to skip segments that are likely legitimate content."""
        text_lower = text.lower()

        # Skip if contains sports scores or game results
        sports_patterns = [
            r'\d+\s*-\s*\d+',  # Score patterns like "21-14"
            r'\bwins?\s+\d+\s*-\s*\d+\b',
            r'\bdefeats?\s+\w+\s+\d+\s*-\s*\d+\b'
        ]

        for pattern in sports_patterns:
            if re.search(pattern, text):
                return True

        # Skip if contains multiple location names
        # Simple heuristic: multiple capitalized words
        words = text.split()
        capitalized_words = [
            w for w in words if w and w[0].isupper() and w.isalpha()]
        if len(capitalized_words) >= 4:
            return True

        # Skip if looks like a news headline structure
        if (len(text) < 200 and not any(term in text_lower for term in [
            "subscribe", "login", "contact", "privacy"])):
            # If it's short and doesn't contain clear boilerplate terms, be
            # very careful
            journalism_terms = [
                "county",
                "school",
                "community",
                "wins",
                "defeats",
                "injury"]
            if sum(1 for term in journalism_terms if term in text_lower) >= 1:
                return True

        return False

    def clean_content(self, content: str, domain: str,
                     article_id: Optional[str] = None,
                     dry_run: bool = True) -> Tuple[str, any]:
        """Clean content with conservative approach."""

        # Get the base results
        cleaned_content, telemetry = super().clean_content(
            content, domain, article_id, dry_run
        )

        # Apply additional filtering to removed segments
        if not dry_run and telemetry.segments_removed > 0:
            # For non-dry runs, we need to be extra careful
            # Re-evaluate each segment with our conservative checks
            conservative_segments = []

            for segment in telemetry.removed_segments:
                segment_text = segment.get('text', '')
                pattern_type = segment.get('pattern_type', 'unknown')

                if not self._should_skip_segment(segment_text, pattern_type):
                    conservative_segments.append(segment)

            # Update telemetry
            telemetry.removed_segments = conservative_segments
            telemetry.segments_removed = len(conservative_segments)

        return cleaned_content, telemetry


def create_conservative_cleaner(
        db_path: str = 'data/mitzou.db') -> ConservativeContentCleaner:
    """Factory function to create a conservative content cleaner."""
    return ConservativeContentCleaner(
        db_path=db_path, confidence_threshold=0.85)
