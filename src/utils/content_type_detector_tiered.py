"""Tiered wire service detection with clear priority ordering.

This module implements a systematic tiered detection strategy for identifying
wire service content, addressing false positives from the previous ad-hoc approach.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .confidence import normalize_score, score_to_label
from .wire_reporters import is_wire_reporter


@dataclass(frozen=True)
class DetectionTier:
    """Represents a detection tier with evidence."""

    tier: int
    name: str
    confidence_level: str  # "strongest", "strong", "medium", "weak"
    evidence: list[str]
    service_name: str | None = None


@dataclass(frozen=True)
class ContentTypeResult:
    """Structured result describing detected article type."""

    status: str
    confidence_score: float
    confidence: str
    reason: str
    evidence: dict[str, list[str]]
    detector_version: str
    detection_tier: int | None = None  # Which tier made the determination


class TieredWireServiceDetector:
    """
    Tiered wire service detection with clear priority ordering.

    Detection Tiers (in order of execution):
    1. URL Structure Analysis (Strongest Signal)
       - Wire service names in URL paths
       - Geographic scope indicators
       - BUT: Exclude if on wire service's own domain

    2. Byline Analysis (Strong Signal)
       - Wire service bylines and author fields
       - CRITICAL: Local byline exception - if byline matches publisher, it's local
       - Multiple bylines (common in syndicated content)

    3. Content Metadata (Strong Signal)
       - Copyright notices
       - Dateline formats with explicit wire attribution
       - BUT: Exclude common false positive patterns (NWS weather alerts)

    4. Content Pattern Analysis (Weak Signal - Last Resort)
       - Only used when higher tiers provide supporting evidence
       - Generic content patterns alone are insufficient
    """

    VERSION = "2025-11-24-tiered-v1"

    # Tier 1: Strong URL patterns (actual wire service domains)
    _WIRE_SERVICE_DOMAINS = {
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

    # Tier 1: URL path patterns indicating syndication
    # NOTE: ALL wire URL patterns are now DISABLED.
    # Analysis of ground truth data shows that local publishers intentionally
    # republish wire service content (AP, CNN, Reuters, Stacker) in dedicated
    # sections. URLs like /ap-, /cnn-, /stacker/ indicate LICENSED SYNDICATED
    # CONTENT that the outlet has permission to publish, NOT unattributed wire
    # syndication.
    #
    # The business requirement is to treat ALL content on local news sites as
    # local content, regardless of wire service attribution in URLs or bylines.
    _WIRE_URL_PATH_PATTERNS = [
        # All disabled - local outlets license and republish wire content
        # (r"/ap-", "Associated Press"),
        # (r"/reuters-", "Reuters"),
        # (r"/wire/", "Wire Service"),
    ]
    
    # Content partnership exclusions - these sections indicate intentional
    # republishing by local affiliates, NOT unattributed wire syndication
    _CONTENT_PARTNERSHIP_PATTERNS = [
        r"/cnn-",  # CNN content sections (cnn-sports, cnn-spanish, etc.)
        r"/stacker-",  # Stacker syndicated content sections
        r"/stacker/",  # Alternative Stacker URL format
    ]

    # Tier 1: Geographic scope patterns (require additional evidence)
    # NOTE: These patterns are NO LONGER USED for wire detection
    # Local news sites often have /national/ and /world/ sections where they
    # intentionally publish licensed syndicated content (AFP, AP, etc.)
    # This is NOT unattributed wire syndication - it's licensed republishing
    # and should be treated as local content
    _GEOGRAPHIC_SCOPE_PATTERNS = [
        # Disabled - too many false positives
        # r"/national/",
        # r"/nation/",
        # r"/world/",
        # r"/international/",
    ]

    # Known local broadcaster callsigns (Missouri market)
    # These are NOT wire services when appearing on their own domains
    _LOCAL_BROADCASTER_CALLSIGNS = {
        "KMIZ": ["abc17news.com"],
        "KOMU": ["komu.com"],
        "KRCG": ["krcgtv.com"],
        "KQFX": ["fox22now.com"],
        "KJLU": ["zimmerradio.com"],
        "KSMU": ["ksmu.org"],  # Local NPR affiliate
    }

    # Tier 2: Wire service byline patterns
    # NOTE: These patterns are significantly relaxed. Wire service bylines
    # (like "Afp Afp", "Associated Press") on local news sites often indicate
    # LICENSED SYNDICATED CONTENT that the outlet is intentionally republishing,
    # not unattributed wire syndication. We now only flag wire content when
    # it appears on sites without explicit wire service attribution in the URL.
    #
    # Key change: Bylines alone are no longer sufficient for wire detection.
    # They must be combined with strong URL signals (like /ap-, /wire/)
    _WIRE_BYLINE_PATTERNS = [
        # Disabled - local outlets intentionally republish wire content
        # These bylines indicate licensed content, not unattributed syndication
        # (r"^afp\s+afp$", "AFP"),
        # (r"^(by\s+)?afp(\s+staff)?$", "AFP"),
        # (r"^(by\s+)?agence france[- ]presse$", "AFP"),
        # (r"^(by\s+)?ap(\s+staff)?$", "Associated Press"),
        # (r"^(by\s+)?associated press$", "Associated Press"),
        # (r"^(by\s+)?reuters(\s+staff)?$", "Reuters"),
        # (r"^(by\s+)?cnn(\s+(staff|wire))?$", "CNN"),
        # (r"\busa\s+today\b", "USA TODAY"),
        # (r"^(by\s+)?bloomberg$", "Bloomberg"),
        # (r"\bkansas\s+reflector\b", "States Newsroom"),
        # (r"\b(the\s+)?missouri\s+independent\b", "The Missouri Independent"),
        # (r",\s*associated press$", "Associated Press"),
        # (r",\s*reuters$", "Reuters"),
        # (r",\s*cnn$", "CNN"),
        # (r",\s*afp$", "AFP"),
    ]

    # Tier 3: Dateline patterns (with NWS exclusion)
    # These appear in the opening of wire articles
    _DATELINE_PATTERNS = [
        # Format: CITY (AP) — or CITY (Reuters) —
        (r"^[A-Z][A-Za-z\s,]+\s+\(AP\)\s+[—–-]", "Associated Press"),
        (r"^[A-Z][A-Za-z\s,]+\s+\(Reuters\)\s+[—–-]", "Reuters"),
        (r"^[A-Z][A-Za-z\s,]+\s+\(AFP\)\s+[—–-]", "AFP"),
        (r"^[A-Z][A-Za-z\s,]+\s+\(CNN\)\s+[—–-]", "CNN"),
        (r"^[A-Z][A-Za-z\s,]+\s+\(Bloomberg\)\s+[—–-]", "Bloomberg"),
    ]

    # FALSE POSITIVE EXCLUSIONS
    # NWS weather alerts are NOT wire service content
    _NWS_EXCLUSION_PATTERNS = [
        r"\bNWS\b",  # National Weather Service
        r"\bNOAA\b",  # National Oceanic and Atmospheric Administration
        r"Dense Fog Advisory",
        r"Weather Advisory",
        r"Winter Storm Warning",
        r"Severe Thunderstorm Warning",
    ]

    def detect_wire_service(
        self,
        *,
        url: str,
        content: str | None,
        metadata: dict | None = None,
        source: str | None = None,
    ) -> ContentTypeResult | None:
        """
        Detect wire service content using tiered detection strategy.

        Args:
            url: Article URL
            content: Article text content
            metadata: Article metadata including byline
            source: Publisher source name

        Returns:
            ContentTypeResult if wire service detected, None otherwise
        """
        # Check for NWS/weather alert exclusions first
        if self._is_weather_alert_exclusion(url, content, metadata):
            return None

        # Tier 1: URL Structure Analysis
        tier1_result = self._tier1_url_analysis(url, source)
        if tier1_result and tier1_result.confidence_level == "strongest":
            return self._build_result(tier1_result)

        # Tier 2: Byline Analysis
        tier2_result = self._tier2_byline_analysis(url, metadata, source)
        if tier2_result:
            return self._build_result(tier2_result)

        # Tier 3: Content Metadata (datelines, copyright)
        if content:
            tier3_result = self._tier3_content_metadata(url, content, source)
            if tier3_result:
                return self._build_result(tier3_result)

        # Tier 4: Content Pattern Analysis (only with supporting evidence)
        # Geographic scope URLs need additional content evidence
        if tier1_result and tier1_result.confidence_level == "medium":
            if content:
                tier4_result = self._tier4_content_patterns(content)
                if tier4_result:
                    # Combine tier 1 and tier 4 evidence
                    return self._build_result(
                        DetectionTier(
                            tier=4,
                            name="URL + Content Pattern",
                            confidence_level="medium",
                            evidence=tier1_result.evidence + tier4_result.evidence,
                            service_name=tier1_result.service_name
                            or tier4_result.service_name,
                        )
                    )

        return None

    def _is_weather_alert_exclusion(
        self, url: str, content: str | None, metadata: dict | None
    ) -> bool:
        """Check if this is a weather alert that should not be classified as wire."""
        # Check URL
        if "/alerts/" in url or "/weather/" in url:
            # Check for NWS patterns
            title = (metadata or {}).get("title", "")
            if any(
                re.search(pattern, title, re.IGNORECASE)
                for pattern in self._NWS_EXCLUSION_PATTERNS
            ):
                return True

            # Check content opening
            if content:
                opening = content[:200]
                if any(
                    re.search(pattern, opening, re.IGNORECASE)
                    for pattern in self._NWS_EXCLUSION_PATTERNS
                ):
                    return True

        return False

    def _tier1_url_analysis(
        self, url: str, source: str | None
    ) -> DetectionTier | None:
        """
        Tier 1: URL Structure Analysis (Strongest Signal).

        Checks for:
        - Wire service names in URL paths
        - Geographic scope indicators
        - BUT excludes content on wire service's own domain
        - BUT excludes content partnership sections (CNN, Stacker)
        """
        url_lower = url.lower()

        # Check if on wire service's own domain (NOT syndicated)
        for domain, service_name in self._WIRE_SERVICE_DOMAINS.items():
            if domain in url_lower:
                # Content on the service's own domain is original, not wire
                return None

        # Check for content partnership patterns (EXCLUSION)
        # These represent intentional republishing, not wire syndication
        for pattern in self._CONTENT_PARTNERSHIP_PATTERNS:
            if re.search(pattern, url_lower):
                # Content in partnership sections should not be flagged as wire
                return None

        # Check for wire service path patterns (STRONG signal)
        for pattern, service_name in self._WIRE_URL_PATH_PATTERNS:
            if re.search(pattern, url_lower):
                return DetectionTier(
                    tier=1,
                    name="URL Structure (Wire Path)",
                    confidence_level="strongest",
                    evidence=[f"Wire URL pattern: {pattern}"],
                    service_name=service_name,
                )

        # Check for geographic scope patterns (MEDIUM signal - needs confirmation)
        for pattern in self._GEOGRAPHIC_SCOPE_PATTERNS:
            if re.search(pattern, url_lower):
                # Geographic scope on local sites suggests wire, but needs more evidence
                return DetectionTier(
                    tier=1,
                    name="URL Structure (Geographic Scope)",
                    confidence_level="medium",
                    evidence=[f"Geographic scope URL: {pattern}"],
                    service_name=None,
                )

        return None

    def _tier2_byline_analysis(
        self, url: str, metadata: dict | None, source: str | None
    ) -> DetectionTier | None:
        """
        Tier 2: Byline Analysis (Strong Signal).

        CRITICAL EXCEPTION: If byline matches publisher source, treat as local content.
        Also excludes wire service bylines on the service's own domain.
        """
        if not metadata:
            return None

        author = metadata.get("byline", "")
        if not author:
            return None

        # Handle dict/list byline formats
        if isinstance(author, dict):
            authors_list = author.get("authors", [])
            if authors_list and isinstance(authors_list, list):
                author = ", ".join(str(a) for a in authors_list)
            else:
                author = str(author.get("original", ""))
        elif isinstance(author, list):
            author = ", ".join(str(a) for a in author)

        author_lower = author.lower().strip()
        url_lower = url.lower()

        # Check if byline matches local source (EXCLUSION)
        if source:
            source_lower = source.lower()
            # Check for local broadcaster callsigns
            for callsign, domains in self._LOCAL_BROADCASTER_CALLSIGNS.items():
                if callsign.lower() in author_lower:
                    # Check if this is on the broadcaster's own site
                    if callsign.lower() in url_lower or any(
                        domain in url_lower for domain in domains
                    ):
                        # Local broadcaster on own site - NOT wire
                        return None

        # Check for known wire reporters
        wire_reporter_check = is_wire_reporter(author)
        if wire_reporter_check:
            service_name, confidence = wire_reporter_check
            
            # Check if on wire service's own domain
            for domain, svc_name in self._WIRE_SERVICE_DOMAINS.items():
                if domain in url_lower and svc_name == service_name:
                    # On service's own domain - NOT wire
                    return None
            
            return DetectionTier(
                tier=2,
                name="Byline (Known Wire Reporter)",
                confidence_level="strong",
                evidence=[f"Wire reporter: {service_name}"],
                service_name=service_name,
            )

        # Check for wire service byline patterns
        for pattern, service_name in self._WIRE_BYLINE_PATTERNS:
            if re.search(pattern, author_lower, re.IGNORECASE):
                # Check if on wire service's own domain
                for domain, svc_name in self._WIRE_SERVICE_DOMAINS.items():
                    if domain in url_lower and svc_name == service_name:
                        # On service's own domain - NOT wire
                        return None
                
                return DetectionTier(
                    tier=2,
                    name="Byline (Wire Service Pattern)",
                    confidence_level="strong",
                    evidence=[f"Wire byline: {service_name}"],
                    service_name=service_name,
                )

        return None

    def _tier3_content_metadata(
        self, url: str, content: str, source: str | None
    ) -> DetectionTier | None:
        """
        Tier 3: Content Metadata (Strong Signal).

        Checks for:
        - Datelines in opening (e.g., "WASHINGTON (AP) —")
        - Copyright notices
        - BUT excludes if on service's own domain
        """
        opening = content[:200] if len(content) > 200 else content

        # Check for dateline patterns in opening
        for pattern, service_name in self._DATELINE_PATTERNS:
            match = re.search(pattern, opening, re.MULTILINE)
            if match:
                # Verify not on service's own domain
                url_lower = url.lower()
                is_own_source = any(
                    domain in url_lower and svc == service_name
                    for domain, svc in self._WIRE_SERVICE_DOMAINS.items()
                )
                if not is_own_source:
                    return DetectionTier(
                        tier=3,
                        name="Content Metadata (Dateline)",
                        confidence_level="strong",
                        evidence=[f"Dateline: {service_name}"],
                        service_name=service_name,
                    )

        # Check for copyright in closing
        closing = content[-200:] if len(content) > 200 else content
        copyright_patterns = [
            (
                r"©\s*\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR|AFP)",
                "copyright",
            ),
            (
                r"Copyright\s+\d{4}\s+(?:The\s+)?(Associated Press|AP|Reuters|CNN|Bloomberg|NPR|AFP)",
                "copyright",
            ),
        ]

        for pattern, marker_type in copyright_patterns:
            match = re.search(pattern, closing, re.IGNORECASE)
            if match:
                service = match.group(1)
                service_name = self._normalize_service_name(service)

                # Verify not on service's own domain
                url_lower = url.lower()
                is_own_source = any(
                    domain in url_lower and svc == service_name
                    for domain, svc in self._WIRE_SERVICE_DOMAINS.items()
                )
                if not is_own_source:
                    return DetectionTier(
                        tier=3,
                        name="Content Metadata (Copyright)",
                        confidence_level="strong",
                        evidence=[f"Copyright: {service_name}"],
                        service_name=service_name,
                    )

        return None

    def _tier4_content_patterns(self, content: str) -> DetectionTier | None:
        """
        Tier 4: Content Pattern Analysis (Weak Signal - Last Resort).

        Only used when higher tiers provide supporting evidence.
        Looks for generic wire service mentions.
        """
        # This tier requires supporting evidence from other tiers
        # and should only be called when tier 1 found geographic scope patterns
        opening = content[:300] if len(content) > 300 else content

        # Look for wire service mentions in context
        wire_patterns = [
            (r"(?:according to|reports?)\s+(AP|Associated Press)", "Associated Press"),
            (r"(?:according to|reports?)\s+Reuters", "Reuters"),
            (r"(?:according to|reports?)\s+AFP", "AFP"),
            (r"(?:according to|reports?)\s+CNN", "CNN"),
        ]

        for pattern, service_name in wire_patterns:
            if re.search(pattern, opening, re.IGNORECASE):
                return DetectionTier(
                    tier=4,
                    name="Content Pattern (Wire Attribution)",
                    confidence_level="weak",
                    evidence=[f"Wire attribution: {service_name}"],
                    service_name=service_name,
                )

        return None

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

    def _build_result(self, tier: DetectionTier) -> ContentTypeResult:
        """Build a ContentTypeResult from a DetectionTier."""
        evidence = {
            "tier": [f"Tier {tier.tier}: {tier.name}"],
            "signals": tier.evidence,
        }
        if tier.service_name:
            evidence["service"] = [tier.service_name]

        # Map confidence level to score
        confidence_map = {
            "strongest": (1.0, "high"),
            "strong": (0.85, "high"),
            "medium": (0.65, "medium"),
            "weak": (0.5, "medium"),
        }
        confidence_score, confidence_label = confidence_map.get(
            tier.confidence_level, (0.5, "medium")
        )

        return ContentTypeResult(
            status="wire",
            confidence_score=confidence_score,
            confidence=confidence_label,
            reason=f"wire_detected_tier{tier.tier}",
            evidence=evidence,
            detector_version=self.VERSION,
            detection_tier=tier.tier,
        )
