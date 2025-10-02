# ruff: noqa: E501

"""
Content cleaning utilities for removing boilerplate text from articles.

This module provides algorithms to detect and remove repeated text segments
that appear across multiple articles from the same domain, such as
subscription prompts, navigation elements, and other boilerplate content.
"""

import re
import hashlib
import logging
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

try:
    from .content_cleaning_ml import (
        ContentCleaningMLFeatureExtractor,
        MLTrainingExample
    )
except ImportError:
    # Handle case where ML module is not available
    ContentCleaningMLFeatureExtractor = None
    MLTrainingExample = None

logger = logging.getLogger(__name__)


@dataclass
class BoilerplateMatch:
    """Represents a potential boilerplate text match."""
    text_segment: str
    segment_hash: str
    domain: str
    article_count: int
    article_ids: List[str]
    confidence_score: float
    segment_length: int
    position_stats: Dict[str, float]  # start, end, middle percentages


@dataclass
class ContentCleaningTelemetry:
    """Telemetry data for content cleaning operations."""
    operation_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    total_articles_checked: int
    domains_processed: int
    boilerplate_patterns_found: int
    articles_modified: int
    total_characters_removed: int
    decisions: List[Dict]  # Track each removal decision

    def to_dict(self) -> Dict:
        """Convert telemetry to dictionary for logging."""
        return {
            "operation_id": self.operation_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_articles_checked": self.total_articles_checked,
            "domains_processed": self.domains_processed,
            "boilerplate_patterns_found": self.boilerplate_patterns_found,
            "articles_modified": self.articles_modified,
            "total_characters_removed": self.total_characters_removed,
            "decisions_count": len(
                self.decisions)}


class ContentCleaner:
    """Identifies and removes repeated boilerplate content from articles."""

    def __init__(self,
                 min_segment_length: int = 50,
                 min_occurrence_count: int = 3,
                 min_confidence_threshold: float = 0.7):
        """
        Initialize content cleaner.

        Args:
            min_segment_length: Minimum length of text segments to consider
            min_occurrence_count: Minimum times segment must appear to be considered boilerplate
            min_confidence_threshold: Minimum confidence score to remove content
        """
        self.min_segment_length = min_segment_length
        self.min_occurrence_count = min_occurrence_count
        self.min_confidence_threshold = min_confidence_threshold
        self.telemetry = None

    def start_telemetry(self, operation_id: str) -> ContentCleaningTelemetry:
        """Start telemetry tracking for this operation."""
        self.telemetry = ContentCleaningTelemetry(
            operation_id=operation_id,
            started_at=datetime.utcnow(),
            finished_at=None,
            total_articles_checked=0,
            domains_processed=0,
            boilerplate_patterns_found=0,
            articles_modified=0,
            total_characters_removed=0,
            decisions=[]
        )
        logger.info(f"Started content cleaning operation: {operation_id}")
        return self.telemetry

    def finish_telemetry(self):
        """Finish telemetry tracking."""
        if self.telemetry:
            self.telemetry.finished_at = datetime.utcnow()
            logger.info(
                f"Finished content cleaning operation: {
                    self.telemetry.operation_id}")
            logger.info(f"Telemetry: {self.telemetry.to_dict()}")

    def extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"

    def generate_text_segments(
            self, content: str, min_length: int = None) -> List[Tuple[str, int, int]]:
        """
        Generate overlapping text segments from content.

        Returns:
            List of (segment_text, start_pos, end_pos) tuples
        """
        if min_length is None:
            min_length = self.min_segment_length

        segments = []

        # Split by sentences to get meaningful segments
        sentences = re.split(r'[.!?]+', content)

        # Create segments of different sizes
        for i in range(len(sentences)):
            for window_size in [1, 2, 3, 4, 5]:  # 1-5 sentence windows
                if i + window_size <= len(sentences):
                    segment_sentences = sentences[i:i + window_size]
                    segment_text = '. '.join(
                        s.strip() for s in segment_sentences if s.strip())

                    if len(segment_text) >= min_length:
                        # Find position in original content
                        start_pos = content.find(segment_text)
                        if start_pos != -1:
                            end_pos = start_pos + len(segment_text)
                            segments.append((segment_text, start_pos, end_pos))

        return segments

    def calculate_segment_hash(self, text: str) -> str:
        """Calculate normalized hash for text segment."""
        # Normalize text: lowercase, remove extra whitespace, punctuation
        # normalization
        normalized = re.sub(r'\s+', ' ', text.lower().strip())
        normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def analyze_domain_content(
            self,
            articles: List[Dict]) -> List[BoilerplateMatch]:
        """
        Analyze articles from a single domain to find repeated content.

        Args:
            articles: List of article dictionaries with 'id', 'content', 'url'

        Returns:
            List of potential boilerplate matches
        """
        if len(articles) < self.min_occurrence_count:
            return []

        domain = self.extract_domain(
            articles[0]['url']) if articles else "unknown"
        logger.debug(
            f"Analyzing {
                len(articles)} articles from domain: {domain}")

        # Track segments across all articles
        # hash -> [(article_id, text, start_pos, end_pos)]
        segment_occurrences = defaultdict(list)

        for article in articles:
            content = article.get('content', '') or ''
            if not content:
                continue

            segments = self.generate_text_segments(content)

            for segment_text, start_pos, end_pos in segments:
                segment_hash = self.calculate_segment_hash(segment_text)
                segment_occurrences[segment_hash].append(
                    (article['id'], segment_text, start_pos, end_pos, len(content)))

        # Identify potential boilerplate
        boilerplate_matches = []

        for segment_hash, occurrences in segment_occurrences.items():
            if len(occurrences) >= self.min_occurrence_count:
                # Calculate statistics
                article_ids = [occ[0] for occ in occurrences]
                text_samples = [occ[1] for occ in occurrences]
                positions = [(occ[2], occ[3], occ[4])
                             for occ in occurrences]  # start, end, content_length

                # Use the longest version of the text
                representative_text = max(text_samples, key=len)

                # Calculate position statistics
                start_percentages = [
                    start / content_len for start,
                    end,
                    content_len in positions if content_len > 0]
                end_percentages = [
                    end / content_len for start,
                    end,
                    content_len in positions if content_len > 0]

                position_stats = {
                    "avg_start_percentage": sum(start_percentages) /
                    len(start_percentages) if start_percentages else 0,
                    "avg_end_percentage": sum(end_percentages) /
                    len(end_percentages) if end_percentages else 0,
                    "start_std": self._calculate_std(start_percentages),
                    "end_std": self._calculate_std(end_percentages)}

                # Calculate confidence score
                confidence = self._calculate_confidence_score(
                    len(occurrences), len(articles), len(representative_text), position_stats)

                match = BoilerplateMatch(
                    text_segment=representative_text,
                    segment_hash=segment_hash,
                    domain=domain,
                    article_count=len(occurrences),
                    article_ids=article_ids,
                    confidence_score=confidence,
                    segment_length=len(representative_text),
                    position_stats=position_stats
                )

                boilerplate_matches.append(match)

                # Log the match
                logger.debug(
                    f"Found potential boilerplate in {domain}: " f"{
                        len(occurrences)} occurrences, confidence={
                        confidence:.3f}, " f"length={
                        len(representative_text)}")

        # Sort by confidence score (highest first)
        boilerplate_matches.sort(
            key=lambda x: x.confidence_score,
            reverse=True)

        return boilerplate_matches

    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5

    def _calculate_confidence_score(
            self,
            occurrences: int,
            total_articles: int,
            text_length: int,
            position_stats: Dict) -> float:
        """
        Calculate confidence score for boilerplate detection.

        Higher scores indicate higher likelihood of being boilerplate.
        """
        # Frequency factor (more occurrences = higher confidence)
        frequency_factor = min(occurrences / total_articles, 1.0)

        # Length factor (moderate length text is more likely to be boilerplate)
        # Very short text might be too generic, very long text might be actual
        # content
        if text_length < 100:
            length_factor = 0.5  # Too short
        elif text_length > 1000:
            length_factor = 0.3  # Too long, might be actual content
        else:
            length_factor = 1.0  # Good length for boilerplate

        # Position consistency factor (boilerplate often appears in consistent
        # positions)
        position_consistency = 1.0 - \
            (position_stats.get("start_std", 1.0) + position_stats.get("end_std", 1.0)) / 2
        position_consistency = max(0.0, position_consistency)

        # Position location factor (content at very beginning or end is more
        # likely boilerplate)
        avg_start = position_stats.get("avg_start_percentage", 0.5)
        avg_end = position_stats.get("avg_end_percentage", 0.5)

        if avg_start < 0.1 or avg_end > 0.9:  # Beginning or end of article
            position_location_factor = 1.2
        elif avg_start > 0.8 and avg_end < 1.0:  # Near the end
            position_location_factor = 1.1
        else:
            position_location_factor = 0.8

        # Combine factors
        confidence = (frequency_factor * 0.4 +
                      length_factor * 0.2 +
                      position_consistency * 0.2 +
                      position_location_factor * 0.2)

        return min(confidence, 1.0)

    def should_remove_segment(
            self, match: BoilerplateMatch) -> Tuple[bool, str]:
        """
        Decide whether a segment should be removed.

        Returns:
            Tuple of (should_remove, reason)
        """
        # Check confidence threshold
        if match.confidence_score < self.min_confidence_threshold:
            return False, f"Low confidence: {
                match.confidence_score:.3f} < {
                self.min_confidence_threshold}"

        # Additional safety checks
        if match.segment_length > 2000:
            return False, f"Segment too long: {
                match.segment_length} characters"

        if match.article_count < self.min_occurrence_count:
            return False, f"Insufficient occurrences: {
                match.article_count} < {
                self.min_occurrence_count}"

        # Check for common boilerplate patterns
        text_lower = match.text_segment.lower()

        # Positive indicators (more likely to be boilerplate)
        boilerplate_indicators = [
            "subscribe", "paywall", "premium", "login", "sign up",
            "advertisement", "sponsored", "copyright", "all rights reserved",
            "terms of service", "privacy policy", "cookie", "newsletter",
            "follow us", "social media", "share this", "related articles"
        ]

        indicator_count = sum(
            1 for indicator in boilerplate_indicators if indicator in text_lower)

        if indicator_count >= 2:
            return True, f"High boilerplate indicators: {indicator_count} matches"

        if match.confidence_score > 0.85:
            return True, f"Very high confidence: {match.confidence_score:.3f}"

        return True, f"Passed threshold: confidence={
            match.confidence_score:.3f}"

    def log_decision(
            self,
            match: BoilerplateMatch,
            should_remove: bool,
            reason: str):
        """Log a removal decision for telemetry."""
        if self.telemetry:
            decision = {
                "segment_hash": match.segment_hash,
                "domain": match.domain,
                "confidence_score": match.confidence_score,
                "article_count": match.article_count,
                "segment_length": match.segment_length,
                "should_remove": should_remove,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
                "text_preview": match.text_segment[:100] + "..." if len(match.text_segment) > 100 else match.text_segment
            }
            self.telemetry.decisions.append(decision)

        logger.info(f"Decision for {match.domain} segment (hash={match.segment_hash[:8]}): "
                    f"{'REMOVE' if should_remove else 'KEEP'} - {reason}")

    def extract_ml_features(self, match: BoilerplateMatch,
                            total_articles_in_domain: int) -> Dict:
        """
        Extract features for machine learning model training.

        Returns dictionary of features that can be used to train
        a classifier to predict whether content should be removed.
        """
        import numpy as np

        text = match.text_segment.lower()

        # Basic statistical features
        features = {
            # Occurrence features
            "occurrence_count": match.article_count,
            "occurrence_ratio": match.article_count / total_articles_in_domain,
            "domain_prevalence": match.article_count / total_articles_in_domain,

            # Text length features
            "segment_length": match.segment_length,
            "log_segment_length": np.log(match.segment_length + 1),
            "length_category": self._categorize_length(match.segment_length),

            # Position features
            "avg_start_position": match.position_stats.get("avg_start_percentage", 0),
            "avg_end_position": match.position_stats.get("avg_end_percentage", 0),
            "position_consistency": 1.0 - (match.position_stats.get("start_std", 1.0) +
                                           match.position_stats.get("end_std", 1.0)) / 2,
            "is_at_beginning": match.position_stats.get("avg_start_percentage", 0) < 0.1,
            "is_at_end": match.position_stats.get("avg_end_percentage", 0) > 0.9,

            # Content pattern features
            "has_subscription_terms": any(term in text for term in [
                "subscribe", "subscription", "premium", "paywall", "unlock"
            ]),
            "has_social_terms": any(term in text for term in [
                "follow", "like", "share", "twitter", "facebook", "instagram"
            ]),
            "has_legal_terms": any(term in text for term in [
                "copyright", "rights reserved", "terms", "privacy", "policy"
            ]),
            "has_advertisement_terms": any(term in text for term in [
                "advertisement", "sponsored", "ads", "promotion"
            ]),
            "has_navigation_terms": any(term in text for term in [
                "menu", "navigation", "home", "contact", "about"
            ]),

            # Linguistic features
            "sentence_count": len(re.split(r'[.!?]+', text)),
            "word_count": len(text.split()),
            "avg_word_length": np.mean([len(word) for word in text.split()]) if text.split() else 0,
            "punctuation_ratio": len([c for c in text if not c.isalnum() and not c.isspace()]) / len(text) if text else 0,
            "uppercase_ratio": len([c for c in text if c.isupper()]) / len(text) if text else 0,
            "digit_ratio": len([c for c in text if c.isdigit()]) / len(text) if text else 0,

            # Domain-specific features
            "domain": match.domain,
            "domain_category": self._categorize_domain(match.domain),

            # Repetition features
            "confidence_score": match.confidence_score,
        }

        # Add TF-IDF-like features for common boilerplate terms
        boilerplate_terms = [
            "subscribe",
            "newsletter",
            "premium",
            "login",
            "register",
            "sign up",
            "advertisement",
            "sponsored",
            "copyright",
            "privacy",
            "cookie",
            "follow us",
            "share",
            "like",
            "social",
            "related articles"]

        for term in boilerplate_terms:
            features[f"contains_{term.replace(' ', '_')}"] = term in text
            features[f"count_{term.replace(' ', '_')}"] = text.count(term)

        return features

    def _categorize_length(self, length: int) -> str:
        """Categorize text length into bins."""
        if length < 50:
            return "very_short"
        elif length < 150:
            return "short"
        elif length < 300:
            return "medium"
        elif length < 500:
            return "long"
        else:
            return "very_long"

    def _categorize_domain(self, domain: str) -> str:
        """Categorize domain type based on common patterns."""
        domain_lower = domain.lower()

        if any(
            term in domain_lower for term in [
                "news",
                "times",
                "post",
                "herald",
                "gazette"]):
            return "news"
        elif any(term in domain_lower for term in ["blog", "wordpress", "medium"]):
            return "blog"
        elif any(term in domain_lower for term in [".gov", "government"]):
            return "government"
        elif any(term in domain_lower for term in [".edu", "university", "college"]):
            return "education"
        else:
            return "other"
