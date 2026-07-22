"""The cleaner must remove furniture it has never seen on that source before.

BalancedBoundaryContentCleaner learns per-source: a phrase has to recur several
times within ONE publisher before it is removed, and sources with fewer than
`min_occurrences` articles are skipped entirely. Cross-publisher walls never
satisfy that — "Login to continue reading" is spread thinly over 16 hosts — so
they survived indefinitely. Measured consequence: 11,684 of 96,766 stored
articles still carried one of these phrases.

These tests pin the learning-free pass that closes that gap, using the phrases
as they actually appear in production.
"""

from src.utils.boilerplate import looks_like_furniture, strip_boilerplate
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner

STORY = (
    "The county commission voted 4-1 on Tuesday to approve the measure. "
    "Residents said the work would begin in the spring."
)
# Verbatim from the corpus, 16 hosts, 548 occurrences each.
WALL = (
    "Login to continue reading. Sign up for complimentary access. "
    "Javascript is required for you to be able to read premium content."
)


def _cleaner() -> BalancedBoundaryContentCleaner:
    # Bypass __init__: this pass is pure text handling with no DB or telemetry.
    return BalancedBoundaryContentCleaner.__new__(BalancedBoundaryContentCleaner)


class TestKnownBoilerplateRemoval:
    def test_removes_a_cross_publisher_wall(self):
        result = _cleaner()._remove_known_boilerplate(STORY + " " + WALL)
        assert result["chars_removed"] > 0
        assert "complimentary access" not in result["cleaned_text"].lower()
        assert "premium content" not in result["cleaned_text"].lower()

    def test_keeps_the_story(self):
        result = _cleaner()._remove_known_boilerplate(WALL + " " + STORY)
        assert "county commission" in result["cleaned_text"]
        assert "would begin in the spring" in result["cleaned_text"]

    def test_reports_what_it_removed(self):
        result = _cleaner()._remove_known_boilerplate(STORY + " " + WALL)
        assert len(result["removed_segments"]) == 3
        assert all(
            "continue reading" in s.lower()
            or "complimentary" in s.lower()
            or "premium content" in s.lower()
            for s in result["removed_segments"]
        )

    def test_clean_article_is_untouched(self):
        """No match must mean no edit — not even whitespace normalisation."""
        result = _cleaner()._remove_known_boilerplate(STORY)
        assert result["chars_removed"] == 0
        assert result["removed_segments"] == []
        assert result["cleaned_text"] == STORY

    def test_empty_input_is_safe(self):
        result = _cleaner()._remove_known_boilerplate("")
        assert result["cleaned_text"] == ""
        assert result["chars_removed"] == 0

    def test_comment_policy_block_removed(self):
        body = (
            STORY + " Please avoid obscene, vulgar, lewd, racist or "
            "sexually-oriented language. Threats of harming another "
            "person will not be tolerated."
        )
        cleaned = _cleaner()._remove_known_boilerplate(body)["cleaned_text"].lower()
        assert "obscene" not in cleaned
        assert "county commission" in cleaned


class TestFurnitureIsNotJustShortText:
    """looks_like_furniture must demand positive evidence, not just brevity."""

    def test_a_short_paragraph_is_not_furniture(self):
        assert looks_like_furniture("The vote was unanimous.") is False

    def test_a_wall_is_furniture(self):
        assert looks_like_furniture("Login to continue reading") is True

    def test_a_proper_noun_run_is_furniture(self):
        assert looks_like_furniture("Canada Mexico Bahamas Cuba Haiti Jamaica") is True

    def test_registration_prose_is_furniture(self):
        assert (
            looks_like_furniture(
                "Enter your e-mail and choose a password to create your account."
            )
            is True
        )


class TestSharedDefinition:
    """The cleaner and telemetry must strip identically."""

    def test_cleaner_pass_matches_strip_boilerplate(self):
        body = STORY + " " + WALL
        via_cleaner = _cleaner()._remove_known_boilerplate(body)["cleaned_text"]
        assert via_cleaner == strip_boilerplate(body)
