#!/usr/bin/env python3

import sqlite3
import re
from typing import Any, List, Dict, Tuple, Set, Optional
from collections import defaultdict
import logging
import json
from datetime import datetime

from .content_cleaning_telemetry import ContentCleaningTelemetry
from .byline_cleaner import BylineCleaner

NAVIGATION_KEYWORDS: Set[str] = {
    "news",
    "home",
    "local",
    "sports",
    "obituaries",
    "e-edition",
    "eedition",
    "magazines",
    "weekly",
    "record",
    "records",
    "a&e",
    "opinion",
    "world",
    "contact",
    "us",
    "support",
    "guide",
    "all",
    "sections",
    "business",
    "submitted",
    "religion",
    "history",
    "ageless",
    "community",
    "events",
    "photos",
    "videos",
    "lifestyle",
    "calendar",
    "jobs",
    "classifieds",
    "marketplace",
    "homes",
    "autos",
    "semoball",
    "health",
    "arts",
    "entertainment",
    "arts&entertainment",
    "photo",
    "video",
    "records",
    "difference",
    "makers",
    "shopping",
    "speak",
    "out",
    "links",
    "submit",
    "submission",
    "forms",
    "support",
    "guide",
    "newsletters",
    "terms",
    "service",
    "ai",
    "policy",
}

SUPPRESSIBLE_WIRE_PROVIDERS: Set[str] = {
    'CNN NewsSource',
    'CNN',
    'NPR',
    'PBS',
}

SOCIAL_SHARE_WORDS: Set[str] = {
    "facebook",
    "twitter",
    "whatsapp",
    "linkedin",
    "sms",
    "email",
    "print",
    "copy",
    "article",
    "link",
    "save",
    "share",
    "story",
    "this",
    "messenger",
    "telegram",
    "pinterest",
    "reddit",
    "flipboard",
    "comments",
    "comment",
    "text",
    "thread",
    "send",
    "on",
    "via",
    "to",
}

SOCIAL_SHARE_PHRASES = (
    "share this story",
    "share this article",
    "share on facebook",
    "share on twitter",
    "follow us on facebook",
    "share via",
)

SOCIAL_SHARE_PREFIX_SEPARATORS = " \t\u2022•|-–—:\u00b7·"


class BalancedBoundaryContentCleaner:
    """
    Balanced content cleaner that removes segments with reasonable boundaries,
    avoiding obvious partial sentences while not being overly restrictive.
    """

    def __init__(
        self,
        db_path: str = "data/mizzou.db",
        enable_telemetry: bool = True,
    ):
        self.db_path = db_path
        self.enable_telemetry = enable_telemetry
        self.logger = logging.getLogger(__name__)
        self.telemetry = ContentCleaningTelemetry(
            enable_telemetry=enable_telemetry
        )

        # Initialize wire service detector
        self.wire_detector = BylineCleaner()

    def _connect_to_db(self) -> sqlite3.Connection:
        """Create a new SQLite connection with consistent timeout settings."""
        return sqlite3.connect(
            self.db_path,
            timeout=10,
            check_same_thread=False,
        )

    def analyze_domain(
        self,
        domain: str,
        sample_size: int = None,
        min_occurrences: int = 3,
    ) -> Dict:  # pragma: no cover
        """Analyze domain with balanced boundary requirements."""
        self.logger.info(f"Analyzing domain: {domain}")

        articles = self._get_articles_for_domain(domain, sample_size)

        # Check if we have persistent patterns for this domain first
        persistent_segments = self._get_persistent_patterns_for_domain(domain)

        # If we have persistent patterns, use them regardless of article count
        if persistent_segments:
            self.logger.info(
                "Using %d persistent patterns for %s",
                len(persistent_segments),
                domain,
            )

            stats = self._calculate_domain_stats(articles, persistent_segments)
            return {
                "domain": domain,
                "article_count": len(articles),
                "segments": persistent_segments,
                "stats": stats
            }

        # Otherwise, use the minimum article threshold (now 3 instead of 5)
        if len(articles) < min_occurrences:
            return {
                "domain": domain,
                "article_count": len(articles),
                "segments": [],
            }

        # Start telemetry session
        telemetry_id = self.telemetry.start_cleaning_session(
            domain=domain,
            article_count=len(articles),
            min_occurrences=min_occurrences,
            min_boundary_score=0.3
        )

        # Phase 1: Find candidates (same as before)
        rough_candidates = self._find_rough_candidates(articles)

        # Phase 2: Balanced boundary filtering
        balanced_segments = self._filter_with_balanced_boundaries(
            articles, rough_candidates, min_occurrences, telemetry_id
        )

        # Filter segments by minimum length (150 characters)
        # unless high-confidence, and detect wire services
        length_filtered_segments = []
        wire_detected = None

        for seg in balanced_segments:
            text = seg.get('text', '')

            # Check for wire service detection in any segment
            if not wire_detected:
                wire_service_info = self._detect_wire_service_in_pattern(
                    text, domain)
                if wire_service_info:
                    wire_detected = wire_service_info
                    if self.enable_telemetry:
                        self.telemetry.log_wire_detection(
                            provider=wire_service_info['provider'],
                            detection_method=wire_service_info[
                                'detection_method'
                            ],
                            pattern_text=text,
                            confidence=wire_service_info['confidence'],
                            detection_stage='domain_analysis_segment',
                            article_ids=seg.get('article_ids', []),
                            domain=domain,
                            extra_metadata={
                                'pattern_type': seg.get('pattern_type'),
                                'segment_length': len(text),
                            },
                        )
                    # Note: We don't have article_id in domain analysis
                    # Wire detection will be logged but not saved to DB
                    self.logger.info(
                        f"Wire service detected in {domain} segment: "
                        f"{wire_detected['provider']}")

            if (len(text) >= 150 or
                    self._is_high_confidence_boilerplate(text)):
                length_filtered_segments.append(seg)

        # Calculate statistics
        stats = self._calculate_domain_stats(articles,
                                             length_filtered_segments)

        # Finalize telemetry
        self.telemetry.finalize_cleaning_session(
            rough_candidates_found=len(rough_candidates),
            segments_detected=len(length_filtered_segments),
            total_removable_chars=stats['total_removable_chars'],
            removal_percentage=stats['removal_percentage']
        )

        return {
            "domain": domain,
            "article_count": len(articles),
            "segments": length_filtered_segments,
            "stats": stats
        }

    def _get_persistent_patterns_for_domain(
        self,
        domain: str,
    ) -> List[Dict]:  # pragma: no cover
        """Get stored persistent patterns for a domain."""
        conn = self._connect_to_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT text_content, pattern_type, confidence_score
            FROM persistent_boilerplate_patterns
            WHERE domain = ?
        """, (domain,))

        patterns = []
        for row in cursor.fetchall():
            patterns.append({
                "text": row[0],
                "pattern_type": row[1],
                "boundary_score": row[2],
                "occurrences": 1,  # Persistent patterns are pre-validated
                "length": len(row[0]),
                "article_ids": [],  # Will be populated during analysis
                "positions": {},  # Will be populated during analysis
                "position_consistency": 1.0,  # Perfect for stored patterns
                "removal_reason": f"Persistent {row[1]} pattern"
            })

        conn.close()
        return patterns

    def _get_articles_for_domain(
        self,
        domain: str,
        sample_size: int = None,
    ) -> List[Dict]:  # pragma: no cover
        """Get articles for a specific domain."""
        conn = self._connect_to_db()
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

    def _find_rough_candidates(
        self,
        articles: List[Dict],
    ) -> Dict[str, Set[str]]:  # pragma: no cover
        """Find rough candidates using multiple methods."""
        candidates = defaultdict(set)

        for article in articles:
            content = article["content"]
            article_id = str(article["id"])

            # Method 1: Sentences
            sentences = re.split(r'[.!?]+\s+', content)
            for sentence in sentences:
                sentence = sentence.strip()
                if 30 <= len(sentence) <= 600:
                    normalized = re.sub(r'\s+', ' ', sentence)
                    candidates[normalized].add(article_id)

            # Method 2: Paragraphs
            paragraphs = re.split(r'\n\s*\n', content)
            for paragraph in paragraphs:
                paragraph = paragraph.strip()
                if 40 <= len(paragraph) <= 1200:
                    normalized = re.sub(r'\s+', ' ', paragraph)
                    candidates[normalized].add(article_id)

            # Method 3: Lines (for navigation)
            lines = content.split('\n')
            for line in lines:
                line = line.strip()
                if 20 <= len(line) <= 1200:
                    normalized = re.sub(r'\s+', ' ', line)
                    candidates[normalized].add(article_id)

            # Method 4: Leading navigation prefix without separators
            nav_prefix = self._extract_navigation_prefix(content)
            if nav_prefix:
                normalized = re.sub(r'\s+', ' ', nav_prefix.strip())
                if 50 <= len(normalized) <= 400:
                    candidates[normalized].add(article_id)

        # Filter candidates
        filtered_candidates = {
            text: article_ids
            for text, article_ids in candidates.items()
            if len(article_ids) >= 2
        }

        self.logger.info(f"Found {len(filtered_candidates)} rough candidates")
        return filtered_candidates

    @staticmethod
    def _normalize_navigation_token(token: str) -> str:
        """Normalize navigation token for keyword matching."""
        if not token:
            return ""

        normalized = token.lower()
        normalized = normalized.replace("’", "'")
        normalized = normalized.replace("—", "-")
        normalized = normalized.replace("–", "-")

    # Treat common navigation separators as spacing to preserve order
        normalized = re.sub(r"[>\u00bb\u203a|/:]+", " ", normalized)
        normalized = normalized.replace("&", " & ")

        # Remove residual punctuation (keep hyphen for e-edition style tokens)
        normalized = re.sub(r"[^a-z0-9\-\s&]", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        if not normalized:
            return ""

        for part in normalized.split():
            part_clean = part.strip("-")
            if not part_clean:
                continue
            if part_clean in NAVIGATION_KEYWORDS:
                return part_clean

        # Fall back to the compact form if no keyword match is found
        return normalized.replace(" ", "")

    def _extract_navigation_prefix(self, content: str) -> Optional[str]:
        """Extract repeated navigation clusters at the start of content."""
        if not content:
            return None

        snippet = content.lstrip()
        if not snippet:
            return None

        snippet = snippet[:400]
        matches = list(re.finditer(r"\S+", snippet))
        if not matches:
            return None

        allowed_hits = []
        keyword_hits: Set[str] = set()
        end_index = None
        seen_connector = False

        def _is_connector(raw_token: str) -> bool:
            return bool(
                re.fullmatch(r"[>\u00bb\u203a|/\\•·\u2022]+", raw_token)
                or re.fullmatch(r"[-–—]+", raw_token)
            )

        for match in matches:
            token = match.group()
            if _is_connector(token):
                seen_connector = True
                continue

            normalized = self._normalize_navigation_token(token)
            if normalized and normalized in NAVIGATION_KEYWORDS:
                allowed_hits.append(match)
                keyword_hits.add(normalized)
                end_index = match.end()
                continue

            # Any other token terminates the navigation cluster
            break

        if not allowed_hits or end_index is None:
            return None

        # Require a sufficiently rich navigation cluster
        if len(allowed_hits) < 3:
            return None

        # Ensure hallmark navigation terms are present
        required_tokens = {"news", "sports"}
        if not required_tokens.issubset(keyword_hits):
            return None

        if (not seen_connector and "sections" not in keyword_hits
                and "all" not in keyword_hits):
            return None

        return snippet[:end_index].strip()

    def _filter_with_balanced_boundaries(
        self,
        articles: List[Dict],
        rough_candidates: Dict[str, Set[str]],
        min_occurrences: int,
        telemetry_id: str,
    ) -> List[Dict]:
        """Filter candidates using balanced boundary rules."""
        balanced_segments = []
        articles_by_id = {str(article["id"]): article for article in articles}

        for candidate_text, candidate_article_ids in rough_candidates.items():
            if len(candidate_article_ids) < min_occurrences:
                continue

            # Check if this candidate has reasonable boundaries
            boundary_score = self._assess_boundary_quality(candidate_text)

            # Skip obvious partial sentences
            if boundary_score < 0.3:
                # Log rejected segment
                self.telemetry.log_segment_detection(
                    segment_text=candidate_text,
                    boundary_score=boundary_score,
                    occurrences=len(candidate_article_ids),
                    pattern_type="rejected",
                    position_consistency=0.0,
                    segment_length=len(candidate_text),
                    article_ids=list(candidate_article_ids),
                    was_removed=False,
                    removal_reason=f"Low boundary score: {boundary_score:.2f}"
                )
                continue

            # Find exact matches
            exact_matches = {}
            for article_id in candidate_article_ids:
                article = articles_by_id[article_id]
                content = article["content"]

                positions = []
                search_start = 0

                while True:
                    pos = content.find(candidate_text, search_start)
                    if pos == -1:
                        break

                    end_pos = pos + len(candidate_text)
                    positions.append((pos, end_pos))
                    search_start = pos + 1

                if positions:
                    exact_matches[article_id] = positions

            # Keep if still meets minimum after filtering
            if len(exact_matches) >= min_occurrences:
                position_consistency = self._calculate_position_consistency(
                    exact_matches, articles_by_id
                )

                if position_consistency > 0.2:
                    pattern_type = self._classify_pattern(candidate_text)
                    removal_reason = self._generate_removal_reason(
                        candidate_text,
                        pattern_type,
                        boundary_score,
                        len(exact_matches),
                    )

                    segment = {
                        "text": candidate_text,
                        "length": len(candidate_text),
                        "occurrences": len(exact_matches),
                        "article_ids": list(exact_matches.keys()),
                        "positions": exact_matches,
                        "position_consistency": position_consistency,
                        "pattern_type": pattern_type,
                        "boundary_score": boundary_score,
                        "removal_reason": removal_reason
                    }
                    balanced_segments.append(segment)

                    # Log accepted segment with detailed reasoning
                    self.telemetry.log_segment_detection(
                        segment_text=candidate_text,
                        boundary_score=boundary_score,
                        occurrences=len(exact_matches),
                        pattern_type=pattern_type,
                        position_consistency=position_consistency,
                        segment_length=len(candidate_text),
                        article_ids=list(exact_matches.keys()),
                        was_removed=True,
                        removal_reason=removal_reason
                    )

        # Sort by occurrences and boundary score
        balanced_segments.sort(
            key=lambda x: (x["occurrences"], x["boundary_score"], x["length"]),
            reverse=True
        )

        self.logger.info(
            f"Filtered to {len(balanced_segments)} balanced segments")
        return balanced_segments

    def _assess_boundary_quality(self, text: str) -> float:
        """
        Assess boundary quality of text (0.0 to 1.0).
        Higher score = better boundaries.
        """
        text = text.strip()
        score = 0.0

        # Check start boundary
        if text[0].isupper():
            score += 0.3
        elif text.lower().startswith(('the ', 'a ', 'an ', 'to ', 'if ', 'we ', 'watch ', 'post ')):
            score += 0.2
        elif text[0].islower():
            score -= 0.3  # Penalty for lowercase start

        # Check end boundary
        if text.endswith(('.', '!', '?')):
            score += 0.3
        elif text.endswith((':', ';', '"', "'")):
            score += 0.2
        elif text.endswith((',', '...', ' and', ' or', ' but')):
            score -= 0.3  # Penalty for obvious fragments

        # Check for obvious mid-sentence fragments
        if any(fragment in text.lower() for fragment in [
            'each comment to let us know',
            'person will not be tolerated',
            'that is degrading to another',
            'racist or sexually-oriented'
        ]):
            score -= 0.5

        # HIGH PRIORITY: Sidebar content and promotional content (should be
        # removed)
        sidebar_indicators = [
            'watch this discussion',
            'post a comment',
            'get an email notification',
            'news updates would you like',
            'receive daily headlines',
            'sign up today',
            'related posts',
            'trending now',
            'most read',
            'popular stories',
            'related articles',
            'you may also like',
            'recommended for you'
        ]

        # Check for headline list patterns (multiple titles concatenated)
        headline_indicators = [
            # Sports results
            r'\w+ \w+ \w+ (defeats?|beats?|wins?|loses?) \w+ \w+',
            # More sports
            r'\w+ (strikes?|place[sd]?|has) .+ (defeat|win|place)',
            r'[A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]+',  # Multiple proper names
        ]

        is_sidebar_content = any(pattern in text.lower()
                                 for pattern in sidebar_indicators)
        has_headline_pattern = any(re.search(pattern, text)
                                   for pattern in headline_indicators)

        # Check for multiple headlines concatenated (common in right-rail)
        proper_name_matches = re.findall(r'[A-Z][a-z]+ [A-Z][a-z]+', text)
        has_multiple_headlines = len(proper_name_matches) > 3

        # Boost score for sidebar/headline content - we want to remove it
        if is_sidebar_content or has_headline_pattern or has_multiple_headlines:
            score += 0.4  # Strong boost for removal

        # Bonus for complete-looking phrases
        if any(pattern in text.lower() for pattern in [
            'watch this discussion',
            'post a comment',
            'please turn off your caps lock',
            'start watching',
            'stop watching'
        ]):
            score += 0.3

        # Bonus for navigation/UI patterns
        nav_patterns = [
            r'^\w+ \w+ \w+$',  # Three words (often navigation)
            r'^(Start|Stop|Watch|Post|Cancel)',  # Action words
            r'(discussion|comment|notification)$',  # UI endings
        ]

        for pattern in nav_patterns:
            if re.search(pattern, text):
                score += 0.2
                break

        # LOWER PRIORITY: Author bio patterns (less aggressive removal)
        bio_patterns = [
            'retired as editor',
            'can be reached at',
            'her collective works',
            'researches and writes'
        ]

        is_author_bio = any(pattern in text.lower()
                            for pattern in bio_patterns)
        if is_author_bio:
            score -= 0.2  # Slight penalty - less likely to remove

        return max(0.0, min(1.0, score))

    def _calculate_position_consistency(self,
                                        exact_matches: Dict[str,
                                                            List[Tuple[int,
                                                                       int]]],
                                        articles_by_id: Dict[str,
                                                             Dict]) -> float:
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

        mean_pos = sum(relative_positions) / len(relative_positions)
        variance = sum((pos - mean_pos) ** 2
                       for pos in relative_positions) / len(relative_positions)

        consistency = max(0.0, 1.0 - (variance * 5))
        return min(1.0, consistency)

    def _classify_pattern(self, text: str) -> str:
        """Classify the type of pattern based on content."""
        text_lower = text.lower()

        # Sidebar/headline list indicators
        sidebar_patterns = [
            'watch this discussion',
            'post a comment',
            'get an email notification',
            'news updates would you like',
            'receive daily headlines',
            'sign up today',
            'related posts'
        ]

        # Multiple headline pattern (common in right-rail)
        # Look for patterns like "Team A defeats Team B" followed by other
        # headlines
        # NOTE: headline_patterns is defined but not used in current version
        _headline_patterns = [  # noqa: F841
            r'[A-Z][a-z]+ (defeats?|beats?|wins?|loses?) [A-Z][a-z]+',
            # Multiple proper names
            r'[A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]+',
            r'\w+ (at|vs|versus) \w+',  # Sports matchups
            # Location-based headlines
            r'[A-Z][a-z]+ \w+ \w+ (in|at|from|over) [A-Z][a-z]+',
        ]

        # Check for sidebar content
        is_sidebar_content = any(
            pattern in text_lower for pattern in sidebar_patterns)
        has_multiple_headlines = len(
            re.findall(
                r'[A-Z][a-z]+ [A-Z][a-z]+',
                text)) > 3

        if is_sidebar_content or has_multiple_headlines:
            return "sidebar"

        # Navigation keywords
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

        # Footer keywords
        footer_keywords = ['copyright', 'rights reserved', 'privacy', 'terms']
        footer_count = sum(1 for keyword in footer_keywords
                           if keyword in text_lower)

        # Subscription keywords
        sub_keywords = ['subscribe', 'subscription', 'paywall', 'premium',
                        'member account', 'print subscriber', 'website account']
        sub_count = sum(1 for keyword in sub_keywords
                        if keyword in text_lower)

        # Trending content
        trending_keywords = ['trending', 'most read', 'popular stories',
                             'recommended for you', 'you may also like']
        trending_count = sum(1 for keyword in trending_keywords
                             if keyword in text_lower)

        if nav_count >= 2:
            return "navigation"
        elif footer_count >= 1:
            return "footer"
        elif sub_count >= 1:
            return "subscription"
        elif trending_count >= 1:
            return "trending"
        else:
            return "other"

    def _generate_removal_reason(
            self,
            text: str,
            pattern_type: str,
            boundary_score: float,
            occurrences: int) -> str:
        """Generate detailed removal reason based on pattern analysis."""
        text_lower = text.lower()
        reasons = []

        # Pattern-specific reasoning
        if pattern_type == "sidebar":
            if any(
                p in text_lower for p in [
                    'watch this discussion',
                    'post a comment']):
                reasons.append("Discussion prompts in sidebar")
            elif any(p in text_lower for p in ['news updates', 'daily headlines', 'sign up']):
                reasons.append("Newsletter signup prompts")
            elif len(text.split()) > 10:  # Longer text
                reasons.append("Multi-headline sidebar content")
            else:
                reasons.append("Sidebar navigation element")

        elif pattern_type == "subscription":
            if "print subscriber" in text_lower:
                reasons.append("Print subscriber account setup")
            elif "member account" in text_lower:
                reasons.append("Member account login prompt")
            elif "paywall" in text_lower or "premium" in text_lower:
                reasons.append("Paywall content restriction")
            else:
                reasons.append("Subscription requirement notice")

        elif pattern_type == "navigation":
            reasons.append("Site navigation menu")

        elif pattern_type == "footer":
            reasons.append("Page footer content")

        elif pattern_type == "trending":
            reasons.append("Trending/recommended articles section")

        else:  # "other"
            # Analyze content for more specific categorization
            if any(
                p in text_lower for p in [
                    'defeated',
                    'beats',
                    'wins',
                    'loses']):
                reasons.append("Sports results headline list")
            elif len(text.split('\n')) > 1:
                reasons.append("Multi-line content block")
            elif text.count(',') > 3:
                reasons.append("Comma-separated list content")
            else:
                reasons.append("Repeated content segment")

        # Add confidence indicators
        confidence_desc = ""
        if boundary_score >= 0.8:
            confidence_desc = "high confidence"
        elif boundary_score >= 0.6:
            confidence_desc = "medium confidence"
        else:
            confidence_desc = "low confidence"

        # Add occurrence context
        occurrence_desc = f"appears {occurrences}x across articles"

        # Combine reasons
        reason_text = "; ".join(reasons)
        full_reason = f"{reason_text} ({confidence_desc}, {occurrence_desc})"

        return full_reason

    def _calculate_domain_stats(self, articles: List[Dict],
                                segments: List[Dict]) -> Dict:
        """Calculate statistics for the domain analysis."""
        total_removable_chars = 0
        affected_articles = set()

        for segment in segments:
            text_content = segment.get("text_content", "")
            segment_length = segment.get("length")
            if segment_length is None:
                segment_length = len(text_content)

            occurrences = segment.get("occurrences") or 1

            total_removable_chars += segment_length * occurrences

            article_ids = segment.get("article_ids") or []
            affected_articles.update(str(article_id)
                                     for article_id in article_ids)

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

    def _remove_persistent_patterns(self, text: str, domain: str,
                                    article_id: Optional[str] = None) -> Dict:
        """Check text against persistent patterns for quick removal."""
        if not self.enable_telemetry:
            return {'cleaned_text': text, 'removals': [],
                    'wire_detected': None}

        patterns = self.telemetry.get_persistent_patterns(domain)
        if not patterns:
            return {'cleaned_text': text, 'removals': [],
                    'wire_detected': None}

        cleaned_text = text
        removals = []
        wire_detected = None

        for pattern in patterns:
            pattern_text = pattern['text_content']

            # WIRE SERVICE DETECTION: Check pattern before removal
            if not wire_detected:
                wire_service_info = self._detect_wire_service_in_pattern(
                    pattern_text, domain)
                if wire_service_info:
                    wire_detected = wire_service_info
                    if self.enable_telemetry:
                        self.telemetry.log_wire_detection(
                            provider=wire_service_info['provider'],
                            detection_method=wire_service_info[
                                'detection_method'
                            ],
                            pattern_text=pattern_text,
                            confidence=wire_service_info['confidence'],
                            detection_stage='persistent_pattern',
                            article_ids=[article_id] if article_id else None,
                            domain=domain,
                            extra_metadata={
                                'pattern_type': pattern['pattern_type'],
                                'pattern_confidence': pattern[
                                    'confidence_score'
                                ],
                                'pattern_occurrences': pattern[
                                    'occurrences_total'
                                ],
                            },
                        )

            # Check if this is a high-confidence boilerplate pattern
            # that overrides length
            is_high_confidence = self._is_high_confidence_boilerplate(
                pattern_text)

            # Apply minimum length filter (150 characters) unless
            # it's high-confidence boilerplate
            if len(pattern_text) < 150 and not is_high_confidence:
                continue

            if pattern_text in cleaned_text:
                # Calculate position before removal
                position = cleaned_text.find(pattern_text)
                cleaned_text = cleaned_text.replace(pattern_text, '')

                removals.append({
                    'text': pattern_text,
                    'position': position,
                    'confidence_score': pattern['confidence_score'],
                    'occurrences_total': pattern['occurrences_total'],
                    'pattern_type': pattern['pattern_type'],
                    'removal_reason': pattern['removal_reason']
                })

        return {'cleaned_text': cleaned_text, 'removals': removals,
                'wire_detected': wire_detected}

    def _detect_social_share_prefix_end(self, text: str) -> Optional[int]:
        """Return index after leading social-share keywords, if present."""
        if not text:
            return None

        # Skip leading whitespace-like punctuation often used as separators.
        prefix_start = 0
        while (
            prefix_start < len(text)
            and text[prefix_start] in SOCIAL_SHARE_PREFIX_SEPARATORS
        ):
            prefix_start += 1

        substring = text[prefix_start:]
        if not substring:
            return None

        share_run = 0
        last_end = prefix_start

        for match in re.finditer(r"[A-Za-z']+", substring):
            word = match.group().lower()
            if word in SOCIAL_SHARE_WORDS:
                share_run += 1
                last_end = prefix_start + match.end()
                continue
            break

        if share_run < 3:
            return None

        trailing_match = re.match(r"[\s\|\-:–—•·,]*", text[last_end:])
        if trailing_match:
            last_end += trailing_match.end()

        return last_end

    def _is_social_share_cluster(self, text: str) -> bool:
        """Return True when text is dominated by social-share keywords."""
        if not text:
            return False

        normalized = ' '.join(re.findall(r"[a-z']+", text.lower())).strip()
        if not normalized:
            return False

        if any(phrase in normalized for phrase in SOCIAL_SHARE_PHRASES):
            # Quick accept for known share phrases when little else is present.
            tokens = normalized.split()
            if len(tokens) <= 20 and sum(
                1 for token in tokens if token in SOCIAL_SHARE_WORDS
            ) >= len(tokens) * 0.6:
                return True

        prefix_end = self._detect_social_share_prefix_end(text)
        if prefix_end is None:
            return False

        remainder = text[prefix_end:].strip()
        if not remainder:
            return True

        remainder_tokens = re.findall(r"[a-z']+", remainder.lower())
        if not remainder_tokens:
            return True

        return all(token in SOCIAL_SHARE_WORDS for token in remainder_tokens)

    def _remove_social_share_header(self, text: str) -> Dict:
        """Remove leading social-share header clusters if present."""
        if not text:
            return {'cleaned_text': text, 'removed_text': None}

        stripped = text.lstrip()
        leading_whitespace = text[:len(text) - len(stripped)]
        lines = stripped.splitlines()

        if not lines:
            return {'cleaned_text': text, 'removed_text': None}

        removed_segments: List[str] = []
        idx = 0

        while idx < len(lines):
            prefix_end = self._detect_social_share_prefix_end(lines[idx])
            if prefix_end is None:
                break

            share_prefix = lines[idx][:prefix_end].strip()
            if share_prefix:
                removed_segments.append(share_prefix)

            remainder = lines[idx][prefix_end:].lstrip()
            if remainder:
                lines[idx] = remainder
                break

            idx += 1

        # Remove any blank lines immediately following the share header
        while (
            idx < len(lines)
            and lines[idx].strip() == ''
            and removed_segments
        ):
            idx += 1

        if not removed_segments:
            return {'cleaned_text': text, 'removed_text': None}

        cleaned_body = '\n'.join(lines[idx:]).lstrip()
        cleaned_text = leading_whitespace + cleaned_body

        removed_text = '\n'.join(removed_segments)
        return {'cleaned_text': cleaned_text, 'removed_text': removed_text}

    def process_single_article(
        self,
        text: str,
        domain: str,
        article_id=None,
        dry_run: bool = False,
    ) -> Tuple[str, Dict]:
        """Process a single article to remove boilerplate."""
        # Start telemetry session
        if self.enable_telemetry:
            self.telemetry.start_cleaning_session(domain, article_count=1)

        original_text = text

        # First check persistent patterns for quick matching
        removed_by_persistent = self._remove_persistent_patterns(
            text, domain, article_id)

        removal_details: List[Dict[str, Any]] = []

        wire_detected = removed_by_persistent.get('wire_detected')
        locality_assessment = None
        source_context = None
        local_byline_override = None
        suppression_applied = False

        if not wire_detected:
            inline_wire = self._detect_inline_wire_indicators(
                original_text, domain)
            if inline_wire:
                wire_detected = inline_wire
                if self.enable_telemetry:
                    self.telemetry.log_wire_detection(
                        provider=inline_wire['provider'],
                        detection_method=inline_wire['detection_method'],
                        pattern_text=inline_wire['pattern'],
                        confidence=inline_wire['confidence'],
                        detection_stage='inline_indicator',
                        article_ids=[article_id] if article_id else None,
                        domain=domain,
                        extra_metadata={
                            'matched_variant': inline_wire.get(
                                'matched_variant'),
                            'indicator_type': 'inline_header',
                        },
                    )

        if wire_detected and article_id:
            source_context = self._get_article_source_context(article_id)
            locality_assessment = self._assess_locality(
                original_text,
                source_context,
                domain,
            )

            if (
                self.enable_telemetry
                and locality_assessment
                and locality_assessment.get('is_local')
            ):
                self.telemetry.log_locality_detection(
                    provider=wire_detected.get('provider'),
                    detection_method=wire_detected.get('detection_method'),
                    article_id=article_id,
                    domain=domain,
                    locality=locality_assessment,
                    source_context=source_context,
                )

            local_byline_override = self._detect_local_byline_override(
                article_id,
            )
            provider = wire_detected.get('provider') if wire_detected else None
            suppression_allowed = (
                local_byline_override
                and provider in SUPPRESSIBLE_WIRE_PROVIDERS
            )
            if suppression_allowed:
                override_payload = {
                    'authors': local_byline_override.get('authors', []),
                    'local_authors': local_byline_override.get(
                        'local_authors', []
                    ),
                }
                wire_detected = {
                    **wire_detected,
                    'suppressed_due_to_local_byline': override_payload,
                }
                suppression_applied = True
            else:
                local_byline_override = None

        should_mark_as_wire = (
            bool(wire_detected)
            and article_id is not None
            and not suppression_applied
        )

        if should_mark_as_wire and not dry_run:
            self._mark_article_as_wire(
                article_id,
                wire_detected,
                locality=locality_assessment,
                source_context=source_context,
            )
        elif article_id is not None and suppression_applied and not dry_run:
            self._clear_wire_classification(article_id)

        if wire_detected:
            if suppression_applied:
                self.logger.info(
                    (
                        "Suppressed wire classification for article %s "
                        "due to local authors: %s"
                    ),
                    article_id,
                    ", ".join(
                        (local_byline_override or {}).get(
                            'local_authors', []
                        )
                    )
                    or '[unknown]',
                )
            else:
                self.logger.info(
                    f"Wire service detected in article {article_id}: "
                    f"{wire_detected['provider']}")

        if removed_by_persistent['removals']:
            for removal in removed_by_persistent['removals']:
                detail = {
                    'pattern_type': removal['pattern_type'],
                    'pattern_name': removal.get('removal_reason'),
                    'confidence_score': removal.get('confidence_score', 0.0),
                    'text': removal['text'],
                    'position': removal.get('position', -1),
                    'length': len(removal['text']),
                    'source': 'persistent_pattern',
                }
                removal_details.append(detail)

                if (
                    self.enable_telemetry
                    and removed_by_persistent['cleaned_text'] != text
                ):
                    self.telemetry.log_segment_detection(
                        segment_text=removal['text'],
                        boundary_score=removal['confidence_score'],
                        occurrences=removal['occurrences_total'],
                        pattern_type=removal['pattern_type'],
                        position_consistency=1.0,
                        segment_length=len(removal['text']),
                        article_ids=[article_id] if article_id else [],
                        was_removed=True,
                        removal_reason=(
                            f"Persistent: {removal['removal_reason']}"
                        ),
                    )

        if removed_by_persistent['cleaned_text'] != text:
            text = removed_by_persistent['cleaned_text']

        share_removal = self._remove_social_share_header(text)
        share_header_removed = bool(share_removal['removed_text'])
        if share_header_removed:
            text = share_removal['cleaned_text']
            removed_text = share_removal['removed_text'] or ''
            removal_details.append({
                'pattern_type': 'social_share_header',
                'pattern_name': 'social_share_header',
                'confidence_score': 1.0,
                'text': removed_text,
                'position': 0,
                'length': len(removed_text),
                'source': 'social_share_header',
            })
            if self.enable_telemetry:
                self.telemetry.log_segment_detection(
                    segment_text=removed_text,
                    boundary_score=1.0,
                    occurrences=1,
                    pattern_type='social_share_header',
                    position_consistency=1.0,
                    segment_length=len(removed_text),
                    article_ids=[article_id] if article_id else [],
                    was_removed=True,
                    removal_reason='High-confidence social share header'
                )

        # Finalize telemetry and return
        if self.enable_telemetry:
            original_len = len(original_text)
            cleaned_len = len(text)
            removed_chars = original_len - cleaned_len
            removal_percentage = (
                (removed_chars / original_len) * 100
                if original_len else 0.0
            )

            self.telemetry.finalize_cleaning_session(
                rough_candidates_found=0,
                segments_detected=len(removal_details),
                total_removable_chars=removed_chars,
                removal_percentage=removal_percentage
            )

        chars_removed = len(original_text) - len(text)
        patterns = [r['pattern_type']
                    for r in removed_by_persistent['removals']]
        if share_header_removed:
            patterns.append('social_share_header')

        return text, {
            'persistent_removals': len(removed_by_persistent['removals']),
            'chars_removed': chars_removed,
            'patterns_matched': patterns,
            'wire_detected': wire_detected,
            'social_share_header_removed': share_header_removed,
            'locality_assessment': locality_assessment,
            'wire_suppressed_due_to_local_byline': suppression_applied,
            'removal_details': removal_details,
            'share_header_removed_text': share_removal['removed_text'],
        }

    def _clear_wire_classification(
        self,
        article_id: str,
    ) -> None:  # pragma: no cover
        """Remove existing wire metadata for an article."""
        conn = None
        try:
            conn = self._connect_to_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE articles SET wire = NULL WHERE id = ?",
                (article_id,),
            )
            conn.commit()
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.debug(
                "Failed to clear wire metadata for article %s: %s",
                article_id,
                exc,
            )
        finally:
            if conn:
                conn.close()

    def _get_article_authors(
        self,
        article_id: str,
    ) -> List[str]:  # pragma: no cover
        """Fetch authors for an article and normalize to a string list."""
        conn = None
        try:
            conn = self._connect_to_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT author FROM articles WHERE id = ?",
                (article_id,),
            )
            row = cursor.fetchone()
            if not row:
                return []

            raw_author = row[0]
            if raw_author in (None, ""):
                return []

            if isinstance(raw_author, bytes):
                try:
                    raw_author = raw_author.decode('utf-8')
                except UnicodeDecodeError:
                    return []

            if isinstance(raw_author, list):
                return [
                    str(item).strip()
                    for item in raw_author
                    if str(item).strip()
                ]

            if isinstance(raw_author, str):
                text = raw_author.strip()
                if not text:
                    return []

                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None

                if isinstance(parsed, list):
                    return [
                        str(item).strip()
                        for item in parsed
                        if str(item).strip()
                    ]

                if isinstance(parsed, str):
                    parsed = parsed.strip()
                    return [parsed] if parsed else []

                # Fallback: split on common separators
                candidates = re.split(r"[|;,]+", text)
                return [
                    candidate.strip()
                    for candidate in candidates
                    if candidate and candidate.strip()
                ]

            return []
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.debug(
                "Failed to load authors for article %s: %s",
                article_id,
                exc,
            )
            return []
        finally:
            if conn:
                conn.close()

    def _detect_local_byline_override(
        self,
        article_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Identify whether article bylines indicate local authors."""
        authors = self._get_article_authors(article_id)
        if not authors:
            return None

        local_authors: List[str] = []
        for author in authors:
            if not author:
                continue

            candidate = author.strip()
            if not candidate:
                continue

            normalized = candidate.lower()

            if re.search(r"\b(via|from)\b", normalized) and re.search(
                (
                    r"\b(ap|associated press|cnn|reuters|npr|bloomberg|"
                    r"usa today|washington post|new york times)\b"
                ),
                normalized,
            ):
                continue

            # Reset detector state before probing author name
            previous_services = self.wire_detector._detected_wire_services
            try:
                self.wire_detector._detected_wire_services = []
                is_wire_author = self.wire_detector._is_wire_service(
                    candidate
                )
            finally:
                self.wire_detector._detected_wire_services = (
                    previous_services
                )
            if is_wire_author:
                continue

            if len(re.findall(r"[A-Za-z]", candidate)) < 3:
                continue

            local_authors.append(candidate)

        if not local_authors:
            return None

        return {
            'authors': authors,
            'local_authors': local_authors,
        }

    def _is_high_confidence_boilerplate(self, text: str) -> bool:
        """
        Identify high-confidence boilerplate patterns that should override
        the minimum length threshold.

        These patterns are obvious boilerplate regardless of length.
        """
        if self._is_social_share_cluster(text):
            return True

        text_cleaned = ' '.join(text.split()).strip().lower()

        # Social media sharing button patterns
        social_sharing_patterns = [
            'facebook twitter whatsapp sms email',
            'facebook twitter whatsapp sms email print',
            'facebook twitter whatsapp sms email print copy',
            'facebook twitter whatsapp sms email print copy article link',
            'facebook twitter whatsapp sms email print copy article link '
            'save',
            'share on facebook twitter whatsapp',
            'share via facebook twitter whatsapp',
            'follow us on facebook twitter instagram',
            'like us on facebook',
            'tweet this',
            'share this article',
            'share this story',
        ]

        # Navigation and UI element patterns
        navigation_patterns = [
            'home about contact us',
            'back to top',
            'scroll to top',
            'return to top',
            'go to main content',
            'skip to content',
            'menu toggle',
            'search site',
        ]

        # Subscription and newsletter patterns
        subscription_patterns = [
            'subscribe to our newsletter',
            'sign up for updates',
            'get daily updates',
            'subscribe now',
            'join our mailing list',
            'email updates',
            'available in full to subscribers',
            'this item is available in full to subscribers',
            'to continue reading please log in or subscribe',
            'to continue reading please login or subscribe',
            'please log in to continue reading',
            'please login to continue reading',
            'need an account print subscribers',
        ]

        # Copyright and legal patterns
        copyright_patterns = [
            'all rights reserved',
            'copyright',
            'terms of use',
            'privacy policy',
            'cookie policy',
        ]

        # Check all pattern categories
        all_patterns = (social_sharing_patterns + navigation_patterns +
                        subscription_patterns + copyright_patterns)

        for pattern in all_patterns:
            if pattern in text_cleaned:
                return True

        # Check for repetitive patterns that suggest boilerplate
        words = text_cleaned.split()
        if len(words) <= 10:  # Only for short segments
            # If same word appears 3+ times, likely boilerplate
            word_counts = {}
            for word in words:
                if len(word) > 2:  # Skip very short words
                    word_counts[word] = word_counts.get(word, 0) + 1
                    if word_counts[word] >= 3:
                        return True

        return False

    def _detect_wire_service_in_pattern(self, pattern_text: str,
                                        domain: str) -> Optional[Dict]:
        """
        Detect if a pattern contains wire service syndication evidence.

        Returns dict with wire service info if detected, None otherwise.
        """
        # Reset detector state before each check
        self.wire_detector._detected_wire_services = []

        blocked_providers: Set[str] = set()

        # Use the byline cleaner's wire service detection
        if self.wire_detector._is_wire_service(pattern_text):
            # Get detected wire services
            detected_services = self.wire_detector._detected_wire_services
            if detected_services:
                wire_service_name = detected_services[-1]  # Latest detected

                # Check if this is from the publication's own source
                is_own_source = (
                    self.wire_detector._is_wire_service_from_own_source(
                        wire_service_name, domain))

                if not is_own_source:  # Only mark as wire if syndicated
                    return {
                        'provider': wire_service_name,
                        'pattern': pattern_text,
                        'confidence': 0.9,
                        'detection_method': 'pattern_analysis'
                    }
                blocked_providers.add(wire_service_name.lower())

        # Check for common wire service patterns in the text
        wire_patterns = [
            # AP patterns
            (r'\b(AP|Associated Press)\b', 'Associated Press'),
            (r'\bAP News\b', 'Associated Press'),
            (r'\bThe Associated Press\b', 'Associated Press'),

            # Reuters patterns
            (r'\bReuters\b', 'Reuters'),
            (r'\bThomson Reuters\b', 'Reuters'),

            # CNN patterns
            (r'\bCNN\b(?!\s+News)', 'CNN'),
            (r'\bCNN NewsSource\b', 'CNN NewsSource'),
            (r'\bCable\s+News\s+Network\b', 'CNN NewsSource'),

            # Other major wire services
            (r'\bBloomberg\b', 'Bloomberg'),
            (r'\bNPR\b', 'NPR'),
            (r'\bPBS\b', 'PBS'),
            (r'\bUSA TODAY\b', 'USA Today'),
            (r'\bWashington Post\b', 'Washington Post'),
            (r'\bNew York Times\b', 'New York Times'),
            (r'\bWall Street Journal\b', 'Wall Street Journal'),

            # Wire service indicators
            (r'\bwire service\b', 'Wire Service'),
            (r'\bsyndicated\b', 'Syndicated Content'),
            (r'\b(from|source|via)\s+wire\b', 'Wire Service'),
        ]

        domain_normalized = (
            re.sub(r'[^a-z0-9]', '', domain.lower()) if domain else ''
        )

        for pattern, service_name in wire_patterns:
            if re.search(pattern, pattern_text, re.IGNORECASE):
                # Normalize provider name using byline cleaner
                normalized_provider = (
                    self.wire_detector._normalize_wire_service(service_name))

                # Don't mark as wire if it matches the domain
                if normalized_provider:
                    provider_lower = normalized_provider.lower()
                    provider_normalized = re.sub(r'[^a-z0-9]', '',
                                                 provider_lower)

                    if provider_lower in blocked_providers:
                        continue

                    if domain_normalized and (
                        provider_lower in domain.lower()
                        or (provider_normalized and
                            provider_normalized in domain_normalized)
                    ):
                        continue

                return {
                    'provider': normalized_provider or service_name,
                    'pattern': pattern_text,
                    'confidence': 0.8,
                    'detection_method': 'regex_pattern'
                }

        return None

    def _get_article_source_context(
        self,
        article_id: str,
    ) -> Dict[str, Optional[str]]:
        """Load publisher metadata linked to an article for locality flags."""
        conn = None
        try:
            conn = self._connect_to_db()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT a.candidate_link_id,
                       cl.source,
                       cl.source_name,
                       cl.source_city,
                       cl.source_county,
                       cl.source_type,
                       s.canonical_name,
                       s.city,
                       s.county
                FROM articles a
                LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id
                LEFT JOIN sources s ON cl.source_id = s.id
                WHERE a.id = ?
                """,
                (article_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {}

            context = {
                'candidate_link_id': row[0],
                'publisher_slug': row[1],
                'publisher_name': row[2] or row[6],
                'publisher_city': row[3] or row[7],
                'publisher_county': row[4] or row[8],
                'publisher_type': row[5],
                'canonical_name': row[6],
                'canonical_city': row[7],
                'canonical_county': row[8],
            }

            return {
                key: value
                for key, value in context.items()
                if value not in (None, "")
            }
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.debug(
                "Failed to load source context for article %s: %s",
                article_id,
                exc,
            )
            return {}
        finally:
            if conn:
                conn.close()

    def _assess_locality(
        self,
        text: str,
        context: Dict[str, Optional[str]],
        domain: str,
    ) -> Optional[Dict[str, Any]]:
        """Heuristically determine if a wire article is locally focused."""
        if not text or not context:
            return None

        threshold = 0.6
        score = 0.0
        signals: List[Dict[str, Any]] = []
        seen_terms: Set[str] = set()
        text_lower = text.lower()

        def register(
            term: Optional[str],
            signal_type: str,
            weight: float,
        ) -> None:
            nonlocal score
            if not term:
                return
            normalized = str(term).strip()
            if not normalized:
                return
            key = normalized.lower()
            if key in seen_terms:
                return
            if self._contains_term(text_lower, normalized):
                seen_terms.add(key)
                signals.append({
                    'type': signal_type,
                    'value': normalized,
                    'weight': weight,
                })
                score = min(1.0, score + weight)

        register(context.get('publisher_city'), 'city', 0.45)
        register(
            context.get('canonical_city'),
            'canonical_city',
            0.35,
        )

        publisher_county = context.get('publisher_county')
        if publisher_county:
            register(f"{publisher_county} County", 'county_phrase', 0.4)
            register(publisher_county, 'county', 0.25)

        canonical_county = context.get('canonical_county')
        if canonical_county and canonical_county != publisher_county:
            register(
                f"{canonical_county} County",
                'canonical_county_phrase',
                0.35,
            )
            register(canonical_county, 'canonical_county', 0.2)

        publisher_name = context.get('publisher_name')
        if publisher_name:
            register(publisher_name, 'publisher_name', 0.25)
            primary_token = publisher_name.split()[0]
            if primary_token:
                register(primary_token, 'publisher_primary_token', 0.12)

        canonical_name = context.get('canonical_name')
        if canonical_name and canonical_name != publisher_name:
            register(canonical_name, 'canonical_name', 0.2)
            canonical_token = canonical_name.split()[0]
            if canonical_token:
                register(canonical_token, 'canonical_primary_token', 0.1)

        publisher_slug = context.get('publisher_slug')
        if publisher_slug and re.search(r"[a-z]", publisher_slug):
            slug_term = publisher_slug.replace('-', ' ').replace('_', ' ')
            register(slug_term, 'publisher_slug', 0.08)

        if not signals:
            return {
                'is_local': False,
                'confidence': 0.0,
                'signals': [],
                'threshold': threshold,
                'raw_score': 0.0,
            }

        confidence = round(score, 2)
        return {
            'is_local': bool(signals) and score >= threshold,
            'confidence': confidence,
            'signals': signals,
            'threshold': threshold,
            'raw_score': round(score, 3),
        }

    @staticmethod
    def _contains_term(text_lower: str, term: str) -> bool:
        """Check whether `term` appears in text with basic boundary rules."""
        if not term:
            return False
        normalized = term.lower().strip()
        if not normalized:
            return False

        collapsed_text = re.sub(r"\s+", " ", text_lower)
        if ' ' in normalized or '-' in normalized:
            normalized_compact = re.sub(r"\s+", " ", normalized)
            return normalized_compact in collapsed_text

        pattern = r"\b{}\b".format(re.escape(normalized))
        return re.search(pattern, text_lower) is not None

    def _detect_inline_wire_indicators(self, text: str,
                                       domain: str) -> Optional[Dict]:
        """Detect inline header indicators like "(AP)" or "By Reuters"."""
        if not text:
            return None

        snippet = text.strip()
        if not snippet:
            return None

        # Focus on the opening paragraph
        lines = snippet.splitlines()
        first_block = ' '.join(lines[:3]) if lines else snippet
        candidate_text = first_block[:300]

        provider_map = {
            'ap': 'The Associated Press',
            'associated press': 'The Associated Press',
            'the associated press': 'The Associated Press',
            'reuters': 'Reuters',
            'bloomberg': 'Bloomberg',
            'cnn': 'CNN NewsSource',
            'cnn newssource': 'CNN NewsSource',
            'npr': 'NPR',
            'pbs': 'PBS',
            'usa today': 'USA Today',
            'washington post': 'Washington Post',
            'the washington post': 'Washington Post',
            'new york times': 'New York Times',
            'the new york times': 'New York Times',
            'wall street journal': 'Wall Street Journal',
            'los angeles times': 'Los Angeles Times',
        }

        base_patterns = [
            r'^\s*\((?P<provider>{token})\)\s*[-–—:]*',
            r'^\s*(?P<provider>{token})\s*[-–—:]+',
            r'^\s*(?:by\s+)?(?P<provider>{token})\b',
        ]

        for raw_provider, normalized in provider_map.items():
            for pattern in base_patterns:
                regex = pattern.format(token=re.escape(raw_provider))
                match = re.match(regex, candidate_text, flags=re.IGNORECASE)
                if not match:
                    continue

                matched_provider = match.group('provider')
                normalized_provider = (
                    self.wire_detector._normalize_wire_service(
                        matched_provider)
                    or normalized
                )

                # Skip if this matches the domain's own source name
                if self.wire_detector._is_wire_service_from_own_source(
                        normalized_provider, domain):
                    continue

                matched_text = match.group(0)
                return {
                    'provider': normalized_provider,
                    'pattern': matched_text,
                    'confidence': 0.85,
                    'detection_method': 'inline_indicator',
                    'matched_variant': raw_provider,
                }

        return None

    def _mark_article_as_wire(
        self,
        article_id: str,
        wire_info: Dict,
        locality: Optional[Dict] = None,
        source_context: Optional[Dict] = None,
    ) -> None:  # pragma: no cover
        """Mark article as wire service content in database."""
        conn = None
        try:
            conn = self._connect_to_db()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT wire FROM articles WHERE id = ?",
                (article_id,),
            )
            existing_wire = cursor.fetchone()
            existing_payload: Dict = {}
            if existing_wire and existing_wire[0]:
                try:
                    existing_payload = json.loads(existing_wire[0])
                except json.JSONDecodeError:
                    existing_payload = {}
                except TypeError:
                    existing_payload = {}
            if not isinstance(existing_payload, dict):
                existing_payload = {}

            # Update the wire column with JSON info about the wire service
            wire_payload: Dict[str, Any] = existing_payload.copy()
            wire_payload.update({
                'provider': wire_info.get('provider'),
                'confidence': wire_info.get('confidence'),
                'detection_method': wire_info.get('detection_method'),
            })

            if not wire_payload.get('detected_at'):
                wire_payload['detected_at'] = (
                    datetime.utcnow().date().isoformat()
                )

            if locality:
                sanitized_locality = {
                    'is_local': locality.get('is_local', False),
                    'confidence': locality.get('confidence'),
                    'signals': locality.get('signals', []),
                    'threshold': locality.get('threshold'),
                }
                wire_payload['locality'] = sanitized_locality

            if source_context:
                allowed_keys = {
                    'publisher_slug',
                    'publisher_name',
                    'publisher_city',
                    'publisher_county',
                    'publisher_type',
                    'canonical_name',
                    'canonical_city',
                    'canonical_county',
                }
                sanitized_source = {
                    key: value
                    for key, value in source_context.items()
                    if key in allowed_keys and value
                }
                if sanitized_source:
                    wire_payload['source_context'] = sanitized_source

            wire_data = json.dumps(wire_payload)

            cursor.execute(
                "UPDATE articles SET wire = ? WHERE id = ?",
                (wire_data, article_id)
            )

            conn.commit()

            self.logger.info(
                f"Marked article {article_id} as wire service: "
                f"{wire_info['provider']}")

        except Exception as e:
            self.logger.error(
                f"Failed to mark article {article_id} as wire: {e}")
        finally:
            if conn:
                conn.close()
