"""
Refactored URL validation module to replace the repetitive if/then logic in crawler_0.ipynb

This module provides a configuration-driven approach to URL validation and exclusion,
replacing the 150+ lines of hardcoded if/then statements with a maintainable,
data-driven solution.

Usage:
    validator = URLValidator('url_validation_config.json')
    if validator.should_include_url(url):
        valid_urls.append(url)
"""

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


class URLValidator:
    """Configuration-driven URL validator for news crawler."""

    def __init__(self, config_path: str):
        """Initialize validator with configuration file.

        Args:
            config_path: Path to JSON configuration file
        """
        self.config = self._load_config(config_path)
        self.general_exclusions = self.config.get("general_exclusions", [])
        self.outlets = self.config.get("outlets", {})
        self.validation_rules = self.config.get("validation_rules", {})

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")

    def should_include_url(self, url: str) -> bool:
        """
        Determine if URL should be included based on validation rules.

        Args:
            url: URL to validate

        Returns:
            True if URL should be included, False if it should be excluded
        """
        # Check general exclusions first (applies to all outlets)
        if self._has_general_exclusion(url):
            return False

        # Get hostname for outlet-specific rules
        hostname = urlparse(url).netloc

        # If no specific configuration for this outlet, include by default
        if hostname not in self.outlets:
            return True

        outlet_config = self.outlets[hostname]

        # Check outlet-specific exclusions
        if self._has_outlet_exclusion(url, outlet_config):
            return False

        # Check required patterns
        if not self._meets_required_patterns(url, outlet_config):
            return False

        # Apply validation rules
        if not self._passes_validation_rules(url, outlet_config):
            return False

        return True

    def _has_general_exclusion(self, url: str) -> bool:
        """Check if URL matches any general exclusion pattern."""
        return any(exclusion in url for exclusion in self.general_exclusions)

    def _has_outlet_exclusion(self, url: str, outlet_config: Dict) -> bool:
        """Check if URL matches any outlet-specific exclusion pattern."""
        exclusions = outlet_config.get("exclusions", [])
        return any(exclusion in url for exclusion in exclusions)

    def _meets_required_patterns(self, url: str, outlet_config: Dict) -> bool:
        """Check if URL contains all required patterns."""
        required_patterns = outlet_config.get("required_patterns", [])
        if not required_patterns:
            return True
        return all(pattern in url for pattern in required_patterns)

    def _passes_validation_rules(self, url: str, outlet_config: Dict) -> bool:
        """Apply custom validation rules for the outlet."""
        rules = outlet_config.get("validation_rules", [])
        if not rules:
            return True

        for rule in rules:
            if not self._apply_validation_rule(url, rule):
                return False

        return True

    def _apply_validation_rule(self, url: str, rule: str) -> bool:
        """Apply a specific validation rule to the URL."""
        if rule == "requires_article_path":
            return "/article" in url
        elif rule == "numeric_ending":
            return url[-4:].isnumeric()
        elif rule == "requires_dash":
            return "-" in url
        elif rule == "requires_html":
            return ".html" in url
        elif rule == "date_pattern":
            # Check for YYYY-MM-DD pattern
            return bool(re.findall(r"\\d{4}-\\d{2}-\\d{2}", url))
        elif rule == "year_pattern":
            # Check for 4-digit year
            return bool(re.findall(r"\\d{4}", url))
        elif rule == "requires_central_news":
            return "/central-news" in url
        elif rule == "no_trailing_slash":
            return not url.endswith("/")
        else:
            # Unknown rule - log warning and return True to be safe
            print(f"Warning: Unknown validation rule '{rule}' for URL: {url}")
            return True

    def get_outlet_config(self, hostname: str) -> Optional[Dict]:
        """Get configuration for a specific outlet."""
        return self.outlets.get(hostname)

    def add_outlet_config(self, hostname: str, config: Dict):
        """Add or update configuration for an outlet."""
        self.outlets[hostname] = config

    def validate_config(self) -> List[str]:
        """Validate the configuration and return list of issues."""
        issues = []

        # Check that all validation rules referenced in outlets are defined
        for hostname, outlet_config in self.outlets.items():
            rules = outlet_config.get("validation_rules", [])
            for rule in rules:
                if rule not in [
                    "requires_article_path",
                    "numeric_ending",
                    "requires_dash",
                    "requires_html",
                    "date_pattern",
                    "year_pattern",
                    "requires_central_news",
                    "no_trailing_slash",
                ]:
                    issues.append(
                        f"Unknown validation rule '{rule}' in outlet '{hostname}'"
                    )

        return issues


def refactor_crawler_validation(crawler_notebook_path: str, config_path: str):
    """
    Example function showing how to refactor the existing crawler validation logic.

    This replaces the 150+ lines of if/then statements with a clean, maintainable approach.

    Original problematic code pattern:
        if ".pdf" in u: continue
        if "/event" in u: continue
        if (urllib.parse.urlsplit(u).hostname == 'www.stltoday.com') and (not '/article' in u): continue
        # ... 150+ more lines of similar if/then statements

    Refactored approach:
        validator = URLValidator(config_path)
        valid_urls = [url for url in internal_urls if validator.should_include_url(url)]
    """
    validator = URLValidator(config_path)

    # Example of how to replace the existing validation loop
    def filter_urls(internal_urls: List[str]) -> List[str]:
        """Replace the massive if/then chain with clean validation."""
        valid_urls = []

        for url in internal_urls:
            try:
                if validator.should_include_url(url):
                    valid_urls.append(url)
            except Exception as e:
                # Log error and continue processing
                print(f"Error validating URL {url}: {e}")
                continue

        return valid_urls

    return filter_urls


# Example usage and testing
if __name__ == "__main__":
    # Initialize validator
    validator = URLValidator("url_validation_config.json")

    # Test URLs
    test_urls = [
        "https://www.columbiamissourian.com/news/article123",
        "https://www.columbiamissourian.com/news/",  # Should be excluded (trailing slash)
        "https://www.stltoday.com/news/local",  # Should be excluded (no /article)
        "https://www.stltoday.com/news/article/story123",  # Should be included
        "https://example.com/document.pdf",  # Should be excluded (PDF)
        "https://example.com/events/calendar",  # Should be excluded (event)
    ]

    print("URL Validation Results:")
    for url in test_urls:
        result = validator.should_include_url(url)
        print(f"  {url} -> {'INCLUDE' if result else 'EXCLUDE'}")

    # Validate configuration
    issues = validator.validate_config()
    if issues:
        print("\\nConfiguration issues found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\\nConfiguration is valid!")
