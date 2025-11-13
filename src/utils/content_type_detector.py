"""Heuristics for detecting opinion pieces and obituaries."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .confidence import normalize_score, score_to_label


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

    VERSION = "2025-11-12a"  # Added AFP detection + author field checking

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

    # Common dateline patterns (CITY_NAME, STATE/COUNTRY (WIRE_SERVICE))
    _DATELINE_PATTERN = re.compile(r"^([A-Z][A-Z\s,\.'-]+)\s*[–—-]\s*", re.MULTILINE)

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

    def detect(
        self,
        *,
        url: str,
        title: str | None,
        metadata: dict | None,
        content: str | None = None,
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
    ) -> ContentTypeResult | None:
        """
        Detect wire service content by analyzing URL, content, and metadata.

        Wire services are often indicated in:
        1. Author field: "Afp Afp", "By AP", "Reuters Staff"
        2. First 150 characters (opening dateline: "WASHINGTON (AP) —")
        3. Last 150 characters (attribution: "©2025 The Associated Press")
            "statesnewsroom.org": "States Newsroom",
            "kansasreflector.com": "States Newsroom",
            "missouriindependent.org": "The Missouri Independent",
            "missouriindependent.com": "The Missouri Independent",
            "wave3.com": "WAVE",

        IMPORTANT: This detector is conservative and requires STRONG evidence:
        - Wire service author field (e.g. "Afp Afp"), OR
        - URL pattern match from major wire service domain, OR
        - Explicit wire service byline/dateline in opening (e.g. "By AP")

        It will NOT trigger on:
        - Just a city dateline (local reporters file from DC too)
        - Just a mention in closing credits (local articles cite sources)
        - Weak URL patterns ALONE (requires author/content evidence too)
        """
        matches: dict[str, list[str]] = {}
        detected_services: set[str] = set()
        wire_byline_found = False

        # Check author field for wire service patterns (STRONG signal)
        author = (metadata or {}).get("byline", "") if metadata else ""
        if author:
            author_lower = author.lower().strip()
            # Common wire service author patterns
            wire_author_patterns = [
                (r"^afp\s+afp$", "AFP"),
                (r"^(by\s+)?afp(\s+staff)?$", "AFP"),
                (r"^(by\s+)?agence france[- ]presse$", "AFP"),
                (r"^(by\s+)?ap(\s+staff)?$", "Associated Press"),
                (r"^(by\s+)?associated press$", "Associated Press"),
                (r"^(by\s+)?reuters(\s+staff)?$", "Reuters"),
                (r"^(by\s+)?cnn(\s+(staff|wire))?$", "CNN"),
                (r"\busa\s+today\b", "USA TODAY"),
                (r"^(by\s+)?bloomberg$", "Bloomberg"),
                # Kansas Reflector and Missouri Independent may appear anywhere in the
                # byline, often prefixed by a date or followed by an author name. Match
                # them when they appear anywhere, not only at the start or end.
                (r"\bkansas\s+reflector\b", "States Newsroom"),
                (r"\bkansasreflector\b", "States Newsroom"),
                (r"\b(the\s+)?missouri\s+independent\b", "The Missouri Independent"),
                (r"\b(wave|wave3|wave3\.com|wave3news)\b", "WAVE"),
                (r"\bstates\s*newsroom\b", "States Newsroom"),
                (r"\bafp$", "AFP"),  # Name ending with AFP (e.g., "John Smith AFP")
            ]
            for pattern, service_name in wire_author_patterns:
                if re.search(pattern, author_lower, re.IGNORECASE):
                    matches["author"] = [f"{service_name} (author field)"]
                    detected_services.add(service_name)
                    wire_byline_found = True
                    break

        # Check URL for STRONG wire service patterns (actual wire service domains)
        url_lower = url.lower()
        url_wire_matches = []

        # Strong URL patterns (actual wire service domains)
        # NOTE: Content ON these domains is original, not syndicated
        # We track these to EXCLUDE them from wire detection
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

        # Check if this content is from the wire service's own domain
        is_own_source = False
        for domain, service_name in own_source_domains.items():
            if domain in url_lower:
                is_own_source = True
                break

        # If this is from the service's own domain, it's NOT wire/syndicated
        if is_own_source:
            return None

        # Weak URL patterns (syndication markers on local sites)
        # Only count these if we also have strong content evidence
        weak_url_patterns = [
            "/ap-",
            "/cnn-",
            "/reuters-",
            "/wire/",
            "/world/",
            "/national/",
        ]
        weak_url_match = False
        for pattern in weak_url_patterns:
            if pattern in url_lower:
                url_wire_matches.append(pattern)
                weak_url_match = True
                # Extract service name from pattern
                if "ap" in pattern:
                    detected_services.add("Associated Press")
                elif "cnn" in pattern:
                    detected_services.add("CNN")
                elif "reuters" in pattern:
                    detected_services.add("Reuters")

        if url_wire_matches:
            matches["url"] = url_wire_matches

        # Check article content for STRONG wire service indicators
        if content:
            content_matches = []

            # Check first 150 characters for opening dateline/byline
            opening = content[:150] if len(content) > 150 else content

            # Look for explicit wire service bylines and datelines (STRONG evidence)
            # Dateline format: "CITY (AP) —" or "CITY, State (Reuters) —"
            # Byline format: "By [Service]", "[Service] —"
            # Also catch: "Person Name USA TODAY" (syndicated when not from USA TODAY)
            wire_byline_patterns = [
                # AP datelines (STRONG - very common)
                (r"^[A-Z][A-Z\s,]+\(AP\)\s*[—–-]", "Associated Press"),
                (r"^[A-Z][A-Z\s,]+\(Associated Press\)\s*[—–-]", "Associated Press"),
                # Reuters datelines
                (r"^[A-Z][A-Z\s,]+\(Reuters\)\s*[—–-]", "Reuters"),
                (r"^[A-Z][A-Z\s,]+\(CNN\)\s*[—–-]", "CNN"),
                # AFP datelines
                (r"^[A-Z][A-Z\s,]+\(AFP\)\s*[—–-]", "AFP"),
                (r"^[A-Z][A-Z\s,]+\(Agence France-Presse\)\s*[—–-]", "AFP"),
                # Standard bylines
                (r"^By (AP|Associated Press|A\.P\.)", "Associated Press"),
                (r"^(AP|Associated Press|A\.P\.)\s*[—–-]", "Associated Press"),
                (r"^By (Reuters)", "Reuters"),
                (r"^(Reuters)\s*[—–-]", "Reuters"),
                (r"^By (AFP|Agence France-Presse)", "AFP"),
                (r"^(AFP|Agence France-Presse)\s*[—–-]", "AFP"),
                (r"^By (CNN)", "CNN"),
                (r"^(CNN)\s*[—–-]", "CNN"),
                (r"^By (Bloomberg)", "Bloomberg"),
                (r"^(Bloomberg)\s*[—–-]", "Bloomberg"),
                (r"^By (NPR|National Public Radio)", "NPR"),
                (r"^(NPR)\s*[—–-]", "NPR"),
                (r"^By (Kansas Reflector|The Kansas Reflector)", "States Newsroom"),
                (r"^(Kansas Reflector)\s*[—–-]", "States Newsroom"),
                (
                    r"^By (The Missouri Independent|Missouri Independent)",
                    "The Missouri Independent",
                ),
                (
                    r"^(The Missouri Independent)\s*[—–-]",
                    "The Missouri Independent",
                ),
                (r"^By (WAVE|Wave|WAVE3)", "WAVE"),
                (r"^(WAVE|Wave|WAVE3)\s*[—–-]", "WAVE"),
                (r"^By (States Newsroom)", "States Newsroom"),
                (r"^(States Newsroom)\s*[—–-]", "States Newsroom"),
                # Syndicated bylines: "Person Name USA TODAY" etc.
                (r"\b(USA TODAY|USA Today)\s*$", "USA TODAY"),
                (r"\b(Wall Street Journal)\s*$", "Wall Street Journal"),
                (r"\b(New York Times|The New York Times)\s*$", "The New York Times"),
                (r"\b(Washington Post|The Washington Post)\s*$", "The Washington Post"),
                (r"\b(Los Angeles Times)\s*$", "Los Angeles Times"),
                (r"\b(Associated Press)\s*$", "Associated Press"),
                (r"\b(Reuters)\s*$", "Reuters"),
                (r"\b(Bloomberg)\s*$", "Bloomberg"),
                (r"\b(AFP|Agence France-Presse)\s*$", "AFP"),
                (r"\b(States Newsroom)\s*$", "States Newsroom"),
            ]

            for pattern, service_name in wire_byline_patterns:
                if re.search(pattern, opening, re.MULTILINE | re.IGNORECASE):
                    content_matches.append(f"{service_name} (byline)")
                    detected_services.add(service_name)
                    wire_byline_found = True

            # Check for wire service patterns in opening (less strong)
            if not wire_byline_found:
                for (
                    pattern,
                    service_name,
                    case_sensitive,
                ) in self._WIRE_SERVICE_PATTERNS:
                    flags = 0 if case_sensitive else re.IGNORECASE
                    if re.search(pattern, opening, flags):
                        # Only count if it looks like attribution
                        # Look for: "According to AP", "AP reports", etc.
                        context_pattern = rf"(?:By|according to|reports?)\s+{pattern}"
                        if re.search(context_pattern, opening, flags | re.IGNORECASE):
                            content_matches.append(f"{service_name} (opening)")
                            detected_services.add(service_name)

                # Check for 'first appeared in' patterns which often indicate
                # syndicated content (States Newsroom affiliates).
                # Example: "This story first appeared in the Kansas Reflector, a States Newsroom affiliate"
                first_appeared_match = re.search(
                    r"first appeared in (?:the )?([^,]+?),?\s*(?:a|an)?\s*(?:states\s+newsroom\s+affiliate)",
                    content,
                    re.IGNORECASE,
                )
                if first_appeared_match:
                    pub = first_appeared_match.group(1).strip()
                    # Don't mark as syndicated if the current host is the original publisher
                    # Host-check: treat the detected publisher as the original source
                    pub_lower = pub.lower()
                    host_is_pub = False
                    if "kansas" in pub_lower and "reflector" in pub_lower:
                        host_is_pub = "kansasreflector.com" in url_lower
                    elif "missouri" in pub_lower and "independent" in pub_lower:
                        host_is_pub = (
                            "missouriindependent.org" in url_lower
                            or "missouriindependent.com" in url_lower
                        )
                    else:
                        # Generic host check: if the publisher-controlled domain appears in the url
                        # or the publisher name in url (slug style) appears, consider it own source
                        host_is_pub = (
                            pub_lower.replace(" ", "") in url_lower
                            or pub_lower in url_lower
                        )
                    if not host_is_pub:
                        content_matches.append(
                            f"States Newsroom (first_appeared: {pub})"
                        )
                        detected_services.add("States Newsroom")
                        wire_byline_found = True

            # Check last 150 characters for copyright/attribution (STRONG)
            closing = content[-150:] if len(content) > 150 else content
            copyright_patterns = [
                (
                    r"©\s*\d{4}\s+(?:The\s+)?"
                    r"(Associated Press|AP|Reuters|CNN|Bloomberg|NPR|AFP|"
                    r"Agence France-Presse|States Newsroom|WAVE|"
                    r"The Missouri Independent)",
                    "copyright",
                ),
                (
                    r"Copyright\s+\d{4}\s+(?:The\s+)?"
                    r"(Associated Press|AP|Reuters|CNN|Bloomberg|NPR|AFP|"
                    r"Agence France-Presse|States Newsroom|WAVE|"
                    r"The Missouri Independent)",
                    "copyright",
                ),
                (
                    r"All rights reserved\.?\s+(?:The\s+)?"
                    r"(Associated Press|AP|Reuters|CNN|NPR|AFP|Agence France-Presse|"
                    r"States Newsroom|WAVE|The Missouri Independent)",
                    "copyright",
                ),
            ]

            # Also check for "told AFP" / "told Reuters" patterns (STRONG)
            # This is a very common pattern in wire service articles
            told_patterns = [
                (r"told\s+(AFP|Agence France-Presse)", "AFP"),
                (r"told\s+(Reuters)", "Reuters"),
                (r"told\s+(AP|Associated Press)", "Associated Press"),
                (r"told\s+(CNN)", "CNN"),
                (r"told\s+(States Newsroom)", "States Newsroom"),
                (r"told\s+(WAVE|Wave|WAVE3)", "WAVE"),
                (
                    r"told\s+(The Missouri Independent|Missouri Independent)",
                    "The Missouri Independent",
                ),
                (r"told\s+(kansas\s*reflector|kansasreflector)", "States Newsroom"),
            ]

            for pattern, service_name in told_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    content_matches.append(f"{service_name} (attribution)")
                    detected_services.add(service_name)

            for pattern, marker_type in copyright_patterns:
                match = re.search(pattern, closing, re.IGNORECASE)
                if match:
                    service = match.group(1)
                    # Normalize service name
                    if service.upper() in ("AP", "ASSOCIATED PRESS"):
                        service_name = "Associated Press"
                    elif service.upper() == "REUTERS":
                        service_name = "Reuters"
                    elif service.upper() == "CNN":
                        service_name = "CNN"
                    elif service.upper() == "BLOOMBERG":
                        service_name = "Bloomberg"
                    elif service.upper() == "NPR":
                        service_name = "NPR"
                    elif service.upper() in ("AFP", "AGENCE FRANCE-PRESSE"):
                        service_name = "AFP"
                    elif service.upper() in ("STATES NEWSROOM", "STATESNEWSROOM"):
                        service_name = "States Newsroom"
                    elif service.upper() in ("WAVE", "WAVE3"):
                        service_name = "WAVE"
                    elif service.upper() in ("KANSAS REFLECTOR", "KANSASREFLECTOR"):
                        service_name = "States Newsroom"
                    elif service.upper() in (
                        "THE MISSOURI INDEPENDENT",
                        "MISSOURI INDEPENDENT",
                    ):
                        service_name = "The Missouri Independent"
                    else:
                        service_name = service

                    # Check if this is from the service's own source
                    # (e.g., "Copyright NPR" on npr.org is NOT syndicated)
                    url_lower = url.lower()
                    is_own_source = False
                    if service_name == "NPR" and "npr.org" in url_lower:
                        is_own_source = True
                    elif (
                        service_name == "Associated Press" and "apnews.com" in url_lower
                    ):
                        is_own_source = True
                    elif service_name == "Reuters" and "reuters.com" in url_lower:
                        is_own_source = True
                    elif service_name == "CNN" and "cnn.com" in url_lower:
                        is_own_source = True
                    elif service_name == "Bloomberg" and "bloomberg.com" in url_lower:
                        is_own_source = True
                    elif (
                        service_name == "States Newsroom"
                        and "statesnewsroom.org" in url_lower
                    ):
                        is_own_source = True
                    elif service_name == "States Newsroom" and (
                        "statesnewsroom.org" in url_lower
                        or "kansasreflector.com" in url_lower
                        or "missouriindependent.org" in url_lower
                        or "missouriindependent.com" in url_lower
                    ):
                        is_own_source = True
                    elif service_name == "The Missouri Independent" and (
                        "missouriindependent.org" in url_lower
                        or "missouriindependent.com" in url_lower
                    ):
                        is_own_source = True
                    elif service_name == "WAVE" and (
                        "wave3.com" in url_lower or "wave3" in url_lower
                    ):
                        is_own_source = True

                    # Only mark as wire if it's NOT from the service's own source
                    if not is_own_source:
                        content_matches.append(f"{service_name} ({marker_type})")
                        detected_services.add(service_name)

            if content_matches:
                matches["content"] = content_matches

        # CONSERVATIVE DECISION LOGIC:
        # Only mark as wire if we have STRONG evidence:
        # 1. Wire byline in opening, OR
        # 2. Copyright/attribution in closing, OR
        # 3. Weak URL match + strong content evidence

        if not matches:
            return None

        # Require strong evidence
        has_strong_evidence = wire_byline_found or any(
            "copyright" in m or "byline" in m for m in matches.get("content", [])
        )

        # Weak URL + weak content = not enough
        if weak_url_match and not has_strong_evidence:
            return None

        # Just a dateline or vague mention = not enough
        if not has_strong_evidence:
            return None

        # Build evidence summary
        evidence = matches.copy()
        if detected_services:
            evidence["detected_services"] = sorted(detected_services)

        # Calculate confidence based on evidence
        score = 0
        if "url" in matches:
            score += 2  # URL patterns are strong indicators
        if "content" in matches:
            score += 2  # Content patterns are strong indicators

        # Normalize score (max 4 points)
        confidence_score = min(score / 4.0, 1.0)
        confidence = "high" if score >= 3 else "medium"

        return ContentTypeResult(
            status="wire",
            confidence_score=confidence_score,
            confidence=confidence,
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
