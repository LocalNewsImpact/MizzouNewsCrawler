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
    """Detect high-signal opinion and obituary content types."""

    VERSION = "2025-09-27a"

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
