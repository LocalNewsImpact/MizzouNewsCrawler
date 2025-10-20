"""
Byline cleaning utility for news articles.
"""

import json
import logging
import re
from difflib import SequenceMatcher

# Import telemetry system
from .byline_telemetry import BylineCleaningTelemetry

logger = logging.getLogger(__name__)


class BylineCleaner:
    """Clean and normalize author bylines from news articles."""

    # Common titles and job descriptions to remove
    TITLES_TO_REMOVE = {
        # Basic titles
        "staff",
        "reporter",
        "editor",
        "publisher",
        "writer",
        "journalist",
        "correspondent",
        "contributor",
        "freelancer",
        "intern",
        "blogger",
        # Senior/lead roles
        "senior",
        "lead",
        "chief",
        "managing",
        "executive",
        "associate",
        "assistant",
        "deputy",
        "acting",
        "interim",
        "former",
        "co-",
        # Department/beat specific
        "news",
        "sports",
        "politics",
        "business",
        "entertainment",
        "lifestyle",
        "health",
        "science",
        "technology",
        "education",
        "crime",
        "courts",
        "government",
        "city",
        "county",
        "state",
        "national",
        "international",
        "investigative",
        "feature",
        "opinion",
        "editorial",
        "column",
        "columnist",
        # Organization roles
        "director",
        "manager",
        "coordinator",
        "specialist",
        "analyst",
        "producer",
        "photographer",
        "videographer",
        "multimedia",
        # Special correspondent/contributor patterns
        "special",
        "contributing",
        "freelance",
        "guest",
        "visiting",
        # Common suffixes/prefixes
        "the",
        "for",
        "at",
        "of",
        "and",
        "from",
        "with",
        "by",
        "staff writer",
        "to",
        "he",
        "tot",
        "teh",  # Common typos and words in "Special to"
        # Publication words (when used as titles/suffixes)
        "tribune",
        "herald",
        "gazette",
        "times",
        "post",
        "press",
        "journal",
        "daily",
        "weekly",
        "newspaper",
        "magazine",
        "publication",
        "citizen",
        "sentinel",
        "observer",
        "chronicle",
        "register",
        "dispatch",
        "record",
        "mirror",
        "beacon",
        "voice",
        "leader",
        "independent",
        # Degrees and credentials
        "phd",
        "md",
        "jd",
        "mba",
        "ma",
        "ms",
        "bs",
        "ba",
    }

    # Wire services and syndicated content sources
    # (preserve these for later filtering)
    WIRE_SERVICES = {
        "associated press",
        "ap",
        "reuters",
        "bloomberg",
        "cnn",
        "cnn newssource",
        "fox news",
        "fox",
        "nbc",
        "abc",
        "abc news",
        "cbs",
        "npr",
        "pbs",
        "usa today",
        "wall street journal",
        "new york times",
        "the new york times",
        "washington post",
        "the washington post",
        "los angeles times",
        "chicago tribune",
        "boston globe",
        "the guardian",
        "bbc",
        "politico",
        "the hill",
        "mcclatchy",
        "gannett",
        "hearst",
        "scripps",
        "sinclair",
    }

    # Normalization mapping for wire services to canonical names
    WIRE_SERVICE_NORMALIZATION = {
        "associated press": "The Associated Press",
        "the associated press": "The Associated Press",
        "ap": "The Associated Press",
        "cnn": "CNN NewsSource",
        "cnn newssource": "CNN NewsSource",
        "hearst": "Hearst",
        "abc": "ABC News",
        "abc news": "ABC News",
        "reuters": "Reuters",
        "bloomberg": "Bloomberg",
        "npr": "NPR",
        "pbs": "PBS",
    }
    # Journalism-specific nouns that are never names
    JOURNALISM_NOUNS = {
        # Core journalism terms
        "news",
        "editor",
        "editors",
        "reporter",
        "reporters",
        "staff",
        "writer",
        "writers",
        "journalist",
        "journalists",
        "correspondent",
        "correspondents",
        "columnist",
        "columnists",
        "publisher",
        "publishers",
        "producer",
        "producers",
        "anchor",
        "anchors",
        # Job functions
        "investigator",
        "investigators",
        "photographer",
        "photographers",
        "videographer",
        "videographers",
        "analyst",
        "analysts",
        "critic",
        "critics",
        "reviewer",
        "reviewers",
        "contributor",
        "contributors",
        "freelancer",
        "freelancers",
        "intern",
        "interns",
        # Editorial roles
        "editorial",
        "editorials",
        "opinion",
        "opinions",
        "commentary",
        "commentaries",
        "column",
        "columns",
        "feature",
        "features",
        "blog",
        "blogs",
        "blogger",
        "bloggers",
        # Publication terms
        "publication",
        "publications",
        "newspaper",
        "newspapers",
        "magazine",
        "magazines",
        "journal",
        "journals",
        "press",
        "media",
        "newsroom",
        "newsrooms",
        "bureau",
        "bureaus",
        "desk",
        "desks",
        "beat",
        "beats",
        # Content types
        "article",
        "articles",
        "story",
        "stories",
        "report",
        "reports",
        "piece",
        "pieces",
        "coverage",
        "interview",
        "interviews",
        "profile",
        "profiles",
        # Time/status indicators
        "former",
        "current",
        "retired",
        "emeritus",
        "acting",
        "interim",
        "temporary",
        # Organizational
        "team",
        "teams",
        "crew",
        "crews",
        "department",
        "departments",
        "division",
        "divisions",
        "section",
        "sections",
        "unit",
        "units",
        "group",
        "groups",
        "name",
        "names",
    }

    # Organization and department patterns (not person names)
    ORGANIZATION_PATTERNS = {
        # Educational institutions
        "university",
        "college",
        "school",
        "academy",
        "institute",
        "campus",
        # Government/Military
        "department",
        "bureau",
        "agency",
        "office",
        "division",
        "unit",
        "wing",
        "squadron",
        "battalion",
        "regiment",
        "corps",
        "command",
        "affairs",
        "administration",
        "ministry",
        "council",
        "committee",
        # Business/Organization types
        "corporation",
        "company",
        "inc",
        "llc",
        "ltd",
        "group",
        "organization",
        "association",
        "foundation",
        "center",
        "centre",
        # Media/Communications
        "media",
        "communications",
        "broadcast",
        "network",
        "channel",
        "productions",
        "studios",
        "publishing",
        "syndicate",
        # Activities/Services
        "activities",
        "services",
        "operations",
        "relations",
        "resources",
        "development",
        "research",
        "studies",
        "programs",
        "initiatives",
    }

    # Wire service partial names that should be filtered
    WIRE_SERVICE_PARTIALS = {
        "associated",
        "reuters",
        "bloomberg",
        "ap news",
        "cnn news",
        "fox news",
        "nbc news",
        "abc news",
        "cbs news",
        "npr news",
        "usa today",
        "wsj",
        "nyt",
        "wapo",
        "latimes",
        "tribune",
        "mcclatchy",
        "gannett",
        "hearst",
        "scripps",
        "sinclair",
    }

    # Patterns for common byline formats
    BYLINE_PATTERNS = [
        # "By Author Name" patterns
        r"^by\s+(.+)$",
        r"^written\s+by\s+(.+)$",
        r"^story\s+by\s+(.+)$",
        r"^report\s+by\s+(.+)$",
        # "Special to" patterns (extract name before "Special")
        r"^(.+?)\s+special\s+to?t?\s*(the|he)?\s*(.+)$",
        r"^(.+?)\s+special\s+correspondent.*$",
        r"^(.+?)\s+special\s+contributor.*$",
        # Email patterns (remove emails)
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        # Phone number patterns (remove phones)
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        r"\(\d{3}\)\s*\d{3}[-.]?\d{4}",
        # Social media handles and references
        r"@\w+",
        r"twitter\.com/\w+",
        r"facebook\.com/[\w.]+",
        r"twitter:\s*@?\w+",
        r"facebook:\s*[\w./]+",
        r"instagram:\s*@?\w+",
        r"linkedin:\s*[\w./]+",
        # Copyright and source attributions
        r"©.*$",
        r"copyright.*$",
        r"all rights reserved.*$",
        r"source:.*$",
        r"photo.*:.*$",
        r"image.*:.*$",
    ]

    # Author separators (order matters - more specific first)
    AUTHOR_SEPARATORS = [
        " and ",
        " & ",
        " with ",
        ", and ",
        " + ",
    ]

    def __init__(self, enable_telemetry: bool = True):
        """Initialize the byline cleaner."""
        # Compile regex patterns for efficiency
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.BYLINE_PATTERNS
        ]

        # Create title removal pattern
        titles_pattern = (
            r"\b(?:"
            + "|".join(re.escape(title) for title in self.TITLES_TO_REMOVE)
            + r")\b"
        )
        self.title_pattern = re.compile(titles_pattern, re.IGNORECASE)

        # Initialize telemetry
        self.telemetry = BylineCleaningTelemetry(enable_telemetry=enable_telemetry)

        # Dynamic publication filter cache
        self._publication_cache: set[Any] | None = None
        self._publication_cache_timestamp: float | None = None

        # Wire service detection tracking
        self._detected_wire_services = []

        # Current source name for wire service filtering
        self._current_source_name: str | None = None

    def clean_byline(
        self,
        byline: str,
        return_json: bool = False,
        source_name: str | None = None,
        article_id: str | None = None,
        candidate_link_id: str | None = None,
        source_id: str | None = None,
        source_canonical_name: str | None = None,
    ) -> list[str] | dict:
        """
        Clean a raw byline string with comprehensive telemetry.

        Args:
            byline: Raw byline text from article
            return_json: If True, return detailed JSON with metadata
            source_name: Optional source/publication name to remove
            article_id: Article ID for telemetry
            candidate_link_id: Candidate link ID for telemetry
            source_id: Source ID for telemetry
            source_canonical_name: Canonical source name for telemetry

        Returns:
            List of cleaned author names or JSON object with details.
            When return_json=True, includes wire_service_detected flag for
            downstream article classification.
        """
        # Start telemetry session
        self.telemetry.start_cleaning_session(
            raw_byline=byline,
            article_id=article_id,
            candidate_link_id=candidate_link_id,
            source_id=source_id,
            source_name=source_name,
            source_canonical_name=source_canonical_name,
        )

        try:
            # Reset wire service detection for this cleaning session
            self._detected_wire_services = []

            # Store source name for wire service filtering
            self._current_source_name = source_canonical_name or source_name

            if not byline or not byline.strip():
                self.telemetry.finalize_cleaning_session(
                    final_authors=[],
                    cleaning_method="empty_input",
                    likely_valid_authors=False,
                    likely_noise=True,
                )
                return self._format_result([], return_json)

            # Step 1: Wire service detection (BEFORE source removal to avoid
            # corruption)
            detected_wire_service = None
            if self._is_wire_service(byline):
                # Get the detected wire service name
                detected_wire_service = (
                    self._detected_wire_services[-1]
                    if self._detected_wire_services
                    else None
                )

                # Check if this wire service is from the publication's
                # own source
                if (
                    detected_wire_service
                    and self._current_source_name
                    and self._is_wire_service_from_own_source(
                        detected_wire_service, self._current_source_name
                    )
                ):
                    # This is local content - continue with normal processing
                    # to extract author name
                    self.telemetry.log_transformation_step(
                        step_name="wire_service_detection",
                        input_text=byline,
                        output_text=byline,
                        transformation_type="classification",
                        confidence_delta=0.6,
                        notes=(
                            f"Detected own-source wire service "
                            f"'{detected_wire_service}' - extracting "
                            f"author name"
                        ),
                    )

                    # Clear the wire service detection since this is local
                    # content
                    self._detected_wire_services = []

                else:
                    # This is syndicated content - preserve wire service
                    # name as-is
                    self.telemetry.log_transformation_step(
                        step_name="wire_service_detection",
                        input_text=byline,
                        output_text=byline,
                        transformation_type="classification",
                        confidence_delta=0.8,
                        notes=(
                            f"Detected syndicated wire service "
                            f"'{detected_wire_service}' - preserving as-is"
                        ),
                    )

                    self.telemetry.finalize_cleaning_session(
                        final_authors=[byline.strip()],
                        cleaning_method="wire_service_passthrough",
                        likely_valid_authors=True,
                        likely_noise=False,
                    )
                    return self._format_result([byline.strip()], return_json)

            # Step 2: Check for "Special to" patterns BEFORE source
            # removal (because source removal might break the pattern
            # matching)
            special_extracted = self._extract_special_contributor(byline)
            if special_extracted:
                logger.debug(
                    f"Extracted using special contributor pattern: {special_extracted}"
                )

                # Clean the extracted name and skip most processing
                cleaned_name = self._clean_author_name(special_extracted)
                if cleaned_name:
                    final_authors = [cleaned_name]

                    self.telemetry.log_transformation_step(
                        step_name="special_contributor_extraction",
                        input_text=byline,
                        output_text=special_extracted,
                        transformation_type="special_pattern_extraction",
                        confidence_delta=0.8,
                        notes="Extracted special contributor and skipped standard processing",
                    )

                    self.telemetry.finalize_cleaning_session(
                        final_authors=final_authors,
                        cleaning_method="special_contributor",
                        likely_valid_authors=True,
                        likely_noise=False,
                    )
                    return self._format_result(final_authors, return_json)

            # Step 3: Source name removal (for standard processing)
            cleaned_byline = byline
            if source_name:
                original_byline = byline
                cleaned_byline = self._remove_source_name(byline, source_name)

                self.telemetry.log_transformation_step(
                    step_name="source_removal",
                    input_text=original_byline,
                    output_text=cleaned_byline,
                    transformation_type="source_filtering",
                    removed_content=(
                        original_byline if cleaned_byline != original_byline else None
                    ),
                    confidence_delta=0.1 if cleaned_byline != original_byline else 0.0,
                    notes=f"Removed source name: {source_name}",
                )

                if cleaned_byline != byline:
                    logger.debug(f"Source removed: '{byline}' -> '{cleaned_byline}'")

            # Step 3.5: Dynamic publication name filtering
            if self._is_publication_name(cleaned_byline):
                self.telemetry.log_transformation_step(
                    step_name="dynamic_publication_filter",
                    input_text=cleaned_byline,
                    output_text="",
                    transformation_type="publication_filtering",
                    removed_content=cleaned_byline,
                    confidence_delta=0.9,
                    notes="Removed publication name using dynamic filter",
                )

                self.telemetry.finalize_cleaning_session(
                    final_authors=[],
                    cleaning_method="publication_filtered",
                    likely_valid_authors=False,
                    likely_noise=True,
                )
                return self._format_result([], return_json)

            logger.debug(f"Processing byline: {cleaned_byline}")

            # Step 4: Standard pattern extraction
            text = cleaned_byline.lower().strip()
            extracted_text = None
            pattern_used = None

            for i, pattern in enumerate(self.compiled_patterns[:4]):
                match = pattern.search(text)
                if match:
                    if match.groups():
                        extracted_text = match.group(1).strip()
                    else:
                        extracted_text = match.group(0).strip()
                    pattern_used = f"pattern_{i}"
                    logger.debug(f"Extracted using pattern: {extracted_text}")
                    break

            if not extracted_text:
                extracted_text = cleaned_byline.strip()
                pattern_used = "no_pattern"
                logger.debug("No pattern matched, using full text")

            self.telemetry.log_transformation_step(
                step_name="pattern_extraction",
                input_text=cleaned_byline,
                output_text=extracted_text,
                transformation_type="text_extraction",
                confidence_delta=(0.2 if pattern_used != "no_pattern" else 0.0),
                notes=f"Used {pattern_used}",
            )

            # Step 4: Remove unwanted patterns (emails, phones, etc.)
            before_pattern_removal = extracted_text
            cleaned_text = self._remove_patterns(extracted_text)

            if cleaned_text != before_pattern_removal:
                self.telemetry.log_transformation_step(
                    step_name="pattern_removal",
                    input_text=before_pattern_removal,
                    output_text=cleaned_text,
                    transformation_type="noise_removal",
                    removed_content=(
                        f"Removed: "
                        f"{before_pattern_removal.replace(cleaned_text, '').strip()}"
                    ),
                    confidence_delta=0.1,
                    notes="Removed emails, phones, and other patterns",
                )

            logger.debug(f"After removing patterns: {cleaned_text}")

            # Step 5: Extract individual authors
            before_author_extraction = cleaned_text

            # If we used special contributor extraction, we already have
            # a single clean author name, so bypass _extract_authors
            if special_extracted:
                authors = [cleaned_text]
                self.telemetry.log_transformation_step(
                    step_name="author_extraction",
                    input_text=before_author_extraction,
                    output_text=str(authors),
                    transformation_type="special_contributor_bypass",
                    confidence_delta=0.3,
                    notes="Bypassed _extract_authors for special contributor",
                )
            else:
                authors = self._extract_authors(cleaned_text)
                self.telemetry.log_transformation_step(
                    step_name="author_extraction",
                    input_text=before_author_extraction,
                    output_text=str(authors),
                    transformation_type="name_parsing",
                    confidence_delta=0.2,
                    notes=f"Extracted {len(authors)} potential authors",
                )

            logger.debug(f"Extracted authors: {authors}")

            # Check if smart processing was used
            if (
                isinstance(authors, list)
                and len(authors) >= 1
                and authors[0] == "__SMART_PROCESSED__"
            ):
                smart_names = authors[1:]
                cleaned_names = []

                for name in smart_names:
                    cleaned_name = self._clean_author_name(name)
                    if cleaned_name.strip():
                        cleaned_names.append(cleaned_name.strip())

                self.telemetry.log_transformation_step(
                    step_name="smart_processing",
                    input_text=str(smart_names),
                    output_text=str(cleaned_names),
                    transformation_type="smart_name_cleaning",
                    confidence_delta=0.3,
                    notes="Used smart processing for name cleaning",
                )

                final_authors = self._deduplicate_authors(cleaned_names)

                self.telemetry.finalize_cleaning_session(
                    final_authors=final_authors,
                    cleaning_method="smart_processing",
                    likely_valid_authors=len(final_authors) > 0,
                    likely_noise=len(final_authors) == 0,
                )

                return self._format_result(final_authors, return_json)

            # Step 6: Clean each author name individually
            before_name_cleaning = authors
            cleaned_authors = [self._clean_author_name(author) for author in authors]
            cleaned_authors = [author for author in cleaned_authors if author.strip()]

            self.telemetry.log_transformation_step(
                step_name="name_cleaning",
                input_text=str(before_name_cleaning),
                output_text=str(cleaned_authors),
                transformation_type="individual_name_cleaning",
                confidence_delta=0.1,
                notes=(
                    f"Cleaned {len(before_name_cleaning)} names to "
                    f"{len(cleaned_authors)}"
                ),
            )

            # Step 7: Remove duplicates and validate
            before_dedup = cleaned_authors
            final_authors = self._deduplicate_authors(cleaned_authors)

            if len(final_authors) != len(before_dedup):
                removed_duplicates = len(before_dedup) - len(final_authors)
                self.telemetry.log_transformation_step(
                    step_name="duplicate_removal",
                    input_text=str(before_dedup),
                    output_text=str(final_authors),
                    transformation_type="deduplication",
                    removed_content=f"Removed {removed_duplicates} duplicates",
                    confidence_delta=0.1,
                    notes=f"Removed {removed_duplicates} duplicate authors",
                )

            # Step 8: Final validation
            valid_authors = self._validate_authors(final_authors)

            if len(valid_authors) != len(final_authors):
                invalid_count = len(final_authors) - len(valid_authors)
                self.telemetry.log_transformation_step(
                    step_name="validation",
                    input_text=str(final_authors),
                    output_text=str(valid_authors),
                    transformation_type="validation",
                    removed_content=f"Removed {invalid_count} invalid names",
                    confidence_delta=0.1,
                    notes=f"Filtered out {invalid_count} invalid author names",
                )

            logger.debug(f"Final authors: {valid_authors}")

            # Finalize telemetry
            self.telemetry.finalize_cleaning_session(
                final_authors=valid_authors,
                cleaning_method="standard_pipeline",
                likely_valid_authors=(
                    len(valid_authors) > 0
                    and all(len(name.split()) >= 2 for name in valid_authors)
                ),
                likely_noise=len(valid_authors) == 0,
                requires_manual_review=(
                    len(valid_authors) == 0 and len(byline.strip()) > 10
                ),
            )

            return self._format_result(valid_authors, return_json)

        except Exception as e:
            # Log error and continue without telemetry
            self.telemetry.log_error(f"Cleaning error: {str(e)}", "processing")
            self.telemetry.finalize_cleaning_session(
                final_authors=[],
                cleaning_method="error_fallback",
                likely_valid_authors=False,
                requires_manual_review=True,
            )
            logger.error(f"Error cleaning byline '{byline}': {e}")
            return self._format_result([], return_json)

    def _process_single_name(self, name_text: str, return_json: bool) -> str | dict:
        """Process a single name that's already been identified as a clean name."""
        # Clean the individual name
        cleaned_name = self._clean_author_name(name_text)

        if cleaned_name.strip():
            return self._format_result([cleaned_name], return_json)
        else:
            return self._format_result([], return_json)

    def _extract_special_contributor(self, byline: str) -> str | None:
        """
        Extract author name from 'Special to' constructions.

        Handles patterns like:
        - "By JOHN DOE Special to the Herald"
        - "By JANE SMITH Special tot he Times" (with typos)
        - "By AUTHOR Special correspondent"

        Args:
            byline: The byline text to process

        Returns:
            Extracted author name or None if no pattern matches
        """
        import re

        # Normalize the byline
        text = byline.lower().strip()

        # Remove "by" prefix first
        text = re.sub(r"^by\s+", "", text)

        # Patterns to match "Special to" constructions
        special_patterns = [
            # "Name Special to [the] Publication"
            r"^(.+?)\s+special\s+(?:to|tot|teh)\s*(?:the|he)?\s*(.+)$",
            # "Name Special correspondent/contributor"
            r"^(.+?)\s+special\s+(?:correspondent|contributor).*$",
            # "Name Special" (standalone)
            r"^(.+?)\s+special\s*$",
        ]

        for pattern in special_patterns:
            match = re.match(pattern, text)
            if match:
                name_part = match.group(1).strip()
                # Make sure we have a reasonable name (at least 2 words)
                if len(name_part.split()) >= 2:
                    return name_part

        return None

    def _normalize_wire_service(self, service_name: str) -> str:
        """
        Normalize wire service name to canonical form.

        Args:
            service_name: Raw wire service name detected

        Returns:
            Normalized canonical wire service name
        """
        service_lower = service_name.lower().strip()
        return self.WIRE_SERVICE_NORMALIZATION.get(service_lower, service_name)

    def _is_wire_service(self, byline: str) -> bool:
        """Check if byline is from wire service/syndicated source."""
        byline_lower = byline.lower().strip()

        # Remove common prefixes to get to the core identifier
        for prefix in ["by ", "from ", "source: ", "- "]:
            if byline_lower.startswith(prefix):
                byline_lower = byline_lower[len(prefix) :].strip()

        # Check if the byline matches known wire services
        for wire_service in self.WIRE_SERVICES:
            if byline_lower == wire_service or byline_lower.startswith(
                wire_service + " "
            ):
                # Track detected wire service with normalization
                normalized_service = self._normalize_wire_service(wire_service)
                self._detected_wire_services.append(normalized_service)
                return True

        # Check for common wire service patterns
        wire_patterns = [
            (
                r"^(ap|reuters|bloomberg|cnn|npr|pbs)$",
                "AP/Reuters/Bloomberg/CNN/NPR/PBS",
            ),
            (
                r"^(the\s+)?(associated\s+press|new\s+york\s+times|"
                r"washington\s+post)$",
                "Major Publication",
            ),
            (
                r"^(usa\s+today|wall\s+street\s+journal|" r"los\s+angeles\s+times)$",
                "National Publication",
            ),
        ]

        for pattern, service_category in wire_patterns:
            if re.match(pattern, byline_lower):
                # Extract the actual matched service
                match = re.match(pattern, byline_lower)
                if match:
                    matched_service = match.group(0)
                    normalized_service = self._normalize_wire_service(matched_service)
                    self._detected_wire_services.append(normalized_service)
                else:
                    self._detected_wire_services.append(service_category)
                return True

        return False

    def _basic_cleaning(self, byline: str) -> str:
        """Perform basic text cleaning and normalization."""
        # Remove extra whitespace and normalize
        cleaned = re.sub(r"\s+", " ", byline.strip())

        # Remove common prefixes
        for pattern in ["by ", "written by ", "story by ", "report by "]:
            if cleaned.lower().startswith(pattern):
                cleaned = cleaned[len(pattern) :].strip()
                break

        # Remove trailing punctuation and common suffixes
        cleaned = re.sub(r"[.,;:]+$", "", cleaned)
        cleaned = re.sub(
            r"\s+(staff|reporter|editor)$", "", cleaned, flags=re.IGNORECASE
        )

        return cleaned

    def _is_wire_service_from_own_source(
        self, wire_service: str, source_name: str
    ) -> bool:
        """
        Check if detected wire service is from the publication's own source.

        Returns True if the wire service matches the source (local content),
        False if it's syndicated content.
        """
        if not wire_service or not source_name:
            return False

        # Calculate similarity using same logic as backfill script
        from difflib import SequenceMatcher

        # Normalize for comparison
        def normalize_for_comparison(text: str) -> str:
            import re

            text = text.lower().strip()
            # Remove articles and common publication words
            text = re.sub(
                r"\b(the|a|an|news|press|daily|weekly|times|post|gazette|herald|tribune|journal)\b",
                "",
                text,
            )
            # Remove extra whitespace and punctuation
            text = re.sub(r"[^\w\s]", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text

        norm_wire = normalize_for_comparison(wire_service)
        norm_source = normalize_for_comparison(source_name)

        # Calculate similarity
        similarity = SequenceMatcher(None, norm_wire, norm_source).ratio()

        # High similarity threshold - this is the publication's own content
        if similarity > 0.7:  # 70% similarity threshold
            return True

        # Check for direct substring matches (case insensitive)
        wire_lower = wire_service.lower()
        source_lower = source_name.lower()

        # Check if wire service is contained in source name or vice versa
        if wire_lower in source_lower or source_lower in wire_lower:
            return True

        return False

    def _remove_source_name(self, text: str, source_name: str) -> str:
        """Remove source/publication name from author text using
        fuzzy matching."""
        if not source_name or not text:
            return text

        # Normalize both strings for comparison
        def normalize_for_comparison(input_text: str) -> str:
            """Normalize text for fuzzy comparison."""
            # Convert to lowercase, remove extra spaces, punctuation
            normalized = re.sub(r"[^\w\s]", "", input_text.lower())
            normalized = re.sub(r"\s+", " ", normalized).strip()
            return normalized

        normalized_source = normalize_for_comparison(source_name)
        normalized_text = normalize_for_comparison(text)

        # Skip if source name is too short (likely false positive)
        if len(normalized_source) < 3:
            return text

        # Calculate similarity ratio for exact match detection
        similarity = SequenceMatcher(None, normalized_source, normalized_text).ratio()

        # High similarity threshold - likely just the publication name
        if similarity > 0.8:
            logger.info(
                f"Removing publication name (similarity: "
                f"{similarity:.2f}): '{text}' matches '{source_name}'"
            )
            return ""

        # Check if source name is contained within the text (partial match)
        # BUT only if the text is mostly just the source name (not author +
        # source)
        if normalized_source in normalized_text:
            # Calculate how much of the text is NOT the source name
            remaining_text = normalized_text.replace(normalized_source, "").strip()
            if normalized_text:
                remaining_ratio = len(remaining_text) / len(normalized_text)
            else:
                remaining_ratio = 0

            # Only remove if most of the text is the publication name
            # Less than 30% is non-source content
            if remaining_ratio < 0.3:
                logger.info(
                    f"Removing publication name (substring match): "
                    f"'{source_name}' found in '{text}'"
                )
                return ""

        # Check if text is contained within source name (reverse match)
        if normalized_text in normalized_source:
            logger.info(
                f"Removing publication name (reverse match): "
                f"'{text}' found in '{source_name}'"
            )
            return ""

        # NEW: Smart partial removal for "Name Publication" patterns
        source_words = normalized_source.split()
        text_words = normalized_text.split()

        # If source has multiple words, try to identify and remove
        # just the publication part
        if len(source_words) > 1 and len(text_words) > 1:
            matching_words = []
            for word in source_words:
                if word in text_words:
                    matching_words.append(word)

            match_ratio = len(matching_words) / len(source_words)

            # If we have a good match ratio, try to remove the publication
            # words
            if match_ratio > 0.6:  # 60% of source words found in text
                # Remove the matching words from the text, but be smarter about it
                # First, let's work with the original text to preserve
                # formatting
                original_words = text.split()
                remaining_words = []

                for word in original_words:
                    word_normalized = re.sub(r"[^\w\s]", "", word.lower())
                    # Skip this word if it matches any source word
                    if word_normalized not in [w.lower() for w in source_words]:
                        remaining_words.append(word)

                # Only return the remaining words if we have something left
                # that looks like a name
                if remaining_words:
                    result = " ".join(remaining_words).strip()

                    # Clean up any remaining email addresses
                    result = re.sub(
                        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                        "",
                        result,
                    )
                    result = re.sub(r"\s+", " ", result).strip()

                    if result:
                        logger.info(
                            f"Removing publication words "
                            f"(word match {match_ratio:.2f}): "
                            f"'{text}' -> '{result}'"
                        )
                        return result
                    else:
                        logger.info(
                            f"Removing entire text "
                            f"(word match {match_ratio:.2f}): "
                            f"'{text}' matches '{source_name}'"
                        )
                        return ""
                else:
                    logger.info(
                        f"Removing entire text "
                        f"(word match {match_ratio:.2f}): "
                        f"'{text}' matches '{source_name}'"
                    )
                    return ""

        # Additional patterns for common publication naming
        # Check for pattern like "Name Publication" where Publication matches
        # source
        if len(text_words) >= 2:
            # Last word(s) might be publication name
            last_word = text_words[-1]
            if len(text_words) >= 2:
                last_two_words = " ".join(text_words[-2:])
            else:
                last_two_words = ""

            # Check if last word has high similarity to any word in source
            for source_word in source_words:
                if len(source_word) > 3:  # Skip short words
                    matcher = SequenceMatcher(None, source_word, last_word)
                    word_similarity = matcher.ratio()
                    if word_similarity > 0.8:
                        # Remove the publication word(s) and return just the
                        # name part
                        name_part = " ".join(text_words[:-1]).strip()
                        if name_part:
                            # Re-capitalize properly
                            name_part = " ".join(
                                word.title() for word in name_part.split()
                            )
                            logger.info(
                                f"Removing publication suffix "
                                f"'{last_word}' (similarity: "
                                f"{word_similarity:.2f})"
                            )
                            return name_part

            # Check last two words against source
            normalized_two = normalize_for_comparison(last_two_words)
            matcher = SequenceMatcher(None, normalized_source, normalized_two)
            two_word_similarity = matcher.ratio()
            if two_word_similarity > 0.7:
                name_part = " ".join(text_words[:-2]).strip()
                if name_part:
                    # Re-capitalize properly
                    name_part = " ".join(word.title() for word in name_part.split())
                    logger.info(
                        f"Removing publication suffix "
                        f"'{last_two_words}' (similarity: "
                        f"{two_word_similarity:.2f})"
                    )
                    return name_part

        # No match found - return original
        return text

    def _remove_patterns(self, text: str) -> str:
        """Remove unwanted patterns like emails, phones, etc."""
        # Skip byline extraction patterns
        for pattern in self.compiled_patterns[4:]:
            text = pattern.sub("", text)

        # Remove domain suffixes (e.g., "• @domain.com", "• .com")
        text = re.sub(r"\s*[•·]\s*@?\w*\.com\b.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(
            r"\s*[•·]\s*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}.*$", "", text, flags=re.IGNORECASE
        )

        # Remove trailing email domains and handles
        text = re.sub(r"\s*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}.*$", "", text)
        text = re.sub(
            r"\s*\.\s*(com|org|net|edu|gov).*$", "", text, flags=re.IGNORECASE
        )

        # Remove parenthetical information
        text = re.sub(r"\([^)]*\)", "", text)

        # Remove bracketed information
        text = re.sub(r"\[[^\]]*\]", "", text)

        # Clean up extra spaces
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _identify_part_type(self, part: str) -> str:
        """
        Identify what type of content a comma-separated part contains.
        Returns: 'name', 'email', 'title', 'photo_credit', or 'mixed'
        """
        part = part.strip()
        if not part:
            return "empty"

        # Check for photo credits (e.g., "Photos Jeremy Jacob", "Photo by John
        # Doe")
        part_lower = part.lower()
        if (
            part_lower.startswith("photo ")
            or part_lower.startswith("photos ")
            or "photo by" in part_lower
            or "photos by" in part_lower
            or part_lower == "photo"
            or part_lower == "photos"
        ):
            return "photo_credit"

        # Check for email
        if "@" in part and "." in part:
            return "email"

        # Check for titles/journalism words
        part_words = part.lower().split()
        title_word_count = 0

        # Check for non-name contexts with Roman numerals
        if (
            len(part_words) == 2
            and part_words[0]
            in ["chapter", "section", "volume", "part", "book", "act", "scene"]
            and part_words[1]
            in ["ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
        ):
            return "title"

        for i, word in enumerate(part_words):
            is_title_word = False

            # Direct match for title/journalism words
            if (
                word in self.TITLES_TO_REMOVE
                or word in self.JOURNALISM_NOUNS
                or word in self.ORGANIZATION_PATTERNS
            ):
                is_title_word = True

            # Check for plural forms
            elif word.endswith("s") and (
                word[:-1] in self.TITLES_TO_REMOVE
                or word[:-1] in self.JOURNALISM_NOUNS
                or word[:-1] in self.ORGANIZATION_PATTERNS
            ):
                is_title_word = True

            # Check for common title modifiers
            elif word in [
                "senior",
                "junior",
                "lead",
                "chief",
                "managing",
                "executive",
                "associate",
                "assistant",
                "deputy",
                "acting",
                "interim",
                "co",
            ]:
                is_title_word = True

            # Check for numbers (indicating positions/levels)
            # But exclude Roman numerals when they appear as name suffixes
            elif word.isdigit() or (
                word in ["ii", "iii", "iv", "v", "vi", "vii", "vii", "viii", "ix", "x"]
                and not (i == len(part_words) - 1 and len(part_words) <= 3)
            ):
                is_title_word = True  # Numbers are often part of titles

            # Check for ordinal indicators
            elif word.endswith(("st", "nd", "rd", "th")) and word[:-2].isdigit():
                is_title_word = True  # Ordinals are often part of titles

            if is_title_word:
                title_word_count += 1

        # Enhanced logic: check if this looks like a title phrase
        # Look for patterns like "2nd Assistant Editor", "Senior Editor II"
        has_title_pattern = False
        for i, word in enumerate(part_words):
            word_lower = word.lower()
            # If we find a clear title word, check surrounding context
            if (
                word_lower in self.TITLES_TO_REMOVE
                or word_lower in self.JOURNALISM_NOUNS
            ):
                has_title_pattern = True
                break

        # If we have title patterns and numbers/ordinals, it's likely all title
        if has_title_pattern and title_word_count >= len(part_words) * 0.6:
            return "title"  # If most words are titles/journalism terms, it's a title section
        if title_word_count >= len(part_words) / 2:
            return "title"

        # If it has some title words but not majority, it's mixed
        if title_word_count > 0:
            return "mixed"

        # Check if it looks like a name (2-3 capitalized words, no special
        # chars)
        if (
            len(part_words) <= 3
            and all(
                word.replace(".", "").replace("'", "").replace("-", "").isalpha()
                for word in part_words
            )
            and not any(
                word.lower() in self.TITLES_TO_REMOVE
                or word.lower() in self.JOURNALISM_NOUNS
                for word in part_words
            )
        ):
            return "name"

        # Default to mixed if unclear
        return "mixed"

    def _extract_authors(self, text: str) -> list[str]:
        """
        Extract author names from cleaned text.
        Uses type identification to distinguish names from emails, titles, etc.
        """
        # Remove social media patterns first
        social_patterns = [
            r"twitter:\s*@?\w+",
            r"facebook:\s*[\w./]+",
            r"instagram:\s*@?\w+",
            r"@\w+",
            r"\btwitter\b(?!\s+[A-Z][a-z]+)",
            r"\bfacebook\b",
            r"\binstagram\b",
            r"\blinkedin\b",
        ]

        for pattern in social_patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Handle "and" separated authors (keep both)
        if " and " in text.lower():
            parts = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
            authors = []
            for part in parts:
                part = part.strip()
                if part:
                    # For "and" separated parts, recursively extract authors
                    # This handles cases like "NAME1 and NAME2, NAME1, NAME2"
                    part_authors = self._extract_authors(part)
                    if isinstance(part_authors, list) and len(part_authors) > 0:
                        # If it returned processed results, add them
                        if part_authors[0] == "__SMART_PROCESSED__":
                            # Smart processing can return multiple names
                            authors.extend(part_authors[1:])
                        else:
                            authors.extend(part_authors)
                    else:
                        # Simple case: just clean the name
                        cleaned = self._clean_author_name(part)
                        if cleaned.strip():
                            authors.append(cleaned)

            # Remove duplicates while preserving order
            seen = set()
            unique_authors = []
            for author in authors:
                author_clean = author.lower().strip()
                if author_clean not in seen:
                    seen.add(author_clean)
                    unique_authors.append(author)

            return unique_authors

        # Handle comma-separated or pipe-separated content with type identification
        # Support formats like "Name, Title" or "Name | Title | @Handle"
        has_comma = "," in text
        has_pipe = "|" in text

        if has_comma or has_pipe:
            # Choose the primary separator (prefer pipe if both exist)
            if has_pipe:
                separator = "|"
                parts = text.split("|")
            else:
                separator = ","
                parts = text.split(",")

            # Identify the type of each part
            part_types = []
            for part in parts:
                part_type = self._identify_part_type(part)
                part_types.append((part.strip(), part_type))

            # Special case: "Last, First" name format detection (only for
            # comma-separated)
            if (
                separator == ","
                and len(parts) == 2
                and len(part_types) == 2
                and all(ptype == "name" for _, ptype in part_types)
            ):
                first_part = part_types[0][0]  # Potential last name
                second_part = part_types[1][0]  # Potential first name(s)

                # Check if this looks like "Last, First" pattern
                first_part_words = first_part.split()
                second_part_words = second_part.split()

                # Last name should be 1 word, first name(s) should be 1-2 words
                if len(first_part_words) == 1 and 1 <= len(second_part_words) <= 2:
                    # This looks like "Last, First" - reorder to "First Last"
                    reordered_name = f"{second_part} {first_part}"
                    logger.debug(
                        f"Detected 'Last, First' format: '{text}' -> '{reordered_name}'"
                    )
                    return [reordered_name]

            # Count different types
            non_name_count = sum(
                1
                for _, ptype in part_types
                if ptype in ["email", "title", "photo_credit"]
            )

            # Smart processing: if we have multiple non-name parts,
            # extract just the name part(s)
            condition = non_name_count >= 2 or (non_name_count >= 1 and len(parts) >= 3)
            if condition:
                # Find parts that are clearly names (not photo credits)
                name_parts = [part for part, ptype in part_types if ptype == "name"]

                if name_parts:
                    # Return ALL clear names, not just the first one
                    return ["__SMART_PROCESSED__"] + name_parts
                else:
                    # If no clear names, take the first part that's not
                    # email/title/photo_credit
                    for part, ptype in part_types:
                        if ptype not in ["email", "title", "photo_credit"] and part:
                            return ["__SMART_PROCESSED__", part]

                    # If all parts are email/title/photo_credit, return empty list
                    # This handles cases like "Senior Editor II, Managing
                    # Director III"
                    return ["__SMART_PROCESSED__"]

            # If not using smart processing, handle normally
            # Keep parts that are names or mixed (not email/title/photo_credit)
            authors = []
            for part, ptype in part_types:
                if ptype in ["name", "mixed"] and part:
                    # For mixed types that might contain person + organization,
                    # try to filter out organization words
                    if ptype == "mixed":
                        filtered_part = self._filter_organization_words(part)
                        if filtered_part.strip():  # Only add if something remains
                            authors.append(filtered_part)
                    else:
                        authors.append(part)

            if authors:
                # Apply deduplication to all comma-separated results
                return self._deduplicate_authors(authors)

        # Default: return as single author, but only if it's not a title or
        # photo credit
        if text.strip():
            # Check if the entire text is just a title or photo credit
            text_type = self._identify_part_type(text)
            if text_type in ["title", "photo_credit"]:
                return []  # Don't return titles or photo credits as names

            # For mixed content, try to filter organization words
            if text_type == "mixed":
                filtered_text = self._filter_organization_words(text)
                if filtered_text.strip():
                    return [filtered_text]
                else:
                    return []  # Nothing left after filtering

            return [text]
        else:
            return []

    def _filter_organization_words(self, text: str) -> str:
        """
        Remove organization/publication words from mixed person/org text.
        # Priority order:
        # 1. Check for recognized organizations/publications using n-gram
        # 2. Use database-informed person name detection
        # 3. Apply individual word filtering as fallback

        Args:
            text: Text that might contain person + organization words

        Returns:
            Text with organization words filtered out
        """
        if not text:
            return ""

        words = text.split()
        publication_names = self.get_publication_names()
        organization_names = self.get_organization_names()

        # Combine all organization names for matching
        all_org_names = set()
        all_org_names.update(publication_names)
        all_org_names.update(organization_names)
        all_org_names.update(self.WIRE_SERVICES)  # Add wire services!

        # Convert to lowercase for case-insensitive matching
        org_names_lower = {name.lower() for name in all_org_names}

        # STEP 1: ORGANIZATION/PUBLICATION DETECTION (Priority)
        # Check for complete publication/organization matches first
        text_lower = text.lower()
        text_words = text_lower.split()
        spans_to_remove = []

        # Check for multi-word organization matches ONLY (minimum 2 words)
        # Single-word matches will be handled in STEP 3 after person name
        # protection
        for org_name in org_names_lower:
            org_words = org_name.split()
            if len(org_words) >= 2:  # Require at least 2 words
                # Strategy 1: Try exact match first
                for start_idx in range(len(text_words) - len(org_words) + 1):
                    end_idx = start_idx + len(org_words)
                    text_ngram = text_words[start_idx:end_idx]
                    if text_ngram == org_words:
                        # Calculate character positions for span removal
                        words_before = text_words[:start_idx]
                        char_start = len(" ".join(words_before))
                        if words_before:  # Add space if there are words before
                            char_start += 1

                        # Calculate end position
                        matched_text = " ".join(text_ngram)
                        char_end = char_start + len(matched_text)

                        spans_to_remove.append((char_start, char_end))

                        # Track if this was a wire service
                        if org_name in {ws.lower() for ws in self.WIRE_SERVICES}:
                            # Find the original wire service name and normalize
                            # it
                            for service in self.WIRE_SERVICES:
                                if service.lower() == org_name:
                                    normalized_service = self._normalize_wire_service(
                                        service
                                    )
                                    self._detected_wire_services.append(
                                        normalized_service
                                    )
                                    break

                # Strategy 2: Check if text contains a subsequence of org words
                # (e.g., "missouri independent" matches "the missouri independent")
                if len(org_words) >= 3:  # Only for longer organization names
                    # Try all contiguous subsequences of length 2+
                    for subseq_len in range(2, len(org_words)):
                        max_start = len(org_words) - subseq_len + 1
                        for subseq_start in range(max_start):
                            subseq_end = subseq_start + subseq_len
                            org_subseq = org_words[subseq_start:subseq_end]

                            # Check if this subsequence appears in text
                            subseq_max_start = len(text_words) - len(org_subseq) + 1
                            for start_idx in range(subseq_max_start):
                                end_idx = start_idx + len(org_subseq)
                                text_ngram = text_words[start_idx:end_idx]
                                if text_ngram == org_subseq:
                                    # Calculate character positions
                                    words_before = text_words[:start_idx]
                                    char_start = len(" ".join(words_before))
                                    if words_before:
                                        char_start += 1

                                    matched_text = " ".join(text_ngram)
                                    char_end = char_start + len(matched_text)

                                    spans_to_remove.append((char_start, char_end))

        # Apply organization removal spans (prioritized)
        if spans_to_remove:
            # Sort spans by start position (reverse order for safe removal)
            spans_to_remove.sort(key=lambda x: x[0], reverse=True)
            result_text = text

            for start, end in spans_to_remove:
                result_text = result_text[:start] + result_text[end:]

            # Clean up extra spaces
            result_text = re.sub(r"\s+", " ", result_text).strip()

            # If we removed organizations and have something left, return it
            if result_text:
                return result_text
            else:
                # If removing organizations left nothing, return empty
                return ""

        # STEP 2: DATABASE-INFORMED PERSON NAME DETECTION
        # Get known name patterns from database to inform protection
        known_name_patterns = self._get_known_name_patterns()
        protected_spans = []

        # Check if beginning looks like a known person name pattern
        if len(text_words) >= 2:
            for name_len in [3, 2]:  # Check 3 words first, then 2
                if len(text_words) >= name_len:
                    potential_name = text_words[:name_len]

                    # Check if this matches known name patterns
                    if self._matches_known_name_pattern(
                        potential_name, known_name_patterns
                    ):
                        # Calculate character span for this name
                        name_text = " ".join(words[:name_len])
                        char_end = len(name_text)
                        protected_spans.append((0, char_end))
                        break  # Use the longer name if found

                    # Fallback: basic person name heuristics
                    looks_like_person = True

                    for i, word in enumerate(potential_name):
                        original_word = words[i] if i < len(words) else ""

                        # Must be alphabetic (allow apostrophes, hyphens)
                        clean_word = word.replace("'", "").replace("-", "")
                        if not clean_word.isalpha():
                            looks_like_person = False
                            break

                        # Must be capitalized in original
                        if not (original_word and original_word[0].isupper()):
                            looks_like_person = False
                            break

                        # Must not be an obvious organization word
                        if (
                            word in self.ORGANIZATION_PATTERNS
                            or word in self.JOURNALISM_NOUNS
                            or word in self.TITLES_TO_REMOVE
                        ):
                            looks_like_person = False
                            break

                    if looks_like_person:
                        # Calculate character span for this name
                        name_text = " ".join(words[:name_len])
                        char_end = len(name_text)
                        protected_spans.append((0, char_end))
                        break  # Use the longer name if found

        # STEP 3: INDIVIDUAL WORD FILTERING (Fallback)
        # If no organizations were removed and no person names protected,
        # apply individual word filtering including single-word wire services
        filtered_words = []
        wire_services_lower = {name.lower() for name in self.WIRE_SERVICES}

        for word in words:
            word_lower = word.lower().strip()

            # Check if this word is a wire service
            if word_lower in wire_services_lower:
                # Track removed wire service with normalization
                # Find the original service name from WIRE_SERVICES
                for service in self.WIRE_SERVICES:
                    if service.lower() == word_lower:
                        normalized_service = self._normalize_wire_service(service)
                        self._detected_wire_services.append(normalized_service)
                        break
                continue  # Skip this word

            # Skip obvious organization patterns, journalism terms
            if (
                word_lower not in self.ORGANIZATION_PATTERNS
                and word_lower not in self.WIRE_SERVICE_PARTIALS
                and word_lower not in self.JOURNALISM_NOUNS
                and word_lower not in self.TITLES_TO_REMOVE
            ):
                filtered_words.append(word)

        return " ".join(filtered_words).strip()

    def _get_known_name_patterns(self) -> dict[str, int]:
        """
        Get patterns of known person names from the database.
        Returns dictionary with pattern -> frequency count.
        """
        try:
            import sqlite3

            db_path = "data/mizzou.db"

            # Query for existing clean author names to build patterns
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Get clean author names from the database
            cursor.execute(
                """
                SELECT clean_authors FROM articles
                WHERE clean_authors IS NOT NULL
                AND clean_authors != '[]'
                AND clean_authors != ''
            """
            )

            name_patterns = {}
            for (clean_authors_json,) in cursor.fetchall():
                try:
                    import json

                    authors = json.loads(clean_authors_json)
                    for author in authors:
                        if isinstance(author, str) and author.strip():
                            # Extract patterns: first name, last name, etc.
                            words = author.strip().split()
                            if len(words) >= 2:
                                # Pattern: first + last name
                                first_lower = words[0].lower()
                                last_lower = words[-1].lower()
                                pattern = f"{first_lower}_{last_lower}"
                                name_patterns[pattern] = (
                                    name_patterns.get(pattern, 0) + 1
                                )

                                # Pattern: first name frequency
                                first_pattern = f"first_{first_lower}"
                                name_patterns[first_pattern] = (
                                    name_patterns.get(first_pattern, 0) + 1
                                )

                                # Pattern: last name frequency
                                last_pattern = f"last_{last_lower}"
                                name_patterns[last_pattern] = (
                                    name_patterns.get(last_pattern, 0) + 1
                                )

                except (json.JSONDecodeError, TypeError):
                    continue

            conn.close()
            return name_patterns

        except Exception:
            # Return empty dict if database access fails
            return {}

    def _matches_known_name_pattern(
        self, potential_name: list[str], known_patterns: dict[str, int]
    ) -> bool:
        """
        Check if potential name matches patterns from known authors.

        Args:
            potential_name: List of words that might form a person name
            known_patterns: Dictionary of known name patterns with frequencies

        Returns:
            True if this looks like a known person name pattern
        """
        if not potential_name or not known_patterns:
            return False

        # Check for exact name pattern match
        if len(potential_name) >= 2:
            first_word = potential_name[0].lower()
            last_word = potential_name[-1].lower()

            # Check if we've seen this first+last combination before
            full_pattern = f"{first_word}_{last_word}"
            if full_pattern in known_patterns and known_patterns[full_pattern] >= 2:
                return True

            # Check if first name appears frequently
            first_pattern = f"first_{first_word}"
            if first_pattern in known_patterns and known_patterns[first_pattern] >= 5:
                return True

            # Check if last name appears frequently
            last_pattern = f"last_{last_word}"
            if last_pattern in known_patterns and known_patterns[last_pattern] >= 3:
                return True

        return False

    def _clean_author_name(self, name: str) -> str:
        """Clean an individual author name."""
        if not name:
            return ""

        # First decode any HTML entities
        import html

        name = html.unescape(name)

        # Check if this name is actually a publication name
        if self._is_publication_name(name):
            return ""  # Filter out publication names

        # Check if this name is a continuous URL string
        if self._is_url_fragment(name):
            return ""  # Filter out actual URL strings

        # Clean up separators and trailing URL-like fragments
        # Split on common separators and keep only the name part
        import re

        separators = [
            r"\s*•\s*",
            r"\s*\|\s*",
            r"\s*–\s*",
            r"\s*—\s*",
            r"\s*-\s*(?=\w+\s*\.|\.)",
            r"\s*,\s*(?=\.)",
            r"\s+(?=\.com|\.org|\.net|\.edu)",
        ]

        cleaned_name = name
        for separator in separators:
            parts = re.split(separator, cleaned_name, flags=re.IGNORECASE)
            if len(parts) > 1:
                # Take the first part if it looks like a name
                first_part = parts[0].strip()
                words = first_part.split()
                if (
                    len(words) >= 2
                    and all(
                        word.replace(".", "")
                        .replace("'", "")
                        .replace("-", "")
                        .isalpha()
                        for word in words
                        if word
                    )
                    and all(
                        word[0].isupper()
                        for word in words
                        if word and word[0].isalpha()
                    )
                ):
                    cleaned_name = first_part
                    break

        # Handle mixed person/organization cases
        cleaned = self._filter_organization_words(cleaned_name)

        # Remove common patterns like ", Title", ", Title Title", etc.
        # This handles cases like "Mike Wilson, News Editors"
        comma_split = cleaned.split(",", 1)
        if len(comma_split) == 2:
            main_name = comma_split[0].strip()
            title_part = comma_split[1].strip()

            # Check if the title part contains only title words or journalism
            # nouns
            title_words = title_part.lower().split()
            is_all_titles = True
            for word in title_words:
                if (
                    word not in self.TITLES_TO_REMOVE
                    and word not in self.JOURNALISM_NOUNS
                ):
                    is_all_titles = False
                    break

            if is_all_titles:
                cleaned = main_name
            else:
                cleaned = name  # Keep original if not all title words

        # Remove titles and job descriptions using the compiled pattern
        cleaned = self.title_pattern.sub(" ", cleaned)

        # Remove extra whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Handle name capitalization
        cleaned = self._normalize_capitalization(cleaned)

        # Remove leading/trailing non-letter characters, but preserve quotes
        # around nicknames
        # First, check if we have quoted nicknames that should be preserved
        has_quoted_nickname = re.search(r'"[^"]+\"', cleaned)

        if not has_quoted_nickname:
            # Only remove leading/trailing punctuation if no quoted nicknames
            cleaned = re.sub(r"^[^a-zA-Z]+|[^a-zA-Z\s\'.-]+$", "", cleaned)
        else:
            # More conservative cleanup - only remove obvious junk
            cleaned = re.sub(r'^[^\w"\']+|[^\w"\'.]+$', "", cleaned)

        return cleaned.strip()

    def _normalize_capitalization(self, name: str) -> str:
        """Normalize name capitalization."""
        if not name:
            return ""

        # Always normalize - handle special cases for names
        words = name.split()
        normalized = []

        for word in words:
            # Handle prefixes like 'de', 'von', 'van', etc.
            if word.lower() in [
                "de",
                "da",
                "del",
                "della",
                "von",
                "van",
                "der",
                "le",
                "la",
                "du",
            ]:
                normalized.append(word.lower())
            # Handle suffixes like Jr., Sr., III - always normalize these
            elif word.lower().rstrip(".") in ["jr", "sr", "ii", "iii", "iv"]:
                base_word = word.lower().rstrip(".")
                if base_word in ["ii", "iii", "iv"]:
                    # Roman numerals should be uppercase
                    suffix = "." if word.endswith(".") else ""
                    normalized.append(base_word.upper() + suffix)
                else:
                    # Jr, Sr should be title case
                    suffix = "." if word.endswith(".") else ""
                    normalized.append(base_word.title() + suffix)
            # Handle hyphenated names
            elif "-" in word:
                parts = word.split("-")
                normalized.append("-".join(part.title() for part in parts))
            else:
                # Apply title case if the word is all caps or all lowercase
                if word.isupper() or word.islower():
                    normalized.append(word.title())
                else:
                    # Keep existing capitalization for mixed case
                    normalized.append(word)

        return " ".join(normalized)

    def _deduplicate_authors(self, authors: list[str]) -> list[str]:
        """Remove duplicate author names, preferring non-hyphenated versions."""
        if not authors:
            return []

        deduplicated = []

        # First pass: identify hyphen/space variants
        author_groups = {}  # Maps normalized name to list of variants

        for author in authors:
            if not author:
                continue

            # Create a key that treats hyphens and spaces as equivalent
            hyphen_normalized = re.sub(r"[\s\-–—]+", "", author.lower())

            if hyphen_normalized not in author_groups:
                author_groups[hyphen_normalized] = []
            author_groups[hyphen_normalized].append(author)

        # Second pass: for each group, prefer the version without hyphens
        for normalized_key, variants in author_groups.items():
            if len(variants) == 1:
                # Only one variant, keep it
                deduplicated.append(variants[0])
            else:
                # Multiple variants - prefer the one without hyphens
                non_hyphenated = [
                    v
                    for v in variants
                    if "-" not in v and "–" not in v and "—" not in v
                ]

                if non_hyphenated:
                    # Prefer the first non-hyphenated version
                    deduplicated.append(non_hyphenated[0])
                else:
                    # All have hyphens, keep the first one
                    deduplicated.append(variants[0])

        return deduplicated

    def _validate_authors(self, authors: list[str]) -> list[str]:
        """Validate author names and filter out invalid entries."""
        valid_authors = []

        for author in authors:
            if not author:
                continue

            # Must have at least 2 characters
            if len(author) < 2:
                continue

            # Must contain at least one letter
            if not re.search(r"[a-zA-Z]", author):
                continue

            # Reject if it's just a single word that looks like a title or
            # journalism term
            words = author.split()
            if len(words) == 1:
                word_lower = words[0].lower()
                if (
                    word_lower in self.TITLES_TO_REMOVE
                    or word_lower in self.JOURNALISM_NOUNS
                ):
                    continue

            # Reject common non-name patterns
            if re.match(r"^(staff|the|by|and|with|for|at|of)$", author.lower()):
                continue

            # Reject if it's too long (likely not a name)
            if len(author) > 100:
                continue

            valid_authors.append(author)

        return valid_authors

    def _format_result(self, authors: list[str], return_json: bool) -> list[str] | dict:
        """Format the final result as array or JSON."""
        # FINAL STEP: Remove any duplicates that made it through
        if authors:
            seen = set()
            deduplicated_authors = []
            for author in authors:
                if author and author.strip():
                    author_normalized = author.strip().lower()
                    if author_normalized not in seen:
                        seen.add(author_normalized)
                        deduplicated_authors.append(author.strip())
            authors = deduplicated_authors

        # Deduplicate wire services and filter out source matches
        unique_wire_services = []
        seen_services = set()
        for service in self._detected_wire_services:
            service_normalized = service.lower().strip()
            if service_normalized not in seen_services:
                # Check if this wire service matches the source name
                # (indicating local content)
                if hasattr(self, "_current_source_name") and self._current_source_name:
                    if self._is_wire_service_from_own_source(
                        service, self._current_source_name
                    ):
                        # This is local content, not wire content - skip it
                        continue

                seen_services.add(service_normalized)
                unique_wire_services.append(service)

        # CRITICAL FIX: Remove wire service names from authors when wire
        # content is detected
        if unique_wire_services:
            # Create a set of all wire service variations for filtering
            wire_service_names = set()
            for service in unique_wire_services:
                wire_service_names.add(service.lower().strip())
                # Also add common variations
                if service.lower() == "the associated press":
                    wire_service_names.update(["associated press", "ap"])
                elif service.lower() == "cnn newssource":
                    wire_service_names.update(["cnn", "cnn newsource"])
                elif service.lower() == "abc news":
                    wire_service_names.update(["abc"])

            # Filter out wire service names from authors
            filtered_authors = []
            for author in authors:
                author_normalized = author.lower().strip()
                if author_normalized not in wire_service_names:
                    filtered_authors.append(author)

            authors = filtered_authors

        if return_json:
            return {
                "authors": authors,
                "count": len(authors),
                "primary_author": authors[0] if authors else None,
                "has_multiple_authors": len(authors) > 1,
                "wire_services": unique_wire_services,
                "is_wire_content": len(unique_wire_services) > 0,
                "primary_wire_service": (
                    unique_wire_services[0] if unique_wire_services else None
                ),
            }
        else:
            # Return array for normalized individual names (better for DB
            # operations)
            return authors

    def get_detected_wire_services(self) -> list[str]:
        """
        Get list of wire services detected in the last cleaning operation.

        Returns:
            List of wire service names that were removed from byline
        """
        return list(self._detected_wire_services)

    def get_primary_wire_service(self) -> str | None:
        """
        Get the primary (first detected) wire service from last cleaning.

        Returns:
            Primary wire service name or None if no wire services detected
        """
        return self._detected_wire_services[0] if self._detected_wire_services else None

    def clean_bulk_bylines(
        self, bylines: list[str], return_json: bool = False
    ) -> list[str | dict]:
        """
        Clean multiple bylines in bulk.

        Args:
            bylines: List of raw byline strings
            return_json: If True, return structured JSON for each

        Returns:
            List of cleaned bylines (strings or JSON objects)
        """
        return [self.clean_byline(byline, return_json) for byline in bylines]

    def get_publication_names(
        self,
        force_refresh: bool = False,
    ) -> set:  # pragma: no cover
        """
        Get comprehensive list of publication names from database.

        Args:
            force_refresh: Force refresh of cache even if still valid

        Returns:
            Set of normalized publication names for filtering
        """
        import time

        from sqlalchemy import text

        from src.models.database import DatabaseManager

        # Check if cache is still valid (refresh every 1 hour)
        current_time = time.time()
        cache_age = 3600  # 1 hour in seconds

        if (
            not force_refresh
            and self._publication_cache is not None
            and self._publication_cache_timestamp is not None
            and current_time - self._publication_cache_timestamp < cache_age
        ):
            return self._publication_cache

        # Fetch fresh data from database
        publication_names = set()

        try:
            db = DatabaseManager()
            session = db.session

            # Get all canonical names from sources
            result = session.execute(
                text(
                    """
                SELECT DISTINCT canonical_name
                FROM sources
                WHERE canonical_name IS NOT NULL
                AND canonical_name != ''
            """
                )
            )

            for row in result:
                canonical_name = row[0]
                if canonical_name:
                    # Add full name
                    publication_names.add(canonical_name.lower().strip())

                    # Add individual words for partial matching
                    words = canonical_name.lower().split()
                    for word in words:
                        # Only add significant words (3+ chars, not common)
                        common_words = {
                            "the",
                            "and",
                            "news",
                            "daily",
                            "county",
                            "city",
                            "post",
                            "times",
                            "press",
                            "herald",
                            "tribune",
                            "gazette",
                            "journal",
                            "review",
                        }
                        if len(word) >= 3 and word not in common_words:
                            publication_names.add(word)

            session.close()

        except Exception as e:
            logger.warning(f"Failed to load publication names: {e}")
            # Fallback to wire services if database fails
            publication_names = set(self.WIRE_SERVICES)

        # Cache the results
        self._publication_cache = publication_names
        self._publication_cache_timestamp = current_time

        logger.info(f"Loaded {len(publication_names)} publication names")
        return publication_names

    def refresh_publication_cache(self):
        """Force refresh of publication name cache."""
        self.get_publication_names(force_refresh=True)

    def get_organization_names(
        self,
        force_refresh: bool = False,
    ) -> set:  # pragma: no cover
        """
        Get organization names from gazetteer table for filtering.

        Args:
            force_refresh: Force refresh of cache even if still valid

        Returns:
            Set of normalized organization names for filtering
        """
        import time

        from src.models.database import DatabaseManager

        current_time = time.time()
        cache_duration = 3600  # 1 hour

        # Check cache validity
        if (
            not force_refresh
            and hasattr(self, "_organization_cache")
            and hasattr(self, "_organization_cache_timestamp")
            and (current_time - self._organization_cache_timestamp) < cache_duration
        ):
            return self._organization_cache

        organization_names = set()

        try:
            db_manager = DatabaseManager()
            from sqlalchemy import text

            # Query gazetteer for organization-type entities
            query = text(
                """
                SELECT DISTINCT name FROM gazetteer
                WHERE category IN (
                    'schools',
                    'government',
                    'healthcare',
                    'businesses'
                )
                AND name IS NOT NULL
                """
            )

            result = db_manager.session.execute(query)
            for row in result:
                name = row[0]
                if name and len(name.strip()) >= 3:
                    # Add full name
                    organization_names.add(name.lower().strip())

                    # Add individual significant words
                    words = name.lower().split()
                    for word in words:
                        # Only add significant organizational words
                        common_words = {
                            "the",
                            "and",
                            "of",
                            "for",
                            "at",
                            "in",
                            "on",
                            "to",
                            "center",
                            "department",
                            "office",
                            "services",
                        }
                        if len(word) >= 4 and word not in common_words:
                            organization_names.add(word)

            db_manager.close()

        except Exception as e:
            logger.warning(f"Failed to load organization names: {e}")
            # Fallback to empty set if database fails
            organization_names = set()

        # Cache the results
        self._organization_cache = organization_names
        self._organization_cache_timestamp = current_time

        logger.info(
            "Loaded %s organization names from gazetteer",
            len(organization_names),
        )
        return organization_names

    def _is_publication_name(self, text: str) -> bool:
        """
        Check if text matches any known publication name or organization.
        Publication names are typically binomial n-grams (multiple words).
        Single words should NOT be filtered as publication names.

        Args:
            text: Text to check

        Returns:
            True if text appears to be a publication name or organization
        """
        if not text or len(text.strip()) < 3:
            return False

        normalized_text = text.lower().strip()
        words = normalized_text.split()

        # CRITICAL: Publication names are binomial n-grams (multiple words)
        # Single words like "Prince", "McDonald's" should NOT be filtered
        # Only consider multi-word phrases as potential publication names
        if len(words) < 2:
            return False

        publication_names = self.get_publication_names()
        organization_names = self.get_organization_names()

        # IMPORTANT: If text contains commas, it's likely mixed content
        # Don't filter out comma-separated content at this stage
        if "," in normalized_text:
            return False

        # Check exact match in publications (only for multi-word phrases)
        if normalized_text in publication_names:
            return True

        # Check exact match in organizations (only for multi-word phrases)
        if normalized_text in organization_names:
            return True

        # Check wire service partials (only for multi-word phrases)
        if normalized_text in self.WIRE_SERVICE_PARTIALS:
            return True

        # Check if it's an organization (contains organization keywords)
        org_word_count = sum(1 for word in words if word in self.ORGANIZATION_PATTERNS)

        # If >40% of words are organization-related, it's likely an org
        if len(words) > 0 and org_word_count / len(words) > 0.4:
            return True

        # Check if text is mostly publication words
        pub_word_count = sum(1 for word in words if word in publication_names)

        # If >60% of words are publication-related, consider it publication
        if len(words) > 0 and pub_word_count / len(words) > 0.6:
            return True

        return False

    def _is_url_fragment(self, text: str) -> bool:
        """
        Check if text appears to be a continuous URL string.
        Only detects actual URLs, not spaced-out fragments like ". Com".

        Args:
            text: Text to check

        Returns:
            True if text appears to be a continuous URL string
        """
        if not text or len(text.strip()) < 3:
            return False

        text_clean = text.strip()

        # If there are multiple spaces, it's not a continuous URL
        if "  " in text_clean or text_clean.count(" ") > 1:
            return False

        # Remove single spaces for checking (like "site .com" -> "site.com")
        text_no_spaces = text_clean.replace(" ", "").lower()

        # URL patterns that indicate continuous URL strings
        import re

        url_patterns = [
            r"^https?://",  # http:// or https://
            r"^www\.",  # starts with www.
            r"^\w+\.\w{2,4}$",  # domain.tld format
            r"^\w+\.\w+\.\w{2,4}$",  # subdomain.domain.tld
            r"\.com$|\.org$|\.net$|\.edu$|\.gov$",  # ends with common TLD
        ]

        for pattern in url_patterns:
            if re.search(pattern, text_no_spaces):
                return True

        # Special case: malformed URLs with extra dots (like "Www..Com")
        # But only if it's a continuous string without spaces
        if (
            len(text_clean.split()) <= 1
            and "www" in text_no_spaces
            and text_no_spaces.count(".") >= 2
        ):
            return True

        return False

    def _extract_name_from_url_fragment(self, text: str) -> str:
        """
        Extract valid name from text containing both names and URL fragments.
        For cases like "Jack Silberberg • .Com", extract "Jack Silberberg".

        Args:
            text: Text that may contain both valid names and URL fragments

        Returns:
            Cleaned text with URL fragments removed, or empty if no valid name
        """
        if not text or not text.strip():
            return ""

        import re

        # Split on separators that might separate names from URL fragments
        # Including bullets, dashes, pipes, unusual spacing, etc.
        separators = [
            r"\s*•\s*",  # bullet separator: "Name • .Com"
            r"\s*\|\s*",  # pipe separator: "Name | .Com"
            r"\s*-\s*",  # dash separator: "Name - .Com"
            r"\s*–\s*",  # en-dash separator: "Name – .Com"
            r"\s*—\s*",  # em-dash separator: "Name — .Com"
            r"\s*\.\s*(?=\.)",  # dot before URL: "Name . .Com"
            r"\s*,\s*(?=\w*\.)",  # comma before URL: "Name , .Com"
        ]

        original_text = text.strip()
        best_name = ""

        # Try each separator pattern
        for separator_pattern in separators:
            parts = re.split(separator_pattern, original_text)
            if len(parts) > 1:
                # Check each part to see if it's a valid name vs URL fragment
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue

                    # Check if this part is a URL fragment
                    if self._is_url_fragment(part):
                        continue  # Skip URL fragments

                    # Check if this part looks like a valid name
                    # (2-3 words, mostly alphabetic, capitalized)
                    words = part.split()
                    if (
                        len(words) >= 2
                        and len(words) <= 4
                        and all(
                            word.replace(".", "")
                            .replace("'", "")
                            .replace("-", "")
                            .isalpha()
                            for word in words
                            if word
                        )
                        and all(
                            word[0].isupper()
                            for word in words
                            if word and word[0].isalpha()
                        )
                    ):
                        # This looks like a valid name - keep the longest one
                        if len(part) > len(best_name):
                            best_name = part

        # If we found a valid name through separation, return it
        if best_name:
            return best_name.strip()

        # Fallback: if the entire text is a URL fragment, return empty
        if self._is_url_fragment(original_text):
            return ""

        # Otherwise, return the original text (it might be a valid name)
        return original_text


def clean_byline(byline: str, return_json: bool = False) -> str | dict:
    """
    Convenience function to clean a single byline.

    Args:
        byline: Raw byline string
        return_json: If True, return structured JSON

    Returns:
        Cleaned byline string or JSON structure
    """
    cleaner = BylineCleaner()
    return cleaner.clean_byline(byline, return_json)


# Example usage and testing
if __name__ == "__main__":  # pragma: no cover
    # Test cases
    test_bylines = [
        "By John Smith, Staff Reporter",
        "Sarah Johnson and Mike Wilson, News Editors",
        "Staff Writer Bob Jones, bjones@newspaper.com",
        "By JANE DOE, SENIOR POLITICAL CORRESPONDENT",
        "mary williams & tom brown, sports writers",
        "Dr. Robert Chen, Medical Correspondent, with additional reporting by Lisa Park",
        "Staff",
        "By the Associated Press",
        "John O'Connor Jr., Business Editor (555) 123-4567",
        "Maria de la Cruz and James van der Berg III",
        "By Alex Thompson, alex.thompson@news.com, Twitter: @alexnews",
    ]

    cleaner = BylineCleaner()

    print("=== Byline Cleaning Test Results ===\n")

    for i, byline in enumerate(test_bylines, 1):
        print(f"Test {i}:")
        print(f"  Original: {byline}")

        # Clean as string
        cleaned_str = cleaner.clean_byline(byline, return_json=False)
        print(f"  String:   {cleaned_str}")

        # Clean as JSON
        cleaned_json = cleaner.clean_byline(byline, return_json=True)
        print(f"  JSON:     {json.dumps(cleaned_json, indent=12)}")
        print()
