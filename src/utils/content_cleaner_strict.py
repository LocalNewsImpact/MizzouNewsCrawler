#!/usr/bin/env python3

import logging
import re
import sqlite3
from collections import defaultdict
from typing import Any


class StrictBoundaryContentCleaner:
    """
    Strict content cleaner that only removes segments with BOTH proper start
    and proper end boundaries (complete sentences or paragraphs).
    """

    def __init__(self, db_path: str = "data/mizzou.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

    def analyze_domain(
        self, domain: str, sample_size: int = None, min_occurrences: int = 3
    ) -> dict:
        """Analyze domain with strict boundary requirements."""
        self.logger.info(f"Analyzing domain: {domain}")

        articles = self._get_articles_for_domain(domain, sample_size)
        if len(articles) < min_occurrences:
            return {"domain": domain, "article_count": len(articles), "segments": []}

        # Phase 1: Find rough candidates
        rough_candidates = self._find_rough_candidates(articles)

        # Phase 2: Strict boundary validation
        strict_segments = self._validate_strict_boundaries(
            articles, rough_candidates, min_occurrences
        )

        # Calculate statistics
        stats = self._calculate_domain_stats(articles, strict_segments)

        return {
            "domain": domain,
            "article_count": len(articles),
            "segments": strict_segments,
            "stats": stats,
        }

    def _get_articles_for_domain(
        self, domain: str, sample_size: int = None
    ) -> list[dict]:
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

        params: list[Any] = [f"%{domain}%"]
        if sample_size:
            query += " LIMIT ?"
            params.append(sample_size)

        cursor.execute(query, params)
        articles = [
            {"id": row[0], "url": row[1], "content": row[2], "text_hash": row[3]}
            for row in cursor.fetchall()
        ]

        conn.close()
        return articles

    def _find_rough_candidates(self, articles: list[dict]) -> dict[str, set[str]]:
        """Phase 1: Find rough candidates using complete structures only."""
        candidates = defaultdict(set)

        for article in articles:
            content = article["content"]
            article_id = str(article["id"])

            # Method 1: Complete sentences (end with proper punctuation)
            sentences = re.split(r"[.!?]+\s+", content)
            for sentence in sentences:
                sentence = sentence.strip()
                if 30 <= len(sentence) <= 400:
                    # Only include if it looks like a complete sentence
                    if self._is_complete_sentence(sentence):
                        normalized = re.sub(r"\s+", " ", sentence)
                        candidates[normalized].add(article_id)

            # Method 2: Complete paragraphs (bounded by double newlines)
            paragraphs = re.split(r"\n\s*\n", content)
            for paragraph in paragraphs:
                paragraph = paragraph.strip()
                if 40 <= len(paragraph) <= 600:
                    # Clean up internal whitespace but keep structure
                    normalized = re.sub(r"\s+", " ", paragraph)
                    candidates[normalized].add(article_id)

            # Method 3: Complete lines (for navigation/headers)
            lines = content.split("\n")
            for line in lines:
                line = line.strip()
                if 20 <= len(line) <= 300:
                    # Only include lines that look complete
                    if self._is_complete_line(line):
                        normalized = re.sub(r"\s+", " ", line)
                        candidates[normalized].add(article_id)

        # Filter candidates that appear in multiple articles
        filtered_candidates = {
            text: article_ids
            for text, article_ids in candidates.items()
            if len(article_ids) >= 2
        }

        self.logger.info(f"Found {len(filtered_candidates)} rough candidates")
        return filtered_candidates

    def _is_complete_sentence(self, text: str) -> bool:
        """Check if text appears to be a complete sentence."""
        text = text.strip()

        # Must start with capital letter or common sentence starters
        if not (
            text[0].isupper()
            or text.lower().startswith(("the ", "a ", "an ", "to ", "if ", "we "))
        ):
            return False

        # Must end with proper punctuation
        if not text.endswith((".", "!", "?", ":", ";")):
            return False

        # Should have reasonable word count
        word_count = len(text.split())
        if word_count < 3 or word_count > 50:
            return False

        return True

    def _is_complete_line(self, text: str) -> bool:
        """Check if text appears to be a complete line/phrase."""
        text = text.strip()

        # Skip very short fragments
        if len(text) < 20:
            return False

        # Skip if it looks like a fragment (ends mid-word or with comma)
        if text.endswith((",", "...", " and", " or", " but")):
            return False

        # Skip if it starts mid-sentence (lowercase, no capital)
        if text[0].islower() and not text.lower().startswith(("the ", "a ", "an ")):
            return False

        return True

    def _validate_strict_boundaries(
        self,
        articles: list[dict],
        rough_candidates: dict[str, set[str]],
        min_occurrences: int,
    ) -> list[dict]:
        """Phase 2: Validate candidates have strict proper boundaries."""
        strict_segments = []
        articles_by_id = {str(article["id"]): article for article in articles}

        for candidate_text, candidate_article_ids in rough_candidates.items():
            if len(candidate_article_ids) < min_occurrences:
                continue

            # Find exact matches and validate boundaries
            boundary_valid_matches = {}

            for article_id in candidate_article_ids:
                article = articles_by_id[article_id]
                content = article["content"]

                # Find all exact occurrences
                positions = []
                search_start = 0

                while True:
                    pos = content.find(candidate_text, search_start)
                    if pos == -1:
                        break

                    end_pos = pos + len(candidate_text)

                    # Validate this occurrence has proper boundaries
                    if self._has_proper_boundaries(content, pos, end_pos):
                        positions.append((pos, end_pos))

                    search_start = pos + 1

                if positions:
                    boundary_valid_matches[article_id] = positions

            # Only keep if still meets minimum occurrence after boundary
            # validation
            if len(boundary_valid_matches) >= min_occurrences:
                # Calculate position consistency
                position_consistency = self._calculate_position_consistency(
                    boundary_valid_matches, articles_by_id
                )

                if position_consistency > 0.2:
                    segment = {
                        "text": candidate_text,
                        "length": len(candidate_text),
                        "occurrences": len(boundary_valid_matches),
                        "article_ids": list(boundary_valid_matches.keys()),
                        "positions": boundary_valid_matches,
                        "position_consistency": position_consistency,
                        "pattern_type": self._classify_pattern(candidate_text),
                        "boundary_validated": True,
                    }
                    strict_segments.append(segment)

        # Sort by occurrences and length
        strict_segments.sort(
            key=lambda x: (x["occurrences"], x["length"]), reverse=True
        )

        self.logger.info(f"Validated {len(strict_segments)} strict boundary segments")
        return strict_segments

    def _has_proper_boundaries(
        self, content: str, start_pos: int, end_pos: int
    ) -> bool:
        """Check if a text segment has proper start and end boundaries."""
        text = content[start_pos:end_pos]

        # Check character before start position
        proper_start = True
        if start_pos > 0:
            char_before = content[start_pos - 1]
            # Should be preceded by sentence boundary or paragraph boundary
            if not (
                char_before in ".!?\n"
                or (
                    char_before == " "
                    and start_pos > 1
                    and content[start_pos - 2] in ".!?\n"
                )
            ):
                proper_start = False

        # Check character after end position
        proper_end = True
        if end_pos < len(content):
            char_after = content[end_pos]
            # Should be followed by sentence boundary or paragraph boundary
            if not (char_after in ".!?\n " or end_pos == len(content) - 1):
                proper_end = False

        # Text itself should look complete
        text_complete = (
            self._is_complete_sentence(text)
            or self._is_complete_paragraph(text)
            or self._is_complete_phrase(text)
        )

        return proper_start and proper_end and text_complete

    def _is_complete_paragraph(self, text: str) -> bool:
        """Check if text is a complete paragraph."""
        text = text.strip()

        # Should be substantial
        if len(text) < 40:
            return False

        # Should end properly
        if not text.endswith((".", "!", "?", ":", ";", '"', "'")):
            return False

        # Should start properly (capital letter or quote)
        if not (text[0].isupper() or text[0] in "\"'"):
            return False

        return True

    def _is_complete_phrase(self, text: str) -> bool:
        """Check if text is a complete phrase (like navigation items)."""
        text = text.strip()

        # Navigation or UI phrases
        nav_patterns = [
            r"^(Watch|Post|Start|Stop|Cancel|Subscribe|Login|Register)",
            r"(discussion|comment|notification|subscription)$",
            r"^(Click here|Learn more|Read more|Continue reading)",
            r"(terms|privacy|policy|guidelines)$",
        ]

        for pattern in nav_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        return False

    def _calculate_position_consistency(
        self,
        exact_matches: dict[str, list[tuple[int, int]]],
        articles_by_id: dict[str, dict],
    ) -> float:
        """Calculate position consistency (0.0 to 1.0)."""
        if len(exact_matches) < 2:
            return 0.0

        relative_positions = []

        for article_id, positions in exact_matches.items():
            article = articles_by_id[article_id]
            content_length = len(article["content"])

            for start_pos, end_pos in positions:
                if content_length > 0:
                    rel_pos = start_pos / content_length
                    relative_positions.append(rel_pos)

        if len(relative_positions) < 2:
            return 0.0

        # Calculate variance in relative positions
        mean_pos = sum(relative_positions) / len(relative_positions)
        variance = sum((pos - mean_pos) ** 2 for pos in relative_positions) / len(
            relative_positions
        )

        # Convert to consistency score
        consistency = max(0.0, 1.0 - (variance * 5))
        return min(1.0, consistency)

    def _classify_pattern(self, text: str) -> str:
        """Classify the type of pattern based on content."""
        text_lower = text.lower()

        # Navigation patterns
        nav_keywords = [
            "news",
            "sports",
            "obituaries",
            "contact",
            "subscribe",
            "home",
            "about",
            "business",
            "opinion",
            "world",
            "local",
        ]
        nav_count = sum(1 for keyword in nav_keywords if keyword in text_lower)

        # Footer patterns
        footer_keywords = ["copyright", "rights reserved", "privacy", "terms"]
        footer_count = sum(1 for keyword in footer_keywords if keyword in text_lower)

        # Subscription patterns
        sub_keywords = ["subscribe", "subscription", "paywall", "premium"]
        sub_count = sum(1 for keyword in sub_keywords if keyword in text_lower)

        if nav_count >= 2:
            return "navigation"
        elif footer_count >= 1:
            return "footer"
        elif sub_count >= 1:
            return "subscription"
        else:
            return "other"

    def _calculate_domain_stats(
        self, articles: list[dict], segments: list[dict]
    ) -> dict:
        """Calculate statistics for the domain analysis."""
        total_removable_chars = 0
        affected_articles = set()

        for segment in segments:
            total_removable_chars += segment["length"] * segment["occurrences"]
            affected_articles.update(segment["article_ids"])

        total_content_chars = sum(len(article["content"]) for article in articles)

        return {
            "total_articles": len(articles),
            "affected_articles": len(affected_articles),
            "total_segments": len(segments),
            "total_removable_chars": total_removable_chars,
            "total_content_chars": total_content_chars,
            "removal_percentage": (
                (total_removable_chars / total_content_chars * 100)
                if total_content_chars > 0
                else 0
            ),
        }
