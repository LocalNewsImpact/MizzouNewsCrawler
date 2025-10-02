#!/usr/bin/env python3

import sqlite3
import re
from typing import List, Dict, Tuple, Set
from collections import defaultdict
import logging


class ProperBoundaryContentCleaner:
    """
    Content cleaner that only removes text segments with proper boundaries:
    - Complete sentences (ending with ., !, ?)
    - Complete paragraphs (surrounded by double newlines)
    - Complete lines (full line boundaries)
    """

    def __init__(self, db_path: str = "data/mizzou.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

    def analyze_domain(self, domain: str, sample_size: int = None,
                      min_occurrences: int = 3) -> Dict:
        """Analyze domain for exact duplicate segments with proper boundaries."""
        self.logger.info(f"Analyzing domain: {domain}")

        articles = self._get_articles_for_domain(domain, sample_size)
        if len(articles) < min_occurrences:
            return {"domain": domain, "article_count": len(articles),
                   "segments": []}

        # Extract properly bounded segments
        self.logger.info("Extracting properly bounded segments...")
        proper_segments = self._extract_proper_boundary_segments(articles)

        # Find segments that appear across multiple articles
        self.logger.info("Finding duplicate segments...")
        duplicate_segments = self._find_duplicate_segments(proper_segments,
                                                          min_occurrences)

        # Calculate statistics
        stats = self._calculate_domain_stats(articles, duplicate_segments)

        return {
            "domain": domain,
            "article_count": len(articles),
            "segments": duplicate_segments,
            "stats": stats
        }

    def _get_articles_for_domain(self, domain: str,
                                sample_size: int = None) -> List[Dict]:
        """Get articles for a specific domain."""
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

    def _extract_proper_boundary_segments(
            self, articles: List[Dict]) -> Dict[str, Set[str]]:
        """
        Extract segments with proper boundaries:
        1. Complete sentences (ending with punctuation)
        2. Complete paragraphs (surrounded by double newlines)
        3. Complete lines (full line from start to end)
        """
        segments = defaultdict(set)

        for article in articles:
            content = article["content"]
            article_id = str(article["id"])

            # Method 1: Complete sentences
            sentences = self._extract_complete_sentences(content)
            for sentence in sentences:
                if 30 <= len(sentence) <= 500:  # Reasonable length
                    normalized = re.sub(r'\s+', ' ', sentence.strip())
                    segments[normalized].add(article_id)

            # Method 2: Complete paragraphs
            paragraphs = self._extract_complete_paragraphs(content)
            for paragraph in paragraphs:
                if 40 <= len(paragraph) <= 800:  # Reasonable length
                    normalized = re.sub(r'\s+', ' ', paragraph.strip())
                    segments[normalized].add(article_id)

            # Method 3: Complete lines (but only meaningful ones)
            lines = self._extract_meaningful_lines(content)
            for line in lines:
                if 20 <= len(line) <= 300:  # Reasonable length
                    normalized = re.sub(r'\s+', ' ', line.strip())
                    segments[normalized].add(article_id)

        # Filter segments that appear in multiple articles
        filtered_segments = {
            text: article_ids
            for text, article_ids in segments.items()
            if len(article_ids) >= 2
        }

        self.logger.info(
            f"Found {
                len(filtered_segments)} properly bounded candidates")
        return filtered_segments

    def _extract_complete_sentences(self, content: str) -> List[str]:
        """Extract complete sentences that end with proper punctuation."""
        # Split on sentence endings, but keep the punctuation
        sentences = re.split(r'(?<=[.!?])\s+', content)

        complete_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            # Must end with proper punctuation
            if sentence and sentence[-1] in '.!?':
                # Must start with capital letter or quote
                if sentence and (
                        sentence[0].isupper() or sentence[0] in '"\''):
                    complete_sentences.append(sentence)

        return complete_sentences

    def _extract_complete_paragraphs(self, content: str) -> List[str]:
        """Extract complete paragraphs (separated by double newlines)."""
        paragraphs = re.split(r'\n\s*\n', content)

        complete_paragraphs = []
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if paragraph:
                # Should be a complete paragraph - either ends with punctuation
                # or is clearly a heading/title
                if (paragraph[-1] in '.!?:' or
                    self._looks_like_heading(paragraph)):
                    complete_paragraphs.append(paragraph)

        return complete_paragraphs

    def _extract_meaningful_lines(self, content: str) -> List[str]:
        """Extract complete lines that appear to be meaningful units."""
        lines = content.split('\n')

        meaningful_lines = []
        for line in lines:
            line = line.strip()
            if line:
                # Line should be a complete unit
                if (self._is_complete_line(line)):
                    meaningful_lines.append(line)

        return meaningful_lines

    def _looks_like_heading(self, text: str) -> bool:
        """Check if text looks like a heading or title."""
        # Headings are usually short, don't end with periods
        if len(text) > 100:
            return False

        # Contains navigation-like words
        nav_words = ['home', 'news', 'sports', 'contact', 'subscribe', 'about']
        has_nav_words = any(word in text.lower() for word in nav_words)

        # All caps or title case
        is_formatted = text.isupper() or text.istitle()

        return has_nav_words or is_formatted

    def _is_complete_line(self, line: str) -> bool:
        """Check if a line appears to be a complete unit."""
        # Complete sentences
        if line[-1] in '.!?':
            return True

        # Navigation items, headings, UI elements
        nav_keywords = ['click', 'subscribe', 'login', 'register', 'contact',
                       'home', 'news', 'sports', 'menu', 'search']
        if any(keyword in line.lower() for keyword in nav_keywords):
            return True

        # UI elements (buttons, links, etc.)
        ui_keywords = ['watch', 'start', 'stop', 'cancel', 'report', 'share']
        if any(keyword in line.lower() for keyword in ui_keywords):
            return True

        # Copyright, terms, etc.
        legal_keywords = ['copyright', 'rights reserved', 'privacy', 'terms']
        if any(keyword in line.lower() for keyword in legal_keywords):
            return True

        return False

    def _find_duplicate_segments(self, proper_segments: Dict[str, Set[str]],
                                min_occurrences: int) -> List[Dict]:
        """Find segments that appear with exact boundaries across articles."""
        duplicate_segments = []
        articles_by_id = {}

        # Get articles by ID for position calculations
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for segment_text, article_ids in proper_segments.items():
            if len(article_ids) >= min_occurrences:
                for article_id in article_ids:
                    if article_id not in articles_by_id:
                        cursor.execute(
                            "SELECT content FROM articles WHERE id = ?",
                            (article_id,)
                        )
                        row = cursor.fetchone()
                        if row:
                            articles_by_id[article_id] = {"content": row[0]}
        conn.close()

        for segment_text, article_ids in proper_segments.items():
            if len(article_ids) >= min_occurrences:
                # Find exact positions in each article
                positions = {}
                for article_id in article_ids:
                    if article_id in articles_by_id:
                        content = articles_by_id[article_id]["content"]
                        article_positions = []

                        # Find all occurrences of this exact segment
                        start = 0
                        while True:
                            pos = content.find(segment_text, start)
                            if pos == -1:
                                break
                            article_positions.append(
                                (pos, pos + len(segment_text)))
                            start = pos + 1

                        if article_positions:
                            positions[article_id] = article_positions

                if len(positions) >= min_occurrences:
                    # Calculate position consistency
                    position_consistency = self._calculate_position_consistency(
                        positions, articles_by_id)

                    if position_consistency > 0.2:
                        segment = {
                            "text": segment_text,
                            "length": len(segment_text),
                            "occurrences": len(positions),
                            "article_ids": list(
                                positions.keys()),
                            "positions": positions,
                            "position_consistency": position_consistency,
                            "pattern_type": self._classify_pattern(segment_text)}
                        duplicate_segments.append(segment)

        # Sort by occurrences and length
        duplicate_segments.sort(key=lambda x: (x["occurrences"], x["length"]),
                               reverse=True)

        self.logger.info(
            f"Found {
                len(duplicate_segments)} properly bounded duplicates")
        return duplicate_segments

    def _calculate_position_consistency(self, positions: Dict[str, List[Tuple[int, int]]],
                                       articles_by_id: Dict[str, Dict]) -> float:
        """Calculate position consistency (0.0 to 1.0)."""
        if len(positions) < 2:
            return 0.0

        # Get relative positions as fraction of content length
        relative_positions = []

        for article_id, article_positions in positions.items():
            if article_id in articles_by_id:
                content_length = len(articles_by_id[article_id]["content"])

                for start_pos, end_pos in article_positions:
                    if content_length > 0:
                        rel_pos = start_pos / content_length
                        relative_positions.append(rel_pos)

        if len(relative_positions) < 2:
            return 0.0

        # Calculate variance in relative positions
        mean_pos = sum(relative_positions) / len(relative_positions)
        variance = sum((pos - mean_pos) ** 2
                      for pos in relative_positions) / len(relative_positions)

        # Convert to consistency score
        consistency = max(0.0, 1.0 - (variance * 5))
        return min(1.0, consistency)

    def _classify_pattern(self, text: str) -> str:
        """Classify the type of pattern based on content."""
        text_lower = text.lower()

        # Navigation patterns
        nav_keywords = [
            'news',
            'sports',
            'obituaries',
            'contact',
            'subscribe',
            'home',
            'about',
            'business',
            'opinion',
            'world',
            'local']
        nav_count = sum(1 for keyword in nav_keywords
                       if keyword in text_lower)

        # Footer patterns
        footer_keywords = ['copyright', 'rights reserved', 'privacy', 'terms']
        footer_count = sum(1 for keyword in footer_keywords
                          if keyword in text_lower)

        # Subscription patterns
        sub_keywords = ['subscribe', 'subscription', 'paywall', 'premium']
        sub_count = sum(1 for keyword in sub_keywords
                       if keyword in text_lower)

        if nav_count >= 2:
            return "navigation"
        elif footer_count >= 1:
            return "footer"
        elif sub_count >= 1:
            return "subscription"
        else:
            return "other"

    def _calculate_domain_stats(self, articles: List[Dict],
                               segments: List[Dict]) -> Dict:
        """Calculate statistics for the domain analysis."""
        total_removable_chars = 0
        affected_articles = set()

        for segment in segments:
            total_removable_chars += segment["length"] * segment["occurrences"]
            affected_articles.update(segment["article_ids"])

        total_content_chars = sum(len(article["content"])
                                 for article in articles)

        return {
            "total_articles": len(articles),
            "affected_articles": len(affected_articles),
            "total_segments": len(segments),
            "total_removable_chars": total_removable_chars,
            "total_content_chars": total_content_chars,
            "removal_percentage": (total_removable_chars / total_content_chars
                                 * 100) if total_content_chars > 0 else 0
        }

    def clean_article_content(self, content: str,
                             segments_to_remove: List[Dict]) -> str:
        """Remove segments with proper boundaries from article content."""
        cleaned_content = content

        # Sort segments by length (longest first)
        segments_sorted = sorted(segments_to_remove,
                               key=lambda x: x["length"], reverse=True)

        for segment in segments_sorted:
            segment_text = segment["text"]
            cleaned_content = cleaned_content.replace(segment_text, "")

        # Clean up extra whitespace while preserving paragraph structure
        cleaned_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', cleaned_content)
        cleaned_content = re.sub(r'^\s+|\s+$', '', cleaned_content)

        return cleaned_content
