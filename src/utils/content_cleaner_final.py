"""
Content cleaning utilities for removing boilerplate text from articles.

This module provides algorithms to detect and remove repeated text segments
that appear across multiple articles from the same domain.
"""

import re
import hashlib
import logging
import sqlite3
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class BoilerplateMatch:
    """Represents a detected boilerplate text segment."""
    text: str
    hash_value: str
    occurrence_count: int
    confidence_score: float
    domains: List[str]
    positions: List[Tuple[float, float]]  # (start_pct, end_pct)


@dataclass
class CleaningTelemetry:
    """Telemetry data for content cleaning operations."""
    article_id: int
    domain: str
    original_length: int
    cleaned_length: int
    segments_removed: int
    confidence_threshold: float
    processing_time: float
    timestamp: str
    removed_segments: List[Dict]


class ContentCleaner:
    """Main content cleaning engine."""

    def __init__(self, db_path: str, confidence_threshold: float = 0.7):
        """Initialize the content cleaner."""
        self.db_path = db_path
        self.confidence_threshold = confidence_threshold
        self.min_occurrence_count = 3
        self._boilerplate_cache = {}

    def analyze_domain(self, domain: str,
                      sample_size: Optional[int] = None) -> Dict:
        """Analyze content from a domain to identify boilerplate."""
        articles = self._get_domain_articles(domain, sample_size)

        if len(articles) < self.min_occurrence_count:
            return {
                "domain": domain,
                "articles": len(articles),
                "boilerplate_segments": []
            }

        # Find common segments
        segments = self._find_common_segments(articles)

        # Score segments
        boilerplate_matches = []
        for segment_hash, data in segments.items():
            if data["count"] >= self.min_occurrence_count:
                match = self._score_segment(data, domain, len(articles))
                if match.confidence_score >= self.confidence_threshold:
                    boilerplate_matches.append(match)

        # Sort by confidence
        boilerplate_matches.sort(
            key=lambda x: x.confidence_score,
            reverse=True
        )

        return {
            "domain": domain,
            "articles": len(articles),
            "boilerplate_segments": len(boilerplate_matches),
            "segments": [
                {
                    "text": (match.text[:200] + "..."
                            if len(match.text) > 200 else match.text),
                    "hash": match.hash_value,
                    "occurrence_count": match.occurrence_count,
                    "confidence_score": match.confidence_score,
                    "avg_position": self._calc_avg_position(match.positions)
                }
                for match in boilerplate_matches[:20]
            ]
        }

    def clean_content(self, content: str, domain: str,
                     article_id: Optional[int] = None,
                     dry_run: bool = True) -> Tuple[str, CleaningTelemetry]:
        """Clean content by removing detected boilerplate segments."""
        start_time = datetime.utcnow()
        original_length = len(content)

        # Get boilerplate patterns for domain
        if domain not in self._boilerplate_cache:
            self._boilerplate_cache[domain] = self.analyze_domain(domain)

        domain_analysis = self._boilerplate_cache[domain]
        removed_segments = []
        cleaned_content = content

        # Apply removal if not dry run
        if not dry_run:
            for segment_info in domain_analysis.get("segments", []):
                # This would need full implementation to retrieve text
                # and safely remove from content
                pass

        # Create telemetry
        telemetry = CleaningTelemetry(
            article_id=article_id or 0,
            domain=domain,
            original_length=original_length,
            cleaned_length=len(cleaned_content),
            segments_removed=len(removed_segments),
            confidence_threshold=self.confidence_threshold,
            processing_time=(
                datetime.utcnow() - start_time
            ).total_seconds(),
            timestamp=datetime.utcnow().isoformat(),
            removed_segments=removed_segments
        )

        return cleaned_content, telemetry

    def _get_domain_articles(self, domain: str,
                           sample_size: Optional[int] = None) -> List[Dict]:
        """Get articles from a specific domain."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = """
        SELECT id, url, content, text_hash
        FROM articles
        WHERE url LIKE ?
        AND content IS NOT NULL
        AND content != ''
        ORDER BY id DESC
        """

        params = [f"%{domain}%"]
        if sample_size:
            query += " LIMIT ?"
            params.append(sample_size)

        cursor.execute(query, params)
        articles = [
            {
                "id": row[0],
                "url": row[1],
                "content": row[2],
                "text_hash": row[3]
            }
            for row in cursor.fetchall()
        ]

        conn.close()
        return articles

    def _find_common_segments(self, articles: List[Dict]) -> Dict:
        """Find text segments that appear across multiple articles."""
        segment_occurrences = defaultdict(lambda: {
            "count": 0,
            "text": "",
            "positions": [],
            "article_ids": []
        })

        for article in articles:
            content = article["content"]
            article_id = article["id"]

            segments = self._extract_segments(content)

            for segment_text, start_pos, end_pos in segments:
                if len(segment_text.strip()) < 20:
                    continue

                segment_hash = hashlib.sha256(
                    segment_text.strip().encode()
                ).hexdigest()

                # Calculate position percentages
                content_length = len(content)
                start_pct = (start_pos / content_length
                           if content_length > 0 else 0)
                end_pct = (end_pos / content_length
                         if content_length > 0 else 0)

                segment_occurrences[segment_hash]["count"] += 1
                segment_occurrences[segment_hash]["text"] = (
                    segment_text.strip()
                )
                segment_occurrences[segment_hash]["positions"].append(
                    (start_pct, end_pct)
                )
                segment_occurrences[segment_hash]["article_ids"].append(
                    article_id
                )

        return segment_occurrences

    def _extract_segments(self, content: str) -> List[Tuple[str, int, int]]:
        """Extract potential boilerplate segments from content."""
        segments = []

        # Extract sentences
        sentences = re.split(r'[.!?]+', content)
        current_pos = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 20:
                start_pos = content.find(sentence, current_pos)
                if start_pos != -1:
                    end_pos = start_pos + len(sentence)
                    segments.append((sentence, start_pos, end_pos))
                    current_pos = end_pos

        # Extract paragraphs
        paragraphs = content.split('\n\n')
        current_pos = 0
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if len(paragraph) > 50:
                start_pos = content.find(paragraph, current_pos)
                if start_pos != -1:
                    end_pos = start_pos + len(paragraph)
                    segments.append((paragraph, start_pos, end_pos))
                    current_pos = end_pos

        return segments

    def _score_segment(self, segment_data: Dict, domain: str,
                      total_articles: int) -> BoilerplateMatch:
        """Score a segment for boilerplate likelihood."""
        text = segment_data["text"]
        occurrence_count = segment_data["count"]
        positions = segment_data["positions"]

        # Calculate confidence using rule-based approach
        confidence = self._calculate_confidence(
            text, occurrence_count, total_articles, positions
        )

        segment_hash = hashlib.sha256(text.encode()).hexdigest()

        return BoilerplateMatch(
            text=text,
            hash_value=segment_hash,
            occurrence_count=occurrence_count,
            confidence_score=confidence,
            domains=[domain],
            positions=positions
        )

    def _calculate_confidence(self, text: str, occurrence_count: int,
                            total_articles: int,
                            positions: List[Tuple[float, float]]) -> float:
        """Calculate confidence score using rule-based approach."""
        text_lower = text.lower()
        confidence = 0.0

        # Occurrence frequency (0-0.4 points)
        occurrence_ratio = occurrence_count / total_articles
        confidence += min(occurrence_ratio * 0.8, 0.4)

        # Position consistency (0-0.3 points)
        if positions:
            start_positions = [pos[0] for pos in positions]
            end_positions = [pos[1] for pos in positions]

            start_std = self._calculate_std(start_positions)
            end_std = self._calculate_std(end_positions)

            position_consistency = 1.0 - (start_std + end_std) / 2
            confidence += position_consistency * 0.3

        # Content patterns (0-0.3 points)
        boilerplate_terms = [
            "subscribe", "newsletter", "sign up", "follow us", "share",
            "copyright", "privacy", "terms", "login", "register"
        ]

        term_matches = sum(
            1 for term in boilerplate_terms if term in text_lower
        )
        confidence += min(
            term_matches / len(boilerplate_terms), 1.0
        ) * 0.3

        return min(confidence, 1.0)

    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) <= 1:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5

    def _calc_avg_position(self, positions: List[Tuple[float, float]]) -> Dict:
        """Calculate average position statistics."""
        if not positions:
            return {"start": 0.0, "end": 0.0}

        start_avg = sum(pos[0] for pos in positions) / len(positions)
        end_avg = sum(pos[1] for pos in positions) / len(positions)

        return {"start": start_avg, "end": end_avg}


def create_content_cleaning_cli(db_path: str) -> ContentCleaner:
    """Factory function to create a content cleaner for CLI use."""
    return ContentCleaner(db_path=db_path)
