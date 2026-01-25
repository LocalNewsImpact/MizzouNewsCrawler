#!/usr/bin/env python3
"""Migrate hardcoded URL patterns to verification_patterns table."""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from src.models.verification import VerificationPattern
from sqlalchemy import text

# Hardcoded patterns from src/utils/url_classifier.py
PATTERNS_TO_MIGRATE = [
    # Gallery and multimedia pages
    (r"/video-gallery/", "video_gallery", "Video gallery pages"),
    (r"/photo-gallery/", "photo_gallery", "Photo gallery pages"),
    (r"/photos/", "photos", "Photo collection pages"),
    (r"/videos/", "videos", "Video collection pages"),
    (r"/galleries/", "galleries", "Gallery collection pages"),
    (r"/gallery/", "gallery", "Individual gallery pages"),
    (r"/slideshow", "slideshow", "Slideshow pages"),
    (r"/image[_-][0-9a-f\-]+\.html", "image_placeholder", "Image placeholder pages with hex IDs"),
    # Category and listing pages
    (r"/category/", "category", "Category listing pages"),
    (r"/tag/", "tag", "Tag listing pages"),
    (r"/topics?/", "topic", "Topic listing pages"),
    (r"/section/", "section", "Section listing pages"),
    (r"/archive", "archive", "Archive pages"),
    (r"/search", "search", "Search result pages"),
    # Static/service pages
    (r"/about", "about", "About pages"),
    (r"/contact", "contact", "Contact pages"),
    (r"/staff", "staff", "Staff directory pages"),
    (r"/advertise", "advertise", "Advertising pages"),
    (r"/subscribe", "subscribe", "Subscription pages"),
    (r"/newsletter", "newsletter", "Newsletter signup pages"),
    (r"/privacy", "privacy", "Privacy policy pages"),
    (r"/terms", "terms", "Terms of service pages"),
    (r"/sitemap", "sitemap", "Sitemap pages"),
    (r"/rss", "rss", "RSS feed pages"),
    (r"/feed", "feed", "Feed pages"),
    # Advertising and promotional pages
    (r"/posterboard-ads/", "posterboard_ads", "Posterboard advertisement pages"),
    (r"/classifieds/", "classifieds", "Classified ads pages"),
    (r"/marketplace/", "marketplace", "Marketplace pages"),
    (r"/deals/", "deals", "Deals and promotions pages"),
    (r"/coupons/", "coupons", "Coupon pages"),
    (r"/promotions/", "promotions", "Promotional pages"),
    (r"/sponsored/", "sponsored", "Sponsored content pages"),
    (r"/shopping", "shopping", "Shopping pages"),
    # Technical pages
    (r"\.pdf$", "pdf", "PDF documents"),
    (r"\.xml$", "xml", "XML documents"),
    (r"\.json$", "json", "JSON files"),
    (r"/api/", "api", "API endpoints"),
    (r"/wp-admin", "wp_admin", "WordPress admin pages"),
    (r"/wp-content", "wp_content", "WordPress content directory"),
    (r"/wp-includes", "wp_includes", "WordPress includes directory"),
]


def migrate_patterns():
    """Migrate hardcoded patterns to database."""
    db = DatabaseManager()

    with db.get_session() as session:
        # Check existing patterns
        existing = session.execute(text('''
            SELECT pattern_regex FROM verification_patterns WHERE is_active = true
        ''')).fetchall()
        existing_regexes = {row[0] for row in existing}

        added = 0
        skipped = 0

        for pattern_regex, pattern_type, description in PATTERNS_TO_MIGRATE:
            if pattern_regex in existing_regexes:
                print(f"⊘ Skipping {pattern_regex:40s} (already exists)")
                skipped += 1
                continue

            pattern = VerificationPattern(
                id=str(uuid.uuid4()),
                pattern_type=pattern_type,
                pattern_regex=pattern_regex,
                pattern_description=description,
                is_active=True,
                total_matches=0,
                article_matches=0,
                non_article_matches=0
            )
            session.add(pattern)
            print(f"✓ Added   {pattern_regex:40s} ({pattern_type})")
            added += 1

        session.commit()

        print(f"\nMigration complete:")
        print(f"  Added: {added}")
        print(f"  Skipped: {skipped}")
        print(f"  Total patterns in DB: {len(existing_regexes) + added}")


if __name__ == "__main__":
    migrate_patterns()
