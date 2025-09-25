"""
Improved content cleaning with better detection of navigation menus and blocks.
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
    positions: List[Tuple[float, float]]
    pattern_type: str  # 'navigation', 'footer', 'paragraph', 'sentence'


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


class ImprovedContentCleaner:
    """Improved content cleaning with better block detection."""
    
    def __init__(self, db_path: str, confidence_threshold: float = 0.6):
        """Initialize the improved content cleaner."""
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
        
        # Find common segments using multiple strategies
        segments = self._find_common_segments_improved(articles)
        
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
                    "pattern_type": match.pattern_type,
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
        
        # Find and remove segments
        segments_to_remove = []
        for segment_info in domain_analysis.get("segments", []):
            # The segment text is already in the segment_info from analyze_domain
            # We need to find the full text by matching the preview
            segment_preview = segment_info.get("text", "")
            
            # Try to find the full segment in the content
            # Look for the segment by matching the beginning of the preview
            if len(segment_preview) >= 50:
                search_text = segment_preview.replace("...", "")
                matches = []
                
                # Find all occurrences of this segment
                start = 0
                while True:
                    pos = cleaned_content.find(search_text, start)
                    if pos == -1:
                        break
                    
                    # Extract a larger block around this position to get full segment
                    # Look for natural break points
                    segment_start = pos
                    segment_end = pos + len(search_text)
                    
                    # Extend to word boundaries if reasonable
                    while (segment_end < len(cleaned_content) and 
                           cleaned_content[segment_end] not in '\n.!?'):
                        segment_end += 1
                        if segment_end - segment_start > len(search_text) * 2:
                            break
                    
                    full_segment = cleaned_content[segment_start:segment_end]
                    matches.append((segment_start, full_segment, segment_info))
                    start = pos + 1
                
                segments_to_remove.extend(matches)
        
        # Remove duplicates and sort by position (descending)
        unique_segments = {}
        for start_pos, segment_text, segment_info in segments_to_remove:
            key = (start_pos, len(segment_text))
            if key not in unique_segments:
                unique_segments[key] = (start_pos, segment_text, segment_info)
        
        sorted_segments = sorted(unique_segments.values(), 
                               key=lambda x: x[0], reverse=True)
        
        # Apply removal
        for start_pos, segment_text, segment_info in sorted_segments:
            if not dry_run:
                # Remove the segment
                cleaned_content = (cleaned_content[:start_pos] + 
                                 cleaned_content[start_pos + len(segment_text):])
            
            removed_segments.append({
                "hash": segment_info["hash"],
                "text": segment_text[:100] + "..." 
                       if len(segment_text) > 100 else segment_text,
                "confidence": segment_info["confidence_score"],
                "length": len(segment_text),
                "position": start_pos,
                "pattern_type": segment_info.get("pattern_type", "unknown")
            })
        
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
    
    def _find_common_segments_improved(self, articles: List[Dict]) -> Dict:
        """Find text segments using multiple improved strategies."""
        segment_occurrences = defaultdict(lambda: {
            "count": 0,
            "text": "",
            "positions": [],
            "article_ids": [],
            "pattern_type": "unknown"
        })
        
        for article in articles:
            content = article["content"]
            article_id = article["id"]
            
            # Strategy 1: Large blocks (navigation menus, headers)
            blocks = self._extract_large_blocks(content)
            self._process_segments(blocks, "large_block", segment_occurrences, 
                                 content, article_id)
            
            # Strategy 2: Paragraph-level segments
            paragraphs = self._extract_paragraphs(content)
            self._process_segments(paragraphs, "paragraph", segment_occurrences,
                                 content, article_id)
            
            # Strategy 3: Navigation-like patterns
            nav_patterns = self._extract_navigation_patterns(content)
            self._process_segments(nav_patterns, "navigation", segment_occurrences,
                                 content, article_id)
            
            # Strategy 4: Footer-like patterns
            footer_patterns = self._extract_footer_patterns(content)
            self._process_segments(footer_patterns, "footer", segment_occurrences,
                                 content, article_id)
        
        return segment_occurrences
    
    def _extract_large_blocks(self, content: str) -> List[Tuple[str, int, int]]:
        """Extract large text blocks that might be navigation or headers."""
        blocks = []
        
        # Look for blocks at the beginning of content (first 1000 chars)
        if len(content) > 100:
            # Try different block sizes
            for block_size in [200, 300, 400, 500]:
                if len(content) >= block_size:
                    block = content[:block_size].strip()
                    if len(block) > 50:  # Minimum block size
                        blocks.append((block, 0, block_size))
        
        # Look for blocks at the end of content (last 500 chars)
        if len(content) > 500:
            for block_size in [100, 200, 300]:
                if len(content) >= block_size:
                    start_pos = len(content) - block_size
                    block = content[start_pos:].strip()
                    if len(block) > 30:
                        blocks.append((block, start_pos, len(content)))
        
        return blocks
    
    def _extract_paragraphs(self, content: str) -> List[Tuple[str, int, int]]:
        """Extract paragraph-level segments."""
        segments = []
        
        # Split on double newlines
        paragraphs = content.split('\n\n')
        current_pos = 0
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if len(paragraph) > 50:  # Minimum paragraph length
                start_pos = content.find(paragraph, current_pos)
                if start_pos != -1:
                    end_pos = start_pos + len(paragraph)
                    segments.append((paragraph, start_pos, end_pos))
                    current_pos = end_pos
        
        return segments
    
    def _extract_navigation_patterns(self, content: str) -> List[Tuple[str, int, int]]:
        """Extract patterns that look like navigation menus."""
        patterns = []
        
        # Look for repeated words that suggest navigation
        nav_keywords = [
            'news', 'sports', 'obituaries', 'contact', 'subscribe', 'home',
            'about', 'business', 'opinion', 'world', 'local', 'weather',
            'e-edition', 'magazines', 'gallery', 'photo', 'video'
        ]
        
        # Find text that contains multiple navigation keywords
        words = content.lower().split()
        nav_word_count = sum(1 for word in words if any(keyword in word for keyword in nav_keywords))
        
        # If high density of nav words, look for the containing block
        if nav_word_count >= 5:
            # Find continuous blocks with high nav word density
            block_size = 300
            for i in range(0, min(len(content), 1000), 50):
                block = content[i:i + block_size]
                block_words = block.lower().split()
                block_nav_count = sum(1 for word in block_words 
                                    if any(keyword in word for keyword in nav_keywords))
                
                if len(block_words) > 0 and block_nav_count / len(block_words) > 0.3:
                    patterns.append((block.strip(), i, i + len(block)))
        
        return patterns
    
    def _extract_footer_patterns(self, content: str) -> List[Tuple[str, int, int]]:
        """Extract patterns that look like footers."""
        patterns = []
        
        footer_keywords = [
            'copyright', 'rights reserved', 'privacy', 'terms', 'sitemap',
            'sign up', 'newsletter', 'follow us', 'contact us'
        ]
        
        # Look at the last 500 characters for footer patterns
        if len(content) > 200:
            footer_section = content[-500:]
            footer_words = footer_section.lower().split()
            footer_keyword_count = sum(1 for word in footer_words
                                     if any(keyword in word for keyword in footer_keywords))
            
            if footer_keyword_count >= 2:
                start_pos = len(content) - 500
                patterns.append((footer_section.strip(), start_pos, len(content)))
        
        return patterns
    
    def _process_segments(self, segments: List[Tuple[str, int, int]], 
                         pattern_type: str, segment_occurrences: Dict,
                         content: str, article_id: str):
        """Process extracted segments and add to occurrences."""
        for segment_text, start_pos, end_pos in segments:
            if len(segment_text.strip()) < 30:  # Skip very short segments
                continue
            
            segment_hash = hashlib.sha256(
                segment_text.strip().encode()
            ).hexdigest()
            
            # Calculate position percentages
            content_length = len(content)
            start_pct = (start_pos / content_length if content_length > 0 else 0)
            end_pct = (end_pos / content_length if content_length > 0 else 0)
            
            segment_occurrences[segment_hash]["count"] += 1
            segment_occurrences[segment_hash]["text"] = segment_text.strip()
            segment_occurrences[segment_hash]["positions"].append((start_pct, end_pct))
            segment_occurrences[segment_hash]["article_ids"].append(article_id)
            segment_occurrences[segment_hash]["pattern_type"] = pattern_type
    
    def _score_segment(self, segment_data: Dict, domain: str, 
                      total_articles: int) -> BoilerplateMatch:
        """Score a segment for boilerplate likelihood."""
        text = segment_data["text"]
        occurrence_count = segment_data["count"]
        positions = segment_data["positions"]
        pattern_type = segment_data.get("pattern_type", "unknown")
        
        # Calculate confidence using improved rules
        confidence = self._calculate_improved_confidence(
            text, occurrence_count, total_articles, positions, pattern_type
        )
        
        segment_hash = hashlib.sha256(text.encode()).hexdigest()
        
        return BoilerplateMatch(
            text=text,
            hash_value=segment_hash,
            occurrence_count=occurrence_count,
            confidence_score=confidence,
            domains=[domain],
            positions=positions,
            pattern_type=pattern_type
        )
    
    def _calculate_improved_confidence(self, text: str, occurrence_count: int,
                                     total_articles: int, 
                                     positions: List[Tuple[float, float]],
                                     pattern_type: str) -> float:
        """Calculate confidence score with improved logic."""
        text_lower = text.lower()
        confidence = 0.0
        
        # Base occurrence frequency (0-0.3 points)
        occurrence_ratio = occurrence_count / total_articles
        confidence += min(occurrence_ratio * 0.6, 0.3)
        
        # Pattern type bonus (0-0.2 points)
        pattern_bonuses = {
            "navigation": 0.2,
            "large_block": 0.15,
            "footer": 0.15,
            "paragraph": 0.1,
            "unknown": 0.0
        }
        confidence += pattern_bonuses.get(pattern_type, 0.0)
        
        # Position consistency (0-0.2 points)
        if positions:
            start_positions = [pos[0] for pos in positions]
            end_positions = [pos[1] for pos in positions]
            
            start_std = self._calculate_std(start_positions)
            end_std = self._calculate_std(end_positions)
            
            position_consistency = 1.0 - (start_std + end_std) / 2
            confidence += position_consistency * 0.2
        
        # Content patterns (0-0.2 points)
        nav_terms = [
            "news", "sports", "obituaries", "contact", "subscribe", "home",
            "e-edition", "magazines", "gallery", "business", "opinion"
        ]
        
        footer_terms = [
            "copyright", "privacy", "terms", "sitemap", "newsletter",
            "follow us", "sign up", "rights reserved"
        ]
        
        nav_matches = sum(1 for term in nav_terms if term in text_lower)
        footer_matches = sum(1 for term in footer_terms if term in text_lower)
        
        pattern_score = max(
            nav_matches / len(nav_terms),
            footer_matches / len(footer_terms)
        )
        confidence += pattern_score * 0.2
        
        # Position bias - beginning/end content more likely boilerplate (0-0.1 points)
        if positions:
            avg_start = sum(pos[0] for pos in positions) / len(positions)
            avg_end = sum(pos[1] for pos in positions) / len(positions)
            
            if avg_start < 0.1 or avg_end > 0.9:  # Very beginning or end
                confidence += 0.1
            elif avg_start < 0.2 or avg_end > 0.8:  # Near beginning or end
                confidence += 0.05
        
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
    
    def _get_segment_texts(self) -> Dict[str, str]:
        """Get mapping of segment hashes to texts (placeholder)."""
        # This would need to be implemented to store/retrieve segment texts
        return {}


def create_improved_content_cleaner(db_path: str) -> ImprovedContentCleaner:
    """Factory function to create an improved content cleaner."""
    return ImprovedContentCleaner(db_path=db_path)