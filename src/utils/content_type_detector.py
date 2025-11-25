"""Heuristics for detecting opinion pieces and obituaries."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .confidence import normalize_score, score_to_label
from .wire_reporters import is_wire_reporter


@dataclass(frozen=True)
class ContentTypeResult:
    """Structured result describing detected article type."""

    status: str
    confidence_score: float
    confidence: str
    reason: str
    evidence: dict[str, list[str]]
    detector_version: str


class ContentTypeDetector:
    """Detect special content types (obituaries, opinion pieces, wire)."""

    VERSION = "2025-11-25a"  # Database-driven wire patterns (url/content/author types)

    # Cache for local broadcaster callsigns (loaded from database)
    _local_callsigns_cache: set[str] | None = None
    _cache_timestamp: float | None = None
    _cache_ttl_seconds = 300  # 5 minutes

    # Cache for wire service patterns (loaded from database)
    _wire_patterns_cache: list[tuple] | None = None
    _wire_patterns_timestamp: float | None = None

    # Known callsign to domain mappings (Missouri market)
    # Used when callsign doesn't appear directly in URL
    _CALLSIGN_DOMAINS = {
        "KMIZ": ["abc17news.com"],
        "KOMU": ["komu.com"],
        "KRCG": ["krcgtv.com"],
        "KQFX": ["fox22now.com"],
        "KJLU": ["zimmerradio.com"],
    }

    # Wire service indicators for dateline detection
    _WIRE_SERVICE_PATTERNS = (
        # Format: (pattern, canonical_name, case_sensitive)
        (r"\b(AP|A\.P\.)\b", "Associated Press", False),
        (r"\b(ASSOCIATED PRESS|Associated Press)\b", "Associated Press", True),
        (r"\bREUTERS\b", "Reuters", False),
        (r"\b(Reuters)\b", "Reuters", True),
        (r"\b(CNN|C\.N\.N\.)\b", "CNN", False),
        (r"\b(Bloomberg|BLOOMBERG)\b", "Bloomberg", False),
        (r"\b(NPR|N\.P\.R\.)\b", "NPR", False),
        (r"\b(PBS|P\.B\.S\.)\b", "PBS", False),
        (r"\b(UPI|U\.P\.I\.)\b", "UPI", False),
        (r"\b(AFP|Agence France-Presse)\b", "AFP", False),
        (
            r"\b(States\s+Newsroom|StatesNewsroom|States-Newsroom)\b",
            "States Newsroom",
            False,
        ),
        (
            r"\b(The\s+Missouri\s+Independent|Missouri\s+Independent)\b",
            "The Missouri Independent",
            False,
        ),
        (
            r"\b(Kansas\s+Reflector|KansasReflector|kansasreflector)\b",
            "States Newsroom",
            False,
        ),
        (r"\b(WAVE|Wave|WAVE3|wave3)\b", "WAVE", False),
        (r"\bThe New York Times\b", "The New York Times", True),
        (r"\bThe Washington Post\b", "The Washington Post", True),
        (r"\bUSA TODAY\b", "USA TODAY", True),
        (r"\bWall Street Journal\b", "Wall Street Journal", True),
        (r"\bLos Angeles Times\b", "Los Angeles Times", True),
        (r"\bTribune News Service\b", "Tribune News Service", True),
        (r"\bGannett\b", "Gannett", True),
        (r"\bMcClatchy\b", "McClatchy", True),
    )

    # Note: Dateline patterns are now loaded from wire_services table
    # Note: Wire URL patterns are now loaded from wire_services table
    # These legacy constants remain for backward compatibility but are not used

    _WIRE_URL_PATTERNS = (
        "cnn.com",
        "apnews.com",
        "reuters.com",
        "bloomberg.com",
        "npr.org",
        "pbs.org",
        "nytimes.com",
        "washingtonpost.com",
        "usatoday.com",
        "wsj.com",
        "latimes.com",
        "/ap-",
        "/cnn-",
        "/reuters-",
        "/wire/",
        "/national/",
        "/world/",
        "statesnewsroom.org",
        "kansasreflector.com",
        "missouriindependent.org",
        "missouriindependent.com",
        "wave3.com",
    )

    _OBITUARY_TITLE_KEYWORDS = (
        "obituary",
        "obituaries",
        "death notice",
        "death notices",
        "celebration of life",
        "in memoriam",
        "life story",
        "remembering",
    )
    _OBITUARY_STRONG_TITLE_KEYWORDS = {
        "obituary",
        "obituaries",
        "death notice",
        "death notices",
        "celebration of life",
        "in memoriam",
    }
    _OBITUARY_WEAK_TITLE_KEYWORDS = {
        "life story",
        "remembering",
    }
    _OBITUARY_URL_SEGMENTS = (
        "obituary",
        "obituaries",
        "obits",
        "death-notice",
        "deathnotice",
        "in-memoriam",
        "celebration-of-life",
        "life-story",
        "remembering",
    )
    _OBITUARY_HIGH_CONFIDENCE_URL_SEGMENTS = {
        "obituary",
        "obituaries",
        "obits",
        "death-notice",
        "deathnotice",
        "in-memoriam",
    }
    _OBITUARY_CONTENT_KEYWORDS = (
        "obituary",
        "obituaries",
        "celebration of life",
        "passed away",
        "funeral service",
        "funeral services",
        "memorial service",
        "memorial services",
        "visitation",
        "visitation will be",
        "survived by",
        "interment",
        "laid to rest",
        "arrangements for",
        "arrangements are under the direction",
        "cremation",
        "mass of christian burial",
    )
    _OBITUARY_HIGH_SIGNAL_CONTENT_KEYWORDS = {
        "passed away",
        "funeral service",
        "funeral services",
        "memorial service",
        "memorial services",
        "visitation",
        "visitation will be",
        "survived by",
        "interment",
        "laid to rest",
        "cremation",
        "mass of christian burial",
    }
    _OBITUARY_TITLE_STOPWORDS = {
        "county",
        "city",
        "school",
        "district",
        "council",
        "news",
        "update",
        "report",
        "minutes",
        "meeting",
        "preview",
        "recap",
        "agenda",
    }
    _TITLE_YEAR_PATTERN = re.compile(r"\b(18|19|20)\d{2}\b")

    _OPINION_TITLE_PREFIXES = (
        "opinion",
        "editorial",
        "column",
        "commentary",
        "guest column",
        "guest commentary",
        "letter",
        "letters",
        "perspective",
    )
    _OPINION_URL_SEGMENTS = (
        "opinion",
        "opinions",
        "editorial",
        "editorials",
        "column",
        "columns",
        "columnists",
        "commentary",
        "letters",
        "letters-to-the-editor",
        "perspective",
    )

    _TITLE_CONFIDENCE_WEIGHT = 2
    _URL_CONFIDENCE_WEIGHT = 2
    _METADATA_CONFIDENCE_WEIGHT = 1
    _OBITUARY_MAX_SCORE = 12
    _OPINION_MAX_SCORE = 6

    def _get_local_broadcaster_callsigns(self, dataset: str = "missouri") -> set[str]:
        """Get local broadcaster callsigns from database with caching.

        Args:
            dataset: Dataset identifier to filter callsigns

        Returns:
            Set of callsign strings (e.g., {'KMIZ', 'KOMU', 'KRCG'})
        """
        import time

        # Check cache validity
        now = time.time()
        if (
            self._local_callsigns_cache is not None
            and self._cache_timestamp is not None
            and (now - self._cache_timestamp) < self._cache_ttl_seconds
        ):
            return self._local_callsigns_cache

        # Load from database
        try:
            from src.models import LocalBroadcasterCallsign
            from src.models.database import DatabaseManager

            db = DatabaseManager()
            with db.get_session() as session:
                callsigns = (
                    session.query(LocalBroadcasterCallsign.callsign)
                    .filter(LocalBroadcasterCallsign.dataset == dataset)
                    .all()
                )
                self._local_callsigns_cache = {c[0] for c in callsigns}
                self._cache_timestamp = now
                return self._local_callsigns_cache
        except Exception:
            # Fallback to empty set if database unavailable
            # This prevents failures in environments without DB access
            return set()

    def _get_wire_service_patterns(
        self, pattern_type: str | None = None
    ) -> list[tuple]:
        """Get wire service patterns from database with caching.

        Args:
            pattern_type: Filter patterns by type ('url', 'content', 'author').
                         If None, returns all patterns.

        Returns:
            List of tuples: (pattern, service_name, case_sensitive)
            Sorted by priority (lower = higher priority)
        """
        import time

        # Check cache validity
        now = time.time()
        cache_key = f"patterns_{pattern_type}"

        # Use type-specific cache
        if pattern_type:
            if not hasattr(self, "_pattern_cache_by_type"):
                self._pattern_cache_by_type = {}
            if not hasattr(self, "_pattern_timestamp_by_type"):
                self._pattern_timestamp_by_type = {}

            if (
                cache_key in self._pattern_cache_by_type
                and cache_key in self._pattern_timestamp_by_type
                and (now - self._pattern_timestamp_by_type[cache_key])
                < self._cache_ttl_seconds
            ):
                return self._pattern_cache_by_type[cache_key]
        else:
            # Use global cache for all patterns
            if (
                self._wire_patterns_cache is not None
                and self._wire_patterns_timestamp is not None
                and (now - self._wire_patterns_timestamp) < self._cache_ttl_seconds
            ):
                return self._wire_patterns_cache

        # Load from database
        try:
            from src.models import WireService
            from src.models.database import DatabaseManager

            db = DatabaseManager()
            with db.get_session() as session:
                query = session.query(
                    WireService.pattern,
                    WireService.service_name,
                    WireService.case_sensitive,
                    WireService.priority,
                ).filter(WireService.active.is_(True))

                # Apply pattern_type filter if specified
                if pattern_type:
                    query = query.filter(WireService.pattern_type == pattern_type)

                patterns = query.order_by(WireService.priority, WireService.id).all()

                result = [(p[0], p[1], p[2]) for p in patterns]

                # Store in appropriate cache
                if pattern_type:
                    self._pattern_cache_by_type[cache_key] = result
                    self._pattern_timestamp_by_type[cache_key] = now
                else:
                    self._wire_patterns_cache = result
                    self._wire_patterns_timestamp = now

                return result
        except Exception:
            # Fallback to empty list if database unavailable
            return []

    def detect(
        self,
        *,
        url: str,
        title: str | None,
        metadata: dict | None,
        content: str | None = None,
        author: str | None = None,
    ) -> ContentTypeResult | None:
        """Return the detected content type for the article, if any."""

        normalized_metadata = metadata or {}
        keywords = self._normalize_keywords(normalized_metadata.get("keywords"))
        meta_description = normalized_metadata.get("meta_description")

        # Check for wire service content first (highest priority)
        wire_result = self._detect_wire_service(
            url=url,
            content=content,
            metadata=normalized_metadata,
            author=author,
            title=title,
        )
        if wire_result:
            return wire_result

        obituary_result = self._detect_obituary(
            url=url,
            title=title,
            keywords=keywords,
            meta_description=meta_description,
            content=content,
        )
        if obituary_result:
            return obituary_result

        return self._detect_opinion(
            url=url,
            title=title,
            keywords=keywords,
            meta_description=meta_description,
        )

    def _detect_wire_service(
        self,
        *,
        url: str,
        content: str | None,
        metadata: dict | None = None,
        author: str | None = None,
        title: str | None = None,
    ) -> ContentTypeResult | None:
        """
        Detect wire service content using tiered detection strategy.

        Detection Tiers (in priority order):
        1. URL Structure (STRONGEST): Wire service paths, national/world sections
        2. Byline Analysis (STRONG): Known wire reporters, wire service patterns
           - CRITICAL: Excludes if byline matches publisher (KMIZ on KMIZ = local)
        3. Metadata/Copyright (STRONG): Structured attribution, copyright notices
        4. Content Patterns (WEAK): Dateline patterns, requires additional evidence

        Returns wire detection only with strong evidence. Avoids false positives
        from local reporters filing from DC or articles that merely cite sources.
        """
        matches: dict[str, list[str]] = {}
        detected_services: set[str] = set()
        url_lower = url.lower()

        # ===================================================================
        # TIER 0: Exclude wire service's own domains (not syndicated)
        # ===================================================================
        own_source_domains = {
            "cnn.com": "CNN",
            "apnews.com": "Associated Press",
            "reuters.com": "Reuters",
            "bloomberg.com": "Bloomberg",
            "npr.org": "NPR",
            "pbs.org": "PBS",
            "nytimes.com": "The New York Times",
            "washingtonpost.com": "The Washington Post",
            "usatoday.com": "USA TODAY",
            "wsj.com": "Wall Street Journal",
            "latimes.com": "Los Angeles Times",
            "statesnewsroom.org": "States Newsroom",
            "kansasreflector.com": "States Newsroom",
            "missouriindependent.org": "The Missouri Independent",
            "missouriindependent.com": "The Missouri Independent",
            "wave3.com": "WAVE",
        }

        for domain, service_name in own_source_domains.items():
            if domain in url_lower:
                return None  # Own content, not syndicated

        # ===================================================================
        # TIER 1: URL Structure Analysis (STRONGEST SIGNAL)
        # ===================================================================
        strong_url_signal = False
        weak_url_signal = False

        # Load patterns from database
        wire_url_patterns = self._get_wire_service_patterns(pattern_type="url")

        for pattern, service_name, case_sensitive in wire_url_patterns:
            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(pattern, url, flags):
                matches.setdefault("url", []).append(pattern)
                detected_services.add(service_name)

                # Categorize URL pattern strength
                pattern_lower = pattern.lower()
                strong_indicators = [
                    "/ap-", "/cnn-", "/reuters-", "/wire/", "/stacker"
                ]
                if any(indicator in pattern_lower for indicator in strong_indicators):
                    strong_url_signal = True
                elif any(
                    indicator in pattern_lower
                    for indicator in ["/national", "/world"]
                ):
                    weak_url_signal = True
                else:
                    # Domain patterns or service-name-in-path
                    strong_url_signal = True

        # Strong URL signal alone is sufficient
        if strong_url_signal:
            return self._build_wire_result(matches, detected_services, tier="url")

        # ===================================================================
        # TIER 2: Byline Analysis (STRONG SIGNAL with Publisher Check)
        # ===================================================================
        byline_signal = False

        # Extract author from various sources
        author_raw = author or (metadata.get("author") if metadata else None) or (
            metadata.get("byline") if metadata else None
        )

        # Handle structured byline metadata
        if metadata and isinstance(metadata.get("byline"), dict):
            byline_meta = metadata["byline"]
            if byline_meta.get("is_wire_content"):
                byline_signal = True
                service_names = byline_meta.get("wire_services", []) or []
                for svc in service_names:
                    if svc:
                        detected_services.add(str(svc))
                matches.setdefault("byline_metadata", []).append("marked_as_wire")

        # Extract author string
        if isinstance(author_raw, dict):
            author_str = ", ".join(str(a) for a in author_raw.get("authors", []))
            if not author_str:
                author_str = str(author_raw.get("original", ""))
        elif isinstance(author_raw, list):
            author_str = ", ".join(str(a) for a in author_raw)
        else:
            author_str = str(author_raw) if author_raw else ""

        if author_str:
            author_lower = author_str.lower().strip()

            # CRITICAL: Check if byline matches publisher
            # Extract publisher from URL (domain or callsign)
            publisher_indicators = self._extract_publisher_from_url(url_lower)

            # Check if author contains publisher name
            byline_matches_publisher = any(
                indicator in author_lower for indicator in publisher_indicators
            )

            if byline_matches_publisher:
                # Author matches publisher - this is LOCAL content
                # Example: "KMIZ News" on abc17news.com (KMIZ's site)
                return None

            # Check author patterns from database (STRONGEST SIGNAL)
            # Loads patterns with pattern_type='author' for byline matching
            wire_author_patterns = self._get_wire_service_patterns(
                pattern_type="author"
            )
            for pattern, service_name, case_sensitive in wire_author_patterns:
                flags = 0 if case_sensitive else re.IGNORECASE
                if re.search(pattern, author_str, flags):
                    matches.setdefault("byline", []).append(
                        f"{service_name} (author pattern)"
                    )
                    detected_services.add(service_name)
                    byline_signal = True
                    break
            
            # Only check additional patterns if not already detected
            if not byline_signal:
                # Check against known wire reporters (from telemetry DB)
                wire_reporter_check = is_wire_reporter(author_str)
                if wire_reporter_check:
                    service_name, confidence = wire_reporter_check
                    matches.setdefault("byline", []).append(
                        f"{service_name} (known wire reporter)"
                    )
                    detected_services.add(service_name)
                    byline_signal = True

        # Byline signal is strong enough alone
        if byline_signal:
            return self._build_wire_result(matches, detected_services, tier="byline")

        # ===================================================================
        # TIER 3: Metadata/Copyright Analysis (STRONG SIGNAL)
        # ===================================================================
        copyright_signal = False

        if content:
            # Check last 150 chars for copyright
            closing = content[-150:] if len(content) > 150 else content
            copyright_patterns = [
                (
                    r"©\s*\d{4}\s+(?:The\s+)?"
                    r"(Associated Press|AP|Reuters|CNN|Bloomberg|NPR|AFP)"
                ),
                (
                    r"Copyright\s+\d{4}\s+(?:The\s+)?"
                    r"(Associated Press|AP|Reuters|CNN|Bloomberg|NPR|AFP)"
                ),
            ]

            for pattern in copyright_patterns:
                match = re.search(pattern, closing, re.IGNORECASE)
                if match:
                    service = self._normalize_service_name(match.group(1))
                    matches.setdefault("copyright", []).append(service)
                    detected_services.add(service)
                    copyright_signal = True

        if copyright_signal:
            return self._build_wire_result(matches, detected_services, tier="copyright")

        # ===================================================================
        # TIER 4: Content Pattern Analysis (WEAK - Requires Additional Evidence)
        # ===================================================================
        content_signal = False

        if content:
            content_start = content[:300].lower()

            # Only check content patterns if we have SOME other signal (weak URL, etc.)
            if weak_url_signal or title:
                # NPR transcript pattern
                if "host:" in content_start:
                    matches.setdefault("content", []).append("NPR transcript pattern")
                    detected_services.add("NPR")
                    content_signal = True

                # AP dateline
                if "(ap)" in content_start:
                    matches.setdefault("content", []).append("AP dateline")
                    detected_services.add("Associated Press")
                    content_signal = True

                # NWS/Weather patterns (only with title confirmation)
                if title and any(
                    kw in title.lower()
                    for kw in ["weather alert", "dense fog", "nws"]
                ):
                    if "national weather service" in content_start:
                        matches.setdefault("content", []).append("NWS attribution")
                        detected_services.add("National Weather Service")
                        content_signal = True

        # Content patterns require additional evidence (weak URL + content)
        if content_signal and weak_url_signal:
            return self._build_wire_result(
                matches, detected_services, tier="content_weak"
            )

        # No strong evidence found
        return None

    def _extract_publisher_from_url(self, url_lower: str) -> list[str]:
        """Extract publisher indicators from URL for byline matching."""
        indicators = []

        # Extract domain
        domain_match = re.search(r"//([^/]+)", url_lower)
        if domain_match:
            domain = domain_match.group(1).replace("www.", "")
            # e.g., "abc17news" from abc17news.com
            indicators.append(domain.split(".")[0])

        # Check for known callsigns in URL
        for callsign, domains in self._CALLSIGN_DOMAINS.items():
            if any(d in url_lower for d in domains):
                indicators.append(callsign.lower())

        return indicators

    def _normalize_service_name(self, service: str) -> str:
        """Normalize wire service names to canonical form."""
        service_upper = service.upper()
        if service_upper in ("AP", "ASSOCIATED PRESS"):
            return "Associated Press"
        elif service_upper == "REUTERS":
            return "Reuters"
        elif service_upper == "CNN":
            return "CNN"
        elif service_upper == "BLOOMBERG":
            return "Bloomberg"
        elif service_upper == "NPR":
            return "NPR"
        elif service_upper in ("AFP", "AGENCE FRANCE-PRESSE"):
            return "AFP"
        return service

    def _build_wire_result(
        self, matches: dict, detected_services: set, tier: str
    ) -> ContentTypeResult:
        """Build wire detection result with confidence based on tier."""
        evidence = matches.copy()
        if detected_services:
            evidence["detected_services"] = sorted(detected_services)
        evidence["detection_tier"] = tier

        # Tier-based confidence
        confidence_map = {
            "url": (1.0, "high"),
            "byline": (0.9, "high"),
            "copyright": (0.85, "high"),
            "content_weak": (0.6, "medium"),
        }
        confidence_score, confidence_label = confidence_map.get(
            tier, (0.5, "medium")
        )

        return ContentTypeResult(
            status="wire",
            confidence_score=confidence_score,
            confidence=confidence_label,
            reason="wire_service_detected",
            evidence=evidence,
            detector_version=self.VERSION,
        )

    def _detect_obituary(
        self,
        *,
        url: str,
        title: str | None,
        keywords: Iterable[str],
        meta_description: str | None,
        content: str | None,
    ) -> ContentTypeResult | None:
        matches: dict[str, list[str]] = {}
        score = 0
        strong_signal_detected = False

        title_matches = self._find_keyword_matches(
            title,
            self._OBITUARY_TITLE_KEYWORDS,
        )
        if title_matches:
            unique_title_matches = sorted(set(title_matches))
            matches["title"] = unique_title_matches
            title_strong_hits = (
                set(unique_title_matches) & self._OBITUARY_STRONG_TITLE_KEYWORDS
            )
            title_weak_hits = set(unique_title_matches) - title_strong_hits
            if title_strong_hits:
                score += self._TITLE_CONFIDENCE_WEIGHT
                strong_signal_detected = True
            if title_weak_hits:
                score += self._METADATA_CONFIDENCE_WEIGHT

        url_matches = self._find_segment_matches(
            url,
            self._OBITUARY_URL_SEGMENTS,
        )
        if url_matches:
            unique_url_matches = sorted(set(url_matches))
            matches["url"] = unique_url_matches
            url_strong_hits = (
                set(unique_url_matches) & self._OBITUARY_HIGH_CONFIDENCE_URL_SEGMENTS
            )
            url_weak_hits = set(unique_url_matches) - url_strong_hits
            if url_strong_hits:
                score += self._URL_CONFIDENCE_WEIGHT
                strong_signal_detected = True
            if url_weak_hits:
                score += self._METADATA_CONFIDENCE_WEIGHT

        keyword_matches = self._matches_from_iterable(
            keywords,
            self._OBITUARY_TITLE_KEYWORDS,
        )
        if keyword_matches:
            unique_keyword_matches = sorted(set(keyword_matches))
            matches["keywords"] = unique_keyword_matches
            keyword_strong_hits = (
                set(unique_keyword_matches) & self._OBITUARY_STRONG_TITLE_KEYWORDS
            )
            if keyword_strong_hits:
                score += self._METADATA_CONFIDENCE_WEIGHT
                strong_signal_detected = True

        description_matches = self._find_keyword_matches(
            meta_description,
            self._OBITUARY_TITLE_KEYWORDS,
        )
        if description_matches:
            unique_description_matches = sorted(set(description_matches))
            matches["meta_description"] = unique_description_matches
            description_strong_hits = (
                set(unique_description_matches) & self._OBITUARY_STRONG_TITLE_KEYWORDS
            )
            if description_strong_hits:
                score += self._METADATA_CONFIDENCE_WEIGHT
                strong_signal_detected = True

        title_pattern_matches = self._find_obituary_title_patterns(title)
        if title_pattern_matches:
            matches["title_patterns"] = sorted(set(title_pattern_matches))
            score += self._METADATA_CONFIDENCE_WEIGHT

        lead = content[:800] if content else ""
        if lead:
            content_matches = self._find_keyword_matches(
                lead,
                self._OBITUARY_CONTENT_KEYWORDS,
            )
            if content_matches:
                unique_content_matches = sorted(set(content_matches))
                matches["content"] = unique_content_matches
                if (
                    set(unique_content_matches)
                    & self._OBITUARY_HIGH_SIGNAL_CONTENT_KEYWORDS
                ):
                    score += self._TITLE_CONFIDENCE_WEIGHT
                    strong_signal_detected = True

        if (
            "content" in matches
            and (set(matches["content"]) & self._OBITUARY_HIGH_SIGNAL_CONTENT_KEYWORDS)
            and "title_patterns" in matches
        ):
            score += self._METADATA_CONFIDENCE_WEIGHT

        if not matches:
            return None

        if not strong_signal_detected:
            return None

        if score < self._TITLE_CONFIDENCE_WEIGHT:
            return None

        confidence_score = normalize_score(score, self._OBITUARY_MAX_SCORE)
        confidence = score_to_label(score)
        return ContentTypeResult(
            status="obituary",
            confidence_score=confidence_score,
            confidence=confidence,
            reason="matched_obituary_signals",
            evidence=matches,
            detector_version=self.VERSION,
        )

    def _detect_opinion(
        self,
        *,
        url: str,
        title: str | None,
        keywords: Iterable[str],
        meta_description: str | None,
    ) -> ContentTypeResult | None:
        matches: dict[str, list[str]] = {}
        score = 0
        strong_signal_detected = False

        title_matches = self._find_opinion_title_matches(title)
        if title_matches:
            matches["title"] = title_matches
            score += self._TITLE_CONFIDENCE_WEIGHT
            strong_signal_detected = True

        url_matches = self._find_segment_matches(
            url,
            self._OPINION_URL_SEGMENTS,
        )
        if url_matches:
            matches["url"] = url_matches
            score += self._URL_CONFIDENCE_WEIGHT
            strong_signal_detected = True

        keyword_matches = self._matches_from_iterable(
            keywords,
            self._OPINION_TITLE_PREFIXES,
        )
        if keyword_matches:
            matches["keywords"] = keyword_matches
            score += self._METADATA_CONFIDENCE_WEIGHT

        description_matches = self._find_keyword_matches(
            meta_description,
            self._OPINION_TITLE_PREFIXES,
        )
        if description_matches:
            matches["meta_description"] = description_matches
            score += self._METADATA_CONFIDENCE_WEIGHT

        if not matches:
            return None

        if not strong_signal_detected:
            return None

        if score < self._TITLE_CONFIDENCE_WEIGHT:
            return None

        confidence_score = normalize_score(score, self._OPINION_MAX_SCORE)
        confidence = score_to_label(score)
        return ContentTypeResult(
            status="opinion",
            confidence_score=confidence_score,
            confidence=confidence,
            reason="matched_opinion_signals",
            evidence=matches,
            detector_version=self.VERSION,
        )

    @staticmethod
    def _normalize_keywords(raw_keywords: str | list[str] | None) -> list[str]:
        if not raw_keywords:
            return []
        if isinstance(raw_keywords, str):
            return [raw_keywords.lower()]
        keywords: list[str] = []
        for keyword in raw_keywords:
            if not keyword:
                continue
            keywords.append(str(keyword).lower())
        return keywords

    @staticmethod
    def _find_keyword_matches(
        value: str | None,
        patterns: Iterable[str],
    ) -> list[str]:
        if not value:
            return []
        lower_value = value.lower()
        matches = [pattern for pattern in patterns if pattern in lower_value]
        return matches

    @staticmethod
    def _find_segment_matches(
        url: str,
        segments: Iterable[str],
    ) -> list[str]:
        lower_url = url.lower()
        return [segment for segment in segments if segment in lower_url]

    @staticmethod
    def _matches_from_iterable(
        haystack: Iterable[str],
        needles: Iterable[str],
    ) -> list[str]:
        needles_normalized = {needle.lower() for needle in needles}
        matches: set[str] = set()
        for item in haystack:
            if not item:
                continue
            item_lower = item.lower()
            for needle in needles_normalized:
                if needle in item_lower:
                    matches.add(needle)
        return sorted(matches)

    def _find_obituary_title_patterns(
        self,
        title: str | None,
    ) -> list[str]:
        if not title:
            return []
        normalized = title.strip()
        if not normalized:
            return []

        tokens = [token for token in re.split(r"\s+", normalized) if token]
        cleaned_tokens = [re.sub(r"[^A-Za-z]", "", token) for token in tokens]
        cleaned_tokens = [token for token in cleaned_tokens if token]
        if not cleaned_tokens:
            return []

        lower_tokens = [token.lower() for token in cleaned_tokens]
        patterns: list[str] = []

        if 1 < len(cleaned_tokens) <= 5 and all(
            token.isupper() for token in cleaned_tokens
        ):
            patterns.append("all_caps_name")

        if (
            1 < len(cleaned_tokens) <= 5
            and all(token.istitle() for token in tokens)
            and not any(
                token in self._OBITUARY_TITLE_STOPWORDS for token in lower_tokens
            )
        ):
            patterns.append("personal_name_title")

        if self._TITLE_YEAR_PATTERN.search(normalized) and re.search(
            r"\s[-–—]\s",
            normalized,
        ):
            patterns.append("life_year_span")

        return patterns

    def _find_opinion_title_matches(self, title: str | None) -> list[str]:
        if not title:
            return []
        lower_title = title.lower().strip()
        matches: list[str] = []
        for prefix in self._OPINION_TITLE_PREFIXES:
            prefix_lower = prefix.lower()
            anchored_variations = (
                f"{prefix_lower}:",
                f"{prefix_lower} –",
                f"{prefix_lower} —",
                f"{prefix_lower} -",
                f"{prefix_lower} |",
            )
            if any(
                lower_title.startswith(variation) for variation in anchored_variations
            ):
                matches.append(prefix_lower)
                continue

            if (
                prefix_lower in {"editorial", "opinion", "commentary"}
                and prefix_lower in lower_title
            ):
                matches.append(prefix_lower)
        return matches
