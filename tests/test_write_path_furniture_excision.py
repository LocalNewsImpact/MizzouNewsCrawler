"""The furniture detector must shape the STORED body, not only gate on it.

Until 2026-07-28 boilerplate.py was consulted only to decide a status. The text
that got stored came solely from content_cleaner_balanced's per-source learned
patterns, so on a host with no learned pattern nothing was removed at all --
measured over a 3-hour production run, 120 cleaning sessions recorded ZERO
removed segments while bodies still carried consent notices.

Wiring the detector into the write path is easy to get wrong in two specific
ways, and both were caught by measuring against real stored bodies rather than
by reasoning. Each has a test here.

1. strip_furniture() is the DETECTION-side function and is too destructive to
   edit a stored article with. Over the 161 bodies this pipeline stored on
   2026-07-28 it rewrote 149 of them by collapsing newlines, and it deleted a
   maconhomepress.com honor roll as a "menu run" -- the agate false positive
   this module's own thresholds already warn about.

2. Dropping whole furniture LINES loses stories, because extractors that emit
   no paragraph breaks put the banner and the article on one line.
"""

from src.utils.boilerplate import (
    CONSENT,
    MAX_WHOLE_LINE_DROP,
    excise_furniture_lines,
    strip_furniture,
)

# Shape of the real stltoday.com capture: consent notice and story on ONE line.
BANNER = (
    "This website utilizes technologies such as cookies to enable essential "
    "site functionality, as well as for analytics, personalization, and "
    "targeted advertising. To learn more, view the following link: Privacy Policy"
)
STORY = (
    "ST. LOUIS COUNTY - A worker hired to paint the KSDK television "
    "transmission tower helped save a man who climbed it Wednesday afternoon "
    "without authorization. Rescuers in a basket were raised up to reach him. "
    "The man was taken to a hospital and is expected to recover, police said."
)

# The maconhomepress.com honor roll, copied in the shape the extractor really
# emits it: one name per line. That shape is the whole point -- a run of short
# capitalised fragments with no sentence punctuation is indistinguishable from a
# nav bar by structure alone, which is exactly why the run heuristic eats it.
AGATE = "\n".join(
    [
        "Class 1",
        "Macey Harrington",
        "Team GPA: 3.55",
        "Jordan Harrington",
        "Jessalyn Parks",
        "Alana Fesler",
        "Lanie Witt",
        "Jaycee Christensen",
        "Kenny Vaught",
        "Haley Bachman",
        "Sophia Brower",
        "Jessica Compton",
        "Presleigh Williams",
    ]
)


class TestLayoutIsPreserved:
    """A reformatted body is a destructive edit even when no words are lost."""

    def test_newlines_survive(self):
        body = "First paragraph here.\n\nSecond paragraph here.\n\nThird one."
        kept, _ = excise_furniture_lines(body)
        assert kept.count("\n") == body.strip().count("\n")

    def test_a_clean_body_is_returned_byte_identical(self):
        body = "The council voted Tuesday.\nThe measure passed five to two."
        assert excise_furniture_lines(body)[0] == body

    def test_strip_furniture_would_not_have_been_safe_here(self):
        """Why the write path needs its own function.

        Pins the actual difference rather than trusting the docstring: the
        detection-side helper collapses the line structure.
        """
        body = "First paragraph here.\n\nSecond paragraph here."
        assert "\n" not in strip_furniture(body).text
        assert "\n" in excise_furniture_lines(body)[0]


class TestAgateSurvives:
    """Legitimate local copy that reads like a list is not furniture."""

    def test_an_honor_roll_is_not_removed(self):
        kept, _ = excise_furniture_lines("Honor roll:\n" + AGATE)
        assert "Macey Harrington" in kept
        assert "Presleigh Williams" in kept

    def test_the_detection_helper_does_remove_it(self):
        """The reason the write path may not use menu-run removal.

        Documents the real divergence: this is fine for deciding "is this
        block furniture" and wrong for editing a stored article.
        """
        assert "Macey Harrington" not in strip_furniture(AGATE).text


class TestMixedLinesAreEditedNotDropped:
    def test_a_banner_and_a_story_on_one_line_keeps_the_story(self):
        kept, kinds = excise_furniture_lines(BANNER + " " + STORY)
        assert "A worker hired to paint" in kept
        assert "utilizes technologies such as cookies" not in kept
        assert CONSENT in kinds

    def test_a_short_banner_alone_is_dropped_whole(self):
        kept, kinds = excise_furniture_lines(BANNER)
        assert kept == ""
        assert CONSENT in kinds

    def test_the_threshold_separates_those_two_cases(self):
        """A banner alone is short; a banner glued to a story is not."""
        assert len(BANNER) < MAX_WHOLE_LINE_DROP
        assert len(BANNER + " " + STORY) > MAX_WHOLE_LINE_DROP


class TestTheKindReachesTheCaller:
    """The status depends on it, so it must survive excision."""

    def test_consent_is_reported(self):
        assert CONSENT in excise_furniture_lines(BANNER)[1]

    def test_a_clean_body_reports_nothing(self):
        assert excise_furniture_lines(STORY)[1] == frozenset()
