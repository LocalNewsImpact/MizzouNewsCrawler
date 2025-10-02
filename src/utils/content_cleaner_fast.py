#!/usr/bin/env python3

import sqlite3
import re
from typing import List, Dict
from collections import defaultdict
import logging


class FastExactContentCleaner:
    """
    Fast content cleaner that finds exact duplicate text segments by:
    1. Extracting meaningful text blocks from each article
    2. Finding blocks that appear identically across multiple articles
    """

    def __init__(self, db_path: str = "data/mizzou.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

    def analyze_domain(self, domain: str, sample_size: int = None,
                      min_occurrences: int = 3) -> Dict:
        """Analyze a domain for exact duplicate text segments."""
        self.logger.info(f"Analyzing domain: {domain}")

        articles = self._get_articles_for_domain(domain, sample_size)
        if len(articles) < min_occurrences:
            return {"domain": domain, "article_count": len(articles),
                   "segments": []}

        # Extract blocks from all articles
        all_blocks = self._extract_blocks_from_articles(articles)

        # Find blocks that appear in multiple articles
        duplicate_blocks = self._find_duplicate_blocks(all_blocks,
                                                      min_occurrences)

        # Calculate statistics
        stats = self._calculate_domain_stats(articles, duplicate_blocks)

        return {
            "domain": domain,
            "article_count": len(articles),
            "segments": duplicate_blocks,
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

    def _extract_blocks_from_articles(self, articles: List[Dict]) -> Dict:
        """
        Extract meaningful text blocks from all articles.
        Returns: {block_text: {article_id: [positions], ...}}
        """
        all_blocks = defaultdict(lambda: defaultdict(list))

        for article in articles:
            content = article["content"]
            article_id = article["id"]

            # Extract different types of blocks
            blocks = []

            # 1. Paragraph blocks (split on double newlines)
            paragraphs = re.split(r'\n\s*\n', content)
            current_pos = 0
            for paragraph in paragraphs:
                paragraph = paragraph.strip()
                if len(paragraph) >= 30:  # Minimum meaningful size
                    # Find exact position in original content
                    pos = content.find(paragraph, current_pos)
                    if pos != -1:
                        blocks.append((paragraph, pos, pos + len(paragraph)))
                        current_pos = pos + len(paragraph)

            # 2. Line-based blocks (for navigation menus, etc.)
            lines = content.split('\n')
            current_pos = 0
            for line in lines:
                line = line.strip()
                if len(line) >= 20:  # Minimum line length
                    pos = content.find(line, current_pos)
                    if pos != -1:
                        blocks.append((line, pos, pos + len(line)))
                        current_pos = pos + len(line)

            # 3. Sentence blocks (split on periods)
            sentences = re.split(r'\.\s+', content)
            current_pos = 0
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) >= 40:  # Minimum sentence length
                    pos = content.find(sentence, current_pos)
                    if pos != -1:
                        blocks.append((sentence, pos, pos + len(sentence)))
                        current_pos = pos + len(sentence)

            # Store blocks for this article
            for block_text, start_pos, end_pos in blocks:
                # Normalize whitespace for matching
                normalized_text = re.sub(r'\s+', ' ', block_text).strip()
                if len(normalized_text) >= 30:
                    all_blocks[normalized_text][article_id].append(
                        (start_pos, end_pos)
                    )

        return all_blocks

    def _find_duplicate_blocks(self, all_blocks: Dict,
                              min_occurrences: int) -> List[Dict]:
        """Find blocks that appear in multiple articles."""
        duplicate_blocks = []

        for block_text, article_positions in all_blocks.items():
            if len(article_positions) >= min_occurrences:
                # Calculate position consistency
                article_ids = list(article_positions.keys())
                position_consistency = self._calculate_position_consistency(
                    block_text, article_positions
                )

                # Only keep blocks with reasonable consistency
                if position_consistency > 0.2:
                    segment = {
                        "text": block_text,
                        "length": len(block_text),
                        "occurrences": len(article_ids),
                        "article_ids": article_ids,
                        "positions": dict(article_positions),
                        "position_consistency": position_consistency,
                        "pattern_type": self._classify_pattern(block_text)
                    }
                    duplicate_blocks.append(segment)

        # Sort by occurrences and length
        duplicate_blocks.sort(key=lambda x: (x["occurrences"], x["length"]),
                             reverse=True)

        return duplicate_blocks

    def _calculate_position_consistency(self, block_text: str,
                                       article_positions: Dict) -> float:
        """Calculate position consistency (0.0 to 1.0)."""
        if len(article_positions) < 2:
            return 0.0

        # Get relative positions as fraction of content length
        relative_positions = []

        # We need to get content lengths - simplified approach
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for article_id, positions in article_positions.items():
            cursor.execute(
                "SELECT LENGTH(content) FROM articles WHERE id = ?",
                (article_id,)
            )
            result = cursor.fetchone()
            if result and result[0]:
                content_length = result[0]
                for start_pos, end_pos in positions:
                    rel_pos = start_pos / content_length
                    relative_positions.append(rel_pos)

        conn.close()

        if len(relative_positions) < 2:
            return 0.0

        # Calculate variance in relative positions
        mean_pos = sum(relative_positions) / len(relative_positions)
        variance = sum((pos - mean_pos) ** 2
                      for pos in relative_positions) / len(relative_positions)

        # Convert to consistency score (lower variance = higher consistency)
        consistency = max(0.0, 1.0 - (variance * 5))
        return min(1.0, consistency)

    def _classify_pattern(self, text: str) -> str:
        """Classify the type of pattern based on content."""
        text_lower = text.lower()

        # Navigation patterns
        nav_keywords = ['news', 'sports', 'obituaries', 'contact', 'subscribe',
                       'home', 'about', 'business', 'opinion', 'world', 'local']
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
            # Count each occurrence
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
