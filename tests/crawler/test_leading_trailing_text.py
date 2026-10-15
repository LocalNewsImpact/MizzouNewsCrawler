"""Leading/trailing text that is not the story is removed; the story is not.

The cases are the ones measured on 247 archived WSU captures, 2026-10-14:
what the rule must remove (gift and donation asks, a repeated headline, media
labels, a trailing widget) and what it must keep (an opening paragraph the
other extractors missed, ROT47 premium paragraphs, anything in the middle).
"""

from __future__ import annotations

import inspect

from src.crawler import ContentExtractor
from src.crawler.leading_trailing import trim_leading_trailing

P1 = (
    "WENATCHEE - A new event series will help residents who arrived in the "
    "last five years connect with local organizations and each other."
)
P2 = (
    "The program introduces the valley's history, services and amenities, and "
    "gives participants tools to get involved in civic life."
)
P3 = (
    "The first event is April 25 at the Hilton Garden Inn in Wenatchee, and "
    "registration opens March 4 for residents and invited nonprofit leaders."
)
STORY = [P1, P2, P3]

GIFT = (
    "As a subscriber, you can share up to 3 articles each month with friends "
    "for free. Just click Gift this Article on this page, then copy the link."
)
DONATION = (
    "Will you chip in to support our nonprofit newsroom with a donation today? "
    "Yes, I want to support My Edmonds News!"
)


def full(*lines: str) -> str:
    return "\n".join(lines)


class TestWhatIsRemoved:
    def test_a_gift_prompt_kept_by_its_only_voter_is_still_removed(self):
        """Wenatchee: boilerpipe3 was the one voter and it kept the prompt too."""
        base = full(GIFT, *STORY)
        result = trim_leading_trailing(base, [full(GIFT, *STORY)])
        assert result.text == full(*STORY)
        assert result.leading == (GIFT,)

    def test_a_donation_ask_is_removed(self):
        """My Edmonds: newspaper3k also kept the ask; the other three did not."""
        base = full(DONATION, *STORY)
        others = [full(*STORY), full(*STORY), full(*STORY), full(DONATION, *STORY)]
        assert trim_leading_trailing(base, others).text == full(*STORY)

    def test_a_repeated_headline_is_removed(self):
        title = "Wenatchee Valley 101 helps new residents connect"
        base = full(title, *STORY)
        others = [full(*STORY)] * 4
        assert trim_leading_trailing(base, others, title).text == full(*STORY)

    def test_media_labels_are_removed(self):
        base = full("Read", "Listen", "(Runtime 0:56)", *STORY)
        assert trim_leading_trailing(base, [full(*STORY)] * 4).text == full(*STORY)

    def test_a_trailing_widget_is_removed(self):
        widget = "Get email notifications on {{subject}} daily!"
        base = full(*STORY, widget)
        result = trim_leading_trailing(base, [full(*STORY)] * 4)
        assert result.text == full(*STORY)
        assert result.trailing == (widget,)


class TestWhatIsKept:
    def test_an_opening_paragraph_the_others_missed_stays(self):
        """tdn.com: goose3 and readability start mid-story, so the lede had
        support 0 -- but it is a full sentence and nothing else marks it."""
        base = full(*STORY)
        others = [full(P2, P3)] * 4
        assert trim_leading_trailing(base, others).text == base

    def test_rot47_premium_paragraphs_stay(self):
        """TownNews encodes only the story body; ciphertext looks like junk."""
        cipher = (
            "kAm%96 $@4:2= $64FC:EJ u2:C?6DD p4E A2DD65 E96 $6?2E6 H:E9 2 G@E6]k^Am"
        )
        base = full(*STORY, cipher)
        assert cipher in trim_leading_trailing(base, [full(*STORY)] * 4).text

    def test_nothing_in_the_middle_is_touched(self):
        base = full(P1, "Read", P2, DONATION, P3)
        others = [full(P1, P2, P3)] * 4
        assert trim_leading_trailing(base, others).text == base

    def test_fragments_get_no_vote(self):
        """Yakima: three fragments outvoted the complete bodies and a pure vote
        cut 2,282 chars of story to 58."""
        base = full(*STORY)
        fragments = ["Photo caption only, nothing else here at all."] * 3
        assert trim_leading_trailing(base, fragments).text == base

    def test_with_no_other_extractor_nothing_is_removed(self):
        base = full(GIFT, *STORY)
        assert trim_leading_trailing(base, []).text == base

    def test_the_layout_is_kept(self):
        base = full("Read", *STORY)
        kept = trim_leading_trailing(base, [full(*STORY)] * 4).text
        assert kept.split("\n") == STORY


def test_the_mcmetadata_parse_applies_it():
    source = inspect.getsource(ContentExtractor._parse_with_mcmetadata)
    assert "trim_leading_trailing(" in source
    assert '"leading_trailing_removed": trimmed_lines' in source
