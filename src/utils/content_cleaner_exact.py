#!/usr/bin/env python3

import sqlite3
import re
from typing import List, Dict, Tuple
from collections import defaultdict
import logging


class ExactContentCleaner:
    """
    Content cleaner that only removes text blocks that are EXACTLY duplicated
    at identical boundaries across multiple articles from same domain.
    """

    def __init__(self, db_path: str = "data/mizzou.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

    def analyze_domain(
            self,
            domain: str,
            sample_size: int = None,
            min_occurrences: int = 3) -> Dict:
        """
        Analyze a domain for exact duplicate text segments.
        Only segments with identical boundaries across articles are considered.
        """
        self.logger.info(f"Analyzing domain: {domain}")

        articles = self._get_articles_for_domain(domain, sample_size)
        if len(articles) < min_occurrences:
            self.logger.warning(
                f"Not enough articles ({
                    len(articles)}) for domain {domain}")
            return {
                "domain": domain,
                "article_count": len(articles),
                "segments": []}

        # Find exact duplicate segments
        exact_segments = self._find_exact_duplicate_segments(
            articles, min_occurrences)

        # Calculate statistics
        stats = self._calculate_domain_stats(articles, exact_segments)

        return {
            "domain": domain,
            "article_count": len(articles),
            "segments": exact_segments,
            "stats": stats
        }

    def _get_articles_for_domain(
            self,
            domain: str,
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

    def _find_exact_duplicate_segments(
            self,
            articles: List[Dict],
            min_occurrences: int) -> List[Dict]:
        """
        Find text segments that appear with EXACTLY the same boundaries
        across multiple articles.
        """
        # For each pair of articles, find all common substrings
        all_exact_matches = defaultdict(lambda: {
            "text": "",
            "length": 0,
            "article_ids": set(),
            # article_id -> [(start, end), ...]
            "positions": defaultdict(list),
            "position_consistency": 0.0
        })

        # Compare every pair of articles
        for i, article1 in enumerate(articles):
            for j, article2 in enumerate(articles[i+1:], i+1):
                exact_matches = self._find_exact_matches_between_articles(
                    article1, article2
                )

                for match_text, positions1, positions2 in exact_matches:
                    # Create a unique key for this exact text
                    match_key = hash(match_text.strip())

                    # Record this match
                    match_info = all_exact_matches[match_key]
                    match_info["text"] = match_text.strip()
                    match_info["length"] = len(match_text.strip())
                    match_info["article_ids"].add(article1["id"])
                    match_info["article_ids"].add(article2["id"])

                    # Record positions for each article
                    for start, end in positions1:
                        match_info["positions"][article1["id"]].append(
                            (start, end))
                    for start, end in positions2:
                        match_info["positions"][article2["id"]].append(
                            (start, end))

        # Filter segments that appear in at least min_occurrences articles
        # and calculate position consistency
        valid_segments = []
        for match_key, match_info in all_exact_matches.items():
            if len(match_info["article_ids"]) >= min_occurrences:
                # Calculate position consistency (how often it appears at
                # similar positions)
                match_info["position_consistency"] = self._calculate_position_consistency(
                    match_info["positions"], articles)

                # Only keep segments with reasonable length and consistency
                if (match_info["length"] >= 30 and
                        match_info["position_consistency"] > 0.3):

                    segment = {
                        "text": match_info["text"],
                        "length": match_info["length"],
                        "occurrences": len(
                            match_info["article_ids"]),
                        "article_ids": list(
                            match_info["article_ids"]),
                        "positions": dict(
                            match_info["positions"]),
                        "position_consistency": match_info["position_consistency"],
                        "pattern_type": self._classify_pattern(
                            match_info["text"])}
                    valid_segments.append(segment)

        # Sort by occurrences and length
        valid_segments.sort(
            key=lambda x: (
                x["occurrences"],
                x["length"]),
            reverse=True)

        return valid_segments

    def _find_exact_matches_between_articles(
            self, article1: Dict, article2: Dict) -> List[Tuple[str, List[Tuple[int, int]], List[Tuple[int, int]]]]:
        """
        Find all exact text matches between two articles.
        Returns list of (match_text, positions_in_article1, positions_in_article2)
        """
        content1 = article1["content"]
        content2 = article2["content"]

        matches = []

        # Use a sliding window approach to find common substrings
        # Start with larger windows and work down
        for min_length in [100, 75, 50, 30]:  # Minimum lengths to consider
            # Find all substrings of min_length or longer in content1
            for i in range(len(content1) - min_length + 1):
                # Try different ending positions
                for j in range(i + min_length, min(i + 500,
                               len(content1) + 1)):  # Max 500 chars
                    substring = content1[i:j]

                    # Skip if this substring is too short or just whitespace
                    if len(substring.strip()) < min_length:
                        continue

                    # Look for exact matches in content2
                    positions_in_content2 = []
                    search_start = 0
                    while True:
                        pos = content2.find(substring, search_start)
                        if pos == -1:
                            break
                        positions_in_content2.append(
                            (pos, pos + len(substring)))
                        search_start = pos + 1

                    # If we found exact matches, record them
                    if positions_in_content2:
                        matches.append((
                            substring,
                            [(i, j)],  # Position in article1
                            positions_in_content2  # Positions in article2
                        ))

        # Remove overlapping matches, keeping the longest ones
        matches = self._remove_overlapping_matches(matches)

        return matches

    def _remove_overlapping_matches(self,
                                    matches: List[Tuple[str,
                                                        List[Tuple[int,
                                                                   int]],
                                                        List[Tuple[int,
                                                                   int]]]]) -> List[Tuple[str,
                                                                                          List[Tuple[int,
                                                                                                     int]],
                                                                                          List[Tuple[int,
                                                                                                     int]]]]:
        """Remove overlapping matches, keeping the longest ones."""
        if not matches:
            return matches

        # Sort by length (longest first)
        matches.sort(key=lambda x: len(x[0]), reverse=True)

        non_overlapping = []
        used_ranges_1 = []
        used_ranges_2 = []

        for match_text, pos1_list, pos2_list in matches:
            # Check if this match overlaps with any already selected matches
            overlap_found = False

            for start1, end1 in pos1_list:
                for used_start1, used_end1 in used_ranges_1:
                    if not (end1 <= used_start1 or start1 >=
                            used_end1):  # Overlaps
                        overlap_found = True
                        break
                if overlap_found:
                    break

            if not overlap_found:
                for start2, end2 in pos2_list:
                    for used_start2, used_end2 in used_ranges_2:
                        if not (
                                end2 <= used_start2 or start2 >= used_end2):  # Overlaps
                            overlap_found = True
                            break
                    if overlap_found:
                        break

            if not overlap_found:
                non_overlapping.append((match_text, pos1_list, pos2_list))
                used_ranges_1.extend(pos1_list)
                used_ranges_2.extend(pos2_list)

        return non_overlapping

    def _calculate_position_consistency(
            self, positions: Dict[str, List[Tuple[int, int]]], articles: List[Dict]) -> float:
        """
        Calculate how consistently a segment appears at similar positions
        across different articles (0.0 to 1.0).
        """
        if len(positions) < 2:
            return 0.0

        # Get relative positions (as fraction of total content length)
        relative_positions = []
        for article in articles:
            article_id = article["id"]
            if article_id in positions:
                content_length = len(article["content"])
                for start, end in positions[article_id]:
                    if content_length > 0:
                        rel_start = start / content_length
                        relative_positions.append(rel_start)

        if len(relative_positions) < 2:
            return 0.0

        # Calculate variance in relative positions
        mean_pos = sum(relative_positions) / len(relative_positions)
        variance = sum(
            (pos - mean_pos) ** 2 for pos in relative_positions) / len(relative_positions)

        # Convert variance to consistency score (lower variance = higher
        # consistency)
        consistency = max(0.0, 1.0 - (variance * 10))  # Scale factor of 10

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
            'local',
            'weather']
        nav_count = sum(1 for keyword in nav_keywords if keyword in text_lower)

        # Footer patterns
        footer_keywords = ['copyright', 'rights reserved', 'privacy', 'terms']
        footer_count = sum(
            1 for keyword in footer_keywords if keyword in text_lower)

        # Subscription/paywall patterns
        sub_keywords = [
            'subscribe',
            'subscription',
            'paywall',
            'premium',
            'members only']
        sub_count = sum(1 for keyword in sub_keywords if keyword in text_lower)

        if nav_count >= 3:
            return "navigation"
        elif footer_count >= 1:
            return "footer"
        elif sub_count >= 1:
            return "subscription"
        else:
            return "other"

    def _calculate_domain_stats(
            self,
            articles: List[Dict],
            segments: List[Dict]) -> Dict:
        """Calculate statistics for the domain analysis."""
        total_removable_chars = 0
        affected_articles = set()

        for segment in segments:
            total_removable_chars += segment["length"] * segment["occurrences"]
            affected_articles.update(segment["article_ids"])

        total_content_chars = sum(
            len(article["content"]) for article in articles)

        return {
            "total_articles": len(articles),
            "affected_articles": len(affected_articles),
            "total_segments": len(segments),
            "total_removable_chars": total_removable_chars,
            "total_content_chars": total_content_chars,
            "removal_percentage": (
                total_removable_chars /
                total_content_chars *
                100) if total_content_chars > 0 else 0}

    def clean_article_content(
            self,
            content: str,
            segments_to_remove: List[Dict]) -> str:
        """Remove exact duplicate segments from article content."""
        cleaned_content = content

        # Sort segments by length (longest first) to avoid partial removals
        segments_sorted = sorted(
            segments_to_remove,
            key=lambda x: x["length"],
            reverse=True)

        for segment in segments_sorted:
            segment_text = segment["text"]
            # Remove all exact occurrences
            cleaned_content = cleaned_content.replace(segment_text, "")

        # Clean up extra whitespace
        cleaned_content = re.sub(
            r'\n\s*\n\s*\n',
            '\n\n',
            cleaned_content)  # Multiple newlines
        # Leading/trailing whitespace
        cleaned_content = re.sub(r'^\s+|\s+$', '', cleaned_content)

        return cleaned_content
