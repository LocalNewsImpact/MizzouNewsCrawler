"""Navigation menus are a RUN of segments, not one segment.

Extractors emit nav bars one item per line — "Home", "Categories",
"Classifieds" — so every item is a 1-word segment and no per-segment phrase or
shape test reaches it. That is why 23 hand-marked articles came back with the
cleaner having done nothing at all: text_len == raw_len on every one.

Calibrated against those 23: the run rule removes 63.1% of a marked article's
text against 3.7% of an unmarked one.
"""

from src.utils.boilerplate import (
    MENU_RUN_MIN_ITEMS,
    strip_boilerplate,
    strip_menu_runs,
)

# Shape taken from lamardemocrat.com: one nav item per line.
NAV = "\n".join(
    [
        "Home",
        "Categories",
        "Classifieds",
        "Columns",
        "Government",
        "Legals",
        "News",
        "Obituaries",
        "Photo Galleries",
        "Schools",
        "Social",
        "Sports",
    ]
)
STORY = (
    "The county commission voted 4-1 on Tuesday to approve the measure. "
    "Residents said the work would begin in the spring."
)


class TestMenuRuns:
    def test_a_nav_bar_is_removed(self):
        out = strip_menu_runs(NAV + "\n" + STORY)
        assert "Classifieds" not in out
        assert "Obituaries" not in out
        assert "county commission" in out

    def test_an_all_menu_body_strips_to_nothing(self):
        """Some captures are pure navigation — there is no article to keep."""
        assert strip_menu_runs(NAV).strip() == ""

    def test_a_short_run_is_kept(self):
        """Below the run threshold this is far too weak a signal to act on."""
        short = "\n".join(["Home", "News", "Sports"])
        assert len(short.split("\n")) < MENU_RUN_MIN_ITEMS
        assert "Home" in strip_menu_runs(short)

    def test_capitalised_prose_survives(self):
        """The failure mode this rule must not have."""
        line = "Mayor John Smith met Governor Jane Doe in Jefferson City."
        assert "Mayor John Smith" in strip_menu_runs(line)

    def test_a_list_of_names_is_not_stripped_when_sentences(self):
        body = "\n".join(
            [
                "Sheriff Bob Jones spoke first.",
                "Deputy Ann Lee followed him.",
                "Chief Dan Ray closed the meeting.",
                "Mayor Kim Fox thanked them.",
                "Clerk Sue Ash read the minutes.",
                "Judge Ed Poe adjourned.",
            ]
        )
        out = strip_menu_runs(body)
        assert "Sheriff Bob Jones" in out
        assert "Judge Ed Poe" in out


class TestNavPhrasesAdded:
    def test_skip_to_main_content_removed(self):
        """46 distinct hosts, 985 articles — no newsroom writes this."""
        out = strip_boilerplate("Skip to main content\n" + STORY)
        assert "skip to main content" not in out.lower()
        assert "county commission" in out

    def test_toggle_navigation_removed(self):
        out = strip_boilerplate("Toggle navigation\n" + STORY)
        assert "toggle navigation" not in out.lower()


class TestCombined:
    def test_full_chrome_header_stripped_story_kept(self):
        body = "Skip to main content\nLog in\n" + NAV + "\n" + STORY
        out = strip_boilerplate(body)
        assert "county commission" in out
        assert "Classifieds" not in out
        assert "skip to main content" not in out.lower()
        assert len(out) < len(body) / 2
