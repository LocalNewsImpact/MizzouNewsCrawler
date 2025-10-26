"""
Machine Learning feature extraction for content cleaning.

This module provides tools to extract features from content segments
for training ML models to predict boilerplate content.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MLTrainingExample:
    """A training example for the ML model."""

    features: dict[str, Any]
    label: bool  # True if should be removed, False if should be kept
    segment_hash: str
    domain: str
    human_decision: bool  # Whether this was a human or algorithmic decision
    confidence: float  # Confidence in the decision
    timestamp: str


class ContentCleaningMLFeatureExtractor:
    """Extract ML features from content segments for boilerplate detection."""

    def __init__(self):
        """Initialize the feature extractor."""
        self.boilerplate_terms = [
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
            "related articles",
            "terms of service",
            "privacy policy",
            "all rights reserved",
        ]

        self.navigation_terms = [
            "menu",
            "navigation",
            "home",
            "contact",
            "about",
            "sitemap",
        ]

        self.subscription_terms = [
            "paywall",
            "unlock",
            "subscription",
            "member",
            "premium content",
        ]

    def extract_features(
        self,
        segment_text: str,
        segment_hash: str,
        domain: str,
        occurrence_count: int,
        total_articles_in_domain: int,
        position_stats: dict,
        confidence_score: float,
    ) -> dict:
        """
        Extract comprehensive features for ML model training.

        Args:
            segment_text: The text segment to analyze
            segment_hash: Hash of the segment
            domain: Domain where segment appears
            occurrence_count: Number of times segment appears
            total_articles_in_domain: Total articles in the domain
            position_stats: Statistics about segment position
            confidence_score: Current rule-based confidence score

        Returns:
            Dictionary of features for ML training
        """
        text = segment_text.lower()

        # Basic statistical features
        features = {
            # Occurrence features
            "occurrence_count": occurrence_count,
            "occurrence_ratio": occurrence_count / max(total_articles_in_domain, 1),
            "log_occurrence_count": np.log(occurrence_count + 1),
            # Text length features
            "segment_length": len(segment_text),
            "log_segment_length": np.log(len(segment_text) + 1),
            "word_count": len(segment_text.split()),
            "sentence_count": len(re.split(r"[.!?]+", segment_text)),
            "avg_word_length": (
                np.mean([len(w) for w in segment_text.split()])
                if segment_text.split()
                else 0
            ),
            # Position features
            "avg_start_position": position_stats.get("avg_start_percentage", 0),
            "avg_end_position": position_stats.get("avg_end_percentage", 0),
            "start_std": position_stats.get("start_std", 0),
            "end_std": position_stats.get("end_std", 0),
            "position_consistency": 1.0
            - (
                position_stats.get("start_std", 1.0)
                + position_stats.get("end_std", 1.0)
            )
            / 2,
            # Binary position features
            "is_at_very_beginning": position_stats.get("avg_start_percentage", 0)
            < 0.05,
            "is_at_beginning": position_stats.get("avg_start_percentage", 0) < 0.15,
            "is_at_end": position_stats.get("avg_end_percentage", 0) > 0.85,
            "is_at_very_end": position_stats.get("avg_end_percentage", 0) > 0.95,
            "is_in_middle": (0.2 < position_stats.get("avg_start_percentage", 0) < 0.8),
            # Character composition features
            "punctuation_ratio": self._calculate_char_ratio(
                text, lambda c: not c.isalnum() and not c.isspace()
            ),
            "uppercase_ratio": self._calculate_char_ratio(segment_text, str.isupper),
            "digit_ratio": self._calculate_char_ratio(text, str.isdigit),
            "whitespace_ratio": self._calculate_char_ratio(text, str.isspace),
            # Rule-based score as feature
            "rule_based_confidence": confidence_score,
            # Domain features
            "domain_category": self._categorize_domain(domain),
            "domain_length": len(domain),
        }

        # Add categorical features as one-hot encoded
        length_category = self._categorize_length(len(segment_text))
        for category in ["very_short", "short", "medium", "long", "very_long"]:
            features[f"length_is_{category}"] = length_category == category

        # Add domain category one-hot encoding
        domain_category = self._categorize_domain(domain)
        for category in ["news", "blog", "government", "education", "other"]:
            features[f"domain_is_{category}"] = domain_category == category

        # Add pattern matching features
        features.update(self._extract_pattern_features(text))

        # Add linguistic features
        features.update(self._extract_linguistic_features(text))

        # Add structural features
        features.update(self._extract_structural_features(segment_text))

        return features

    def _calculate_char_ratio(self, text: str, condition_func) -> float:
        """Calculate ratio of characters meeting condition."""
        if not text:
            return 0.0
        return len([c for c in text if condition_func(c)]) / len(text)

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
            term in domain_lower
            for term in ["news", "times", "post", "herald", "gazette"]
        ):
            return "news"
        elif any(term in domain_lower for term in ["blog", "wordpress", "medium"]):
            return "blog"
        elif any(term in domain_lower for term in [".gov", "government"]):
            return "government"
        elif any(term in domain_lower for term in [".edu", "university", "college"]):
            return "education"
        else:
            return "other"

    def _extract_pattern_features(self, text: str) -> dict[str, Any]:
        """Extract pattern-based features."""
        features: dict[str, Any] = {}

        # Boilerplate term counts and presence
        boilerplate_count = sum(1 for term in self.boilerplate_terms if term in text)
        features["boilerplate_term_count"] = boilerplate_count
        features["has_boilerplate_terms"] = boilerplate_count > 0
        features["boilerplate_term_density"] = boilerplate_count / max(
            len(text.split()), 1
        )

        # Specific pattern categories
        features["has_subscription_terms"] = any(
            term in text for term in self.subscription_terms
        )
        features["has_navigation_terms"] = any(
            term in text for term in self.navigation_terms
        )

        # Email and URL patterns
        features["has_email"] = bool(
            re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text)
        )
        features["has_url"] = bool(
            re.search(
                r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
                text,
            )
        )
        features["has_phone"] = bool(
            re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
        )

        # Copyright and legal patterns
        features["has_copyright"] = "copyright" in text or "©" in text
        features["has_rights_reserved"] = "rights reserved" in text
        features["has_legal_language"] = any(
            term in text for term in ["terms", "policy", "legal", "disclaimer"]
        )

        return features

    def _extract_linguistic_features(self, text: str) -> dict[str, Any]:
        """Extract linguistic features from text."""
        words = text.split()
        sentences = re.split(r"[.!?]+", text)

        features: dict[str, Any] = {}

        if words:
            # Word-level features
            features["avg_word_length"] = np.mean([len(word) for word in words])
            features["max_word_length"] = max(len(word) for word in words)
            features["short_word_ratio"] = len([w for w in words if len(w) <= 3]) / len(
                words
            )
            features["long_word_ratio"] = len([w for w in words if len(w) >= 8]) / len(
                words
            )

            # Common word patterns
            features["has_common_stopwords"] = any(
                word in text
                for word in ["the", "and", "or", "but", "in", "on", "at", "to", "for"]
            )
            features["has_imperatives"] = any(
                word in text
                for word in ["click", "visit", "follow", "subscribe", "join", "sign"]
            )

        if sentences:
            # Sentence-level features
            sentence_lengths = [len(s.strip()) for s in sentences if s.strip()]
            if sentence_lengths:
                features["avg_sentence_length"] = np.mean(sentence_lengths)
                features["sentence_length_std"] = np.std(sentence_lengths)

        # Repetition features
        features["repeated_words"] = len(words) - len(set(words)) if words else 0
        features["repetition_ratio"] = features["repeated_words"] / max(len(words), 1)

        return features

    def _extract_structural_features(self, text: str) -> dict[str, Any]:
        """Extract structural features from text."""
        features: dict[str, Any] = {}

        # HTML/markup patterns (in case some made it through)
        features["has_html_tags"] = bool(re.search(r"<[^>]+>", text))
        features["has_brackets"] = "[" in text or "]" in text
        features["has_parentheses"] = "(" in text or ")" in text

        # List-like structures
        features["has_bullet_points"] = bool(
            re.search(r"^\s*[-•*]\s+", text, re.MULTILINE)
        )
        features["has_numbered_list"] = bool(
            re.search(r"^\s*\d+\.\s+", text, re.MULTILINE)
        )

        # Formatting indicators
        features["has_all_caps_words"] = bool(re.search(r"\b[A-Z]{3,}\b", text))
        features["has_excessive_punctuation"] = bool(re.search(r"[!?]{2,}", text))

        # Line break patterns
        lines = text.split("\n")
        features["line_count"] = len(lines)
        features["avg_line_length"] = (
            np.mean([len(line) for line in lines]) if lines else 0
        )
        features["has_short_lines"] = any(len(line.strip()) < 20 for line in lines)

        return features

    def create_training_example(
        self,
        features: dict,
        should_remove: bool,
        segment_hash: str,
        domain: str,
        human_decision: bool = False,
        confidence: float = 1.0,
    ) -> MLTrainingExample:
        """Create a training example for the ML model."""
        return MLTrainingExample(
            features=features,
            label=should_remove,
            segment_hash=segment_hash,
            domain=domain,
            human_decision=human_decision,
            confidence=confidence,
            timestamp=datetime.utcnow().isoformat(),
        )
