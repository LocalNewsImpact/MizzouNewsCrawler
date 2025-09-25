#!/usr/bin/env python3

import sqlite3
import re
from typing import List, Dict, Tuple, Set
from collections import defaultdict
import logging


class TwoPhaseContentCleaner:
    """
    Two-phase content cleaner:
    1. Phase 1: Find rough matches using simple text blocks
    2. Phase 2: Refine boundaries to ensure exact duplicate matching
    """
    
    def __init__(self, db_path: str = "data/mizzou.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
    
    def analyze_domain(self, domain: str, sample_size: int = None, 
                      min_occurrences: int = 3) -> Dict:
        """Analyze domain using two-phase approach."""
        self.logger.info(f"Analyzing domain: {domain}")
        
        articles = self._get_articles_for_domain(domain, sample_size)
        if len(articles) < min_occurrences:
            return {"domain": domain, "article_count": len(articles), 
                   "segments": []}
        
        # Phase 1: Find rough candidate segments
        self.logger.info("Phase 1: Finding rough candidate segments...")
        rough_candidates = self._find_rough_candidates(articles)
        
        # Phase 2: Refine boundaries for exact matching
        self.logger.info("Phase 2: Refining boundaries for exact matching...")
        exact_segments = self._refine_boundaries(articles, rough_candidates, 
                                                min_occurrences)
        
        # Calculate statistics
        stats = self._calculate_domain_stats(articles, exact_segments)
        
        return {
            "domain": domain,
            "article_count": len(articles),
            "segments": exact_segments,
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
    
    def _find_rough_candidates(self, articles: List[Dict]) -> Dict[str, Set[str]]:
        """
        Phase 1: Find rough candidate segments using simple methods.
        Returns: {candidate_text: {article_ids that contain it}}
        """
        candidates = defaultdict(set)
        
        for article in articles:
            content = article["content"]
            article_id = str(article["id"])
            
            # Method 1: Extract sentences (split on periods)
            sentences = re.split(r'\.[\s\n]+', content)
            for sentence in sentences:
                sentence = sentence.strip()
                if 30 <= len(sentence) <= 300:  # Reasonable sentence length
                    # Normalize whitespace for rough matching
                    normalized = re.sub(r'\s+', ' ', sentence)
                    candidates[normalized].add(article_id)
            
            # Method 2: Extract lines that might be navigation/headers
            lines = content.split('\n')
            for line in lines:
                line = line.strip()
                if 20 <= len(line) <= 200:  # Reasonable line length
                    normalized = re.sub(r'\s+', ' ', line)
                    candidates[normalized].add(article_id)
            
            # Method 3: Extract paragraphs
            paragraphs = re.split(r'\n\s*\n', content)
            for paragraph in paragraphs:
                paragraph = paragraph.strip()
                if 40 <= len(paragraph) <= 500:  # Reasonable paragraph length
                    normalized = re.sub(r'\s+', ' ', paragraph)
                    candidates[normalized].add(article_id)
        
        # Filter candidates that appear in multiple articles
        filtered_candidates = {
            text: article_ids 
            for text, article_ids in candidates.items()
            if len(article_ids) >= 2  # Appears in at least 2 articles
        }
        
        self.logger.info(f"Found {len(filtered_candidates)} rough candidates")
        return filtered_candidates
    
    def _refine_boundaries(self, articles: List[Dict], 
                          rough_candidates: Dict[str, Set[str]], 
                          min_occurrences: int) -> List[Dict]:
        """
        Phase 2: Refine boundaries to find exact duplicate segments.
        """
        exact_segments = []
        articles_by_id = {str(article["id"]): article for article in articles}
        
        for candidate_text, candidate_article_ids in rough_candidates.items():
            if len(candidate_article_ids) < min_occurrences:
                continue
            
            # Find exact matches of this candidate text in each article
            exact_matches = self._find_exact_boundaries(
                candidate_text, candidate_article_ids, articles_by_id
            )
            
            if len(exact_matches) >= min_occurrences:
                # Calculate position consistency
                position_consistency = self._calculate_position_consistency(
                    exact_matches, articles_by_id
                )
                
                # Only keep segments with reasonable consistency
                if position_consistency > 0.2:
                    segment = {
                        "text": candidate_text,
                        "length": len(candidate_text),
                        "occurrences": len(exact_matches),
                        "article_ids": list(exact_matches.keys()),
                        "positions": exact_matches,
                        "position_consistency": position_consistency,
                        "pattern_type": self._classify_pattern(candidate_text)
                    }
                    exact_segments.append(segment)
        
        # Sort by occurrences and length
        exact_segments.sort(key=lambda x: (x["occurrences"], x["length"]), 
                           reverse=True)
        
        self.logger.info(f"Refined to {len(exact_segments)} exact segments")
        return exact_segments
    
    def _find_exact_boundaries(self, candidate_text: str, 
                              candidate_article_ids: Set[str], 
                              articles_by_id: Dict[str, Dict]) -> Dict[str, List[Tuple[int, int]]]:
        """
        Find exact boundaries where candidate_text appears in each article.
        Returns: {article_id: [(start, end), ...]}
        """
        exact_matches = {}
        
        for article_id in candidate_article_ids:
            article = articles_by_id[article_id]
            content = article["content"]
            
            # Find all exact occurrences of the candidate text
            positions = []
            search_start = 0
            
            while True:
                # Try to find the exact candidate text
                pos = content.find(candidate_text, search_start)
                if pos == -1:
                    break
                
                end_pos = pos + len(candidate_text)
                positions.append((pos, end_pos))
                search_start = pos + 1
            
            # If we found exact matches, record them
            if positions:
                exact_matches[article_id] = positions
        
        return exact_matches
    
    def _calculate_position_consistency(self, exact_matches: Dict[str, List[Tuple[int, int]]], 
                                       articles_by_id: Dict[str, Dict]) -> float:
        """Calculate position consistency (0.0 to 1.0)."""
        if len(exact_matches) < 2:
            return 0.0
        
        # Get relative positions as fraction of content length
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
    
    def clean_article_content(self, content: str, 
                             segments_to_remove: List[Dict]) -> str:
        """Remove exact duplicate segments from article content."""
        cleaned_content = content
        
        # Sort segments by length (longest first) to avoid partial removals
        segments_sorted = sorted(segments_to_remove, 
                               key=lambda x: x["length"], reverse=True)
        
        for segment in segments_sorted:
            segment_text = segment["text"]
            # Remove all exact occurrences
            cleaned_content = cleaned_content.replace(segment_text, "")
        
        # Clean up extra whitespace
        cleaned_content = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_content)
        cleaned_content = re.sub(r'^\s+|\s+$', '', cleaned_content)
        
        return cleaned_content