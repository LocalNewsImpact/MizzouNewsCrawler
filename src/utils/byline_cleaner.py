"""
Byline cleaning utility for news articles.
"""

import json
import logging
import re
from difflib import SequenceMatcher
from typing import List, Optional

logger = logging.getLogger(__name__)

import json
import logging
import re
from typing import Dict, List, Optional, Union

# Import telemetry system
from .byline_telemetry import BylineCleaningTelemetry

logger = logging.getLogger(__name__)


class BylineCleaner:
    """Clean and normalize author bylines from news articles."""
    
    # Common titles and job descriptions to remove
    TITLES_TO_REMOVE = {
        # Basic titles
        'staff', 'reporter', 'editor', 'publisher', 'writer', 'journalist',
        'correspondent', 'contributor', 'freelancer', 'intern', 'blogger',
        
        # Senior/lead roles
        'senior', 'lead', 'chief', 'managing', 'executive', 'associate',
        'assistant', 'deputy', 'acting', 'interim', 'former', 'co-',
        
        # Department/beat specific
        'news', 'sports', 'politics', 'business', 'entertainment', 'lifestyle',
        'health', 'science', 'technology', 'education', 'crime', 'courts',
        'government', 'city', 'county', 'state', 'national', 'international',
        'investigative', 'feature', 'opinion', 'editorial', 'column', 'columnist',
        
        # Organization roles
        'director', 'manager', 'coordinator', 'specialist', 'analyst',
        'producer', 'photographer', 'videographer', 'multimedia',
        
        # Common suffixes/prefixes
        'the', 'for', 'at', 'of', 'and', 'from', 'with', 'by', 'staff writer',
        
        # Publication words (when used as titles/suffixes)
        'tribune', 'herald', 'gazette', 'times', 'post', 'news', 'press',
        'journal', 'daily', 'weekly', 'newspaper', 'magazine', 'publication',
        'citizen', 'sentinel', 'observer', 'chronicle', 'register', 'dispatch',
        'record', 'mirror', 'beacon', 'voice', 'leader', 'independent',
        
        # Degrees and credentials
        'phd', 'md', 'jd', 'mba', 'ma', 'ms', 'bs', 'ba'
    }
    
    # Wire services and syndicated content sources (preserve these for later filtering)
    WIRE_SERVICES = {
        'associated press', 'ap', 'reuters', 'bloomberg', 'cnn', 'fox news', 'fox',
        'nbc', 'abc', 'cbs', 'npr', 'pbs', 'usa today', 'wall street journal',
        'new york times', 'washington post', 'los angeles times', 'chicago tribune',
        'boston globe', 'the guardian', 'bbc', 'politico', 'the hill',
        'mcclatchy', 'gannett', 'hearst', 'scripps', 'sinclair'
    }
    
    # Journalism-specific nouns that are never names
    JOURNALISM_NOUNS = {
        # Core journalism terms
        'news', 'editor', 'editors', 'reporter', 'reporters', 'staff', 'writer', 'writers',
        'journalist', 'journalists', 'correspondent', 'correspondents', 'columnist', 'columnists',
        'publisher', 'publishers', 'producer', 'producers', 'anchor', 'anchors',
        
        # Job functions
        'investigator', 'investigators', 'photographer', 'photographers', 'videographer', 'videographers',
        'analyst', 'analysts', 'critic', 'critics', 'reviewer', 'reviewers',
        'contributor', 'contributors', 'freelancer', 'freelancers', 'intern', 'interns',
        
        # Editorial roles
        'editorial', 'editorials', 'opinion', 'opinions', 'commentary', 'commentaries',
        'column', 'columns', 'feature', 'features', 'blog', 'blogs', 'blogger', 'bloggers',
        
        # Publication terms
        'publication', 'publications', 'newspaper', 'newspapers', 'magazine', 'magazines',
        'journal', 'journals', 'press', 'media', 'newsroom', 'newsrooms',
        'bureau', 'bureaus', 'desk', 'desks', 'beat', 'beats',
        
        # Content types
        'article', 'articles', 'story', 'stories', 'report', 'reports', 'piece', 'pieces',
        'coverage', 'interview', 'interviews', 'profile', 'profiles',
        
        # Time/status indicators
        'former', 'current', 'retired', 'emeritus', 'acting', 'interim', 'temporary',
        
        # Organizational
        'team', 'teams', 'crew', 'crews', 'department', 'departments', 'division', 'divisions',
        'section', 'sections', 'unit', 'units', 'group', 'groups', 'name', 'names'
    }
    
    # Organization and department patterns (not person names)
    ORGANIZATION_PATTERNS = {
        # Educational institutions
        'university', 'college', 'school', 'academy', 'institute', 'campus',
        
        # Government/Military
        'department', 'bureau', 'agency', 'office', 'division', 'unit',
        'wing', 'squadron', 'battalion', 'regiment', 'corps', 'command',
        'affairs', 'administration', 'ministry', 'council', 'committee',
        
        # Business/Organization types
        'corporation', 'company', 'inc', 'llc', 'ltd', 'group', 'organization',
        'association', 'foundation', 'institute', 'center', 'centre',
        
        # Media/Communications
        'media', 'communications', 'broadcast', 'network', 'channel',
        'productions', 'studios', 'publishing', 'syndicate',
        
        # Activities/Services
        'activities', 'services', 'operations', 'relations', 'resources',
        'development', 'research', 'studies', 'programs', 'initiatives'
    }
    
    # Wire service partial names that should be filtered
    WIRE_SERVICE_PARTIALS = {
        'associated', 'reuters', 'bloomberg', 'ap news', 'cnn news',
        'fox news', 'nbc news', 'abc news', 'cbs news', 'npr news',
        'usa today', 'wsj', 'nyt', 'wapo', 'latimes', 'tribune',
        'mcclatchy', 'gannett', 'hearst', 'scripps', 'sinclair'
    }
    
    # Patterns for common byline formats
    BYLINE_PATTERNS = [
        # "By Author Name" patterns
        r'^by\s+(.+)$',
        r'^written\s+by\s+(.+)$',
        r'^story\s+by\s+(.+)$',
        r'^report\s+by\s+(.+)$',
        
        # Email patterns (remove emails)
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        
        # Phone number patterns (remove phones)
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        r'\(\d{3}\)\s*\d{3}[-.]?\d{4}',
        
        # Social media handles and references
        r'@\w+',
        r'twitter\.com/\w+',
        r'facebook\.com/[\w.]+',
        r'twitter:\s*@?\w+',
        r'facebook:\s*[\w./]+',
        r'instagram:\s*@?\w+',
        r'linkedin:\s*[\w./]+',
        
        # Copyright and source attributions
        r'©.*$',
        r'copyright.*$',
        r'all rights reserved.*$',
        r'source:.*$',
        r'photo.*:.*$',
        r'image.*:.*$',
    ]
    
    # Author separators (order matters - more specific first)
    AUTHOR_SEPARATORS = [
        ' and ',
        ' & ',
        ' with ',
        ', and ',
        ' + ',
    ]
    
    def __init__(self, enable_telemetry: bool = True):
        """Initialize the byline cleaner."""
        # Compile regex patterns for efficiency
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.BYLINE_PATTERNS
        ]
        
        # Create title removal pattern
        titles_pattern = r'\b(?:' + '|'.join(re.escape(title) for title in self.TITLES_TO_REMOVE) + r')\b'
        self.title_pattern = re.compile(titles_pattern, re.IGNORECASE)
        
        # Initialize telemetry
        self.telemetry = BylineCleaningTelemetry(enable_telemetry=enable_telemetry)
        
        # Dynamic publication filter cache
        self._publication_cache = None
        self._publication_cache_timestamp = None
    
    def clean_byline(
        self, 
        byline: str, 
        return_json: bool = False, 
        source_name: Optional[str] = None,
        article_id: Optional[str] = None,
        candidate_link_id: Optional[str] = None,
        source_id: Optional[str] = None,
        source_canonical_name: Optional[str] = None
    ) -> Union[List[str], Dict]:
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
            List of cleaned author names or JSON object with details
        """
        # Start telemetry session
        telemetry_id = self.telemetry.start_cleaning_session(
            raw_byline=byline,
            article_id=article_id,
            candidate_link_id=candidate_link_id,
            source_id=source_id,
            source_name=source_name,
            source_canonical_name=source_canonical_name
        )
        
        try:
            if not byline or not byline.strip():
                self.telemetry.finalize_cleaning_session(
                    final_authors=[],
                    cleaning_method="empty_input",
                    likely_valid_authors=False,
                    likely_noise=True
                )
                return self._format_result([], return_json)
            
            # Step 1: Source name removal
            cleaned_byline = byline
            if source_name:
                original_byline = byline
                cleaned_byline = self._remove_source_name(byline, source_name)
                
                self.telemetry.log_transformation_step(
                    step_name="source_removal",
                    input_text=original_byline,
                    output_text=cleaned_byline,
                    transformation_type="source_filtering",
                    removed_content=(original_byline if cleaned_byline != original_byline else None),
                    confidence_delta=0.1 if cleaned_byline != original_byline else 0.0,
                    notes=f"Removed source name: {source_name}"
                )
                
                if cleaned_byline != byline:
                    logger.debug(f"Source removed: '{byline}' -> '{cleaned_byline}'")
            
            # Step 1.5: Dynamic publication name filtering
            if self._is_publication_name(cleaned_byline):
                self.telemetry.log_transformation_step(
                    step_name="dynamic_publication_filter",
                    input_text=cleaned_byline,
                    output_text="",
                    transformation_type="publication_filtering",
                    removed_content=cleaned_byline,
                    confidence_delta=0.9,
                    notes="Removed publication name using dynamic filter"
                )
                
                self.telemetry.finalize_cleaning_session(
                    final_authors=[],
                    cleaning_method="publication_filtered",
                    likely_valid_authors=False,
                    likely_noise=True
                )
                return self._format_result([], return_json)
            
            # Step 2: Wire service detection
            if self._is_wire_service(cleaned_byline):
                self.telemetry.log_transformation_step(
                    step_name="wire_service_detection",
                    input_text=cleaned_byline,
                    output_text=cleaned_byline,
                    transformation_type="classification",
                    confidence_delta=0.8,
                    notes="Detected wire service byline - preserving as-is"
                )
                
                self.telemetry.finalize_cleaning_session(
                    final_authors=[cleaned_byline.strip()],
                    cleaning_method="wire_service_passthrough",
                    likely_valid_authors=True,
                    likely_noise=False
                )
                return self._format_result([cleaned_byline.strip()], return_json)
            
            logger.debug(f"Processing byline: {cleaned_byline}")
            
            # Step 3: Pattern extraction
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
                logger.debug(f"No pattern matched, using full text")
            
            self.telemetry.log_transformation_step(
                step_name="pattern_extraction",
                input_text=cleaned_byline,
                output_text=extracted_text,
                transformation_type="text_extraction",
                confidence_delta=0.2 if pattern_used != "no_pattern" else 0.0,
                notes=f"Used {pattern_used}"
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
                    removed_content=f"Removed: {before_pattern_removal.replace(cleaned_text, '').strip()}",
                    confidence_delta=0.1,
                    notes="Removed emails, phones, and other patterns"
                )
            
            logger.debug(f"After removing patterns: {cleaned_text}")
            
            # Step 5: Extract individual authors
            before_author_extraction = cleaned_text
            authors = self._extract_authors(cleaned_text)
            
            self.telemetry.log_transformation_step(
                step_name="author_extraction",
                input_text=before_author_extraction,
                output_text=str(authors),
                transformation_type="name_parsing",
                confidence_delta=0.2,
                notes=f"Extracted {len(authors)} potential authors"
            )
            
            logger.debug(f"Extracted authors: {authors}")
            
            # Check if smart processing was used
            if (isinstance(authors, list) and len(authors) >= 1 and 
                authors[0] == "__SMART_PROCESSED__"):
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
                    notes="Used smart processing for name cleaning"
                )
                
                final_authors = self._deduplicate_authors(cleaned_names)
                
                self.telemetry.finalize_cleaning_session(
                    final_authors=final_authors,
                    cleaning_method="smart_processing",
                    likely_valid_authors=len(final_authors) > 0,
                    likely_noise=len(final_authors) == 0
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
                notes=f"Cleaned {len(before_name_cleaning)} names to {len(cleaned_authors)}"
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
                    notes=f"Removed {removed_duplicates} duplicate authors"
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
                    notes=f"Filtered out {invalid_count} invalid author names"
                )
            
            logger.debug(f"Final authors: {valid_authors}")
            
            # Finalize telemetry
            self.telemetry.finalize_cleaning_session(
                final_authors=valid_authors,
                cleaning_method="standard_pipeline",
                likely_valid_authors=len(valid_authors) > 0 and all(
                    len(name.split()) >= 2 for name in valid_authors
                ),
                likely_noise=len(valid_authors) == 0,
                requires_manual_review=(
                    len(valid_authors) == 0 and len(byline.strip()) > 10
                )
            )
            
            return self._format_result(valid_authors, return_json)
            
        except Exception as e:
            # Log error and continue without telemetry
            self.telemetry.log_error(f"Cleaning error: {str(e)}", "processing")
            self.telemetry.finalize_cleaning_session(
                final_authors=[],
                cleaning_method="error_fallback",
                likely_valid_authors=False,
                requires_manual_review=True
            )
            logger.error(f"Error cleaning byline '{byline}': {e}")
            return self._format_result([], return_json)
    
    def _process_single_name(self, name_text: str, return_json: bool) -> Union[str, Dict]:
        """Process a single name that's already been identified as a clean name."""
        # Clean the individual name
        cleaned_name = self._clean_author_name(name_text)
        
        if cleaned_name.strip():
            return self._format_result([cleaned_name], return_json)
        else:
            return self._format_result([], return_json)
    
    def _is_wire_service(self, byline: str) -> bool:
        """Check if byline is from wire service/syndicated source."""
        byline_lower = byline.lower().strip()
        
        # Remove common prefixes to get to the core identifier
        for prefix in ['by ', 'from ', 'source: ', '- ']:
            if byline_lower.startswith(prefix):
                byline_lower = byline_lower[len(prefix):].strip()
        
        # Check if the byline matches known wire services
        for wire_service in self.WIRE_SERVICES:
            if (byline_lower == wire_service or
                    byline_lower.startswith(wire_service + ' ')):
                return True
        
        # Check for common wire service patterns
        wire_patterns = [
            r'^(ap|reuters|bloomberg|cnn|npr|pbs)$',
            r'^(the\s+)?(associated\s+press|new\s+york\s+times|'
            r'washington\s+post)$',
            r'^(usa\s+today|wall\s+street\s+journal|'
            r'los\s+angeles\s+times)$'
        ]
        
        for pattern in wire_patterns:
            if re.match(pattern, byline_lower):
                return True
        
        return False
    
    def _basic_cleaning(self, byline: str) -> str:
        """Perform basic text cleaning and normalization."""
        # Remove extra whitespace and normalize
        cleaned = re.sub(r'\s+', ' ', byline.strip())
        
        # Remove common prefixes
        for pattern in ['by ', 'written by ', 'story by ', 'report by ']:
            if cleaned.lower().startswith(pattern):
                cleaned = cleaned[len(pattern):].strip()
                break
        
        # Remove trailing punctuation and common suffixes
        cleaned = re.sub(r'[.,;:]+$', '', cleaned)
        cleaned = re.sub(r'\s+(staff|reporter|editor)$', '', cleaned, flags=re.IGNORECASE)
        
        return cleaned
    
    def _remove_source_name(self, text: str, source_name: str) -> str:
        """Remove source/publication name from author text using fuzzy matching."""
        if not source_name or not text:
            return text
        
        # Normalize both strings for comparison
        def normalize_for_comparison(input_text: str) -> str:
            """Normalize text for fuzzy comparison."""
            # Convert to lowercase, remove extra spaces, punctuation
            normalized = re.sub(r'[^\w\s]', '', input_text.lower())
            normalized = re.sub(r'\s+', ' ', normalized).strip()
            return normalized
        
        normalized_source = normalize_for_comparison(source_name)
        normalized_text = normalize_for_comparison(text)
        
        # Skip if source name is too short (likely false positive)
        if len(normalized_source) < 3:
            return text
        
        # Calculate similarity ratio for exact match detection
        similarity = SequenceMatcher(None, normalized_source, normalized_text).ratio()
        
        # High similarity threshold - this is likely just the publication name
        if similarity > 0.8:
            logger.info(f"Removing publication name (similarity: {similarity:.2f}): '{text}' matches '{source_name}'")
            return ""
        
        # Check if source name is contained within the text (partial match)
        # BUT only if the text is mostly just the source name (not author + 
        # source)
        if normalized_source in normalized_text:
            # Calculate how much of the text is NOT the source name
            remaining_text = normalized_text.replace(
                normalized_source, '').strip()
            if normalized_text:
                remaining_ratio = len(remaining_text) / len(normalized_text)
            else:
                remaining_ratio = 0
            
            # Only remove if most of the text is the publication name
            if remaining_ratio < 0.3:  # Less than 30% is non-source content
                logger.info(f"Removing publication name (substring match): "
                          f"'{source_name}' found in '{text}'")
                return ""
        
        # Check if text is contained within source name (reverse match)
        if normalized_text in normalized_source:
            logger.info(f"Removing publication name (reverse match): '{text}' found in '{source_name}'")
            return ""
        
        # NEW: Smart partial removal for "Name Publication" patterns
        source_words = normalized_source.split()
        text_words = normalized_text.split()
        
        # If source has multiple words, try to identify and remove just the
        # publication part
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
                # First, let's work with the original text to preserve formatting
                original_words = text.split()
                remaining_words = []
                
                for word in original_words:
                    word_normalized = re.sub(r'[^\w\s]', '', word.lower())
                    # Skip this word if it matches any source word
                    if word_normalized not in [w.lower() for w in source_words]:
                        remaining_words.append(word)
                
                # Only return the remaining words if we have something left
                # that looks like a name
                if remaining_words:
                    result = ' '.join(remaining_words).strip()
                    
                    # Clean up any remaining email addresses
                    result = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', result)
                    result = re.sub(r'\s+', ' ', result).strip()
                    
                    if result:
                        logger.info(
                            f"Removing publication words "
                            f"(word match {match_ratio:.2f}): "
                            f"'{text}' -> '{result}'")
                        return result
                    else:
                        logger.info(
                            f"Removing entire text "
                            f"(word match {match_ratio:.2f}): "
                            f"'{text}' matches '{source_name}'")
                        return ""
                else:
                    logger.info(
                        f"Removing entire text "
                        f"(word match {match_ratio:.2f}): "
                        f"'{text}' matches '{source_name}'")
                    return ""
        
        # Additional patterns for common publication naming
        # Check for pattern like "Name Publication" where Publication matches
        # source
        if len(text_words) >= 2:
            # Last word(s) might be publication name
            last_word = text_words[-1]
            if len(text_words) >= 2:
                last_two_words = ' '.join(text_words[-2:])
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
                        name_part = ' '.join(text_words[:-1]).strip()
                        if name_part:
                            # Re-capitalize properly
                            name_part = ' '.join(
                                word.title() for word in name_part.split())
                            logger.info(
                                f"Removing publication suffix "
                                f"'{last_word}' (similarity: "
                                f"{word_similarity:.2f})")
                            return name_part
            
            # Check last two words against source
            normalized_two = normalize_for_comparison(last_two_words)
            matcher = SequenceMatcher(None, normalized_source, normalized_two)
            two_word_similarity = matcher.ratio()
            if two_word_similarity > 0.7:
                name_part = ' '.join(text_words[:-2]).strip()
                if name_part:
                    # Re-capitalize properly
                    name_part = ' '.join(
                        word.title() for word in name_part.split())
                    logger.info(
                        f"Removing publication suffix "
                        f"'{last_two_words}' (similarity: "
                        f"{two_word_similarity:.2f})")
                    return name_part
        
        # No match found - return original
        return text
    
    def _remove_patterns(self, text: str) -> str:
        """Remove unwanted patterns like emails, phones, etc."""
        # Skip byline extraction patterns
        for pattern in self.compiled_patterns[4:]:
            text = pattern.sub('', text)
        
        # Remove parenthetical information
        text = re.sub(r'\([^)]*\)', '', text)
        
        # Remove bracketed information
        text = re.sub(r'\[[^\]]*\]', '', text)
        
        # Clean up extra spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _identify_part_type(self, part: str) -> str:
        """
        Identify what type of content a comma-separated part contains.
        Returns: 'name', 'email', 'title', or 'mixed'
        """
        part = part.strip()
        if not part:
            return 'empty'
        
        # Check for email
        if '@' in part and '.' in part:
            return 'email'
        
        # Check for titles/journalism words
        part_words = part.lower().split()
        title_word_count = 0
        
        # Check for non-name contexts with Roman numerals
        if (len(part_words) == 2 and
                part_words[0] in ['chapter', 'section', 'volume', 'part',
                                  'book', 'act', 'scene'] and
                part_words[1] in ['ii', 'iii', 'iv', 'v', 'vi', 'vii',
                                  'viii', 'ix', 'x']):
            return 'title'
        
        for i, word in enumerate(part_words):
            is_title_word = False
            
            # Direct match for title/journalism words
            if (word in self.TITLES_TO_REMOVE or
                    word in self.JOURNALISM_NOUNS or
                    word in self.ORGANIZATION_PATTERNS):
                is_title_word = True
            
            # Check for plural forms
            elif (word.endswith('s') and
                  (word[:-1] in self.TITLES_TO_REMOVE or
                   word[:-1] in self.JOURNALISM_NOUNS or
                   word[:-1] in self.ORGANIZATION_PATTERNS)):
                is_title_word = True
            
            # Check for common title modifiers
            elif word in ['senior', 'junior', 'lead', 'chief', 'managing',
                          'executive', 'associate', 'assistant', 'deputy',
                          'acting', 'interim', 'co']:
                is_title_word = True
            
            # Check for numbers (indicating positions/levels)
            # But exclude Roman numerals when they appear as name suffixes
            elif (word.isdigit() or
                  (word in ['ii', 'iii', 'iv', 'v', 'vi', 'vii',
                            'vii', 'viii', 'ix', 'x'] and
                   not (i == len(part_words) - 1 and len(part_words) <= 3))):
                is_title_word = True  # Numbers are often part of titles
            
            # Check for ordinal indicators
            elif (word.endswith(('st', 'nd', 'rd', 'th')) and
                  word[:-2].isdigit()):
                is_title_word = True  # Ordinals are often part of titles
            
            if is_title_word:
                title_word_count += 1
        
        # Enhanced logic: check if this looks like a title phrase
        # Look for patterns like "2nd Assistant Editor", "Senior Editor II"
        has_title_pattern = False
        for i, word in enumerate(part_words):
            word_lower = word.lower()
            # If we find a clear title word, check surrounding context
            if (word_lower in self.TITLES_TO_REMOVE or 
                word_lower in self.JOURNALISM_NOUNS):
                has_title_pattern = True
                break
        
        # If we have title patterns and numbers/ordinals, it's likely all title
        if has_title_pattern and title_word_count >= len(part_words) * 0.6:
            return 'title'        # If most words are titles/journalism terms, it's a title section
        if title_word_count >= len(part_words) / 2:
            return 'title'
        
        # If it has some title words but not majority, it's mixed
        if title_word_count > 0:
            return 'mixed'
        
        # Check if it looks like a name (2-3 capitalized words, no special chars)
        if (len(part_words) <= 3 and 
            all(word.replace('.', '').isalpha() for word in part_words) and
            not any(word.lower() in self.TITLES_TO_REMOVE or 
                   word.lower() in self.JOURNALISM_NOUNS for word in part_words)):
            return 'name'
        
        # Default to mixed if unclear
        return 'mixed'

    def _extract_authors(self, text: str) -> List[str]:
        """
        Extract author names from cleaned text.
        Uses type identification to distinguish names from emails, titles, etc.
        """
        # Remove social media patterns first
        social_patterns = [
            r'twitter:\s*@?\w+',
            r'facebook:\s*[\w./]+',
            r'instagram:\s*@?\w+',
            r'@\w+',
            r'\btwitter\b(?!\s+[A-Z][a-z]+)',
            r'\bfacebook\b',
            r'\binstagram\b',
            r'\blinkedin\b'
        ]
        
        for pattern in social_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Handle "and" separated authors (keep both)
        if ' and ' in text.lower():
            parts = re.split(r'\s+and\s+', text, flags=re.IGNORECASE)
            authors = []
            for part in parts:
                part = part.strip()
                if part:
                    # For "and" separated parts, recursively extract authors
                    # This handles cases like "NAME1 and NAME2, NAME1, NAME2"
                    part_authors = self._extract_authors(part)
                    if (isinstance(part_authors, list) and
                            len(part_authors) > 0):
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
        
        # Handle comma-separated content with type identification
        if ',' in text:
            comma_parts = text.split(',')
            
            # Identify the type of each part
            part_types = []
            for part in comma_parts:
                part_type = self._identify_part_type(part)
                part_types.append((part.strip(), part_type))
            
            # Count different types
            non_name_count = sum(1 for _, ptype in part_types
                                 if ptype in ['email', 'title'])
            
            # Smart processing: if we have multiple non-name parts,
            # extract just the name part(s)
            condition = (non_name_count >= 2 or
                         (non_name_count >= 1 and len(comma_parts) >= 3))
            if condition:
                # Find parts that are clearly names
                name_parts = [part for part, ptype in part_types
                              if ptype == 'name']
                
                if name_parts:
                    # Return ALL clear names, not just the first one
                    return ["__SMART_PROCESSED__"] + name_parts
                else:
                    # If no clear names, take the first part that's not
                    # email/title
                    for part, ptype in part_types:
                        if ptype not in ['email', 'title'] and part:
                            return ["__SMART_PROCESSED__", part]
                    
                    # If all parts are email/title, return empty list
                    # This handles cases like "Senior Editor II, Managing Director III"
                    return ["__SMART_PROCESSED__"]
            
            # If not using smart processing, handle normally
            # Keep parts that are names or mixed (not pure email/title)
            authors = []
            for part, ptype in part_types:
                if ptype in ['name', 'mixed'] and part:
                    # For mixed types that might contain person + organization,
                    # try to filter out organization words
                    if ptype == 'mixed':
                        filtered_part = self._filter_organization_words(part)
                        if filtered_part.strip():  # Only add if something remains
                            authors.append(filtered_part)
                    else:
                        authors.append(part)
            
            if authors:
                # Apply deduplication to all comma-separated results
                return self._deduplicate_authors(authors)
        
        # Default: return as single author, but only if it's not identified as a title
        if text.strip():
            # Check if the entire text is just a title
            text_type = self._identify_part_type(text)
            if text_type == 'title':
                return []  # Don't return titles as names
            
            # For mixed content, try to filter organization words
            if text_type == 'mixed':
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
        Uses fuzzy matching on multi-word phrases (minimum 2 words) to avoid
        removing surnames that happen to appear in organization names.
        
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
        
        # Convert to lowercase for case-insensitive matching
        org_names_lower = {name.lower() for name in all_org_names}
        
        # Find spans to remove using sliding window approach
        spans_to_remove = []
        text_lower = text.lower()
        
        # Check for multi-word organization matches (minimum 2 words)
        for org_name in org_names_lower:
            org_words = org_name.split()
            if len(org_words) >= 2:  # Require at least 2 words
                # Use fuzzy matching - check if organization name appears in text
                if org_name in text_lower:
                    # Find exact position
                    start_pos = text_lower.find(org_name)
                    if start_pos != -1:
                        end_pos = start_pos + len(org_name)
                        spans_to_remove.append((start_pos, end_pos))
                else:
                    # Check for partial matches (e.g., "hancock school" in "hancock place middle school")
                    # This handles cases where we have a subset of the organization name
                    for window_size in range(len(org_words), 1, -1):  # Start with full length, work down
                        for i in range(len(org_words) - window_size + 1):
                            partial_org = ' '.join(org_words[i:i + window_size])
                            if len(partial_org.split()) >= 2 and partial_org in text_lower:
                                start_pos = text_lower.find(partial_org)
                                if start_pos != -1:
                                    end_pos = start_pos + len(partial_org)
                                    spans_to_remove.append((start_pos, end_pos))
                                    break
                        if spans_to_remove:  # Found a match, stop looking
                            break
        
        # Remove overlapping spans and sort by position
        spans_to_remove = sorted(set(spans_to_remove))
        merged_spans = []
        for start, end in spans_to_remove:
            if merged_spans and start <= merged_spans[-1][1]:
                # Overlapping spans, merge them
                merged_spans[-1] = (merged_spans[-1][0], max(merged_spans[-1][1], end))
            else:
                merged_spans.append((start, end))
        
        # Remove organization text by reconstructing string without removed spans
        if not merged_spans:
            # No organization matches found, filter individual journalism terms
            filtered_words = []
            for word in words:
                word_lower = word.lower().strip()
                # Skip obvious organization patterns and journalism terms (single words only)
                if (word_lower not in self.ORGANIZATION_PATTERNS and
                        word_lower not in self.WIRE_SERVICE_PARTIALS and
                        word_lower not in self.JOURNALISM_NOUNS and
                        word_lower not in self.TITLES_TO_REMOVE):
                    filtered_words.append(word)
            return ' '.join(filtered_words).strip()
        
        # Reconstruct text without the organization spans
        result_parts = []
        last_end = 0
        for start, end in merged_spans:
            if start > last_end:
                result_parts.append(text[last_end:start])
            last_end = end
        if last_end < len(text):
            result_parts.append(text[last_end:])
        
        # Clean up extra whitespace and filter remaining individual journalism terms
        result = ' '.join(''.join(result_parts).split())
        
        # Final pass to remove individual journalism terms that weren't part of org names
        final_words = []
        for word in result.split():
            word_lower = word.lower().strip()
            if (word_lower not in self.ORGANIZATION_PATTERNS and
                    word_lower not in self.WIRE_SERVICE_PARTIALS and
                    word_lower not in self.JOURNALISM_NOUNS and
                    word_lower not in self.TITLES_TO_REMOVE):
                final_words.append(word)
        
        return ' '.join(final_words).strip()

    def _clean_author_name(self, name: str) -> str:
        """Clean an individual author name."""
        if not name:
            return ""
        
        # Check if this name is actually a publication name
        if self._is_publication_name(name):
            return ""  # Filter out publication names
        
        # Handle mixed person/organization cases
        cleaned = self._filter_organization_words(name)
        
        # Remove common patterns like ", Title", ", Title Title", etc.
        # This handles cases like "Mike Wilson, News Editors"
        comma_split = cleaned.split(',', 1)
        if len(comma_split) == 2:
            main_name = comma_split[0].strip()
            title_part = comma_split[1].strip()
            
            # Check if the title part contains only title words or journalism nouns
            title_words = title_part.lower().split()
            is_all_titles = True
            for word in title_words:
                if word not in self.TITLES_TO_REMOVE and word not in self.JOURNALISM_NOUNS:
                    is_all_titles = False
                    break
            
            if is_all_titles:
                cleaned = main_name
            else:
                cleaned = name  # Keep original if not all title words
        
        # Remove titles and job descriptions using the compiled pattern
        cleaned = self.title_pattern.sub(' ', cleaned)
        
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Handle name capitalization
        cleaned = self._normalize_capitalization(cleaned)
        
        # Remove leading/trailing non-letter characters
        cleaned = re.sub(r'^[^a-zA-Z]+|[^a-zA-Z\s\'.-]+$', '', cleaned)
        
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
            if word.lower() in ['de', 'da', 'del', 'della', 'von', 'van', 'der', 'le', 'la', 'du']:
                normalized.append(word.lower())
            # Handle suffixes like Jr., Sr., III - always normalize these
            elif word.lower().rstrip('.') in ['jr', 'sr', 'ii', 'iii', 'iv']:
                base_word = word.lower().rstrip('.')
                if base_word in ['ii', 'iii', 'iv']:
                    # Roman numerals should be uppercase
                    suffix = '.' if word.endswith('.') else ''
                    normalized.append(base_word.upper() + suffix)
                else:
                    # Jr, Sr should be title case
                    suffix = '.' if word.endswith('.') else ''
                    normalized.append(base_word.title() + suffix)
            # Handle hyphenated names
            elif '-' in word:
                parts = word.split('-')
                normalized.append('-'.join(part.title() for part in parts))
            else:
                # Apply title case if the word is all caps or all lowercase
                if word.isupper() or word.islower():
                    normalized.append(word.title())
                else:
                    # Keep existing capitalization for mixed case
                    normalized.append(word)
        
        return ' '.join(normalized)
    
    def _deduplicate_authors(self, authors: List[str]) -> List[str]:
        """Remove duplicate author names."""
        if not authors:
            return []
        
        seen = set()
        deduplicated = []
        
        for author in authors:
            if not author:
                continue
            
            # Normalize for comparison (lowercase, no spaces)
            normalized = re.sub(r'\s+', '', author.lower())
            
            if normalized not in seen:
                seen.add(normalized)
                deduplicated.append(author)
        
        return deduplicated
    
    def _validate_authors(self, authors: List[str]) -> List[str]:
        """Validate author names and filter out invalid entries."""
        valid_authors = []
        
        for author in authors:
            if not author:
                continue
            
            # Must have at least 2 characters
            if len(author) < 2:
                continue
            
            # Must contain at least one letter
            if not re.search(r'[a-zA-Z]', author):
                continue
            
            # Reject if it's just a single word that looks like a title or journalism term
            words = author.split()
            if len(words) == 1:
                word_lower = words[0].lower()
                if word_lower in self.TITLES_TO_REMOVE or word_lower in self.JOURNALISM_NOUNS:
                    continue
            
            # Reject common non-name patterns
            if re.match(r'^(staff|the|by|and|with|for|at|of)$', author.lower()):
                continue
            
            # Reject if it's too long (likely not a name)
            if len(author) > 100:
                continue
            
            valid_authors.append(author)
        
        return valid_authors
    
    def _format_result(self, authors: List[str], return_json: bool) -> Union[List[str], Dict]:
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
        
        if return_json:
            return {
                "authors": authors,
                "count": len(authors),
                "primary_author": authors[0] if authors else None,
                "has_multiple_authors": len(authors) > 1
            }
        else:
            # Return array for normalized individual names (better for DB operations)
            return authors
    
    def clean_bulk_bylines(self, bylines: List[str], return_json: bool = False) -> List[Union[str, Dict]]:
        """
        Clean multiple bylines in bulk.
        
        Args:
            bylines: List of raw byline strings
            return_json: If True, return structured JSON for each
            
        Returns:
            List of cleaned bylines (strings or JSON objects)
        """
        return [self.clean_byline(byline, return_json) for byline in bylines]

    def get_publication_names(self, force_refresh: bool = False) -> set:
        """
        Get comprehensive list of publication names from database.
        
        Args:
            force_refresh: Force refresh of cache even if still valid
            
        Returns:
            Set of normalized publication names for filtering
        """
        import time
        from src.models.database import DatabaseManager
        from sqlalchemy import text
        
        # Check if cache is still valid (refresh every 1 hour)
        current_time = time.time()
        cache_age = 3600  # 1 hour in seconds
        
        if (not force_refresh and
                self._publication_cache is not None and
                self._publication_cache_timestamp is not None and
                current_time - self._publication_cache_timestamp < cache_age):
            return self._publication_cache
        
        # Fetch fresh data from database
        publication_names = set()
        
        try:
            db = DatabaseManager()
            session = db.session
            
            # Get all canonical names from sources
            result = session.execute(text("""
                SELECT DISTINCT canonical_name
                FROM sources
                WHERE canonical_name IS NOT NULL
                AND canonical_name != ''
            """))
            
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
                            'the', 'and', 'news', 'daily', 'county', 'city',
                            'post', 'times', 'press', 'herald', 'tribune',
                            'gazette', 'journal', 'review'
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

    def get_organization_names(self, force_refresh: bool = False) -> set:
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
        if (not force_refresh and
                hasattr(self, '_organization_cache') and
                hasattr(self, '_organization_cache_timestamp') and
                current_time - self._organization_cache_timestamp < cache_duration):
            return self._organization_cache
        
        organization_names = set()
        
        try:
            db_manager = DatabaseManager()
            from sqlalchemy import text
            
            # Query gazetteer for organization-type entities
            query = text("""
                SELECT DISTINCT name FROM gazetteer 
                WHERE category IN ('schools', 'government', 'healthcare', 'businesses')
                AND name IS NOT NULL
            """)
            
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
                            'the', 'and', 'of', 'for', 'at', 'in', 'on', 'to',
                            'center', 'department', 'office', 'services'
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
        
        logger.info(f"Loaded {len(organization_names)} organization names from gazetteer")
        return organization_names

    def _is_publication_name(self, text: str) -> bool:
        """
        Check if text matches any known publication name or organization.
        
        Args:
            text: Text to check
            
        Returns:
            True if text appears to be a publication name or organization
        """
        if not text or len(text.strip()) < 3:
            return False
            
        normalized_text = text.lower().strip()
        publication_names = self.get_publication_names()
        organization_names = self.get_organization_names()
        
        # IMPORTANT: If text contains commas, it's likely mixed content
        # Don't filter out comma-separated content at this stage
        if ',' in normalized_text:
            return False
        
        # Check exact match in publications
        if normalized_text in publication_names:
            return True
            
        # Check exact match in organizations
        if normalized_text in organization_names:
            return True
            
        # Check wire service partials
        if normalized_text in self.WIRE_SERVICE_PARTIALS:
            return True
            
        # Check if it's an organization (contains organization keywords)
        words = normalized_text.split()
        org_word_count = sum(
            1 for word in words if word in self.ORGANIZATION_PATTERNS
        )
        
        # If >40% of words are organization-related, it's likely an org
        if len(words) > 0 and org_word_count / len(words) > 0.4:
            return True
            
        # Check if text is mostly publication words
        pub_word_count = sum(
            1 for word in words if word in publication_names
        )
        
        # If >60% of words are publication-related, consider it publication
        if len(words) > 0 and pub_word_count / len(words) > 0.6:
            return True
            
        return False


def clean_byline(byline: str, return_json: bool = False) -> Union[str, Dict]:
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
if __name__ == "__main__":
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
        "By Alex Thompson, alex.thompson@news.com, Twitter: @alexnews"
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