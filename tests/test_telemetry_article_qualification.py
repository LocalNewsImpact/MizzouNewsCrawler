"""What telemetry is allowed to call a successful extraction.

An article is defined by what its text IS, not by how much of it there is. These
tests pin that: a wall of subscription prose fails however long it runs, a short
local story passes, and the two ways a non-article used to be recorded as a
success cannot come back.

The boilerplate phrases and the density threshold are derived from production
data (15,656 cleaned/uncleaned pairs and 1,036 labelled extractions), so these
tests use the real strings rather than invented ones.
"""

from src.utils.comprehensive_telemetry import (
    ExtractionMetrics,
    capitalization_ratio,
    looks_like_article,
    prose_density,
    strip_boilerplate,
    utility_word_rate,
)

STORY = (
    "The county commission voted 4-1 on Tuesday to approve the measure. "
    "Residents said the decision had been a long time coming, and the board "
    "agreed that the work would begin in the spring. "
)
# Verbatim from the corpus: the most common wall across 16-17 hosts.
WALL = (
    "Login to continue reading. Sign up for complimentary access. "
    "Javascript is required for you to be able to read premium content. "
    "Please enable it in your browser settings."
)


def _metrics() -> ExtractionMetrics:
    return ExtractionMetrics("op-1", "art-1", "https://example.com/a", "Example")


class TestArticleIsContentNotLength:
    def test_real_story_qualifies(self):
        assert looks_like_article(STORY) is True

    def test_paywall_wall_is_not_an_article(self):
        assert looks_like_article(WALL) is False

    def test_a_LONG_wall_is_still_not_an_article(self):
        """The point of the change: no byte count can rescue this."""
        padded = (
            WALL + " " + ("Featured Local Savings. Previous Post. Next Post. " * 40)
        )
        assert len(padded) > 2000
        assert looks_like_article(padded) is False

    def test_short_local_story_qualifies(self):
        """Local news runs short; a word floor would have failed this."""
        assert (
            looks_like_article(
                "The board met on Monday and agreed to the plan for the new park."
            )
            is True
        )

    def test_empty_bodies_fail(self):
        # 107 of 1,036 production rows had exactly this and were recorded as
        # successes whenever a title was present.
        assert looks_like_article("") is False
        assert looks_like_article("   \n  ") is False
        assert looks_like_article(None) is False

    def test_scraped_form_control_is_not_an_article(self):
        """The country dropdown: 5,308 chars, identical across four hosts."""
        countries = (
            "Country United States of America US Virgin Islands United States "
            "Minor Outlying Islands Canada Mexico Bahamas Cuba Dominican "
            "Republic Haiti Jamaica Afghanistan Albania Algeria Andorra Angola "
        ) * 6
        assert len(countries) > 1000
        assert looks_like_article(countries) is False


class TestStripBoilerplate:
    def test_trailing_wall_does_not_disqualify_a_story(self):
        assert looks_like_article(STORY * 3 + " " + WALL) is True

    def test_the_wall_is_actually_removed(self):
        stripped = strip_boilerplate(STORY + " " + WALL).lower()
        assert "complimentary access" not in stripped
        assert "county commission" in stripped

    def test_comment_policy_block_removed(self):
        body = (
            STORY
            + " Please avoid obscene, vulgar, lewd, racist or sexually-oriented language."
        )
        stripped = strip_boilerplate(body).lower()
        assert "obscene" not in stripped
        assert "county commission" in stripped

    def test_dateline_is_kept_not_stripped(self):
        """Datelines are content moved to another field, not furniture."""
        assert "kansas city" in strip_boilerplate("KANSAS CITY, Mo. " + STORY).lower()


class TestProseDensity:
    def test_prose_scores_higher_than_a_form(self):
        assert prose_density(STORY) > prose_density("Canada Mexico Albania Angola")

    def test_empty_text_is_zero(self):
        assert prose_density("") == 0.0


class TestCapitalization:
    """Catches proper-noun runs that prose_density is fooled by."""

    def test_country_list_is_mostly_capitalised(self):
        # "United States of America" contains 'of' — density alone scores this
        # 0.21 and lets it through. Capitalisation is what rejects it.
        countries = "United States of America Canada Mexico Bahamas Cuba Haiti"
        assert capitalization_ratio(countries) > 0.60
        assert capitalization_ratio(STORY) < 0.60


class TestUtilityWords:
    """Vocabulary catches text that reads like writing but is about the site."""

    def test_registration_prose_is_rejected(self):
        signup = (
            "Create your account below. Enter your e-mail and choose a password. "
            "You can sign up for our newsletter and manage your account settings "
            "in your browser at any time. Click here to subscribe."
        )
        # Reads like sentences, so density and capitalisation both pass it.
        assert prose_density(signup) >= 0.14
        assert capitalization_ratio(signup) <= 0.60
        # Vocabulary is what rejects it.
        assert utility_word_rate(signup) > 3.0
        assert looks_like_article(signup) is False

    def test_a_story_mentioning_a_subscriber_once_still_qualifies(self):
        assert utility_word_rate(STORY * 3 + " One subscriber objected.") <= 3.0
        assert looks_like_article(STORY * 3 + " One subscriber objected.") is True


class TestFinalizeSuccessVerdict:
    def test_story_is_success(self):
        m = _metrics()
        m.finalize({"title": "T", "content": STORY})
        assert m.is_success is True

    def test_title_with_no_body_is_not_success(self):
        """Previously `has_title or ...` made this a success with no article."""
        m = _metrics()
        m.finalize({"title": "A headline", "content": ""})
        assert m.is_success is False

    def test_paywall_body_is_not_success(self):
        m = _metrics()
        m.finalize({"title": "A headline", "content": WALL})
        assert m.is_success is False


class TestSeleniumUsageIsCountable:
    """successful_method is not a usage counter; methods_attempted is."""

    def test_selenium_backfill_leaves_successful_method_as_the_http_parser(self):
        m = _metrics()
        m.start_method("mcmetadata")
        m.end_method("mcmetadata", True, None, {})
        m.start_method("selenium")
        m.end_method("selenium", True, None, {})

        # This is the ~10x undercount: selenium ran but did not win overall.
        assert m.successful_method == "mcmetadata"
        # The honest signal, and it is persisted alongside successful_method:
        assert m.was_attempted("selenium") is True
        assert "selenium" in m.methods_attempted

    def test_was_attempted_is_false_when_selenium_never_ran(self):
        m = _metrics()
        m.start_method("mcmetadata")
        m.end_method("mcmetadata", True, None, {})
        assert m.was_attempted("selenium") is False
