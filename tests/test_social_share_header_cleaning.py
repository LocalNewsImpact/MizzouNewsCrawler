"""Tests for social-share header removal in BalancedBoundaryContentCleaner."""

# pylint: disable=protected-access

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.content_cleaner_balanced import (  # noqa: E402
    BalancedBoundaryContentCleaner,
)


def test_social_share_header_is_removed():
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)
    original_text = (
        "Facebook Twitter WhatsApp LinkedIn SMS Email Print "
        "Copy article link Save\n"
        "\n"
        "By John Doe\n"
        "The article content starts here."
    )

    cleaned_text, metadata = cleaner.process_single_article(
        original_text, "example.com"
    )

    assert cleaned_text.startswith("By John Doe")
    assert "Facebook Twitter" not in cleaned_text
    assert metadata["social_share_header_removed"] is True
    assert "social_share_header" in metadata["patterns_matched"]
    assert metadata["chars_removed"] == len(original_text) - len(cleaned_text)


def test_content_without_share_header_stays_intact():
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)
    original_text = (
        "Facebook announced new policies today, according to "
        "Twitter officials.\n"
        "More details are expected soon."
    )

    cleaned_text, metadata = cleaner.process_single_article(
        original_text, "example.com"
    )

    assert cleaned_text == original_text
    assert metadata["social_share_header_removed"] is False
    assert metadata["chars_removed"] == 0


def test_social_share_prefix_inline_with_article_text():
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)
    original_text = (
        "Facebook Twitter WhatsApp LinkedIn SMS Email "
        "Actors and first responders rushed to help.\n"
        "Additional coverage follows here."
    )

    cleaned_text, metadata = cleaner.process_single_article(
        original_text, "maryvilleforum.com"
    )

    assert cleaned_text.startswith(
        "Actors and first responders rushed to help."
    )
    assert "Facebook Twitter" not in cleaned_text
    assert metadata["social_share_header_removed"] is True
    assert metadata["chars_removed"] == len(original_text) - len(cleaned_text)


def test_social_share_cluster_heuristics_are_general():
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    assert cleaner._is_social_share_cluster(
        "Facebook Twitter WhatsApp LinkedIn SMS Email"
    )
    assert cleaner._is_social_share_cluster(
        "Share this story on Facebook Twitter Email"
    )
    assert cleaner._is_high_confidence_boilerplate(
        "Facebook Twitter WhatsApp SMS"
    )


def test_long_navigation_block_detected_as_candidate():
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    nav_sections = [
        "Latest News",
        "Business",
        "Sports",
        "Semoball",
        "Obituaries",
        "A&E",
        "Events",
        "Opinion",
        "World",
        "E-Edition",
        "All sections",
        "TORNADO coverage",
        "Donate",
        "E-Edition",
        "Obituaries",
        "News",
        "Latest Stories",
        "Business",
        "Sports",
        "Semoball",
        "Health",
        "Arts & Entertainment",
        "Photo & Video",
        "Sports Gallery",
        "History",
        "Food",
        "Faith",
        "Records",
        "Opinion",
        "Community",
        "Family",
        "Education",
        "Events",
        "World",
        "Elections",
        "Difference Makers",
        "Spirit of America",
        "Olympics",
        "Shopping",
        "Classifieds",
        "Auctions",
        "Homes",
        "semoSearch",
        "Jobs",
        "Submission Forms",
        "Letter to the Editor",
        "Paid Election Letter",
        "Submit",
        "Speak Out",
        "Submit a Story or Photo",
        "View Classified",
        "Delisting Request",
        "Submit Event",
        "Wedding Form",
        "Links",
        "Contact Us",
        "Support Guide",
        "Newsletters",
        "Terms of Service",
        "AI Policy",
    ]
    nav_block = " ".join(nav_sections)

    articles = [
        {
            "id": "1",
            "content": f"{nav_block}\n\nWorld headlines follow.",
        },
        {
            "id": "2",
            "content": f"{nav_block}\n\nMore news content follows here.",
        },
    ]

    candidates = cleaner._find_rough_candidates(articles)
    normalized_nav = re.sub(r"\s+", " ", nav_block.strip())

    assert normalized_nav in candidates
    assert candidates[normalized_nav] == {"1", "2"}


def test_navigation_prefix_with_inline_date_detected():
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

    nav_prefix = (
        "News Local Sports Obituaries E-Edition Magazines Weekly Record A&E "
        "Opinion World Contact Us Support Guide All sections News Local "
        "Sports Obituaries E-Edition Magazines Weekly Record Contact Us "
        "Support Guide Records Business Submitted Opinion Religion History "
        "Ageless A&E"
    )

    articles = [
        {
            "id": "alpha",
            "content": (
                f"{nav_prefix} September 20, 2025 "
                "Sonny Curtis remembered."
            ),
        },
        {
            "id": "beta",
            "content": (
                f"{nav_prefix} September 22, 2025 "
                "Parade coverage continues."
            ),
        },
    ]

    candidates = cleaner._find_rough_candidates(articles)
    normalized_nav = re.sub(r"\s+", " ", nav_prefix.strip())

    assert normalized_nav in candidates
    assert candidates[normalized_nav] == {"alpha", "beta"}
